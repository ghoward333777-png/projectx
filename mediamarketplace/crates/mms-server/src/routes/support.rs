//! Support chat: the visitor chat (embedded on the site or under My media), the AI
//! first-line assistant, the agent console for remote support agents, invite links for
//! contractors, and the administrator's overview. Polling over plain HTTP so it works
//! through the CMS proxy. Agents never reach admin pages; administrators and staff are
//! agents too.

use crate::app::AppState;
use crate::auth::{self, AdminUser, AgentUser, MaybeUser};
use crate::errors::AppResult;
use crate::routes::customers::CsrfOnly;
use axum::extract::{Path, Query, State};
use axum::http::{header, StatusCode};
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::{Form, Json};
use axum_extra::extract::cookie::{Cookie, CookieJar, SameSite};
use minijinja::context;
use mms_core::support::{self, Conversation, Support};
use mms_core::users::User;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;

pub const CHAT_COOKIE: &str = "mms_chat";

fn visitor_token(jar: &CookieJar, uuid: &str) -> String {
    jar.get(CHAT_COOKIE)
        .map(|c| c.value().to_string())
        .and_then(|v| {
            v.split_once(':')
                .map(|(u, t)| (u.to_string(), t.to_string()))
        })
        .filter(|(u, _)| u == uuid)
        .map(|(_, t)| t)
        .unwrap_or_default()
}

fn chat_cookie(state: &AppState, uuid: &str, token: &str) -> Cookie<'static> {
    Cookie::build((CHAT_COOKIE, format!("{uuid}:{token}")))
        .path(auth::cookie_path(state))
        .http_only(true)
        .same_site(SameSite::Lax)
        .max_age(time::Duration::days(30))
        .build()
}

async fn agent_name(state: &AppState, id: Option<i64>) -> AppResult<String> {
    Ok(match id {
        Some(id) => state
            .users
            .by_id(id)
            .await?
            .map(|u| u.name)
            .unwrap_or_default(),
        None => String::new(),
    })
}

fn msg_view(m: &support::ChatMessage) -> Value {
    json!({ "id": m.id, "sender": m.sender, "name": m.sender_name, "body": m.body, "internal": m.internal == 1, "at": m.created_at })
}

async fn visitor_conversation(
    state: &AppState,
    user: &Option<User>,
    jar: &CookieJar,
    uuid: &str,
) -> AppResult<Result<Conversation, Response>> {
    let Some(c) = state.support.by_uuid(uuid).await? else {
        return Ok(Err((
            StatusCode::NOT_FOUND,
            Json(json!({ "error": "No such conversation" })),
        )
            .into_response()));
    };
    if !Support::visitor_may_open(&c, user.as_ref().map(|u| u.id), &visitor_token(jar, uuid)) {
        return Ok(Err((
            StatusCode::FORBIDDEN,
            Json(json!({ "error": "Not your conversation" })),
        )
            .into_response()));
    }
    Ok(Ok(c))
}

// ----- visitor -----

#[derive(Deserialize)]
pub struct ChatQuery {
    #[serde(default)]
    site: Option<String>,
    #[serde(default)]
    subject: String,
}

/// The chat page: embedded on the site (`?site=`) or opened from My media.
pub async fn embed_chat(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Query(q): Query<ChatQuery>,
) -> AppResult<Response> {
    let csp = match q.site.as_deref() {
        Some(site) => match crate::routes::bridges::by_uuid(&state, site).await? {
            Some(s) => format!("frame-ancestors 'self' {}", s.origin),
            None => return Ok((StatusCode::FORBIDDEN, "Unknown site").into_response()),
        },
        None => "frame-ancestors 'self'".to_string(),
    };
    let mode = state.settings.get("chat.mode").await?;
    let guests = state.settings.get("chat.guest").await? == "1";
    // Resume the visitor's open conversation when there is one.
    let existing = match &user {
        Some(u) => state
            .support
            .for_visitor(u.id)
            .await?
            .into_iter()
            .find(|c| c.status != "closed")
            .map(|c| c.uuid),
        None => jar
            .get(CHAT_COOKIE)
            .and_then(|c| c.value().split_once(':').map(|(u, _)| u.to_string())),
    };
    let existing = match existing {
        Some(uuid) => match state.support.by_uuid(&uuid).await? {
            Some(c)
                if Support::visitor_may_open(
                    &c,
                    user.as_ref().map(|u| u.id),
                    &visitor_token(&jar, &uuid),
                ) =>
            {
                Some(c.uuid)
            }
            _ => None,
        },
        None => None,
    };
    let site_name = state.settings.get("general.site_name").await?;
    let html = state.render("chat.html", context! {
        site_name, user, mode, guests, existing => existing.unwrap_or_default(), subject => q.subject, site => q.site.clone().unwrap_or_default(),
        greeting => state.settings.get("chat.greeting").await?, offline => state.settings.get("chat.offline_message").await?,
        online => !state.support.online_agents().await?.is_empty(), login_url => state.url("/login?return=%2Faccount%2Fhelp"),
    })?;
    Ok((
        [
            (header::CONTENT_SECURITY_POLICY, csp),
            (header::CACHE_CONTROL, "private, no-store".to_string()),
        ],
        Html(html),
    )
        .into_response())
}

