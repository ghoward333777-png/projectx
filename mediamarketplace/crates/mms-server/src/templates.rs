use minijinja::Environment;

macro_rules! embed {
    ($env:expr, $($name:literal),* $(,)?) => {
        $( $env.add_template($name, include_str!(concat!("../templates/", $name))).expect(concat!("template ", $name)); )*
    };
}

pub fn environment() -> Environment<'static> {
    let mut env = Environment::new();
    env.set_auto_escape_callback(|_| minijinja::AutoEscape::Html);
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
