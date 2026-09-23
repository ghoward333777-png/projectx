use crate::routes;
use axum::http::{header, HeaderValue};
use axum::routing::{get, post};
use axum::Router;
use mms_core::audit::Audit;
use mms_core::config::Config;
use mms_core::db::Db;
use mms_core::entitlements::Entitlements;
use mms_core::secrets::Secrets;
use mms_core::settings::SettingsStore;
use mms_core::signer::Signer;
use mms_core::users::Users;
use std::sync::Arc;
use tower_http::set_header::SetResponseHeaderLayer;
use tower_http::trace::TraceLayer;

#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub db: Db,
    pub secrets: Secrets,
    pub signer: Signer,
    pub settings: SettingsStore,
    pub users: Users,
    pub entitlements: Entitlements,
    pub audit: Audit,
    pub templates: Arc<minijinja::Environment<'static>>,
}

impl AppState {
    pub fn new(config: Config, db: Db) -> anyhow::Result<Self> {
        let master = config.secret_key_bytes()?;
        let secrets = Secrets::from_master_key(&master);
        Ok(Self {
            signer: Signer::from_master_key(&master),
            settings: SettingsStore::new(db.clone(), secrets.clone()),
            users: Users::new(db.clone()),
            entitlements: Entitlements::new(db.clone()),
            audit: Audit::new(db.clone()),
            templates: Arc::new(crate::templates::environment()),
            config: Arc::new(config),
            db,
            secrets,
        })
    }

    pub fn render(&self, name: &str, ctx: minijinja::Value) -> anyhow::Result<String> {
        Ok(self.templates.get_template(name)?.render(ctx)?)
    }
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/", get(routes::admin::index))
        .route(
            "/setup",
            get(routes::setup::form).post(routes::setup::submit),
        )
        .route(
            "/admin/login",
            get(routes::admin::login_form).post(routes::admin::login),
        )
        .route("/admin/logout", post(routes::admin::logout))
        .route("/admin", get(routes::admin::dashboard))
        .route(
            "/admin/settings",
            get(routes::admin::settings_form).post(routes::admin::settings_save),
        )
        .route("/admin/health", get(routes::admin::health))
        .route(
            "/admin/bridges",
            get(routes::bridges::list).post(routes::bridges::create),
        )
        .route("/admin/bridges/:uuid/delete", post(routes::bridges::delete))
        .route("/sso", get(routes::sso::login))
        .route("/embed/showcase", get(routes::embed::showcase))
        .route("/embed.js", get(routes::embed::loader))
        .route("/static/mms.css", get(routes::embed::css))
        .route("/api/v1/health", get(routes::api::health))
        .route("/api/v1/me", get(routes::api::me))
        .route("/api/v1/me/entitlements", get(routes::api::my_entitlements))
        .layer(SetResponseHeaderLayer::if_not_present(
            header::X_CONTENT_TYPE_OPTIONS,
            HeaderValue::from_static("nosniff"),
        ))
        .layer(SetResponseHeaderLayer::if_not_present(
            header::REFERRER_POLICY,
            HeaderValue::from_static("strict-origin-when-cross-origin"),
        ))
        .layer(TraceLayer::new_for_http())
        .with_state(state)
}