/// My media → Help: the chat inside the account pages.
pub async fn account_help(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login?return=%2Faccount%2Fhelp")).into_response());
    };
    let site_name = state.settings.get("general.site_name").await?;
    let history = state.support.for_visitor(user.id).await?;
    Ok(Html(state.render("account_help.html", context! { user, site_name, tab => "help", history, public_url => state.config.server.public_url })?).into_response())
}

#[derive(Deserialize)]
pub struct StartBody {
    #[serde(default)]
    site: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    email: String,
    #[serde(default)]
    subject: String,
    #[serde(default)]
    page: String,
    #[serde(default)]
    message: String,
}

pub async fn start(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Json(b): Json<StartBody>,
) -> AppResult<Response> {
    if state.settings.get("chat.mode").await? == "off" {
        return Ok((
            StatusCode::FORBIDDEN,
            Json(json!({ "error": "The support chat is switched off" })),
        )
            .into_response());
    }
    if user.is_none() && state.settings.get("chat.guest").await? != "1" {
        return Ok((
            StatusCode::FORBIDDEN,
            Json(json!({ "error": "Please sign in to chat with us" })),
        )
            .into_response());
    }
    if !b.site.is_empty()
        && crate::routes::bridges::by_uuid(&state, &b.site)
            .await?
            .is_none()
    {
        return Ok((
            StatusCode::FORBIDDEN,
            Json(json!({ "error": "Unknown site" })),
        )
            .into_response());
    }
    let token = if user.is_some() {
        String::new()
    } else {
        support::new_token()
    };
    let conv = match state
        .support
        .start(
            user.as_ref().map(|u| u.id),
            &b.name,
            &b.email,
            &token,
            &b.site,
            &b.page,
            &b.subject,
        )
        .await
    {
        Ok(c) => c,
        Err(e) => {
            return Ok((
                StatusCode::BAD_REQUEST,
                Json(json!({ "error": e.to_string() })),
            )
                .into_response())
        }
    };
    let jar = if user.is_none() {
        jar.add(chat_cookie(&state, &conv.uuid, &token))
    } else {
        jar
    };
    let mut messages = Vec::new();
    if !b.message.trim().is_empty() {
        let name = user
            .as_ref()
            .map(|u| u.name.clone())
            .unwrap_or_else(|| conv.guest_name.clone());
        state
            .support
            .add_message(
                &conv,
                "visitor",
                user.as_ref().map(|u| u.id),
                &name,
                &b.message,
                false,
            )
            .await?;
        messages = after_visitor_message(&state, &conv, &user).await?;
    }
    let conv = state.support.by_id(conv.id).await?.unwrap_or(conv);
    Ok((jar, Json(json!({ "conversation": conv.uuid, "status": conv.status, "messages": messages.iter().map(msg_view).collect::<Vec<_>>() }))).into_response())
}

#[derive(Deserialize)]
pub struct SendBody {
    #[serde(default)]
    body: String,
}

pub async fn send(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Path(uuid): Path<String>,
    Json(b): Json<SendBody>,
) -> AppResult<Response> {
    let conv = match visitor_conversation(&state, &user, &jar, &uuid).await? {
        Ok(c) => c,
        Err(r) => return Ok(r),
    };
    let name = user
        .as_ref()
        .map(|u| u.name.clone())
        .unwrap_or_else(|| conv.guest_name.clone());
    let m = match state
        .support
        .add_message(
            &conv,
            "visitor",
            user.as_ref().map(|u| u.id),
            &name,
            &b.body,
            false,
        )
        .await
    {
        Ok(m) => m,
        Err(e) => {
            return Ok((
                StatusCode::BAD_REQUEST,
                Json(json!({ "error": e.to_string() })),
            )
                .into_response())
        }
    };
    let new = after_visitor_message(&state, &conv, &user).await?;
    let conv = state.support.by_id(conv.id).await?.unwrap_or(conv);
    Ok(Json(json!({ "status": conv.status, "sent": m.id, "messages": new.iter().map(msg_view).collect::<Vec<_>>() })).into_response())
}

#[derive(Deserialize)]
pub struct PollQuery {
    #[serde(default)]
    after: i64,
}

