//! Setup Wizards: the agent runner (Claude Messages API with tool use), the tools the
//! wizards call, proposal application, the team page, session pages and the per-page
//! form assistant. Wizards only propose; `apply_proposal` is the one place a proposal
//! becomes a change, and it uses the same store code paths as a manual save.

use crate::app::AppState;
use crate::auth::AdminUser;
use crate::errors::AppResult;
use crate::routes::customers::CsrfOnly;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::{Form, Json};
use minijinja::context;
use mms_core::media::MediaQuery;
use mms_core::pages::PageDraft;
use mms_core::products::ProductDraft;
use mms_core::settings::{self as settings_mod, Kind};
use mms_core::wizards::{self, Proposal, Session, WizardDef};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;

// ----- the runner -----

enum Control {
    Continue,
    Wait(Value),
    Done(String, Value),
}

async fn store_context(state: &AppState, session: &Session, def: &WizardDef) -> AppResult<String> {
    let name = state.settings.get("general.site_name").await?;
    let currency = state.settings.get("store.currency").await?;
    let mode = state.settings.get("commerce.mode").await?;
    let sites = crate::routes::bridges::all(state).await?;
    let cms = sites
        .first()
        .map(|s| format!("{} at {}", s.host, s.origin))
        .unwrap_or_else(|| "no connected site yet".into());
    let mut ctx = format!(
        "{}\n\nYou are: {} — {}\n\nStore facts: name \"{name}\", base currency {currency}, checkout mode {mode}, CMS {cms}, store address {}.\n",
        wizards::RULES, def.title, def.persona, state.config.server.public_url.trim_end_matches('/')
    );
    if !session.context.trim().is_empty() {
        ctx.push_str("\nContext from the Concierge and the administrator:\n");
        ctx.push_str(session.context.trim());
        ctx.push('\n');
    }
    if !session.brief.trim().is_empty() {
        ctx.push_str("\nThe administrator's brief for this session:\n");
        ctx.push_str(session.brief.trim());
        ctx.push('\n');
    }
    Ok(ctx)
}

