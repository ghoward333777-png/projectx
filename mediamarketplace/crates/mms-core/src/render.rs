//! Widget renderer: a pure function of (definition, theme, scheme, brand) -> HTML.
//!
//! The same renderer serves the builder preview, the storefront embed and the
//! standalone export, so what you build is what visitors see. Output is deterministic.

use serde::{Deserialize, Serialize};
use std::fmt::Write;

pub const SCHEMA_VERSION: i64 = 1;

/// Component kinds and the props the builder exposes for each.
/// `(key, label, kind, default)` where kind is text | textarea | number | bool | select:a,b | media | product | color | url
pub fn component_props(
    kind: &str,
) -> &'static [(&'static str, &'static str, &'static str, &'static str)] {
    match kind {
        "container" => &[
            ("layout", "Layout", "select:stack,row,grid,columns", "stack"),
            ("columns", "Columns (grid)", "number", "3"),
            ("gap", "Gap (px)", "number", "16"),
            ("padding", "Padding (px)", "number", "16"),
            ("background", "Background", "color", ""),
            (
                "align",
                "Align items",
                "select:start,center,end,stretch",
                "stretch",
            ),
            ("radius", "Corner radius (px)", "number", "0"),
        ],
        "text" => &[
            ("text", "Text", "textarea", "Your text"),
            (
                "style",
                "Style",
                "select:paragraph,heading,subheading,caption,quote",
                "paragraph",
            ),
            ("align", "Align", "select:left,center,right", "left"),
            ("color", "Colour", "color", ""),
        ],
        "image" => &[
            ("media", "Image", "media", ""),
            ("alt", "Alt text", "text", ""),
            ("fit", "Fit", "select:cover,contain", "cover"),
            (
                "ratio",
                "Aspect ratio",
                "select:auto,16:9,4:3,1:1,3:4",
                "auto",
            ),
            ("radius", "Corner radius (px)", "number", "8"),
            (
                "protect",
                "Protect (right-click and drag off)",
                "bool",
                "false",
            ),
            ("link", "Link URL", "url", ""),
        ],
        "video" => &[
            ("product", "Product (slug)", "product", ""),
            ("media", "Or media file", "media", ""),
            ("poster", "Poster image", "media", ""),
            (
                "player",
                "Player",
                "select:default,plyr,videojs,native",
                "default",
            ),
            ("autoplay", "Autoplay muted", "bool", "false"),
            ("caption", "Caption", "text", ""),
        ],
        "audio" => &[
            ("product", "Product (slug)", "product", ""),
            ("media", "Or media file", "media", ""),
            ("title", "Title", "text", ""),
            ("visualiser", "Visualiser", "select:none,bars,wave", "bars"),
        ],
        "pdf" => &[
            ("product", "Product (slug)", "product", ""),
            ("media", "Or media file", "media", ""),
            ("height", "Height (px)", "number", "600"),
            ("title", "Title", "text", ""),
        ],
        "button" => &[
            ("label", "Label", "text", "Learn more"),
            ("url", "Link URL", "url", "#"),
            (
                "style",
                "Style",
                "select:primary,secondary,outline,link",
                "primary",
            ),
            ("size", "Size", "select:small,medium,large", "medium"),
            ("full", "Full width", "bool", "false"),
        ],
        "product_card" => &[
            ("product", "Product (slug)", "product", ""),
            ("show_price", "Show price", "bool", "true"),
            ("show_description", "Show description", "bool", "true"),
            ("button", "Button label", "text", "View"),
        ],
        "price" => &[
            ("product", "Product (slug)", "product", ""),
            ("prefix", "Prefix", "text", ""),
            ("size", "Size", "select:medium,large,huge", "large"),
        ],
        "add_to_cart" => &[
            ("product", "Product (slug)", "product", ""),
            ("label", "Label", "text", "Buy now"),
            (
                "style",
                "Style",
                "select:primary,secondary,outline",
                "primary",
            ),
        ],
        "countdown" => &[
            (
                "until",
                "Until (UTC, YYYY-MM-DD HH:MM)",
                "text",
                "2026-12-31 00:00",
            ),
            ("label", "Label", "text", "Starts in"),
            ("expired", "Text when over", "text", "Live now"),
        ],
        "icon" => &[
            (
                "icon",
                "Icon",
                "select:play,music,image,file,star,clock,lock,check,heart,download",
                "play",
            ),
            ("size", "Size (px)", "number", "40"),
            ("color", "Colour", "color", ""),
            ("label", "Label", "text", ""),
        ],
        "spacer" => &[("height", "Height (px)", "number", "24")],
        "divider" => &[("style", "Style", "select:line,dots,none", "line")],
        _ => &[],
    }
}