pub async fn poll(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Path(uuid): Path<String>,
    Query(q): Query<PollQuery>,
) -> AppResult<Response> {
    let conv = match visitor_conversation(&state, &user, &jar, &uuid).await? {
        Ok(c) => c,
        Err(r) => return Ok(r),
    };
    let messages = state.support.messages(conv.id, q.after, false).await?;
    if let Some(last) = messages.last() {
        state.support.mark_read(conv.id, "visitor", last.id).await?;
    }
    let agent = agent_name(&state, conv.assigned_to).await?;
    Ok(Json(json!({ "status": conv.status, "agent": agent, "online": !state.support.online_agents().await?.is_empty(), "rating": conv.rating, "messages": messages.iter().map(msg_view).collect::<Vec<_>>() })).into_response())
}

#[derive(Deserialize)]
pub struct RateBody {
    rating: i64,
    #[serde(default)]
    note: String,
}

pub async fn rate(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Path(uuid): Path<String>,
    Json(b): Json<RateBody>,
) -> AppResult<Response> {
    let conv = match visitor_conversation(&state, &user, &jar, &uuid).await? {
        Ok(c) => c,
        Err(r) => return Ok(r),
    };
    if let Err(e) = state.support.rate(conv.id, b.rating, &b.note).await {
        return Ok((
            StatusCode::BAD_REQUEST,
            Json(json!({ "error": e.to_string() })),
        )
            .into_response());
    }
    Ok(Json(json!({ "ok": true })).into_response())
}

pub async fn visitor_close(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let conv = match visitor_conversation(&state, &user, &jar, &uuid).await? {
        Ok(c) => c,
        Err(r) => return Ok(r),
    };
    state.support.set_status(conv.id, "closed").await?;
    state
        .support
        .add_message(
            &conv,
            "system",
            None,
            "",
            "The visitor ended the conversation.",
            false,
        )
        .await?;
    Ok(Json(json!({ "ok": true, "status": "closed" })).into_response())
}

/// What happens after a visitor writes: the assistant answers, or the conversation waits for an agent.
async fn after_visitor_message(
    state: &AppState,
    conv: &Conversation,
    user: &Option<User>,
) -> AppResult<Vec<support::ChatMessage>> {
    let before = state
        .support
        .messages(conv.id, 0, false)
        .await?
        .last()
        .map(|m| m.id)
        .unwrap_or(0);
    let conv = state.support.by_id(conv.id).await?.unwrap_or(conv.clone());
    let mode = state.settings.get("chat.mode").await?;
    match conv.status.as_str() {
        "assigned" => {} // the agent replies
        "closed" => {
            // Re-open, keeping the agent who handled it.
            state
                .support
                .set_status(
                    conv.id,
                    if conv.assigned_to.is_some() {
                        "assigned"
                    } else {
                        "waiting"
                    },
                )
                .await?;
            if conv.assigned_to.is_none() {
                wait_for_agent(
                    state,
                    &conv,
                    "The visitor wrote again after the conversation was closed.",
                )
                .await?;
            }
        }
        "waiting" => {}
        _ => {
            if mode == "agents_only" {
                wait_for_agent(state, &conv, "").await?;
            } else if let Err(e) = run_assistant(state, &conv, user).await {
                tracing::warn!(error = %e, "support assistant unavailable; handing over");
                wait_for_agent(state, &conv, "The assistant was unavailable.").await?;
            }
        }
    }
    Ok(state.support.messages(conv.id, before, false).await?)
}

async fn wait_for_agent(state: &AppState, conv: &Conversation, note: &str) -> AppResult<()> {
    state.support.assign(conv.id, None).await?;
    if !note.is_empty() {
        state
            .support
            .add_message(conv, "agent", None, "System", note, true)
            .await?;
    }
    let online = !state.support.online_agents().await?.is_empty();
    let text = if online {
        "You're being connected to a support agent."
    } else {
        &state.settings.get("chat.offline_message").await?
    };
    state
        .support
        .add_message(conv, "system", None, "", text, false)
        .await?;
    notify_agents(state, conv).await;
    Ok(())
}

async fn notify_agents(state: &AppState, conv: &Conversation) {
    if state
        .settings
        .get("chat.notify_agents")
        .await
        .unwrap_or_default()
        != "1"
    {
        return;
    }
    let Ok(agents) = state.support.agents().await else {
        return;
    };
    let link = format!(
        "{}/agent/c/{}",
        state.config.server.public_url.trim_end_matches('/'),
        conv.uuid
    );
    let who = if conv.guest_name.is_empty() {
        "a customer".to_string()
    } else {
        conv.guest_name.clone()
    };
    let text = format!(
        "{who} is waiting in the support chat{}.\n\nOpen the conversation: {link}",
        if conv.subject.is_empty() {
            String::new()
        } else {
            format!(": {}", conv.subject)
        }
    );
    for a in agents {
        crate::routes::ops::send_quietly(
            state,
            &a.email,
            "A visitor is waiting in the support chat",
            &text,
            None,
            None,
            "chat.waiting",
        )
        .await;
    }
}

