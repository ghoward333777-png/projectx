use minijinja::Environment;

macro_rules! embed {
    ($env:expr, $($name:literal),* $(,)?) => {
        $( $env.add_template($name, include_str!(concat!("../templates/", $name))).expect(concat!("template ", $name)); )*
    };
}

pub fn environment(base: &str) -> Environment<'static> {
    let mut env = Environment::new();
    env.add_global("base", minijinja::Value::from_safe_string(base.to_string()));
    env.set_auto_escape_callback(|_| minijinja::AutoEscape::Html);
    // "USD 149.00" from integer cents and an ISO code.
    env.add_filter("money", |cents: i64, currency: String| {
        format!("{} {}.{:02}", currency, cents / 100, cents % 100)
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
        "embed_showcase.html"
    );
    env
}
