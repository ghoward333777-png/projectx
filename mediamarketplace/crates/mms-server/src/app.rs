use crate::routes;
use axum::http::{header, HeaderValue};
use axum::routing::{get, post};
use axum::Router;
use mms_core::audit::Audit;
use mms_core::commerce::Commerce;
use mms_core::config::Config;
use mms_core::db::Db;
use mms_core::entitlements::Entitlements;
use mms_core::integrations::Integrations;
use mms_core::jobs::Jobs;
use mms_core::media::MediaStore;
use mms_core::pages::Pages;
use mms_core::products::Products;
use mms_core::secrets::Secrets;
use mms_core::settings::SettingsStore;
use mms_core::signer::Signer;
use mms_core::users::Users;
use mms_core::widgets::Widgets;
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
    pub media: MediaStore,
    pub products: Products,
    pub jobs: Jobs,
    pub widgets: Widgets,
    pub commerce: Commerce,
    pub pages: Pages,
    pub integrations: Integrations,
    pub templates: Arc<minijinja::Environment<'static>>,
    /// Mount prefix such as "/store", or "" when served at the domain root.
    pub base: Arc<String>,
}

impl AppState {
    pub fn new(config: Config, db: Db) -> anyhow::Result<Self> {
        let master = config.secret_key_bytes()?;
        let secrets = Secrets::from_master_key(&master);
        let base = config.base_path();
        Ok(Self {
            templates: Arc::new(crate::templates::environment(&base)),
            base: Arc::new(base),
            signer: Signer::from_master_key(&master),
            settings: SettingsStore::new(db.clone(), secrets.clone()),
            users: Users::new(db.clone()),
            entitlements: Entitlements::new(db.clone()),
            audit: Audit::new(db.clone()),
            media: MediaStore::new(db.clone(), &config),
            products: Products::new(db.clone()),
            jobs: Jobs::new(db.clone()),
            widgets: Widgets::new(db.clone()),
            commerce: Commerce::new(db.clone()),
            pages: Pages::new(db.clone()),
            integrations: Integrations::new(db.clone()),
            config: Arc::new(config),
            db,
            secrets,
        })
    }

    /// Absolute path within this server, honouring the mount prefix.
    pub fn url(&self, path: &str) -> String {
        format!("{}{}", self.base, path)
    }

    pub fn render(&self, name: &str, ctx: minijinja::Value) -> anyhow::Result<String> {
        Ok(self.templates.get_template(name)?.render(ctx)?)
    }
}