/// The AI first line: up to a few tool turns, then a reply or a hand-over.
async fn run_assistant(
    state: &AppState,
    conv: &Conversation,
    user: &Option<User>,
) -> anyhow::Result<()> {
    let api_key = state.settings.get("ai.anthropic_api_key").await?;
    if !state.wizard_transport.is_scripted() && api_key.trim().is_empty() {
        anyhow::bail!("no Anthropic API key");
    }
    let model = {
        let m = state.settings.get("ai.model").await?;
        if m.trim().is_empty() {
            mms_core::wizards::DEFAULT_MODEL.to_string()
        } else {
            m
        }
    };
    let site_name = state.settings.get("general.site_name").await?;
    let policy = state.settings.get("chat.policy").await?;
    let visitor = match user {
        Some(u) => format!("The visitor is signed in as {} ({}).", u.name, u.email),
        None => format!(
            "The visitor is a guest named {} ({}); you cannot look up records for guests.",
            conv.guest_name, conv.guest_email
        ),
    };
    let system = format!("{}\n\nStore: {site_name}. {visitor}\n\nStore policy and facts (the only facts you may state beyond the visitor's own records):\n{}", support::ASSISTANT_RULES, if policy.trim().is_empty() { "(none given; keep to how the store works and hand over for anything else)" } else { policy.trim() });
    let mut messages =
        support::transcript_for_model(&state.support.messages(conv.id, 0, false).await?);
    let tools = support::assistant_tools();
    for _ in 0..support::ASSISTANT_MAX_TURNS {
        let body = json!({ "model": model, "max_tokens": 1200, "thinking": { "type": "adaptive" }, "output_config": { "effort": "low" },
            "system": [{ "type": "text", "text": system, "cache_control": { "type": "ephemeral" } }], "tools": tools, "messages": messages });
        let resp = state.wizard_transport.send(&api_key, &body).await?;
        let content = resp["content"].as_array().cloned().unwrap_or_default();
        let text: String = content
            .iter()
            .filter(|b| b["type"] == "text")
            .map(|b| b["text"].as_str().unwrap_or(""))
            .collect::<Vec<_>>()
            .join("\n")
            .trim()
            .to_string();
        let stop = resp["stop_reason"].as_str().unwrap_or("end_turn");
        if stop == "refusal" {
            wait_for_agent(state, conv, "The assistant declined to answer.")
                .await
                .map_err(|e| e.0)?;
            return Ok(());
        }
        if !text.is_empty() {
            state
                .support
                .add_message(conv, "assistant", None, "Assistant", &text, false)
                .await?;
        }
        if stop != "tool_use" {
            return Ok(());
        }
        messages.push(json!({ "role": "assistant", "content": content }));
        let mut results = Vec::new();
        let mut handed_over = false;
        for b in content.iter().filter(|b| b["type"] == "tool_use") {
            let id = b["id"].as_str().unwrap_or("");
            let input = &b["input"];
            let result = match b["name"].as_str().unwrap_or("") {
                "read_help" => {
                    let topic = input["topic"].as_str().unwrap_or("").trim();
                    json!({ "topic": topic, "help": support::help(topic).unwrap_or("No such topic; topics: open, receipts, passes, signin, downloads, refunds, agreements, privacy") })
                }
                "lookup_customer" => match user {
                    Some(u) => customer_summary(state, u.id).await.map_err(|e| e.0)?,
                    None => {
                        json!({ "guest": true, "note": "Not signed in; no records available. Suggest signing in via My media, or hand over." })
                    }
                },
                "escalate" => {
                    let reason = input["reason"].as_str().unwrap_or("").trim();
                    let summary = input["summary"].as_str().unwrap_or("").trim();
                    wait_for_agent(
                        state,
                        conv,
                        &format!("Assistant handed over. Reason: {reason}. Summary: {summary}"),
                    )
                    .await
                    .map_err(|e| e.0)?;
                    handed_over = true;
                    json!({ "ok": true, "note": "A human agent will take over; tell the visitor briefly and stop." })
                }
                "resolve" => json!({ "ok": true }),
                other => json!({ "error": format!("unknown tool {other}") }),
            };
            results.push(
                json!({ "type": "tool_result", "tool_use_id": id, "content": result.to_string() }),
            );
        }
        messages.push(json!({ "role": "user", "content": results }));
        if handed_over {
            return Ok(());
        }
    }
    Ok(())
}