pub const COMPONENT_KINDS: &[(&str, &str)] = &[
    ("container", "Container"),
    ("text", "Text"),
    ("image", "Image"),
    ("video", "Video"),
    ("audio", "Audio"),
    ("pdf", "PDF"),
    ("button", "Button"),
    ("product_card", "Product card"),
    ("price", "Price"),
    ("add_to_cart", "Add to cart"),
    ("countdown", "Countdown"),
    ("icon", "Icon"),
    ("spacer", "Spacer"),
    ("divider", "Divider"),
];

pub const ANIMATIONS: &[&str] = &[
    "none",
    "fade",
    "slide-up",
    "slide-left",
    "zoom",
    "flip",
    "bounce",
    "pulse",
];

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Animation {
    #[serde(default)]
    pub name: String,
    #[serde(default = "default_trigger")]
    pub trigger: String,
    #[serde(default = "default_duration")]
    pub duration_ms: i64,
    #[serde(default)]
    pub delay_ms: i64,
    #[serde(default = "default_easing")]
    pub easing: String,
}

fn default_trigger() -> String {
    "in-view".into()
}
fn default_duration() -> i64 {
    600
}
fn default_easing() -> String {
    "ease-out".into()
}

/// Per-breakpoint overrides.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Responsive {
    #[serde(default)]
    pub hidden: bool,
    #[serde(default)]
    pub width: String, // "", "50%", "100%"
    #[serde(default)]
    pub align: String,
    #[serde(default)]
    pub font_size: String,
    #[serde(default)]
    pub padding: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Component {
    #[serde(default)]
    pub id: String,
    pub kind: String,
    #[serde(default)]
    pub props: serde_json::Map<String, serde_json::Value>,
    #[serde(default)]
    pub children: Vec<Component>,
    #[serde(default)]
    pub animation: Option<Animation>,
    #[serde(default)]
    pub mobile: Option<Responsive>,
    #[serde(default)]
    pub tablet: Option<Responsive>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Definition {
    #[serde(default = "schema_version")]
    pub schema_version: i64,
    pub root: Component,
}

fn schema_version() -> i64 {
    SCHEMA_VERSION
}

impl Definition {
    pub fn parse(json: &str) -> Result<Self, String> {
        let d: Definition =
            serde_json::from_str(json).map_err(|e| format!("invalid widget definition: {e}"))?;
        if d.schema_version > SCHEMA_VERSION {
            return Err(format!(
                "widget schema {} is newer than this server understands ({})",
                d.schema_version, SCHEMA_VERSION
            ));
        }
        if d.root.kind != "container" {
            return Err("the root component must be a container".into());
        }
        let mut count = 0;
        d.root.walk(&mut |c| {
            count += 1;
            if !COMPONENT_KINDS.iter().any(|(k, _)| *k == c.kind) {
                return Err(format!("unknown component kind {}", c.kind));
            }
            Ok(())
        })?;
        if count > 500 {
            return Err("a widget may hold at most 500 components".into());
        }
        Ok(d)
    }

    pub fn empty() -> Self {
        let mut props = serde_json::Map::new();
        props.insert("layout".into(), "stack".into());
        props.insert("padding".into(), 16.into());
        props.insert("gap".into(), 16.into());
        Definition {
            schema_version: SCHEMA_VERSION,
            root: Component {
                id: "root".into(),
                kind: "container".into(),
                props,
                children: vec![],
                animation: None,
                mobile: None,
                tablet: None,
            },
        }
    }
}

impl Component {
    pub fn walk(&self, f: &mut dyn FnMut(&Component) -> Result<(), String>) -> Result<(), String> {
        f(self)?;
        for c in &self.children {
            c.walk(f)?;
        }
        Ok(())
    }

    fn prop(&self, key: &str) -> String {
        match self.props.get(key) {
            Some(serde_json::Value::String(s)) => s.clone(),
            Some(serde_json::Value::Bool(b)) => b.to_string(),
            Some(serde_json::Value::Number(n)) => n.to_string(),
            Some(serde_json::Value::Null) | None => component_props(&self.kind)
                .iter()
                .find(|(k, ..)| *k == key)
                .map(|(.., d)| d.to_string())
                .unwrap_or_default(),
            Some(other) => other.to_string(),
        }
    }

    fn prop_num(&self, key: &str) -> i64 {
        self.prop(key).parse::<f64>().map(|f| f as i64).unwrap_or(0)
    }

    fn prop_bool(&self, key: &str) -> bool {
        matches!(self.prop(key).as_str(), "true" | "1" | "yes")
    }
}

/// Everything the renderer needs from outside the definition.
pub struct RenderContext<'a> {
    pub uuid: &'a str,
    pub base: &'a str,
    pub site: &'a str,
    pub theme: &'a str,
    pub scheme_vars: &'a [(String, String)],
    pub custom_css: &'a str,
    /// Resolves a media uuid to a public URL (thumbnail or original).
    pub media_url: &'a dyn Fn(&str) -> Option<String>,
    /// Resolves a product slug to (title, description, price label, thumbnail url, type).
    pub product: &'a dyn Fn(&str) -> Option<ProductInfo>,
}

