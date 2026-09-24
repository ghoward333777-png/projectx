use minijinja::{AutoEscape, Environment, Error, Output, State, Value};
use std::fmt::Write as _;

/// HTML escaping that leaves "/" alone: paths stay readable and `&#x2f;` never appears in markup.
fn html_formatter(out: &mut Output, state: &State, value: &Value) -> Result<(), Error> {
    if matches!(state.auto_escape(), AutoEscape::Html) && !value.is_safe() {
        if let Some(s) = value.as_str() {
            for ch in s.chars() {
                match ch {
                    '<' => out.write_str("&lt;")?,
                    '>' => out.write_str("&gt;")?,
                    '&' => out.write_str("&amp;")?,
                    '"' => out.write_str("&quot;")?,
                    '\'' => out.write_str("&#x27;")?,
                    c => out.write_char(c)?,
                }
            }
            return Ok(());
        }
    }
    minijinja::escape_formatter(out, state, value)
}

macro_rules! embed {
    ($env:expr, $($name:literal),* $(,)?) => {
        $( $env.add_template($name, include_str!(concat!("../templates/", $name))).expect(concat!("template ", $name)); )*
    };
}

pub fn environment(base: &str) -> Environment<'static> {
    let mut env = Environment::new();
    env.add_global("base", minijinja::Value::from_safe_string(base.to_string()));
    env.set_auto_escape_callback(|_| AutoEscape::Html);
    env.set_formatter(html_formatter);
    // "USD 149.00" from integer cents and an ISO code.
    env.add_filter("money", |cents: i64, currency: String| {
        format!("{} {}.{:02}", currency, cents / 100, cents % 100)
    });
    env.add_filter("urlencode", |s: String| {
        crate::routes::media::urlencoding(&s)
    });
    env.add_filter("convert", |cents: i64, factor: f64| {
        ((cents as f64) * factor).round() as i64
    });
    env.add_filter("truncate", |s: String, n: usize| {
        if s.chars().count() <= n {
            s
        } else {
            format!(
                "{}…",
                s.chars()
                    .take(n.saturating_sub(1))
                    .collect::<String>()
                    .trim_end()
            )
        }
    });
    env.add_filter("duration", |ms: i64| {
        let s = ms / 1000;
        if s >= 3600 {
            format!("{}:{:02}:{:02}", s / 3600, (s % 3600) / 60, s % 60)
        } else {
            format!("{}:{:02}", s / 60, s % 60)
        }
    });
    env.add_filter("filesize", |b: i64| {
        if b >= 1 << 30 {
            format!("{:.1} GB", b as f64 / (1u64 << 30) as f64)
        } else if b >= 1 << 20 {
            format!("{:.1} MB", b as f64 / (1u64 << 20) as f64)
        } else {
            format!("{} KB", (b + 1023) / 1024)
        }
    });
    // "site_pass" -> "Site pass" for badges and labels.
    env.add_filter("label", |raw: String| {
        let mut out = raw.replace('_', " ");
        if let Some(first) = out.get_mut(0..1) {
            first.make_ascii_uppercase();
        }
        out
    });
    embed!(
        env,
        "base.html",
        "setup.html",
        "login.html",
        "dashboard.html",
        "settings.html",
        "health.html",
        "bridges.html",
        "embed_showcase.html",
        "media.html",
        "media_detail.html",
        "products.html",
        "product_form.html",
        "customers.html",
        "customer_detail.html",
        "embed_product.html",
        "embed_player.html",
        "embed_checkout.html",
        "account.html",
        "customer_login.html",
        "widgets.html",
        "builder.html",
        "embed_widget.html",
        "templates.html",
        "site_templates.html",
        "schemes.html",
        "cart.html",
        "checkout.html",
        "checkout_test.html",
        "checkout_done.html",
        "account_orders.html",
        "account_agreements.html",
        "account_subscriptions.html",
        "orders.html",
        "order_detail.html",
        "coupons.html",
        "passes.html",
        "pages.html",
        "page_form.html",
        "page_gate.html",
        "page_view.html",
        "integrations.html",
        "account_nav.html",
        "protection.html",
        "protection_scans.html",
        "violations.html",
        "violation.html",
        "google.html",
        "backups.html",
        "wizards.html",
        "chat.html",
        "account_help.html",
        "agent_nav.html",
        "agent_console.html",
        "agent_conversation.html",
        "agent_join.html",
        "admin_chat.html",
        "wizard_session.html",
        "account_privacy.html"
    );
    env
}