/// The visitor's own records, for the assistant and the agent console.
async fn customer_summary(state: &AppState, user_id: i64) -> AppResult<Value> {
    let orders = state.commerce.orders("", "", Some(user_id)).await?;
    let now = mms_core::now();
    let mut access = Vec::new();
    for e in state.entitlements.for_user(user_id).await? {
        if e.status != "active"
            || e.ends_at
                .as_deref()
                .map(|t| t <= now.as_str())
                .unwrap_or(false)
        {
            continue;
        }
        let title = match e.product_id {
            Some(id) => state.products.by_id(id).await?.map(|p| p.title),
            None => None,
        };
        access.push(
            json!({ "scope": e.scope, "product": title, "ends_at": e.ends_at, "source": e.source }),
        );
    }
    let subs = state.commerce.subscriptions_for(user_id).await?;
    Ok(json!({
        "orders": orders.iter().take(20).map(|o| json!({ "number": o.number, "status": o.status, "total": mms_core::commerce::money(o.total_cents, &o.currency), "paid_at": o.paid_at, "gateway": o.gateway })).collect::<Vec<_>>(),
        "access": access,
        "passes": subs.iter().map(|s| json!({ "status": s.status, "interval": s.interval, "period_end": s.period_end, "cancel_at_period_end": s.cancel_at_period_end == 1 })).collect::<Vec<_>>(),
    }))
}

// ----- agents -----

#[derive(Deserialize)]
pub struct ConsoleQuery {
    #[serde(default)]
    tab: String,
    #[serde(default)]
    notice: String,
    #[serde(default)]
    error: String,
}

async fn conv_view(state: &AppState, c: &Conversation) -> AppResult<Value> {
    let unread = state
        .support
        .messages(c.id, c.agent_read_id, false)
        .await?
        .into_iter()
        .filter(|m| m.sender == "visitor")
        .count();
    Ok(
        json!({ "uuid": c.uuid, "status": c.status, "subject": c.subject, "name": if c.guest_name.is_empty() { match c.user_id { Some(id) => state.users.by_id(id).await?.map(|u| u.name).unwrap_or_default(), None => String::new() } } else { c.guest_name.clone() },
        "email": if c.guest_email.is_empty() { match c.user_id { Some(id) => state.users.by_id(id).await?.map(|u| u.email).unwrap_or_default(), None => String::new() } } else { c.guest_email.clone() },
        "customer": c.user_id.is_some(), "agent": agent_name(state, c.assigned_to).await?, "assigned_to": c.assigned_to, "last": c.last_message_at, "created": c.created_at, "unread": unread, "rating": c.rating, "ai_turns": c.ai_turns, "page": c.page_url }),
    )
}

pub async fn console(
    State(state): State<AppState>,
    agent: AgentUser,
    Query(q): Query<ConsoleQuery>,
) -> AppResult<Response> {
    state.users.touch_seen(agent.user.id).await?;
    let tab = if q.tab.is_empty() {
        "waiting".to_string()
    } else {
        q.tab.clone()
    };
    let list = match tab.as_str() {
        "mine" => state
            .support
            .list("", Some(agent.user.id), 100)
            .await?
            .into_iter()
            .filter(|c| c.status != "closed")
            .collect(),
        "open" => state.support.list("open", None, 100).await?,
        "closed" => state.support.list("closed", None, 100).await?,
        _ => state.support.list("waiting", None, 100).await?,
    };
    let mut rows = Vec::new();
    for c in &list {
        rows.push(conv_view(&state, c).await?);
    }
    let online: Vec<Value> = state
        .support
        .online_agents()
        .await?
        .iter()
        .map(|a| json!({ "name": a.name, "role": if a.agent == 1 { "agent" } else { &a.role } }))
        .collect();
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("agent_console.html", context! { user => agent.user, csrf => agent.csrf, site_name, tab, rows, online, counts => state.support.counts().await?, notice => q.notice, error => q.error, is_staff => agent.user.is_staff() })?).into_response())
}

pub async fn conversation(
    State(state): State<AppState>,
    agent: AgentUser,
    Path(uuid): Path<String>,
    Query(q): Query<ConsoleQuery>,
) -> AppResult<Response> {
    state.users.touch_seen(agent.user.id).await?;
    let Some(c) = state.support.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let messages: Vec<Value> = state
        .support
        .messages(c.id, 0, true)
        .await?
        .iter()
        .map(msg_view)
        .collect();
    if let Some(last) = messages.last() {
        state
            .support
            .mark_read(c.id, "agent", last["id"].as_i64().unwrap_or(0))
            .await?;
    }
    let customer = match c.user_id {
        Some(id) => Some(customer_summary(&state, id).await?),
        None => None,
    };
    let agents: Vec<Value> = state
        .support
        .agents()
        .await?
        .iter()
        .filter(|a| a.id != agent.user.id)
        .map(|a| json!({ "id": a.id, "name": a.name }))
        .collect();
    let canned: Vec<String> = state
        .settings
        .get("chat.canned")
        .await?
        .split('|')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("agent_conversation.html", context! { user => agent.user, csrf => agent.csrf, site_name, c => conv_view(&state, &c).await?, messages, customer, agents, canned, mine => c.assigned_to == Some(agent.user.id), notice => q.notice, error => q.error, is_staff => agent.user.is_staff(), ai => state.wizard_transport.is_scripted() || !state.settings.get("ai.anthropic_api_key").await?.trim().is_empty() })?).into_response())
}