#[derive(Debug, Clone)]
pub struct ProductInfo {
    pub slug: String,
    pub title: String,
    pub description: String,
    pub price: String,
    pub thumb: Option<String>,
    pub kind: String,
}

pub struct Rendered {
    pub html: String,
    pub css: String,
}

fn esc(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '&' => out.push_str("&amp;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#x27;"),
            c => out.push(c),
        }
    }
    out
}

fn safe_url(u: &str) -> String {
    let t = u.trim();
    let lower = t.to_ascii_lowercase();
    if t.is_empty()
        || lower.starts_with("javascript:")
        || lower.starts_with("data:")
        || lower.starts_with("vbscript:")
    {
        "#".into()
    } else {
        esc(t)
    }
}

fn safe_color(c: &str) -> Option<String> {
    let t = c.trim();
    let ok = t.starts_with('#') && t.len() <= 9 && t[1..].chars().all(|c| c.is_ascii_hexdigit())
        || t.starts_with("var(--mms-")
            && t.ends_with(')')
            && t.chars()
                .all(|c| c.is_ascii_alphanumeric() || "()-_".contains(c))
        || t.starts_with("rgb")
            && t.ends_with(')')
            && t.chars()
                .all(|c| c.is_ascii_digit() || "rgba(),. %".contains(c));
    ok.then(|| t.to_string())
}

pub fn render(def: &Definition, ctx: &RenderContext) -> Rendered {
    let scope = format!("mms-w-{}", ctx.uuid);
    let mut html = String::new();
    let mut css = String::new();
    // Scheme variables and theme on the scope element.
    let _ = write!(css, ".{scope}{{");
    for (k, v) in ctx.scheme_vars {
        if k.chars().all(|c| c.is_ascii_alphanumeric() || c == '-') {
            if let Some(v) = safe_color(v).or_else(|| {
                v.chars()
                    .all(|c| c.is_ascii_alphanumeric() || " ,'\"-".contains(c))
                    .then(|| v.clone())
            }) {
                let _ = write!(css, "--mms-{k}:{v};");
            }
        }
    }
    css.push('}');
    let _ = write!(
        html,
        "<div class=\"{scope} mms-widget\" data-theme=\"{}\">",
        esc(ctx.theme)
    );
    render_component(&def.root, ctx, &scope, &mut html, &mut css, 0);
    html.push_str("</div>");
    if !ctx.custom_css.trim().is_empty() {
        css.push_str(&scope_css(ctx.custom_css, &scope));
    }
    Rendered { html, css }
}

