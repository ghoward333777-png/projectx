//! Private pages: admin management, and the public gate with the ten signup templates.

use crate::app::AppState;
use crate::auth::{self, AdminUser, MaybeUser};
use crate::errors::AppResult;
use crate::routes::customers::CsrfOnly;
use crate::routes::shop::{client_ip, user_agent};
use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use axum_extra::extract::CookieJar;
use minijinja::context;
use mms_core::pages::{markdown, Gate, PageDraft, PROTECTION_LEVELS, SIGNUP_TEMPLATES};
use serde::Deserialize;
use std::collections::HashMap;

#[derive(Deserialize)]
pub struct ListQuery {
    #[serde(default)]
    notice: String,
    #[serde(default)]
    error: String,
    #[serde(default)]
    new_key: String,
}

pub async fn list(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<ListQuery>,
) -> AppResult<Response> {
    let pages = state.pages.list().await?;
    let mut rows = Vec::new();
    for p in pages {
        let (signers,): (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM agreements WHERE page_id = ? AND status = 'signed'",
        )
        .bind(p.id)
        .fetch_one(&state.db.pool)
        .await?;
        rows.push(context! { p, signers });
    }
    let site_uuid: Option<String> = sqlx::query_scalar(
        "SELECT uuid FROM bridge_sites WHERE status = 'active' ORDER BY id LIMIT 1",
    )
    .fetch_optional(&state.db.pool)
    .await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("pages.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "pages", rows, notice => q.notice, error => q.error, site => site_uuid })?).into_response())
}

async fn form_ctx(
    state: &AppState,
    admin: &AdminUser,
    page: Option<&mms_core::pages::Page>,
    error: &str,
) -> AppResult<Response> {
    let products = state.products.list_admin("", "", "").await?;
    let site_name = state.settings.get("general.site_name").await?;
    let (keys, signers) = match page {
        Some(p) => {
            let keys = state.pages.keys(p.id).await?;
            let ags = state.pages.agreements(Some(p.id), None).await?;
            let mut signers = Vec::new();
            for a in ags {
                let (email, name, cuuid): (String, String, String) =
                    sqlx::query_as("SELECT email, name, uuid FROM users WHERE id = ?")
                        .bind(a.user_id)
                        .fetch_one(&state.db.pool)
                        .await?;
                signers.push(context! { a, email, name, cuuid });
            }
            (keys, signers)
        }
        None => (vec![], vec![]),
    };
    Ok(Html(state.render("page_form.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "pages", p => page, products, templates => SIGNUP_TEMPLATES.iter().map(|(s, n, _, d)| context!{ slug => s, name => n, desc => d }).collect::<Vec<_>>(), levels => PROTECTION_LEVELS.iter().map(|(s, n)| context!{ slug => s, name => n }).collect::<Vec<_>>(), keys, signers, error, public_url => state.config.server.public_url.trim_end_matches('/') })?).into_response())
}

pub async fn new_form(State(state): State<AppState>, admin: AdminUser) -> AppResult<Response> {
    form_ctx(&state, &admin, None, "").await
}

pub async fn edit_form(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Query(q): Query<ListQuery>,
) -> AppResult<Response> {
    let Some(p) = state.pages.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let error = if q.new_key.is_empty() {
        q.error
    } else {
        format!("New access key (shown once): {}", q.new_key)
    };
    form_ctx(&state, &admin, Some(&p), &error).await
}

fn draft(f: &HashMap<String, String>) -> PageDraft {
    let g = |k: &str| f.get(k).cloned().unwrap_or_default();
    PageDraft {
        title: g("title"),
        content: g("content"),
        agreement: g("agreement"),
        signup_template: g("signup_template"),
        protection: g("protection"),
        product_id: g("product_id").parse().ok().filter(|id| *id > 0),
        incentive: g("incentive"),
        quiz_question: g("quiz_question"),
        quiz_answer: g("quiz_answer"),
        jurisdiction: g("jurisdiction"),
        min_age: g("min_age").parse().unwrap_or(0),
        status: g("status"),
    }
}

pub async fn create(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let d = draft(&f);
    match state.pages.create(&d).await {
        Ok(p) => {
            link_product(&state, &p).await?;
            state
                .audit
                .record(
                    Some(admin.user.id),
                    "page.created",
                    "page",
                    Some(&p.uuid),
                    None,
                    None,
                )
                .await?;
            Ok(
                Redirect::to(&state.url(&format!("/admin/pages/{}?notice=Page+saved.", p.uuid)))
                    .into_response(),
            )
        }
        Err(e) => form_ctx(&state, &admin, None, &e.to_string()).await,
    }
}

/// Keeps the linked private_page product pointing at this page.
async fn link_product(state: &AppState, p: &mms_core::pages::Page) -> AppResult<()> {
    if let Some(pid) = p.product_id {
        sqlx::query("UPDATE products SET settings = json_set(COALESCE(settings, '{}'), '$.page_uuid', ?) WHERE id = ?")
            .bind(&p.uuid).bind(pid).execute(&state.db.pool).await?;
    }
    Ok(())
}

pub async fn update(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let Some(p) = state.pages.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let d = draft(&f);
    match state.pages.update(p.id, &d).await {
        Ok(()) => {
            let p = state.pages.by_id(p.id).await?.expect("exists");
            link_product(&state, &p).await?;
            Ok(
                Redirect::to(&state.url(&format!("/admin/pages/{uuid}?notice=Page+saved.")))
                    .into_response(),
            )
        }
        Err(e) => form_ctx(&state, &admin, Some(&p), &e.to_string()).await,
    }
}

pub async fn delete(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    if let Some(p) = state.pages.by_uuid(&uuid).await? {
        state.pages.delete(p.id).await?;
    }
    Ok(Redirect::to(&state.url("/admin/pages?notice=Page+deleted.")).into_response())
}

pub async fn create_key(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let Some(p) = state.pages.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let max_uses: i64 = f.get("max_uses").and_then(|m| m.parse().ok()).unwrap_or(1);
    let expires = f.get("expires_at").cloned().unwrap_or_default();
    let key = state
        .pages
        .create_key(p.id, max_uses, Some(&expires))
        .await?;
    state
        .audit
        .record(
            Some(admin.user.id),
            "page.key_created",
            "page",
            Some(&p.uuid),
            None,
            Some(serde_json::json!({ "max_uses": max_uses })),
        )
        .await?;
    Ok(Redirect::to(&state.url(&format!("/admin/pages/{uuid}?new_key={key}"))).into_response())
}

pub async fn revoke_key(
    State(state): State<AppState>,
    admin: AdminUser,
    Path((uuid, id)): Path<(String, i64)>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.pages.revoke_key(id).await?;
    Ok(
        Redirect::to(&state.url(&format!("/admin/pages/{uuid}?notice=Key+revoked.")))
            .into_response(),
    )
}

pub async fn revoke_signer(
    State(state): State<AppState>,
    admin: AdminUser,
    Path((uuid, id)): Path<(String, i64)>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.pages.revoke(id).await?;
    state
        .audit
        .record(
            Some(admin.user.id),
            "page.signer_revoked",
            "agreement",
            Some(&id.to_string()),
            None,
            None,
        )
        .await?;
    Ok(
        Redirect::to(&state.url(&format!("/admin/pages/{uuid}?notice=Signer+revoked.")))
            .into_response(),
    )
}

pub async fn signers_csv(
    State(state): State<AppState>,
    _admin: AdminUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(p) = state.pages.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let mut csv = String::from("signed_at,name,email,agreement_version,method,ip,status,hash\n");
    for a in state.pages.agreements(Some(p.id), None).await? {
        let (email,): (String,) = sqlx::query_as("SELECT email FROM users WHERE id = ?")
            .bind(a.user_id)
            .fetch_one(&state.db.pool)
            .await?;
        let q = |s: &str| format!("\"{}\"", s.replace('"', "\"\""));
        csv.push_str(&format!(
            "{},{},{},{},{},{},{},{}\n",
            a.signed_at,
            q(&a.signer_name),
            q(&email),
            a.agreement_version,
            a.method,
            a.ip,
            a.status,
            a.agreement_hash
        ));
    }
    Ok((
        [
            (header::CONTENT_TYPE, "text/csv; charset=utf-8".to_string()),
            (
                header::CONTENT_DISPOSITION,
                format!(
                    "attachment; filename=\"signers-{}.csv\"",
                    mms_core::products::slugify(&p.title)
                ),
            ),
        ],
        csv,
    )
        .into_response())
}

pub async fn agreement_pdf_admin(
    State(state): State<AppState>,
    _admin: AdminUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    match state.pages.agreement_pdf_by_uuid(&uuid, None).await? {
        Some(pdf) => Ok((
            [
                (header::CONTENT_TYPE, "application/pdf".to_string()),
                (
                    header::CONTENT_DISPOSITION,
                    format!("inline; filename=\"agreement-{uuid}.pdf\""),
                ),
            ],
            pdf,
        )
            .into_response()),
        None => Ok(StatusCode::NOT_FOUND.into_response()),
    }
}

// ----- the public gate -----

#[derive(Deserialize)]
pub struct GateQuery {
    site: Option<String>,
    #[serde(default)]
    error: String,
    #[serde(default)]
    notice: String,
}

fn subject(headers: &HeaderMap, user: Option<&mms_core::users::User>) -> String {
    match user {
        Some(u) => format!("user:{}", u.id),
        None => format!("ip:{}", client_ip(headers)),
    }
}

pub async fn limits_pub(state: &AppState) -> AppResult<(i64, i64, i64)> {
    limits(state).await
}

async fn limits(state: &AppState) -> AppResult<(i64, i64, i64)> {
    Ok((
        state
            .settings
            .get("access.attempt_limit")
            .await?
            .parse()
            .unwrap_or(5),
        state
            .settings
            .get("access.attempt_window")
            .await?
            .parse()
            .unwrap_or(900),
        state
            .settings
            .get("access.lockout_seconds")
            .await?
            .parse()
            .unwrap_or(1800),
    ))
}

pub async fn view(
    State(state): State<AppState>,
    MaybeUser(user, token): MaybeUser,
    headers: HeaderMap,
    Path(uuid): Path<String>,
    Query(q): Query<GateQuery>,
) -> AppResult<Response> {
    let csp = match q.site.as_deref() {
        Some(site) => match crate::routes::bridges::by_uuid(&state, site).await? {
            Some(s) => format!("frame-ancestors 'self' {}", s.origin),
            None => return Ok((StatusCode::FORBIDDEN, "Unknown site").into_response()),
        },
        None => "frame-ancestors 'self'".to_string(),
    };
    let Some(page) = state.pages.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let now = mms_core::now();
    let gate = state
        .pages
        .gate(
            &page,
            user.as_ref().map(|u| u.id),
            &subject(&headers, user.as_ref()),
            false,
            &now,
        )
        .await?;
    state
        .audit
        .record(
            user.as_ref().map(|u| u.id),
            "page.gate",
            "page",
            Some(&page.uuid),
            Some(&client_ip(&headers)),
            Some(serde_json::json!({ "decision": format!("{gate:?}") })),
        )
        .await?;
    let site_name = state.settings.get("general.site_name").await?;
    let product = match page.product_id {
        Some(pid) => state.products.by_id(pid).await?,
        None => None,
    };
    let this_url = format!(
        "/page/{}{}",
        page.uuid,
        q.site
            .as_deref()
            .map(|s| format!("?site={s}"))
            .unwrap_or_default()
    );
    let csrf = token
        .as_deref()
        .map(|t| auth::csrf_token(&state, t))
        .unwrap_or_default();
    let html = match gate {
        Gate::Open => {
            // Forensic view record: which user opened which page, when.
            sqlx::query("INSERT INTO playback_sessions (uuid, user_id, product_id, player, started_at, last_seen) SELECT ?, ?, id, 'page', ?, ? FROM products WHERE id = ?")
                .bind(uuid::Uuid::new_v4().to_string()).bind(user.as_ref().map(|u| u.id)).bind(&now).bind(&now).bind(page.product_id).execute(&state.db.pool).await.ok();
            state.render("page_view.html", context! { page, user, site_name, content => minijinja::Value::from_safe_string(markdown(&page.content)), site => q.site.clone().unwrap_or_default(), viewer => user.as_ref().map(|u| u.email.clone()).unwrap_or_default() })?
        }
        other => {
            let template = SIGNUP_TEMPLATES
                .iter()
                .find(|(s, ..)| *s == page.signup_template)
                .map(|(s, n, r, d)| context! { slug => s, name => n, requires => r, desc => d });
            let sections: Vec<String> = page
                .agreement
                .split("\n\n")
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect();
            state.render("page_gate.html", context! { page, user, site_name, gate => format!("{other:?}").split([' ', '(']).next().unwrap_or("").to_string(), locked_until => match &other { Gate::LockedOut { until } => Some(until.clone()), _ => None }, template, sections, buy_url => match &product { Some(p) => crate::routes::commerce_bridge::buy_context(&state, p).await?.0, None => String::new() }, product, this_url, csrf, error => q.error, notice => q.notice, site => q.site.clone().unwrap_or_default(), login_url => state.url(&format!("/login?return={}", crate::routes::media::urlencoding(&this_url))), public_url => state.config.server.public_url.trim_end_matches('/') })?
        }
    };
    Ok((
        [
            (header::CONTENT_SECURITY_POLICY, csp),
            (header::CACHE_CONTROL, "private, no-store".to_string()),
        ],
        Html(html),
    )
        .into_response())
}

/// The loader's generic form: /embed/page?site=&id=
pub async fn view_by_query(
    State(state): State<AppState>,
    user: MaybeUser,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> AppResult<Response> {
    let id = q.get("id").cloned().unwrap_or_default();
    let gq = GateQuery {
        site: q.get("site").cloned(),
        error: q.get("error").cloned().unwrap_or_default(),
        notice: q.get("notice").cloned().unwrap_or_default(),
    };
    view(State(state), user, headers, Path(id), Query(gq)).await
}

#[derive(Deserialize)]
pub struct KeyForm {
    _csrf: String,
    #[serde(default)]
    key: String,
    #[serde(default)]
    site: String,
}

pub async fn submit_key(
    State(state): State<AppState>,
    MaybeUser(user, token): MaybeUser,
    headers: HeaderMap,
    Path(uuid): Path<String>,
    Form(f): Form<KeyForm>,
) -> AppResult<Response> {
    let back = |msg: &str, kind: &str| {
        format!(
            "/page/{uuid}?{kind}={}{}",
            crate::routes::media::urlencoding(msg),
            if f.site.is_empty() {
                String::new()
            } else {
                format!("&site={}", f.site)
            }
        )
    };
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url(&back("Sign in first", "error"))).into_response());
    };
    if f._csrf
        != token
            .as_deref()
            .map(|t| auth::csrf_token(&state, t))
            .unwrap_or_default()
    {
        return Ok((StatusCode::FORBIDDEN, "Invalid form token").into_response());
    }
    let Some(page) = state.pages.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let (limit, window, lockout) = limits(&state).await?;
    let subj = subject(&headers, Some(&user));
    let target = match state
        .pages
        .use_key(&page, user.id, &f.key, &subj, limit, window, lockout)
        .await
    {
        Ok(true) => {
            state
                .audit
                .record(
                    Some(user.id),
                    "page.key_used",
                    "page",
                    Some(&page.uuid),
                    Some(&client_ip(&headers)),
                    None,
                )
                .await?;
            back("Key accepted.", "notice")
        }
        Ok(false) => {
            state
                .audit
                .record(
                    Some(user.id),
                    "page.key_rejected",
                    "page",
                    Some(&page.uuid),
                    Some(&client_ip(&headers)),
                    None,
                )
                .await?;
            back("That key is not valid for this page.", "error")
        }
        Err(e) => {
            state
                .audit
                .record(
                    Some(user.id),
                    "page.locked_out",
                    "page",
                    Some(&page.uuid),
                    Some(&client_ip(&headers)),
                    None,
                )
                .await?;
            back(&e.to_string(), "error")
        }
    };
    Ok(Redirect::to(&state.url(&target)).into_response())
}

pub async fn sign(
    State(state): State<AppState>,
    MaybeUser(user, token): MaybeUser,
    headers: HeaderMap,
    jar: CookieJar,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    let site = f.get("site").cloned().unwrap_or_default();
    let back = |msg: &str, kind: &str| {
        format!(
            "/page/{uuid}?{kind}={}{}",
            crate::routes::media::urlencoding(msg),
            if site.is_empty() {
                String::new()
            } else {
                format!("&site={site}")
            }
        )
    };
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url(&back("Sign in first", "error"))).into_response());
    };
    if f.get("_csrf").map(String::as_str)
        != Some(
            token
                .as_deref()
                .map(|t| auth::csrf_token(&state, t))
                .unwrap_or_default()
                .as_str(),
        )
    {
        return Ok((StatusCode::FORBIDDEN, "Invalid form token").into_response());
    }
    let Some(page) = state.pages.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let confirmations: Vec<String> = ["agree", "read", "consent", "scrolled", "age", "purposes"]
        .iter()
        .filter(|k| f.get(**k).map(|v| v == "1" || v == "on").unwrap_or(false))
        .map(|k| k.to_string())
        .collect();
    let mut confirmations = confirmations;
    if !page.quiz_question.trim().is_empty()
        || mms_core::pages::template_requirements(&page.signup_template).contains(&"quiz")
    {
        confirmations.push("quiz".into());
    }
    if page.min_age > 0 && confirmations.iter().any(|c| c == "age") {
        // The age gate records the declared age bracket alongside the confirmation.
        confirmations.push(format!("age>={}", page.min_age));
    }
    let method = if f.get("method").map(String::as_str) == Some("drawn") {
        "drawn"
    } else {
        "typed"
    };
    let signature = f
        .get("signature")
        .cloned()
        .filter(|s| s.starts_with("data:image/png;base64,"));
    let site_name = state.settings.get("general.site_name").await?;
    let (limit, window, lockout) = limits(&state).await?;
    let subj = subject(&headers, Some(&user));
    match state
        .pages
        .sign(
            &page,
            user.id,
            f.get("name").map(String::as_str).unwrap_or(""),
            method,
            signature.as_deref(),
            &confirmations,
            f.get("quiz").map(String::as_str).unwrap_or(""),
            &client_ip(&headers),
            &user_agent(&headers),
            &site_name,
        )
        .await
    {
        Ok(a) => {
            state
                .pages
                .record_attempt(&subj, page.id, true, limit, window, lockout)
                .await?;
            state
                .audit
                .record(
                    Some(user.id),
                    "page.signed",
                    "agreement",
                    Some(&a.uuid),
                    Some(&client_ip(&headers)),
                    Some(serde_json::json!({ "page": page.uuid, "version": a.agreement_version })),
                )
                .await?;
            crate::routes::shop::emit(&state, "agreement.signed", serde_json::json!({ "page": page.uuid, "user_id": user.id, "agreement": a.uuid, "version": a.agreement_version })).await?;
            if let Some(pdf) = state
                .pages
                .agreement_pdf_by_uuid(&a.uuid, Some(user.id))
                .await?
            {
                let text = format!("Hello {},\n\nattached is your signed copy of the agreement for \"{}\" at {site_name}.\n", user.name, page.title);
                crate::routes::ops::send_quietly(
                    &state,
                    &user.email,
                    &format!("Your signed agreement: {}", page.title),
                    &text,
                    None,
                    Some(("agreement.pdf", &pdf, "application/pdf")),
                    "agreement",
                )
                .await;
            }
            // Paid pages: the linked product goes into the cart and checkout follows.
            if matches!(page.protection.as_str(), "paid" | "paid_key") {
                if let Some(pid) = page.product_id {
                    if let Some(p) = state.products.by_id(pid).await? {
                        let entitled = state
                            .entitlements
                            .check(
                                user.id,
                                &mms_core::entitlements::Subject::Page(page.uuid.clone()),
                                &mms_core::now(),
                            )
                            .await?;
                        if !entitled {
                            let (cart, jar) =
                                crate::routes::shop::current_cart(&state, jar, Some(&user)).await?;
                            state.commerce.add(&cart, &p, 1).await?;
                            return Ok((jar, Redirect::to(&state.url("/checkout"))).into_response());
                        }
                    }
                }
            }
            Ok(Redirect::to(&state.url(&back(
                "Thank you. Your signed copy is under My media.",
                "notice",
            )))
            .into_response())
        }
        Err(e) => {
            state
                .pages
                .record_attempt(&subj, page.id, false, limit, window, lockout)
                .await?;
            Ok(Redirect::to(&state.url(&back(&e.to_string(), "error"))).into_response())
        }
    }
}