pub async fn agent_poll(
    State(state): State<AppState>,
    agent: AgentUser,
    Path(uuid): Path<String>,
    Query(q): Query<PollQuery>,
) -> AppResult<Response> {
    state.users.touch_seen(agent.user.id).await?;
    let Some(c) = state.support.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let messages = state.support.messages(c.id, q.after, true).await?;
    if let Some(last) = messages.last() {
        state.support.mark_read(c.id, "agent", last.id).await?;
    }
    Ok(Json(json!({ "status": c.status, "agent": agent_name(&state, c.assigned_to).await?, "messages": messages.iter().map(msg_view).collect::<Vec<_>>() })).into_response())
}

pub async fn heartbeat(State(state): State<AppState>, agent: AgentUser) -> AppResult<Response> {
    state.users.touch_seen(agent.user.id).await?;
    let waiting: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM chat_conversations WHERE status = 'waiting'")
            .fetch_one(&state.db.pool)
            .await?;
    Ok(
        Json(json!({ "waiting": waiting, "online": state.support.online_agents().await?.len() }))
            .into_response(),
    )
}

pub async fn reply(
    State(state): State<AppState>,
    agent: AgentUser,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = agent.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let Some(c) = state.support.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let internal = f.get("internal").map(|v| v == "1").unwrap_or(false);
    let json_wanted = f.get("_format").map(String::as_str) == Some("json");
    if !internal && c.assigned_to != Some(agent.user.id) {
        state.support.assign(c.id, Some(agent.user.id)).await?;
        if c.assigned_to.is_none() {
            state
                .support
                .add_message(
                    &c,
                    "system",
                    None,
                    "",
                    &format!("{} joined the conversation.", agent.user.name),
                    false,
                )
                .await?;
        }
    }
    match state
        .support
        .add_message(
            &c,
            "agent",
            Some(agent.user.id),
            &agent.user.name,
            f.get("body").map(String::as_str).unwrap_or(""),
            internal,
        )
        .await
    {
        Ok(m) => {
            state
                .audit
                .record(
                    Some(agent.user.id),
                    if internal { "chat.note" } else { "chat.reply" },
                    "chat",
                    Some(&c.uuid),
                    None,
                    None,
                )
                .await?;
            if json_wanted {
                Ok(Json(json!({ "ok": true, "message": msg_view(&m) })).into_response())
            } else {
                Ok(Redirect::to(&state.url(&format!("/agent/c/{uuid}"))).into_response())
            }
        }
        Err(e) => Ok(if json_wanted {
            (
                StatusCode::BAD_REQUEST,
                Json(json!({ "error": e.to_string() })),
            )
                .into_response()
        } else {
            Redirect::to(&state.url(&format!(
                "/agent/c/{uuid}?error={}",
                crate::routes::media::urlencoding(&e.to_string())
            )))
            .into_response()
        }),
    }
}

pub async fn assign(
    State(state): State<AppState>,
    agent: AgentUser,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = agent.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let Some(c) = state.support.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let to: Option<i64> = f
        .get("agent_id")
        .and_then(|v| v.parse().ok())
        .filter(|id: &i64| *id > 0)
        .or(Some(agent.user.id));
    let target = match to {
        Some(id) => state.users.by_id(id).await?.filter(|u| u.is_agent()),
        None => None,
    };
    let Some(target) = target else {
        return Ok(Redirect::to(&state.url(&format!(
            "/agent/c/{uuid}?error=That+person+is+not+an+agent"
        )))
        .into_response());
    };
    state.support.assign(c.id, Some(target.id)).await?;
    state
        .support
        .add_message(
            &c,
            "system",
            None,
            "",
            &format!("{} joined the conversation.", target.name),
            false,
        )
        .await?;
    state
        .audit
        .record(
            Some(agent.user.id),
            "chat.assigned",
            "chat",
            Some(&c.uuid),
            None,
            Some(json!({ "to": target.id })),
        )
        .await?;
    Ok(Redirect::to(&state.url(&format!(
        "/agent/c/{uuid}?notice=Assigned+to+{}",
        crate::routes::media::urlencoding(&target.name)
    )))
    .into_response())
}