fn render_component(
    c: &Component,
    ctx: &RenderContext,
    scope: &str,
    html: &mut String,
    css: &mut String,
    depth: usize,
) {
    if depth > 30 {
        return;
    }
    let id = if c.id.is_empty() {
        "c".to_string()
    } else {
        c.id.chars()
            .filter(|ch| ch.is_ascii_alphanumeric() || *ch == '-' || *ch == '_')
            .collect()
    };
    let cls = format!("mms-c-{id}");
    // Animation and responsive rules.
    let mut classes = vec!["mms-c".to_string(), format!("mms-{}", c.kind), cls.clone()];
    if let Some(a) = &c.animation {
        if !a.name.is_empty() && a.name != "none" && ANIMATIONS.contains(&a.name.as_str()) {
            classes.push(format!(
                "mms-anim mms-anim-{} mms-trigger-{}",
                a.name,
                if a.trigger == "hover" || a.trigger == "load" {
                    a.trigger.clone()
                } else {
                    "in-view".into()
                }
            ));
            let _ = write!(css, ".{scope} .{cls}{{--mms-anim-duration:{}ms;--mms-anim-delay:{}ms;--mms-anim-easing:{};}}", a.duration_ms.clamp(0, 10000), a.delay_ms.clamp(0, 10000), if ["ease", "ease-in", "ease-out", "ease-in-out", "linear"].contains(&a.easing.as_str()) { a.easing.as_str() } else { "ease-out" });
        }
    }
    for (bp, max) in [(&c.tablet, 1024), (&c.mobile, 640)] {
        if let Some(r) = bp {
            let mut rule = String::new();
            if r.hidden {
                rule.push_str("display:none !important;");
            }
            if let Some(w) = pct(&r.width) {
                let _ = write!(rule, "flex-basis:{w};width:{w};max-width:100%;");
            }
            if ["left", "center", "right"].contains(&r.align.as_str()) {
                let _ = write!(rule, "text-align:{};", r.align);
            }
            if let Some(fs) = px(&r.font_size) {
                let _ = write!(rule, "font-size:{fs}px;");
            }
            if let Some(p) = px(&r.padding) {
                let _ = write!(rule, "padding:{p}px;");
            }
            if !rule.is_empty() {
                let _ = write!(
                    css,
                    "@media (max-width:{max}px){{.{scope} .{cls}{{{rule}}}}}"
                );
            }
        }
    }
    let class_attr = classes.join(" ");
    match c.kind.as_str() {
        "container" => {
            let layout = c.prop("layout");
            let cols = c.prop_num("columns").clamp(1, 6);
            let gap = c.prop_num("gap").clamp(0, 200);
            let pad = c.prop_num("padding").clamp(0, 200);
            let radius = c.prop_num("radius").clamp(0, 100);
            let mut style = format!("gap:{gap}px;padding:{pad}px;border-radius:{radius}px;");
            match layout.as_str() {
                "row" => style.push_str("display:flex;flex-wrap:wrap;"),
                "grid" => {
                    let _ = write!(
                        style,
                        "display:grid;grid-template-columns:repeat({cols},minmax(0,1fr));"
                    );
                }
                "columns" => {
                    let _ = write!(
                        style,
                        "display:grid;grid-template-columns:repeat({},minmax(0,1fr));",
                        c.children.len().clamp(1, 6)
                    );
                }
                _ => style.push_str("display:flex;flex-direction:column;"),
            }
            let align = c.prop("align");
            if ["start", "center", "end", "stretch"].contains(&align.as_str()) {
                let _ = write!(style, "align-items:{align};");
            }
            if let Some(bg) = safe_color(&c.prop("background")) {
                let _ = write!(style, "background:{bg};");
            }
            let _ = write!(css, ".{scope} .{cls}{{{style}}}");
            if layout == "grid" || layout == "columns" {
                let _ = write!(
                    css,
                    "@media (max-width:640px){{.{scope} .{cls}{{grid-template-columns:1fr;}}}}"
                );
            }
            let _ = write!(
                html,
                "<div class=\"{class_attr} mms-layout-{}\">",
                esc(&layout)
            );
            for child in &c.children {
                render_component(child, ctx, scope, html, css, depth + 1);
            }
            html.push_str("</div>");
        }
        "text" => {
            let style = c.prop("style");
            let tag = match style.as_str() {
                "heading" => "h2",
                "subheading" => "h3",
                "caption" => "small",
                "quote" => "blockquote",
                _ => "p",
            };
            let mut st = String::new();
            let align = c.prop("align");
            if ["left", "center", "right"].contains(&align.as_str()) {
                let _ = write!(st, "text-align:{align};");
            }
            if let Some(col) = safe_color(&c.prop("color")) {
                let _ = write!(st, "color:{col};");
            }
            if !st.is_empty() {
                let _ = write!(css, ".{scope} .{cls}{{{st}}}");
            }
            let text = esc(&c.prop("text")).replace('\n', "<br>");
            let _ = write!(html, "<{tag} class=\"{class_attr}\">{text}</{tag}>");
        }
        "image" => {
            let url = (ctx.media_url)(&c.prop("media"));
            let fit = if c.prop("fit") == "contain" {
                "contain"
            } else {
                "cover"
            };
            let ratio = match c.prop("ratio").as_str() {
                "16:9" => "16/9",
                "4:3" => "4/3",
                "1:1" => "1/1",
                "3:4" => "3/4",
                _ => "auto",
            };
            let radius = c.prop_num("radius").clamp(0, 100);
            let _ = write!(css, ".{scope} .{cls} img{{object-fit:{fit};aspect-ratio:{ratio};border-radius:{radius}px;width:100%;display:block;}}");
            let protect = c.prop_bool("protect");
            let link = c.prop("link");
            let _ = write!(
                html,
                "<figure class=\"{class_attr}{}\">",
                if protect { " mms-protected" } else { "" }
            );
            if !link.trim().is_empty() {
                let _ = write!(html, "<a href=\"{}\">", safe_url(&link));
            }
            match url {
                Some(u) => {
                    let _ = write!(
                        html,
                        "<img src=\"{}\" alt=\"{}\" loading=\"lazy\"{}>",
                        esc(&u),
                        esc(&c.prop("alt")),
                        if protect {
                            " draggable=\"false\" oncontextmenu=\"return false\""
                        } else {
                            ""
                        }
                    );
                }
                None => html.push_str("<div class=\"mms-placeholder\">Image</div>"),
            }
            if !link.trim().is_empty() {
                html.push_str("</a>");
            }
            html.push_str("</figure>");
        }
        "video" | "audio" => {
            let product = c.prop("product");
            let _ = write!(html, "<div class=\"{class_attr}\">");
            if !product.is_empty() {
                // Product players are gated: the product page decides preview vs. full access.
                let _ = write!(html, "<iframe class=\"mms-product-frame\" src=\"{}/embed/product/{}?site={}\" title=\"{}\" loading=\"lazy\" allow=\"fullscreen; autoplay\"></iframe>", esc(ctx.base), esc(&product), esc(ctx.site), esc(&product));
            } else if let Some(u) = (ctx.media_url)(&c.prop("media")) {
                let poster = (ctx.media_url)(&c.prop("poster"))
                    .map(|p| format!(" poster=\"{}\"", esc(&p)))
                    .unwrap_or_default();
                let player = match c.prop("player").as_str() {
                    "plyr" | "videojs" | "native" => c.prop("player"),
                    _ => "default".into(),
                };
                let _ = write!(html, "<mms-player type=\"{}\" src=\"{}\"{poster} player=\"{}\" base=\"{}\"{}></mms-player>", c.kind, esc(&u), esc(&player), esc(ctx.base), if c.prop_bool("autoplay") { " autoplay muted" } else { "" });
            } else {
                let _ = write!(
                    html,
                    "<div class=\"mms-placeholder\">{}</div>",
                    if c.kind == "video" { "Video" } else { "Audio" }
                );
            }
            let cap = c.prop(if c.kind == "video" {
                "caption"
            } else {
                "title"
            });
            if !cap.is_empty() {
                let _ = write!(html, "<p class=\"mms-caption\">{}</p>", esc(&cap));
            }
            html.push_str("</div>");
        }
        "pdf" => {
            let h = c.prop_num("height").clamp(200, 2000);
            let product = c.prop("product");
            let _ = write!(html, "<div class=\"{class_attr}\">");
            if !product.is_empty() {
                let _ = write!(html, "<iframe class=\"mms-product-frame\" src=\"{}/embed/product/{}?site={}\" title=\"{}\" loading=\"lazy\"></iframe>", esc(ctx.base), esc(&product), esc(ctx.site), esc(&product));
            } else if let Some(u) = (ctx.media_url)(&c.prop("media")) {
                let _ = write!(html, "<iframe src=\"{}\" style=\"width:100%;height:{h}px;border:0\" title=\"{}\"></iframe>", esc(&u), esc(&c.prop("title")));
            } else {
                html.push_str("<div class=\"mms-placeholder\">PDF</div>");
            }
            html.push_str("</div>");
        }
        "button" => {
            let style = match c.prop("style").as_str() {
                "secondary" | "outline" | "link" => c.prop("style"),
                _ => "primary".into(),
            };
            let size = match c.prop("size").as_str() {
                "small" | "large" => c.prop("size"),
                _ => "medium".into(),
            };
            let _ = write!(html, "<a class=\"{class_attr} mms-btn mms-btn-{style} mms-btn-{size}{}\" href=\"{}\">{}</a>", if c.prop_bool("full") { " mms-btn-full" } else { "" }, safe_url(&c.prop("url")), esc(&c.prop("label")));
        }
        "product_card" => {
            let slug = c.prop("product");
            match (ctx.product)(&slug) {
                Some(p) => {
                    let _ = write!(
                        html,
                        "<a class=\"{class_attr} mms-card\" href=\"{}/embed/product/{}?site={}\">",
                        esc(ctx.base),
                        esc(&p.slug),
                        esc(ctx.site)
                    );
                    match &p.thumb {
                        Some(t) => {
                            let _ = write!(html, "<div class=\"mms-card-thumb\" style=\"background-image:url('{}')\"><span class=\"mms-type\">{}</span></div>", esc(t), esc(&p.kind));
                        }
                        None => {
                            let _ = write!(html, "<div class=\"mms-card-thumb\"><span class=\"mms-type\">{}</span></div>", esc(&p.kind));
                        }
                    }
                    let _ = write!(html, "<h3>{}</h3>", esc(&p.title));
                    if c.prop_bool("show_description") && !p.description.is_empty() {
                        let _ = write!(html, "<p>{}</p>", esc(&p.description));
                    }
                    let _ = write!(html, "<div class=\"mms-card-foot\">");
                    if c.prop_bool("show_price") {
                        let _ = write!(html, "<span class=\"mms-price\">{}</span>", esc(&p.price));
                    }
                    let _ = write!(
                        html,
                        "<span class=\"mms-btn mms-btn-primary mms-btn-small\">{}</span></div></a>",
                        esc(&c.prop("button"))
                    );
                }
                None => {
                    let _ = write!(html, "<div class=\"{class_attr} mms-placeholder\">Product card: choose a product</div>");
                }
            }
        }
        "price" => {
            let size = match c.prop("size").as_str() {
                "medium" | "huge" => c.prop("size"),
                _ => "large".into(),
            };
            let price = (ctx.product)(&c.prop("product"))
                .map(|p| p.price)
                .unwrap_or_else(|| "—".into());
            let _ = write!(
                html,
                "<div class=\"{class_attr} mms-price-{size}\">{}{}</div>",
                esc(&c.prop("prefix")),
                esc(&price)
            );
        }
        "add_to_cart" => {
            let style = match c.prop("style").as_str() {
                "secondary" | "outline" => c.prop("style"),
                _ => "primary".into(),
            };
            let slug = c.prop("product");
            let href = if slug.is_empty() {
                "#".to_string()
            } else {
                format!(
                    "{}/embed/checkout?site={}&product={}",
                    esc(ctx.base),
                    esc(ctx.site),
                    esc(&slug)
                )
            };
            let _ = write!(html, "<a class=\"{class_attr} mms-btn mms-btn-{style}\" href=\"{href}\" data-product=\"{}\">{}</a>", esc(&slug), esc(&c.prop("label")));
        }
        "countdown" => {
            let _ = write!(html, "<div class=\"{class_attr} mms-countdown\" data-until=\"{}\" data-expired=\"{}\"><span class=\"mms-countdown-label\">{}</span><span class=\"mms-countdown-value\">…</span></div>", esc(&c.prop("until")), esc(&c.prop("expired")), esc(&c.prop("label")));
        }
        "icon" => {
            let icon = c.prop("icon");
            let size = c.prop_num("size").clamp(12, 200);
            let color = safe_color(&c.prop("color")).unwrap_or_else(|| "currentColor".into());
            let _ = write!(
                css,
                ".{scope} .{cls} svg{{width:{size}px;height:{size}px;color:{color};}}"
            );
            let _ = write!(
                html,
                "<div class=\"{class_attr} mms-icon\">{}{}</div>",
                icon_svg(&icon),
                if c.prop("label").is_empty() {
                    String::new()
                } else {
                    format!("<span>{}</span>", esc(&c.prop("label")))
                }
            );
        }
        "spacer" => {
            let h = c.prop_num("height").clamp(0, 500);
            let _ = write!(
                html,
                "<div class=\"{class_attr}\" style=\"height:{h}px\"></div>"
            );
        }
        "divider" => {
            let style = match c.prop("style").as_str() {
                "dots" | "none" => c.prop("style"),
                _ => "line".into(),
            };
            let _ = write!(html, "<hr class=\"{class_attr} mms-divider-{style}\">");
        }
        _ => {}
    }
}