/// Runs a session until it finishes, waits for the administrator, or fails.
pub async fn run_session(state: &AppState, session_id: i64) -> anyhow::Result<()> {
    let Some(session) = state.wizards.session_by_id(session_id).await? else {
        anyhow::bail!("wizard session {session_id} missing");
    };
    let Some(def) = wizards::wizard(&session.wizard) else {
        anyhow::bail!("unknown wizard {}", session.wizard);
    };
    let api_key = state.settings.get("ai.anthropic_api_key").await?;
    let model = {
        let m = state.settings.get("ai.model").await?;
        if m.trim().is_empty() {
            wizards::DEFAULT_MODEL.to_string()
        } else {
            m
        }
    };
    let effort = state.settings.get("ai.effort").await?;
    state.wizards.set_status(session.id, "running", "").await?;
    let system = store_context(state, &session, def).await.map_err(|e| e.0)?;
    let tools = wizards::tool_definitions(def.tools);
    let mut messages = state.wizards.messages(session.id).await?;
    if messages.is_empty() {
        let goal = if def.goal.is_empty() {
            session.brief.clone()
        } else {
            def.goal.to_string()
        };
        let goal = if goal.trim().is_empty() {
            "Help me with this page.".to_string()
        } else {
            goal
        };
        state
            .wizards
            .append_message(session.id, "user", &json!(goal))
            .await?;
        messages.push(json!({ "role": "user", "content": goal }));
    }
    let max_turns = if session.wizard == "assist" {
        wizards::ASSIST_MAX_TURNS
    } else {
        wizards::MAX_TURNS
    };
    let mut turns = 0;
    loop {
        if turns >= max_turns {
            state.wizards.set_done(session.id, "The wizard reached its turn limit before finishing. Review the proposals so far and start it again with a narrower brief.", &json!([])).await?;
            return Ok(());
        }
        turns += 1;
        let body = json!({
            "model": model, "max_tokens": 8000,
            "thinking": { "type": "adaptive" },
            "output_config": { "effort": if matches!(effort.as_str(), "low" | "medium" | "high") { effort.as_str() } else { "medium" } },
            "system": [{ "type": "text", "text": system, "cache_control": { "type": "ephemeral" } }],
            "tools": tools, "messages": messages,
        });
        let resp = match state.wizard_transport.send(&api_key, &body).await {
            Ok(r) => r,
            Err(e) => {
                state
                    .wizards
                    .set_status(session.id, "failed", &e.to_string())
                    .await?;
                anyhow::bail!("{e}");
            }
        };
        let usage = &resp["usage"];
        state
            .wizards
            .add_usage(
                session.id,
                usage["input_tokens"].as_i64().unwrap_or(0),
                usage["output_tokens"].as_i64().unwrap_or(0),
                usage["cache_read_input_tokens"].as_i64().unwrap_or(0),
            )
            .await?;
        let content = resp["content"].clone();
        if !content.is_array() {
            state
                .wizards
                .set_status(session.id, "failed", "The model returned no content")
                .await?;
            anyhow::bail!("no content");
        }
        state
            .wizards
            .append_message(session.id, "assistant", &content)
            .await?;
        messages.push(json!({ "role": "assistant", "content": content }));
        let stop = resp["stop_reason"].as_str().unwrap_or("end_turn");
        match stop {
            "refusal" => {
                state
                    .wizards
                    .set_status(session.id, "failed", "The model declined this request")
                    .await?;
                return Ok(());
            }
            "max_tokens" => {
                state
                    .wizards
                    .append_message(session.id, "user", &json!("Continue where you left off."))
                    .await?;
                messages.push(json!({ "role": "user", "content": "Continue where you left off." }));
                continue;
            }
            "tool_use" => {
                let session_now = state
                    .wizards
                    .session_by_id(session.id)
                    .await?
                    .unwrap_or(session.clone());
                let mut results = Vec::new();
                let mut control = Control::Continue;
                let mut wait_id = String::new();
                for block in content.as_array().unwrap() {
                    if block["type"] != "tool_use" {
                        continue;
                    }
                    let name = block["name"].as_str().unwrap_or("");
                    let id = block["id"].as_str().unwrap_or("").to_string();
                    if !def.tools.contains(&name) {
                        results.push(json!({ "type": "tool_result", "tool_use_id": id, "content": "This wizard may not use that tool", "is_error": true }));
                        continue;
                    }
                    let (result, c) =
                        match execute_tool(state, &session_now, name, &block["input"]).await {
                            Ok(v) => v,
                            Err(e) => (json!({ "error": e.0.to_string() }), Control::Continue),
                        };
                    match c {
                        Control::Wait(q) => {
                            wait_id = id;
                            control = Control::Wait(q);
                        }
                        Control::Done(s, cl) => {
                            results.push(json!({ "type": "tool_result", "tool_use_id": id, "content": result.to_string() }));
                            control = Control::Done(s, cl);
                        }
                        Control::Continue => results.push(json!({ "type": "tool_result", "tool_use_id": id, "content": result.to_string() })),
                    }
                }
                match control {
                    Control::Wait(questions) => {
                        state
                            .wizards
                            .set_waiting(
                                session.id,
                                &json!({ "questions": questions, "results": results }),
                                &wait_id,
                            )
                            .await?;
                        return Ok(());
                    }
                    Control::Done(summary, checklist) => {
                        state
                            .wizards
                            .append_message(session.id, "user", &json!(results))
                            .await?;
                        state
                            .wizards
                            .set_done(session.id, &summary, &checklist)
                            .await?;
                        state
                            .audit
                            .record(
                                session.created_by,
                                "wizard.finished",
                                "wizard_session",
                                Some(&session.uuid),
                                None,
                                Some(json!({ "wizard": session.wizard, "turns": turns })),
                            )
                            .await?;
                        return Ok(());
                    }
                    Control::Continue => {
                        state
                            .wizards
                            .append_message(session.id, "user", &json!(results))
                            .await?;
                        messages.push(json!({ "role": "user", "content": results }));
                    }
                }
            }
            _ => {
                let text = content
                    .as_array()
                    .unwrap()
                    .iter()
                    .filter(|b| b["type"] == "text")
                    .map(|b| b["text"].as_str().unwrap_or(""))
                    .collect::<Vec<_>>()
                    .join("\n");
                state
                    .wizards
                    .set_done(session.id, text.trim(), &json!([]))
                    .await?;
                return Ok(());
            }
        }
    }
}

/// After a session ends: run the next step of the Concierge's plan, if any.
pub async fn advance_plan(state: &AppState, parent_id: i64) -> anyhow::Result<()> {
    let Some(parent) = state.wizards.session_by_id(parent_id).await? else {
        return Ok(());
    };
    let steps: Vec<Value> = serde_json::from_str(&parent.plan).unwrap_or_default();
    let children = state.wizards.children(parent.id).await?;
    if children
        .iter()
        .any(|c| matches!(c.status.as_str(), "queued" | "running" | "waiting"))
    {
        return Ok(()); // a step is still going; it will call back when it ends
    }
    let idx = children.len();
    if idx >= steps.len() {
        return Ok(());
    }
    let step = &steps[idx];
    let wizard = step["wizard"].as_str().unwrap_or("");
    if wizards::wizard(wizard).is_none() || wizard == "concierge" {
        anyhow::bail!("plan step {idx} names an unknown wizard {wizard}");
    }
    let context = format!(
        "{}\n\nConcierge summary: {}",
        parent.context.trim(),
        parent.summary.trim()
    );
    let child = state
        .wizards
        .create_session(
            wizard,
            step["brief"].as_str().unwrap_or(""),
            context.trim(),
            Some(parent.id),
            parent.created_by,
        )
        .await?;
    state
        .jobs
        .enqueue("wizard.run", json!({ "session": child.uuid }))
        .await?;
    Ok(())
}