pub async fn release(
    State(state): State<AppState>,
    agent: AgentUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = agent.csrf_error(&f._csrf) {
        return Ok(r);
    }
    if let Some(c) = state.support.by_uuid(&uuid).await? {
        state.support.assign(c.id, None).await?;
        notify_agents(&state, &c).await;
    }
    Ok(
        Redirect::to(&state.url(&format!("/agent/c/{uuid}?notice=Back+in+the+queue")))
            .into_response(),
    )
}

pub async fn close(
    State(state): State<AppState>,
    agent: AgentUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = agent.csrf_error(&f._csrf) {
        return Ok(r);
    }
    if let Some(c) = state.support.by_uuid(&uuid).await? {
        state.support.set_status(c.id, "closed").await?;
        state
            .support
            .add_message(
                &c,
                "system",
                None,
                "",
                "The conversation was closed. Write again any time.",
                false,
            )
            .await?;
        state
            .audit
            .record(
                Some(agent.user.id),
                "chat.closed",
                "chat",
                Some(&c.uuid),
                None,
                None,
            )
            .await?;
    }
    Ok(Redirect::to(&state.url(&format!("/agent/c/{uuid}?notice=Closed"))).into_response())
}

/// An AI draft of the agent's next reply, from the transcript and the visitor's records.
pub async fn suggest(
    State(state): State<AppState>,
    agent: AgentUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = agent.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let Some(c) = state.support.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let api_key = state.settings.get("ai.anthropic_api_key").await?;
    if !state.wizard_transport.is_scripted() && api_key.trim().is_empty() {
        return Ok(
            Json(json!({ "error": "Add an Anthropic API key under Settings → AI" }))
                .into_response(),
        );
    }
    let model = {
        let m = state.settings.get("ai.model").await?;
        if m.trim().is_empty() {
            mms_core::wizards::DEFAULT_MODEL.to_string()
        } else {
            m
        }
    };
    let records = match c.user_id {
        Some(id) => customer_summary(&state, id).await?.to_string(),
        None => "guest, no records".to_string(),
    };
    let transcript = state
        .support
        .messages(c.id, 0, true)
        .await?
        .iter()
        .map(|m| {
            format!(
                "{}{}: {}",
                m.sender,
                if m.internal == 1 {
                    " (internal note)"
                } else {
                    ""
                },
                m.body
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    let policy = state.settings.get("chat.policy").await?;
    let body = json!({ "model": model, "max_tokens": 800, "thinking": { "type": "adaptive" }, "output_config": { "effort": "low" },
        "system": [{ "type": "text", "text": format!("You draft replies for a human support agent of a media store. Write only the reply text the agent would send: warm, concrete, two to six sentences, no greeting boilerplate, no promises the agent cannot keep. Facts you may use: the visitor's records and the store policy below.\n\nStore policy:\n{policy}\n\nVisitor records:\n{records}") }],
        "messages": [{ "role": "user", "content": format!("Transcript so far:\n{transcript}\n\nDraft the agent's next reply.") }] });
    let resp = match state.wizard_transport.send(&api_key, &body).await {
        Ok(r) => r,
        Err(e) => return Ok(Json(json!({ "error": e.to_string() })).into_response()),
    };
    let draft: String = resp["content"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .iter()
        .filter(|b| b["type"] == "text")
        .map(|b| b["text"].as_str().unwrap_or(""))
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string();
    Ok(Json(json!({ "draft": draft })).into_response())
}

// ----- invites -----

#[derive(Deserialize)]
pub struct JoinQuery {
    #[serde(default)]
    token: String,
}

pub async fn join_form(
    State(state): State<AppState>,
    Query(q): Query<JoinQuery>,
) -> AppResult<Response> {
    let site_name = state.settings.get("general.site_name").await?;
    let invite = state.support.invite_by_token(&q.token).await?;
    Ok(Html(state.render(
        "agent_join.html",
        context! { site_name, token => q.token, invite, error => "" },
    )?)
    .into_response())
}

#[derive(Deserialize)]
pub struct JoinForm {
    token: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    password: String,
    #[serde(default)]
    password_repeat: String,
}

pub async fn join(
    State(state): State<AppState>,
    jar: CookieJar,
    Form(f): Form<JoinForm>,
) -> AppResult<Response> {
    let site_name = state.settings.get("general.site_name").await?;
    let Some(invite) = state.support.invite_by_token(&f.token).await? else {
        return Ok(Html(state.render("agent_join.html", context! { site_name, token => f.token, invite => Value::Null, error => "This invitation is no longer valid." })?).into_response());
    };
    let err = |msg: &str| {
        state.render("agent_join.html", context! { site_name, token => f.token.clone(), invite => invite.clone(), error => msg }).map(|h| Html(h).into_response())
    };
    if f.password.len() < 10 {
        return Ok(err("Choose a password of at least 10 characters.")?);
    }
    if f.password != f.password_repeat {
        return Ok(err("The passwords do not match.")?);
    }
    let name = if f.name.trim().is_empty() {
        invite.name.clone()
    } else {
        f.name.trim().to_string()
    };
    let user = match state.users.by_email(&invite.email).await? {
        Some(u) => {
            if u.role == "customer" && !u.is_staff() {
                state.users.set_password(u.id, &f.password).await?;
            }
            u
        }
        None => {
            state
                .users
                .create(&invite.email, &name, Some(&f.password), "customer")
                .await?
        }
    };
    state.users.set_agent(user.id, true).await?;
    state
        .support
        .mark_invite_accepted(invite.id, user.id)
        .await?;
    state
        .audit
        .record(
            Some(user.id),
            "agent.joined",
            "user",
            Some(&user.uuid),
            None,
            Some(json!({ "invite": invite.id })),
        )
        .await?;
    Ok((
        jar.add(auth::session_cookie(&state, user.id)),
        Redirect::to(&state.url("/agent?notice=Welcome+to+the+support+console")),
    )
        .into_response())
}

// ----- administrators -----

pub async fn admin_page(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<ConsoleQuery>,
) -> AppResult<Response> {
    let agents: Vec<Value> = {
        let online: Vec<i64> = state
            .support
            .online_agents()
            .await?
            .iter()
            .map(|a| a.id)
            .collect();
        state.support.agents().await?.iter().map(|a| json!({ "id": a.id, "uuid": a.uuid, "name": a.name, "email": a.email, "kind": if a.agent == 1 { "agent" } else { a.role.as_str() }, "online": online.contains(&a.id), "last_seen": a.last_seen_at })).collect()
    };
    let invites = state.support.invites().await?;
    let mut rows = Vec::new();
    for c in state.support.list("", None, 60).await? {
        rows.push(conv_view(&state, &c).await?);
    }
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("admin_chat.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "chat", agents, invites, rows, counts => state.support.counts().await?, mode => state.settings.get("chat.mode").await?, notice => q.notice, error => q.error, public_url => state.config.server.public_url.trim_end_matches('/'), smtp => !state.settings.get("mail.smtp_host").await?.trim().is_empty() })?).into_response())
}

pub async fn invite(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.admin_only() {
        return Ok(r);
    }
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    match state
        .support
        .create_invite(
            f.get("email").map(String::as_str).unwrap_or(""),
            f.get("name").map(String::as_str).unwrap_or(""),
            Some(admin.user.id),
        )
        .await
    {
        Ok((inv, token)) => {
            let link = format!(
                "{}/agent/join?token={token}",
                state.config.server.public_url.trim_end_matches('/')
            );
            let site_name = state.settings.get("general.site_name").await?;
            crate::routes::ops::send_quietly(&state, &inv.email, &format!("You are invited to support {site_name}"), &format!("{} invited you to the {site_name} support console.\n\nOpen this link to set your password (valid for {} days):\n{link}", admin.user.name, support::INVITE_DAYS), None, None, "agent.invite").await;
            state
                .audit
                .record(
                    Some(admin.user.id),
                    "agent.invited",
                    "agent_invite",
                    Some(&inv.id.to_string()),
                    None,
                    Some(json!({ "email": inv.email })),
                )
                .await?;
            Ok(Redirect::to(&state.url(&format!(
                "/admin/chat?notice={}",
                crate::routes::media::urlencoding(&format!(
                    "Invitation created for {}. Send this link (shown once): {link}",
                    inv.email
                ))
            )))
            .into_response())
        }
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/admin/chat?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

pub async fn revoke_invite(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(id): Path<i64>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.admin_only() {
        return Ok(r);
    }
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.support.revoke_invite(id).await?;
    Ok(Redirect::to(&state.url("/admin/chat?notice=Invitation+revoked.")).into_response())
}

/// Customers page: grant or remove agent status by hand.
pub async fn toggle_agent(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.admin_only() {
        return Ok(r);
    }
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let Some(id) = sqlx::query_scalar::<_, i64>("SELECT id FROM users WHERE uuid = ?")
        .bind(&uuid)
        .fetch_optional(&state.db.pool)
        .await?
    else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let on = f.get("agent").map(|v| v == "1").unwrap_or(false);
    state.users.set_agent(id, on).await?;
    state
        .audit
        .record(
            Some(admin.user.id),
            if on { "agent.granted" } else { "agent.removed" },
            "user",
            Some(&uuid),
            None,
            None,
        )
        .await?;
    Ok(Redirect::to(&state.url(&format!("/admin/customers/{uuid}"))).into_response())
}