pub fn router(state: AppState) -> Router {
    let base = state.base.clone();
    let app = Router::new()
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
        .route("/api/v1/ping", get(routes::api::ping))
        .route("/api/v1/health", get(routes::api::health))
        .route("/api/v1/me", get(routes::api::me))
        .route("/api/v1/me/entitlements", get(routes::api::my_entitlements))
        .route(
            "/api/v1/playback/session",
            post(routes::api::playback_session),
        )
        .route(
            "/api/v1/playback/heartbeat",
            post(routes::api::playback_heartbeat),
        )
        .route("/api/v1/ratings", post(routes::api::rate))
        .route("/admin/media", get(routes::media::list))
        .route("/admin/media/upload", post(routes::media::upload))
        .route(
            "/admin/media/:uuid",
            get(routes::media::detail).post(routes::media::update),
        )
        .route("/admin/media/:uuid/delete", post(routes::media::delete))
        .route(
            "/admin/media/:uuid/thumbnails",
            post(routes::media::rethumb),
        )
        .route("/media/*path", get(routes::media::public_file))
        .route("/m/:token", get(routes::media::signed_file))
        .route(
            "/admin/products",
            get(routes::products::list).post(routes::products::create),
        )
        .route("/admin/products/new", get(routes::products::new_form))
        .route(
            "/admin/products/:uuid",
            get(routes::products::edit_form).post(routes::products::update),
        )
        .route(
            "/admin/products/:uuid/delete",
            post(routes::products::delete),
        )
        .route("/admin/categories", post(routes::products::create_category))
        .route(
            "/admin/categories/:id/delete",
            post(routes::products::delete_category),
        )
        .route("/admin/customers", get(routes::customers::list))
        .route("/admin/customers/:uuid", get(routes::customers::detail))
        .route(
            "/admin/customers/:uuid/grant",
            post(routes::customers::grant),
        )
        .route(
            "/admin/customers/:uuid/revoke/:id",
            post(routes::customers::revoke),
        )
        .route("/embed/product/:slug", get(routes::embed::product))
        .route("/embed/player/:slug", get(routes::embed::player))
        .route("/embed/checkout", get(routes::shop::embed_checkout))
        .route("/cart", get(routes::shop::cart_page))
        .route("/cart/add", post(routes::shop::cart_add))
        .route("/cart/update", post(routes::shop::cart_update))
        .route("/cart/remove", post(routes::shop::cart_remove))
        .route("/cart/coupon", post(routes::shop::cart_coupon))
        .route("/cart/country", post(routes::shop::cart_country))
        .route("/checkout", get(routes::shop::checkout_page))
        .route("/checkout/start", post(routes::shop::checkout_start))
        .route(
            "/checkout/return/:gateway",
            get(routes::shop::checkout_return),
        )
        .route("/checkout/cancel/:uuid", get(routes::shop::checkout_cancel))
        .route("/checkout/done/:uuid", get(routes::shop::checkout_done))
        .route(
            "/checkout/test/:uuid",
            get(routes::shop::test_page).post(routes::shop::test_submit),
        )
        .route("/webhooks/:gateway", post(routes::webhooks::receive))
        .route("/account/orders", get(routes::account::orders))
        .route(
            "/account/receipts/:uuid/:format",
            get(routes::account::receipt),
        )
        .route("/account/agreements", get(routes::account::agreements))
        .route(
            "/account/agreements/:uuid/pdf",
            get(routes::account::agreement_pdf),
        )
        .route(
            "/account/subscriptions",
            get(routes::account::subscriptions),
        )
        .route(
            "/account/subscriptions/:uuid/cancel",
            post(routes::account::cancel_subscription),
        )
        .route("/page/:uuid", get(routes::pages::view))
        .route("/embed/page/:uuid", get(routes::pages::view))
        .route("/embed/page", get(routes::pages::view_by_query))
        .route("/embed/cart", get(routes::shop::embed_checkout))
        .route("/embed/sitepass", get(routes::shop::embed_sitepass))
        .route("/page/:uuid/key", post(routes::pages::submit_key))
        .route("/page/:uuid/sign", post(routes::pages::sign))
        .route("/admin/orders", get(routes::orders::list))
        .route("/admin/orders/:uuid", get(routes::orders::detail))
        .route("/admin/orders/:uuid/refund", post(routes::orders::refund))
        .route(
            "/admin/orders/:uuid/receipt.pdf",
            get(routes::orders::receipt_pdf),
        )
        .route(
            "/admin/coupons",
            get(routes::orders::coupons).post(routes::orders::create_coupon),
        )
        .route(
            "/admin/coupons/:id/:status",
            post(routes::orders::coupon_status),
        )
        .route("/admin/tax", post(routes::orders::set_tax))
        .route("/admin/tax/:id/delete", post(routes::orders::delete_tax))
        .route("/admin/passes", get(routes::orders::passes))
        .route(
            "/admin/passes/:id/extend",
            post(routes::orders::extend_pass),
        )
        .route(
            "/admin/pages",
            get(routes::pages::list).post(routes::pages::create),
        )
        .route("/admin/pages/new", get(routes::pages::new_form))
        .route(
            "/admin/pages/:uuid",
            get(routes::pages::edit_form).post(routes::pages::update),
        )
        .route("/admin/pages/:uuid/delete", post(routes::pages::delete))
        .route("/admin/pages/:uuid/keys", post(routes::pages::create_key))
        .route(
            "/admin/pages/:uuid/keys/:id/revoke",
            post(routes::pages::revoke_key),
        )
        .route(
            "/admin/pages/:uuid/signers/:id/revoke",
            post(routes::pages::revoke_signer),
        )
        .route(
            "/admin/pages/:uuid/signers.csv",
            get(routes::pages::signers_csv),
        )
        .route(
            "/admin/agreements/:uuid/pdf",
            get(routes::pages::agreement_pdf_admin),
        )
        .route("/admin/integrations", get(routes::integrations::page))
        .route(
            "/admin/integrations/keys",
            post(routes::integrations::create_key),
        )
        .route(
            "/admin/integrations/keys/:id/revoke",
            post(routes::integrations::revoke_key),
        )
        .route(
            "/admin/integrations/webhooks",
            post(routes::integrations::create_endpoint),
        )
        .route(
            "/admin/integrations/webhooks/:id/delete",
            post(routes::integrations::delete_endpoint),
        )
        .route(
            "/admin/integrations/webhooks/test",
            post(routes::integrations::test_endpoint),
        )
        .route("/api/v1/orders", get(routes::integrations::api_orders))
        .route("/api/v1/orders/:uuid", get(routes::integrations::api_order))
        .route("/api/v1/products", get(routes::integrations::api_products))
        .route(
            "/api/v1/customers",
            get(routes::integrations::api_customers),
        )
        .route(
            "/api/v1/customers/:uuid/entitlements",
            get(routes::integrations::api_entitlements),
        )
        .route("/api/v1/grants", post(routes::integrations::api_grant))
        .route("/account", get(routes::account::my_media))
        .route(
            "/login",
            get(routes::account::login_form).post(routes::account::login),
        )
        .route(
            "/register",
            get(routes::account::register_form).post(routes::account::register),
        )
        .route("/logout", post(routes::account::logout))
        .route("/static/*path", get(routes::embed::static_file))
        .route(
            "/admin/widgets",
            get(routes::widgets::list).post(routes::widgets::create),
        )
        .route("/admin/widgets/:uuid", get(routes::widgets::builder))
        .route(
            "/admin/widgets/:uuid/restore",
            post(routes::widgets::restore),
        )
        .route(
            "/admin/widgets/:uuid/duplicate",
            post(routes::widgets::duplicate),
        )
        .route("/admin/widgets/:uuid/delete", post(routes::widgets::delete))
        .route(
            "/admin/widgets/:uuid/save-template",
            post(routes::widgets::save_as_template),
        )
        .route(
            "/admin/widgets/:uuid/export/:target",
            get(routes::widgets::export),
        )
        .route("/api/v1/widgets/:uuid", post(routes::widgets::api_save))
        .route(
            "/api/v1/widgets/:uuid/preview",
            post(routes::widgets::api_preview),
        )
        .route(
            "/api/v1/widgets/:uuid/versions",
            get(routes::widgets::api_versions),
        )
        .route("/embed/widget", get(routes::widgets::embed_by_query))
        .route("/embed/widget/:uuid", get(routes::widgets::embed))
        .route("/admin/templates", get(routes::templates::gallery))
        .route(
            "/admin/templates/import",
            post(routes::templates::import_template),
        )
        .route(
            "/admin/templates/:slug/preview",
            get(routes::templates::preview),
        )
        .route(
            "/admin/templates/:slug/export",
            get(routes::templates::export_template),
        )
        .route(
            "/admin/templates/:slug/delete",
            post(routes::templates::delete_user_template),
        )
        .route("/admin/site-templates", get(routes::templates::sites))
        .route(
            "/admin/site-templates/import",
            post(routes::templates::import_site),
        )
        .route(
            "/admin/site-templates/:slug/apply",
            post(routes::templates::apply_site),
        )
        .route(
            "/admin/site-templates/:slug/export",
            get(routes::templates::export_site),
        )
        .route(
            "/admin/site-applications/:id/rollback",
            post(routes::templates::rollback_site),
        )
        .route(
            "/admin/schemes",
            get(routes::templates::schemes).post(routes::templates::create_scheme),
        )
        .route("/admin/schemes/brand", post(routes::templates::save_brand))
        .route(
            "/admin/schemes/:slug/delete",
            post(routes::templates::delete_scheme),
        )
        .layer(SetResponseHeaderLayer::if_not_present(
            header::X_CONTENT_TYPE_OPTIONS,
            HeaderValue::from_static("nosniff"),
        ))
        .layer(SetResponseHeaderLayer::if_not_present(
            header::REFERRER_POLICY,
            HeaderValue::from_static("strict-origin-when-cross-origin"),
        ))
        .layer(TraceLayer::new_for_http());
    let app = if base.is_empty() {
        app
    } else {
        // "/store/" is what people type; the nested router only knows "/store".
        let target = base.to_string();
        Router::new().nest(&base, app).route(
            &format!("{base}/"),
            get(move || async move { axum::response::Redirect::to(&target) }),
        )
    };
    app.with_state(state)
}