fn pct(s: &str) -> Option<String> {
    let t = s.trim();
    if t.is_empty() {
        return None;
    }
    let n: f64 = t.trim_end_matches('%').parse().ok()?;
    ((1.0..=100.0).contains(&n)).then(|| format!("{n}%"))
}

fn px(s: &str) -> Option<i64> {
    let t = s.trim().trim_end_matches("px");
    let n: i64 = t.parse().ok()?;
    (0..=400).contains(&n).then_some(n)
}

fn icon_svg(name: &str) -> &'static str {
    match name {
        "music" => "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><path d=\"M9 18V5l12-2v13\"/><circle cx=\"6\" cy=\"18\" r=\"3\"/><circle cx=\"18\" cy=\"16\" r=\"3\"/></svg>",
        "image" => "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><rect x=\"3\" y=\"3\" width=\"18\" height=\"18\" rx=\"2\"/><circle cx=\"8.5\" cy=\"8.5\" r=\"1.5\"/><path d=\"m21 15-5-5L5 21\"/></svg>",
        "file" => "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><path d=\"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z\"/><path d=\"M14 2v6h6\"/></svg>",
        "star" => "<svg viewBox=\"0 0 24 24\" fill=\"currentColor\"><path d=\"m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z\"/></svg>",
        "clock" => "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M12 6v6l4 2\"/></svg>",
        "lock" => "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><rect x=\"3\" y=\"11\" width=\"18\" height=\"11\" rx=\"2\"/><path d=\"M7 11V7a5 5 0 0 1 10 0v4\"/></svg>",
        "check" => "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><path d=\"M20 6 9 17l-5-5\"/></svg>",
        "heart" => "<svg viewBox=\"0 0 24 24\" fill=\"currentColor\"><path d=\"M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8z\"/></svg>",
        "download" => "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><path d=\"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4\"/><path d=\"m7 10 5 5 5-5\"/><path d=\"M12 15V3\"/></svg>",
        _ => "<svg viewBox=\"0 0 24 24\" fill=\"currentColor\"><path d=\"M8 5v14l11-7z\"/></svg>",
    }
}