/// The job body: run a session, then move its parent's plan along.
pub async fn run_job(state: &AppState, session_uuid: &str) -> anyhow::Result<()> {
    let Some(s) = state.wizards.session_by_uuid(session_uuid).await? else {
        anyhow::bail!("no such session")
    };
    let outcome = run_session(state, s.id).await;
    let after = state.wizards.session_by_id(s.id).await?.unwrap_or(s);
    if after.status == "done" || after.status == "failed" {
        if let Some(pid) = after.parent_id {
            advance_plan(state, pid).await?;
        } else if after.wizard == "concierge" {
            advance_plan(state, after.id).await?;
        }
    }
    outcome
}

// ----- tools -----

async fn execute_tool(
    state: &AppState,
    session: &Session,
    name: &str,
    input: &Value,
) -> AppResult<(Value, Control)> {
    let s = |v: &Value, k: &str| v[k].as_str().unwrap_or("").trim().to_string();
    Ok(match name {
        "read_settings" => {
            let section = s(input, "section");
            let values = state.settings.display_values().await?;
            let out: Vec<Value> = values.iter().filter(|(d, _)| section.is_empty() || d.section == section).map(|(d, v)| json!({
                "key": d.key, "section": d.section, "label": d.label, "kind": format!("{:?}", d.kind).to_lowercase(),
                "value": if d.kind == Kind::Secret { if v.is_empty() { "not set".to_string() } else { format!("set ({v})") } } else { v.clone() },
                "default": d.default, "help": d.help, "options": d.options.iter().map(|(k, l)| json!({ "value": k, "label": l })).collect::<Vec<_>>(),
            })).collect();
            (
                json!({ "settings": out, "sections": settings_mod::SECTIONS }),
                Control::Continue,
            )
        }
        "read_store_overview" => (overview(state).await?, Control::Continue),
        "list_media" => {
            let t = s(input, "type");
            let limit = input["limit"].as_i64().unwrap_or(60).clamp(1, 200);
            let (items, total) = state
                .media
                .list(&MediaQuery {
                    q: String::new(),
                    r#type: t,
                    folder_id: None,
                    page: 1,
                    per_page: limit,
                })
                .await?;
            let used: Vec<i64> =
                sqlx::query_scalar("SELECT media_id FROM products WHERE media_id IS NOT NULL")
                    .fetch_all(&state.db.pool)
                    .await?;
            let out: Vec<Value> = items.iter().map(|m| json!({ "uuid": m.uuid, "type": m.r#type, "title": m.title, "tags": m.tags, "caption": m.caption, "bytes": m.bytes, "duration_ms": m.duration_ms, "width": m.width, "height": m.height, "private": m.private == 1, "has_product": used.contains(&m.id) })).collect();
            (json!({ "total": total, "media": out }), Control::Continue)
        }
        "list_products" => {
            let cats = state.products.categories().await?;
            let mut out = Vec::new();
            for p in state
                .products
                .list_admin("", "", &s(input, "status"))
                .await?
            {
                let ids = state.products.category_ids(p.id).await?;
                let media_uuid = match p.media_id {
                    Some(id) => state.media.by_id(id).await?.map(|m| m.uuid),
                    None => None,
                };
                out.push(json!({ "slug": p.slug, "type": p.r#type, "title": p.title, "price_cents": p.price_cents, "currency": p.currency, "status": p.status, "featured": p.featured == 1, "media_uuid": media_uuid, "categories": cats.iter().filter(|c| ids.contains(&c.id)).map(|c| c.name.clone()).collect::<Vec<_>>(), "settings": p.settings_json() }));
            }
            (
                json!({ "products": out, "categories": cats.iter().map(|c| c.name.clone()).collect::<Vec<_>>() }),
                Control::Continue,
            )
        }
        "list_site_templates" => {
            let t: Vec<Value> = mms_core::templates::site_templates().iter().map(|t| json!({ "slug": t.slug, "name": t.name, "industry": t.industry, "description": t.description, "scheme": t.scheme, "pages": t.pages.iter().map(|(p, w)| json!({ "page": p, "widgets": w })).collect::<Vec<_>>() })).collect();
            let schemes: Vec<Value> = mms_core::templates::builtin_schemes()
                .iter()
                .map(|c| json!({ "slug": c.slug, "name": c.name }))
                .collect();
            (
                json!({ "site_templates": t, "schemes": schemes }),
                Control::Continue,
            )
        }
        "read_guide" => {
            let topic = s(input, "topic");
            match wizards::guide(&topic) {
                Some(g) => (json!({ "topic": topic, "guide": g }), Control::Continue),
                None => (
                    json!({ "error": format!("no guide for {topic}; topics: {}", wizards::KNOWLEDGE.iter().map(|(t, _)| *t).collect::<Vec<_>>().join(", ")) }),
                    Control::Continue,
                ),
            }
        }
        "propose_settings" => {
            let mut made = Vec::new();
            let mut rejected = Vec::new();
            for c in input["changes"].as_array().cloned().unwrap_or_default() {
                let key = s(&c, "key");
                let Some(def) = settings_mod::definition(&key) else {
                    rejected.push(format!("{key}: unknown setting"));
                    continue;
                };
                let value = s(&c, "value");
                let needs_input = def.kind == Kind::Secret;
                if !needs_input {
                    if let Err(e) = settings_mod::validate(&key, &value) {
                        rejected.push(format!("{key}: {e}"));
                        continue;
                    }
                }
                let p = state.wizards.add_proposal(session, "setting", &format!("{}: {}", def.label, if needs_input { "enter the secret" } else { &value }), &s(&c, "reason"), &json!({ "key": key, "value": if needs_input { String::new() } else { value.clone() }, "label": def.label, "section": def.section }), needs_input).await?;
                made.push(p.uuid);
            }
            (
                json!({ "proposed": made.len(), "rejected": rejected }),
                Control::Continue,
            )
        }
        "propose_product" => {
            let t = s(input, "type");
            if !mms_core::products::TYPES.iter().any(|(k, _)| *k == t) {
                return Ok((
                    json!({ "error": "unknown product type" }),
                    Control::Continue,
                ));
            }
            let title = s(input, "title");
            let currency = {
                let c = s(input, "currency");
                if c.len() == 3 {
                    c.to_uppercase()
                } else {
                    state.settings.get("store.currency").await?
                }
            };
            let p = state.wizards.add_proposal(session, "product", &format!("Product: {title}"), &s(input, "reason"), &json!({
                "type": t, "title": title, "slug": s(input, "slug"), "description": s(input, "description"), "price_cents": input["price_cents"].as_i64().unwrap_or(0).max(0),
                "currency": currency,
                "media_uuid": s(input, "media_uuid"), "preview_media_uuid": s(input, "preview_media_uuid"), "settings": input["settings"].clone(),
                "categories": input["categories"].as_array().cloned().unwrap_or_default(), "featured": input["featured"].as_bool().unwrap_or(false),
                "status": if s(input, "status") == "published" { "published" } else { "draft" },
            }), false).await?;
            (json!({ "proposal": p.uuid }), Control::Continue)
        }
        "propose_category" => {
            let name = s(input, "name");
            let p = state
                .wizards
                .add_proposal(
                    session,
                    "category",
                    &format!("Category: {name}"),
                    &s(input, "reason"),
                    &json!({ "name": name }),
                    false,
                )
                .await?;
            (json!({ "proposal": p.uuid }), Control::Continue)
        }
        "propose_page" => {
            let title = s(input, "title");
            let p = state.wizards.add_proposal(session, "page", &format!("Private page: {title}"), &s(input, "reason"), &json!({
                "title": title, "content": s(input, "content"), "agreement": s(input, "agreement"), "signup_template": s(input, "signup_template"), "protection": s(input, "protection"),
                "product_slug": s(input, "product_slug"), "incentive": s(input, "incentive"), "quiz_question": s(input, "quiz_question"), "quiz_answer": s(input, "quiz_answer"),
                "jurisdiction": s(input, "jurisdiction"), "min_age": input["min_age"].as_i64().unwrap_or(0), "status": if s(input, "status") == "draft" { "draft" } else { "published" },
            }), false).await?;
            (json!({ "proposal": p.uuid }), Control::Continue)
        }
        "propose_coupon" => {
            let code = s(input, "code").to_uppercase();
            let p = state.wizards.add_proposal(session, "coupon", &format!("Coupon {code}"), &s(input, "reason"), &json!({ "code": code, "kind": if s(input, "kind") == "fixed" { "fixed" } else { "percent" }, "amount": input["amount"].as_i64().unwrap_or(0), "max_uses": input["max_uses"].as_i64().unwrap_or(0), "expires_at": s(input, "expires_at") }), false).await?;
            (json!({ "proposal": p.uuid }), Control::Continue)
        }
        "propose_tax_rate" => {
            let country = s(input, "country").to_uppercase();
            let p = state.wizards.add_proposal(session, "tax_rate", &format!("Tax rate {country}: {}", s(input, "name")), &s(input, "reason"), &json!({ "country": country, "name": s(input, "name"), "rate_bp": input["rate_bp"].as_i64().unwrap_or(0) }), false).await?;
            (json!({ "proposal": p.uuid }), Control::Continue)
        }
        "propose_site_template" => {
            let slug = s(input, "slug");
            let Some(t) = mms_core::templates::site_template(&slug) else {
                return Ok((
                    json!({ "error": "unknown site template" }),
                    Control::Continue,
                ));
            };
            let p = state
                .wizards
                .add_proposal(
                    session,
                    "site_template",
                    &format!("Apply site template: {}", t.name),
                    &s(input, "reason"),
                    &json!({ "slug": slug, "name": t.name }),
                    false,
                )
                .await?;
            (json!({ "proposal": p.uuid }), Control::Continue)
        }
        "ask_admin" => {
            let q = input["questions"].clone();
            if !q.is_array() || q.as_array().unwrap().is_empty() {
                (
                    json!({ "error": "questions must be a non-empty array" }),
                    Control::Continue,
                )
            } else {
                (json!({}), Control::Wait(q))
            }
        }
        "plan_team" => {
            let steps: Vec<Value> = input["steps"]
                .as_array()
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .filter(|st| {
                    let w = st["wizard"].as_str().unwrap_or("");
                    wizards::wizard(w).is_some() && w != "concierge" && w != "assist"
                })
                .collect();
            state.wizards.set_plan(session.id, &json!(steps)).await?;
            (json!({ "planned": steps.len() }), Control::Continue)
        }
        "finish" => {
            let summary = s(input, "summary");
            let checklist = input["checklist"].clone();
            (
                json!({ "ok": true }),
                Control::Done(
                    summary,
                    if checklist.is_array() {
                        checklist
                    } else {
                        json!([])
                    },
                ),
            )
        }
        other => (
            json!({ "error": format!("unknown tool {other}") }),
            Control::Continue,
        ),
    })
}

async fn overview(state: &AppState) -> AppResult<Value> {
    let count = |sql: &'static str| async move {
        sqlx::query_scalar::<_, i64>(sql)
            .fetch_one(&state.db.pool)
            .await
    };
    let health = mms_core::health::run(&state.config, &state.db).await;
    let sites = crate::routes::bridges::all(state).await?;
    let applications: Vec<(String, String)> = sqlx::query_as(
        "SELECT template, applied_at FROM site_applications WHERE rolled_back = 0 ORDER BY id DESC",
    )
    .fetch_all(&state.db.pool)
    .await?;
    let mode = state.settings.get("commerce.mode").await?;
    Ok(json!({
        "store_name": state.settings.get("general.site_name").await?, "currency": state.settings.get("store.currency").await?,
        "checkout_mode": mode, "cms": sites.iter().map(|s| json!({ "host": s.host, "origin": s.origin })).collect::<Vec<_>>(),
        "counts": {
            "media": count("SELECT COUNT(*) FROM media").await?, "products_published": count("SELECT COUNT(*) FROM products WHERE status = 'published'").await?,
            "products_draft": count("SELECT COUNT(*) FROM products WHERE status = 'draft'").await?, "customers": count("SELECT COUNT(*) FROM users WHERE role = 'customer'").await?,
            "orders_paid": count("SELECT COUNT(*) FROM orders WHERE status = 'paid'").await?, "private_pages": count("SELECT COUNT(*) FROM private_pages").await?,
            "widgets": count("SELECT COUNT(*) FROM widgets").await?, "linked_shop_products": state.commerce_bridge.count(if mms_core::commerce_bridge::is_system(&mode) { &mode } else { "woocommerce" }).await?,
        },
        "categories": state.products.categories().await?.iter().map(|c| c.name.clone()).collect::<Vec<_>>(),
        "site_templates_applied": applications.iter().map(|(t, at)| json!({ "template": t, "applied_at": at })).collect::<Vec<_>>(),
        "health": health.checks.iter().map(|c| json!({ "name": c.name, "status": format!("{:?}", c.status).to_lowercase(), "detail": c.detail })).collect::<Vec<_>>(),
        "test_payments": state.settings.get("payments.test_mode").await? == "1",
        "smtp_set": !state.settings.get("mail.host").await?.trim().is_empty(),
    }))
}

// ----- applying proposals -----

/// Applies one proposal through the ordinary store code paths. `overrides` carries
/// values the administrator typed into the card (secrets). Returns a short result line.
pub async fn apply_proposal(
    state: &AppState,
    admin_id: i64,
    p: &Proposal,
    overrides: &HashMap<String, String>,
) -> anyhow::Result<String> {
    let payload: Value = serde_json::from_str(&p.payload).unwrap_or(json!({}));
    let s = |k: &str| payload[k].as_str().unwrap_or("").trim().to_string();
    let result = match p.kind.as_str() {
        "setting" => {
            let key = s("key");
            let value = overrides
                .get("value")
                .cloned()
                .filter(|v| !v.trim().is_empty())
                .unwrap_or_else(|| s("value"));
            if value.trim().is_empty() && p.needs_input == 1 {
                anyhow::bail!("Type the value into the card first");
            }
            state.settings.set(&key, &value).await?;
            format!("{key} saved")
        }
        "category" => match state.products.create_category(&s("name")).await {
            Ok(c) => format!("category {} created", c.name),
            Err(e) if e.to_string().contains("already exists") => {
                "category already existed".to_string()
            }
            Err(e) => return Err(e),
        },
        "product" => {
            let media_id = match s("media_uuid").as_str() {
                "" => None,
                u => state.media.by_uuid(u).await?.map(|m| m.id),
            };
            let preview_media_id = match s("preview_media_uuid").as_str() {
                "" => None,
                u => state.media.by_uuid(u).await?.map(|m| m.id),
            };
            let mut category_ids = Vec::new();
            for name in payload["categories"]
                .as_array()
                .cloned()
                .unwrap_or_default()
            {
                let name = name.as_str().unwrap_or("").trim().to_string();
                if name.is_empty() {
                    continue;
                }
                let existing = state
                    .products
                    .categories()
                    .await?
                    .into_iter()
                    .find(|c| c.name.eq_ignore_ascii_case(&name));
                let id = match existing {
                    Some(c) => c.id,
                    None => state.products.create_category(&name).await?.id,
                };
                category_ids.push(id);
            }
            let d = ProductDraft {
                r#type: s("type"),
                title: s("title"),
                slug: s("slug"),
                description: s("description"),
                price_cents: payload["price_cents"].as_i64().unwrap_or(0),
                currency: s("currency"),
                media_id,
                preview_media_id,
                settings: if payload["settings"].is_object() {
                    payload["settings"].clone()
                } else {
                    json!({})
                },
                featured: payload["featured"].as_bool().unwrap_or(false),
                status: s("status"),
                category_ids,
            };
            let created = state.products.create(&d).await?;
            format!("product {} created ({})", created.title, created.status)
        }
        "page" => {
            let product_id = match s("product_slug").as_str() {
                "" => None,
                slug => state.products.by_slug(slug).await?.map(|p| p.id),
            };
            let d = PageDraft {
                title: s("title"),
                content: s("content"),
                agreement: s("agreement"),
                signup_template: s("signup_template"),
                protection: s("protection"),
                product_id,
                incentive: s("incentive"),
                quiz_question: s("quiz_question"),
                quiz_answer: s("quiz_answer"),
                jurisdiction: s("jurisdiction"),
                min_age: payload["min_age"].as_i64().unwrap_or(0),
                status: s("status"),
            };
            let page = state.pages.create(&d).await?;
            format!("page {} created", page.title)
        }
        "coupon" => {
            let exp = s("expires_at");
            state
                .commerce
                .create_coupon(
                    &s("code"),
                    &s("kind"),
                    payload["amount"].as_i64().unwrap_or(0),
                    payload["max_uses"].as_i64().unwrap_or(0),
                    if exp.is_empty() {
                        None
                    } else {
                        Some(exp.as_str())
                    },
                )
                .await?;
            format!("coupon {} created", s("code"))
        }
        "tax_rate" => {
            state
                .commerce
                .set_tax_rate(
                    &s("country"),
                    &s("name"),
                    payload["rate_bp"].as_i64().unwrap_or(0),
                )
                .await?;
            format!("tax rate for {} saved", s("country"))
        }
        "site_template" => {
            let n =
                crate::routes::templates::apply_site_template(state, &s("slug"), admin_id).await?;
            format!("{n} widgets created and published")
        }
        other => anyhow::bail!("unknown proposal kind {other}"),
    };
    state
        .audit
        .record(
            Some(admin_id),
            "wizard.applied",
            "wizard_proposal",
            Some(&p.uuid),
            None,
            Some(json!({ "wizard": p.wizard, "kind": p.kind, "title": p.title })),
        )
        .await?;
    Ok(result)
}

// ----- pages -----

fn enabled_reason(state: &AppState, api_key: &str) -> Option<&'static str> {
    if state.wizard_transport.is_scripted() || !api_key.trim().is_empty() {
        None
    } else {
        Some("Add an Anthropic API key under Settings → AI to switch the wizards on.")
    }
}

fn session_view(s: &Session) -> Value {
    let def = wizards::wizard(&s.wizard);
    json!({ "uuid": s.uuid, "wizard": s.wizard, "title": def.map(|d| d.title).unwrap_or(&s.wizard), "status": s.status, "brief": s.brief, "summary": s.summary, "error": s.error, "turns": s.turns, "tokens": s.input_tokens + s.output_tokens, "cache_read": s.cache_read_tokens, "created_at": s.created_at, "updated_at": s.updated_at, "parent_id": s.parent_id })
}

#[derive(Deserialize)]
pub struct PageQuery {
    #[serde(default)]
    notice: String,
    #[serde(default)]
    error: String,
}

pub async fn page(
    State(state): State<AppState>,
    admin: AdminUser,
    axum::extract::Query(q): axum::extract::Query<PageQuery>,
) -> AppResult<Response> {
    let api_key = state.settings.get("ai.anthropic_api_key").await?;
    let sessions: Vec<Value> = state
        .wizards
        .sessions(40)
        .await?
        .iter()
        .map(session_view)
        .collect();
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("wizards.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "wizards", team => wizards::team(), sessions, disabled => enabled_reason(&state, &api_key), open => state.wizards.open_proposals().await?, model => state.settings.get("ai.model").await?, effort => state.settings.get("ai.effort").await?, notice => q.notice, error => q.error })?).into_response())
}

#[derive(Deserialize)]
pub struct StartForm {
    _csrf: String,
    wizard: String,
    #[serde(default)]
    brief: String,
}

pub async fn start(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<StartForm>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let api_key = state.settings.get("ai.anthropic_api_key").await?;
    if let Some(reason) = enabled_reason(&state, &api_key) {
        return Ok(Redirect::to(&state.url(&format!(
            "/admin/wizards?error={}",
            crate::routes::media::urlencoding(reason)
        )))
        .into_response());
    }
    if f.wizard == "assist" || wizards::wizard(&f.wizard).is_none() {
        return Ok(StatusCode::BAD_REQUEST.into_response());
    }
    let s = state
        .wizards
        .create_session(&f.wizard, &f.brief, "", None, Some(admin.user.id))
        .await?;
    state
        .jobs
        .enqueue("wizard.run", json!({ "session": s.uuid }))
        .await?;
    state
        .audit
        .record(
            Some(admin.user.id),
            "wizard.started",
            "wizard_session",
            Some(&s.uuid),
            None,
            Some(json!({ "wizard": f.wizard })),
        )
        .await?;
    Ok(Redirect::to(&state.url(&format!("/admin/wizards/{}", s.uuid))).into_response())
}

pub async fn session(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    axum::extract::Query(q): axum::extract::Query<PageQuery>,
) -> AppResult<Response> {
    let Some(s) = state.wizards.session_by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let def = wizards::wizard(&s.wizard);
    let proposals: Vec<Value> = state
        .wizards
        .proposals(s.id)
        .await?
        .iter()
        .map(proposal_view)
        .collect();
    let questions: Value = serde_json::from_str(&s.questions).unwrap_or(json!({}));
    let checklist: Value = serde_json::from_str(&s.checklist).unwrap_or(json!([]));
    let plan: Value = serde_json::from_str(&s.plan).unwrap_or(json!([]));
    let children: Vec<Value> = state
        .wizards
        .children(s.id)
        .await?
        .iter()
        .map(session_view)
        .collect();
    let parent = match s.parent_id {
        Some(id) => state
            .wizards
            .session_by_id(id)
            .await?
            .map(|p| session_view(&p)),
        None => None,
    };
    let paras = |t: &str| {
        t.lines()
            .map(str::trim)
            .filter(|l| !l.is_empty())
            .map(str::to_string)
            .collect::<Vec<_>>()
    };
    let transcript: Vec<Value> = state
        .wizards
        .transcript(s.id)
        .await?
        .into_iter()
        .map(|(r, t)| json!({ "role": r, "paras": paras(&t) }))
        .collect();
    let summary_paras = paras(&s.summary);
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("wizard_session.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "wizards", s => session_view(&s), def, proposals, questions => questions["questions"].clone(), checklist, plan, children, parent, transcript, summary_paras, notice => q.notice, error => q.error, refresh => matches!(s.status.as_str(), "queued" | "running") })?).into_response())
}

fn proposal_view(p: &Proposal) -> Value {
    let payload: Value = serde_json::from_str(&p.payload).unwrap_or(json!({}));
    json!({ "uuid": p.uuid, "kind": p.kind, "title": p.title, "reason": p.reason, "needs_input": p.needs_input == 1, "status": p.status, "result": p.result, "payload": payload, "payload_text": serde_json::to_string_pretty(&payload).unwrap_or_default() })
}

pub async fn answer(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let Some(s) = state.wizards.session_by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if s.status != "waiting" {
        return Ok(Redirect::to(&state.url(&format!(
            "/admin/wizards/{uuid}?error=This+session+is+not+waiting+for+answers"
        )))
        .into_response());
    }
    let pending: Value = serde_json::from_str(&s.questions).unwrap_or(json!({}));
    let mut answers = serde_json::Map::new();
    let mut lines = Vec::new();
    for q in pending["questions"].as_array().cloned().unwrap_or_default() {
        let key = q["key"].as_str().unwrap_or("").to_string();
        let a = f.get(&format!("q_{key}")).cloned().unwrap_or_default();
        lines.push(format!(
            "{}: {}",
            q["question"].as_str().unwrap_or(&key),
            a.trim()
        ));
        answers.insert(key, json!(a.trim()));
    }
    let mut results = pending["results"].as_array().cloned().unwrap_or_default();
    results.push(json!({ "type": "tool_result", "tool_use_id": s.pending_tool_use, "content": json!({ "answers": answers }).to_string() }));
    state
        .wizards
        .append_message(s.id, "user", &json!(results))
        .await?;
    let context = format!(
        "{}\nAdministrator's answers:\n{}",
        s.context.trim(),
        lines.join("\n")
    );
    sqlx::query("UPDATE wizard_sessions SET context = ?, status = 'queued', questions = '[]', pending_tool_use = '', updated_at = ? WHERE id = ?").bind(context.trim()).bind(mms_core::now()).bind(s.id).execute(&state.db.pool).await?;
    state
        .jobs
        .enqueue("wizard.run", json!({ "session": s.uuid }))
        .await?;
    Ok(Redirect::to(&state.url(&format!(
        "/admin/wizards/{uuid}?notice=Answers+sent.+The+wizard+is+working."
    )))
    .into_response())
}

pub async fn apply(
    State(state): State<AppState>,
    admin: AdminUser,
    Path((uuid, pid)): Path<(String, String)>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let Some(p) = state.wizards.proposal_by_uuid(&pid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if let Some(r) = admin_scope(&admin, &p) {
        return Ok(r);
    }
    let json_wanted = f.get("_format").map(String::as_str) == Some("json");
    let outcome = if p.status != "proposed" {
        Err(anyhow::anyhow!("already {}", p.status))
    } else {
        apply_proposal(&state, admin.user.id, &p, &f).await
    };
    let (status, result) = match &outcome {
        Ok(r) => ("applied", r.clone()),
        Err(e) => ("failed", e.to_string()),
    };
    if p.status == "proposed" {
        state.wizards.set_proposal(p.id, status, &result).await?;
    }
    if json_wanted {
        return Ok(Json(json!({ "status": status, "result": result })).into_response());
    }
    Ok(Redirect::to(&state.url(&format!(
        "/admin/wizards/{uuid}?{}={}",
        if status == "applied" {
            "notice"
        } else {
            "error"
        },
        crate::routes::media::urlencoding(&result)
    )))
    .into_response())
}

/// Staff may run wizards and apply catalogue proposals; settings and site templates are for administrators.
fn admin_scope(admin: &AdminUser, p: &Proposal) -> Option<Response> {
    if matches!(p.kind.as_str(), "setting" | "site_template") {
        admin.admin_only()
    } else {
        None
    }
}

pub async fn skip(
    State(state): State<AppState>,
    admin: AdminUser,
    Path((uuid, pid)): Path<(String, String)>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    if let Some(p) = state.wizards.proposal_by_uuid(&pid).await? {
        if p.status == "proposed" {
            state.wizards.set_proposal(p.id, "skipped", "").await?;
        }
    }
    Ok(
        Redirect::to(&state.url(&format!("/admin/wizards/{uuid}?notice=Proposal+skipped.")))
            .into_response(),
    )
}

pub async fn apply_all(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let Some(s) = state.wizards.session_by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let (mut ok, mut failed, mut skipped) = (0, 0, 0);
    for p in state.wizards.proposals(s.id).await? {
        if p.status != "proposed" {
            continue;
        }
        if p.needs_input == 1 || admin_scope(&admin, &p).is_some() {
            skipped += 1;
            continue;
        }
        match apply_proposal(&state, admin.user.id, &p, &HashMap::new()).await {
            Ok(r) => {
                state.wizards.set_proposal(p.id, "applied", &r).await?;
                ok += 1
            }
            Err(e) => {
                state
                    .wizards
                    .set_proposal(p.id, "failed", &e.to_string())
                    .await?;
                failed += 1
            }
        }
    }
    Ok(Redirect::to(&state.url(&format!("/admin/wizards/{uuid}?notice={}", crate::routes::media::urlencoding(&format!("{ok} applied, {failed} failed, {skipped} left for you (secrets or administrator-only)."))))).into_response())
}

// ----- the form assistant (drawer on every admin page) -----

#[derive(Deserialize)]
pub struct AskBody {
    #[serde(default)]
    page: String,
    #[serde(default)]
    question: String,
}

pub async fn ask(
    State(state): State<AppState>,
    admin: AdminUser,
    Json(b): Json<AskBody>,
) -> AppResult<Response> {
    let api_key = state.settings.get("ai.anthropic_api_key").await?;
    if let Some(reason) = enabled_reason(&state, &api_key) {
        return Ok(Json(json!({ "error": reason })).into_response());
    }
    let question = b.question.trim().to_string();
    if question.is_empty() {
        return Ok(Json(json!({ "error": "Ask a question first." })).into_response());
    }
    let page = b.page.trim().chars().take(120).collect::<String>();
    let context = format!("The administrator is on the admin page \"{page}\". Sections on the settings page are addressed by the part after #.");
    let s = state
        .wizards
        .create_session("assist", &question, &context, None, Some(admin.user.id))
        .await?;
    let outcome = run_session(&state, s.id).await;
    let after = state.wizards.session_by_id(s.id).await?.unwrap_or(s);
    let proposals: Vec<Value> = state
        .wizards
        .proposals(after.id)
        .await?
        .iter()
        .map(proposal_view)
        .collect();
    let answer = if after.summary.trim().is_empty() {
        state
            .wizards
            .transcript(after.id)
            .await?
            .into_iter()
            .rev()
            .find(|(r, _)| r == "assistant")
            .map(|(_, t)| t)
            .unwrap_or_default()
    } else {
        after.summary.clone()
    };
    Ok(Json(json!({ "session": after.uuid, "status": after.status, "answer": answer, "error": match outcome { Ok(()) => after.error, Err(e) => e.to_string() }, "proposals": proposals })).into_response())
}