/// Sanitises custom CSS and prefixes every selector with the widget scope.
/// Refuses scripting constructs and remote imports; keeps @media blocks.
pub fn scope_css(input: &str, scope: &str) -> String {
    let lower = input.to_ascii_lowercase();
    if input.len() > 64 * 1024
        || lower.contains("expression(")
        || lower.contains("javascript:")
        || lower.contains("@import")
        || lower.contains("behavior:")
        || lower.contains("-moz-binding")
        || lower.contains("</")
    {
        return String::new();
    }
    // url(): only https, relative or data:image.
    let mut cleaned = String::new();
    let mut rest = input;
    while let Some(i) = rest.find("url(") {
        cleaned.push_str(&rest[..i]);
        let after = &rest[i + 4..];
        let Some(end) = after.find(')') else {
            cleaned.push_str("url()");
            rest = "";
            break;
        };
        let arg = after[..end].trim().trim_matches(|c| c == '"' || c == '\'');
        let ok = arg.starts_with("https://")
            || arg.starts_with('/')
            || arg.starts_with("data:image/")
            || (!arg.contains(':') && !arg.starts_with("//"));
        if ok {
            cleaned.push_str(&rest[i..i + 4 + end + 1]);
        } else {
            cleaned.push_str("url()");
        }
        rest = &after[end + 1..];
    }
    cleaned.push_str(rest);
    scope_block(&cleaned, scope)
}

fn scope_block(css: &str, scope: &str) -> String {
    let mut out = String::new();
    let mut i = 0;
    let b = css.as_bytes();
    while i < b.len() {
        // find next '{'
        let Some(open) = css[i..].find('{') else {
            break;
        };
        let selector = css[i..i + open].trim();
        let start = i + open + 1;
        // matching close, honouring nesting for @media
        let mut depth = 1;
        let mut j = start;
        while j < b.len() && depth > 0 {
            match b[j] {
                b'{' => depth += 1,
                b'}' => depth -= 1,
                _ => {}
            }
            j += 1;
        }
        let body = &css[start..j.saturating_sub(1).max(start)];
        if selector.starts_with('@') {
            if selector.starts_with("@media")
                || selector.starts_with("@supports")
                || selector.starts_with("@container")
            {
                let _ = write!(out, "{selector}{{{}}}", scope_block(body, scope));
            }
            // other at-rules (keyframes, font-face) are dropped
        } else if !selector.is_empty() {
            let scoped: Vec<String> = selector
                .split(',')
                .map(|s| {
                    let s = s.trim();
                    if s == ":root" || s == ":scope" {
                        format!(".{scope}")
                    } else {
                        format!(".{scope} {s}")
                    }
                })
                .collect();
            let _ = write!(out, "{}{{{}}}", scoped.join(","), body.trim());
        }
        i = j;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ctx<'a>(
        css: &'a str,
        media: &'a dyn Fn(&str) -> Option<String>,
        product: &'a dyn Fn(&str) -> Option<ProductInfo>,
        vars: &'a [(String, String)],
    ) -> RenderContext<'a> {
        RenderContext {
            uuid: "abc",
            base: "/mms",
            site: "site-1",
            theme: "auto",
            scheme_vars: vars,
            custom_css: css,
            media_url: media,
            product,
        }
    }

    #[test]
    fn renders_deterministically_and_escapes() {
        let json = r#"{"schema_version":1,"root":{"id":"root","kind":"container","props":{"layout":"columns","gap":24},"children":[
            {"id":"t1","kind":"text","props":{"text":"<b>Hello</b> & welcome","style":"heading","align":"center"},"animation":{"name":"fade","trigger":"in-view"},"mobile":{"hidden":true}},
            {"id":"b1","kind":"button","props":{"label":"Go","url":"javascript:alert(1)","style":"outline"}},
            {"id":"p1","kind":"product_card","props":{"product":"film"}},
            {"id":"i1","kind":"image","props":{"media":"m1","alt":"Lamp","ratio":"16:9","protect":true}}
        ]}}"#;
        let def = Definition::parse(json).unwrap();
        let media = |u: &str| (u == "m1").then(|| "/mms/media/thumbs/m1/640.jpg".to_string());
        let product = |s: &str| {
            (s == "film").then(|| ProductInfo {
                slug: "film".into(),
                title: "Film".into(),
                description: "d".into(),
                price: "USD 9.00".into(),
                thumb: None,
                kind: "Video".into(),
            })
        };
        let vars = vec![
            ("accent".to_string(), "#112233".to_string()),
            ("bad".to_string(), "url(javascript:x)".to_string()),
        ];
        let a = render(&def, &ctx("", &media, &product, &vars));
        let b = render(&def, &ctx("", &media, &product, &vars));
        assert_eq!(a.html, b.html);
        assert_eq!(a.css, b.css);
        assert!(
            a.html.contains("&lt;b&gt;Hello&lt;/b&gt; &amp; welcome"),
            "text is escaped"
        );
        assert!(
            a.html.contains("href=\"#\""),
            "javascript: links are neutralised"
        );
        assert!(a.html.contains("mms-anim-fade") && a.css.contains("--mms-anim-duration:600ms"));
        assert!(a
            .css
            .contains("@media (max-width:640px){.mms-w-abc .mms-c-t1{display:none !important;}}"));
        assert!(a.html.contains("Film") && a.html.contains("USD 9.00"));
        assert!(
            a.html.contains("draggable=\"false\"") && a.html.contains("aspect-ratio:16/9")
                || a.css.contains("aspect-ratio:16/9")
        );
        assert!(a.css.contains("--mms-accent:#112233") && !a.css.contains("javascript"));
        assert!(
            a.css
                .contains("grid-template-columns:repeat(4,minmax(0,1fr))"),
            "columns layout counts children"
        );
    }

    #[test]
    fn parse_rejects_bad_definitions() {
        assert!(Definition::parse("{}").is_err());
        assert!(Definition::parse(r#"{"schema_version":9,"root":{"kind":"container"}}"#).is_err());
        assert!(Definition::parse(r#"{"root":{"kind":"text"}}"#).is_err());
        assert!(Definition::parse(
            r#"{"root":{"kind":"container","children":[{"kind":"marquee"}]}}"#
        )
        .is_err());
        assert!(Definition::parse(r#"{"root":{"kind":"container"}}"#).is_ok());
    }

    #[test]
    fn custom_css_is_scoped_and_sanitised() {
        let out = scope_css("h2, .x { color: red } @media (max-width: 600px) { p { display: none } } :root { --mms-accent: #fff }", "mms-w-1");
        assert_eq!(out, ".mms-w-1 h2,.mms-w-1 .x{color: red}@media (max-width: 600px){.mms-w-1 p{display: none}}.mms-w-1{--mms-accent: #fff}");
        assert_eq!(
            scope_css("p{background:url(javascript:alert(1))}", "s"),
            "",
            "scripting anywhere rejects the whole sheet"
        );
        assert_eq!(
            scope_css("p{background:url(http://evil.example/x.png)}", "s"),
            ".s p{background:url()}",
            "plain http urls are stripped"
        );
        assert_eq!(
            scope_css("p{background:url(https://cdn.example/x.png)}", "s"),
            ".s p{background:url(https://cdn.example/x.png)}"
        );
        assert_eq!(scope_css("@import url(x.css); p{}", "s"), "");
        assert_eq!(scope_css("p{width:expression(1)}", "s"), "");
        assert_eq!(
            scope_css("@keyframes k{from{}to{}} p{color:blue}", "s"),
            ".s p{color:blue}"
        );
    }
}
