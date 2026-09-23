//! Built-in widget templates (35), site templates (12) and colour schemes.
//! Definitions are generated from compact specs so every template is distinct and
//! renders through the same renderer as user widgets.

use crate::render::{Component, Definition, SCHEMA_VERSION};
use serde::Serialize;
use serde_json::{json, Map, Value};

#[derive(Debug, Clone, Serialize)]
pub struct WidgetTemplate {
    pub slug: String,
    pub name: String,
    pub category: String,
    pub description: String,
    pub definition: Definition,
    pub scheme: String,
}

pub const CATEGORIES: &[(&str, &str)] = &[
    ("video", "Video showcase"),
    ("audio", "Audio player"),
    ("gallery", "Image gallery"),
    ("pdf", "PDF viewer"),
    ("card", "Product card"),
    ("hero", "Hero / CTA"),
    ("pricing", "Pricing / site pass"),
    ("live", "Live & meeting"),
];

fn c(id: &str, kind: &str, props: Value, children: Vec<Component>) -> Component {
    let props: Map<String, Value> = props.as_object().cloned().unwrap_or_default();
    Component {
        id: id.into(),
        kind: kind.into(),
        props,
        children,
        animation: None,
        mobile: None,
        tablet: None,
    }
}

fn anim(mut comp: Component, name: &str, trigger: &str, delay: i64) -> Component {
    comp.animation = Some(crate::render::Animation {
        name: name.into(),
        trigger: trigger.into(),
        duration_ms: 600,
        delay_ms: delay,
        easing: "ease-out".into(),
    });
    comp
}

fn root(layout: &str, props: Value, children: Vec<Component>) -> Definition {
    let mut p = props.as_object().cloned().unwrap_or_default();
    p.insert("layout".into(), layout.into());
    p.entry("gap").or_insert(16.into());
    p.entry("padding").or_insert(16.into());
    Definition {
        schema_version: SCHEMA_VERSION,
        root: Component {
            id: "root".into(),
            kind: "container".into(),
            props: p,
            children,
            animation: None,
            mobile: None,
            tablet: None,
        },
    }
}

fn text(id: &str, t: &str, style: &str, align: &str) -> Component {
    c(
        id,
        "text",
        json!({ "text": t, "style": style, "align": align }),
        vec![],
    )
}

fn button(id: &str, label: &str, style: &str) -> Component {
    c(
        id,
        "button",
        json!({ "label": label, "url": "#", "style": style, "size": "medium" }),
        vec![],
    )
}

fn card(id: &str) -> Component {
    c(
        id,
        "product_card",
        json!({ "product": "", "show_price": true, "show_description": true, "button": "View" }),
        vec![],
    )
}

fn video(id: &str) -> Component {
    c(
        id,
        "video",
        json!({ "product": "", "media": "", "player": "default" }),
        vec![],
    )
}

fn audio(id: &str) -> Component {
    c(
        id,
        "audio",
        json!({ "product": "", "media": "", "visualiser": "bars" }),
        vec![],
    )
}

fn image(id: &str, ratio: &str) -> Component {
    c(
        id,
        "image",
        json!({ "media": "", "alt": "", "fit": "cover", "ratio": ratio, "radius": 8 }),
        vec![],
    )
}

fn icon(id: &str, name: &str, label: &str) -> Component {
    c(
        id,
        "icon",
        json!({ "icon": name, "size": 36, "label": label }),
        vec![],
    )
}

fn spacer(id: &str, h: i64) -> Component {
    c(id, "spacer", json!({ "height": h }), vec![])
}

fn grid(id: &str, cols: i64, children: Vec<Component>) -> Component {
    c(
        id,
        "container",
        json!({ "layout": "grid", "columns": cols, "gap": 16, "padding": 0 }),
        children,
    )
}

fn columns(id: &str, children: Vec<Component>) -> Component {
    c(
        id,
        "container",
        json!({ "layout": "columns", "gap": 24, "padding": 0, "align": "center" }),
        children,
    )
}

fn stack(id: &str, pad: i64, bg: &str, children: Vec<Component>) -> Component {
    c(
        id,
        "container",
        json!({ "layout": "stack", "gap": 12, "padding": pad, "background": bg, "radius": 12 }),
        children,
    )
}

/// All 35 built-in widget templates.
pub fn widget_templates() -> Vec<WidgetTemplate> {
    let mut t: Vec<WidgetTemplate> = Vec::new();
    let mut add = |slug: &str, name: &str, cat: &str, desc: &str, scheme: &str, def: Definition| {
        t.push(WidgetTemplate {
            slug: slug.into(),
            name: name.into(),
            category: cat.into(),
            description: desc.into(),
            definition: def,
            scheme: scheme.into(),
        });
    };

    // ---- Video showcase (6) ----
    add(
        "video-hero",
        "Video hero",
        "video",
        "Full-width video with a headline and call to action beneath.",
        "default",
        root(
            "stack",
            json!({}),
            vec![
                video("v"),
                anim(
                    text("h", "Watch the masterclass", "heading", "center"),
                    "fade",
                    "in-view",
                    0,
                ),
                text(
                    "p",
                    "Two hours of hands-on lighting setups.",
                    "paragraph",
                    "center",
                ),
                button("b", "Get access", "primary"),
            ],
        ),
    );
    add(
        "video-split",
        "Video with text",
        "video",
        "Video on the left, title, description and button on the right.",
        "default",
        root(
            "columns",
            json!({ "gap": 32 }),
            vec![
                video("v"),
                stack(
                    "s",
                    0,
                    "",
                    vec![
                        text("h", "Behind the lens", "heading", "left"),
                        text(
                            "p",
                            "Learn the setups professionals use every day.",
                            "paragraph",
                            "left",
                        ),
                        c(
                            "pr",
                            "price",
                            json!({ "product": "", "size": "large" }),
                            vec![],
                        ),
                        c(
                            "cart",
                            "add_to_cart",
                            json!({ "product": "", "label": "Buy now", "style": "primary" }),
                            vec![],
                        ),
                    ],
                ),
            ],
        ),
    );
    add(
        "video-trio",
        "Three video cards",
        "video",
        "A row of three product cards for video products.",
        "default",
        root(
            "stack",
            json!({}),
            vec![
                text("h", "Latest lessons", "heading", "left"),
                grid(
                    "g",
                    3,
                    vec![
                        anim(card("c1"), "slide-up", "in-view", 0),
                        anim(card("c2"), "slide-up", "in-view", 100),
                        anim(card("c3"), "slide-up", "in-view", 200),
                    ],
                ),
            ],
        ),
    );
    add(
        "video-premiere",
        "Premiere countdown",
        "video",
        "Poster image, countdown and a reserve button for an upcoming release.",
        "night",
        root(
            "stack",
            json!({ "background": "var(--mms-surface)", "padding": 24 }),
            vec![
                image("i", "16:9"),
                c(
                    "cd",
                    "countdown",
                    json!({ "until": "2026-12-31 18:00", "label": "Premieres in", "expired": "Now showing" }),
                    vec![],
                ),
                text("h", "The Long Exposure", "heading", "center"),
                button("b", "Reserve your seat", "primary"),
            ],
        ),
    );
    add(
        "video-playlist",
        "Playlist",
        "video",
        "Featured video with a list of four more beneath it.",
        "default",
        root(
            "stack",
            json!({}),
            vec![
                video("v"),
                text("h", "In this series", "subheading", "left"),
                grid("g", 4, vec![card("c1"), card("c2"), card("c3"), card("c4")]),
            ],
        ),
    );
    add(
        "video-testimonial",
        "Video testimonial",
        "video",
        "A quote beside a short video, for social proof.",
        "warm",
        root(
            "columns",
            json!({ "gap": 32 }),
            vec![
                video("v"),
                stack(
                    "s",
                    0,
                    "",
                    vec![
                        text(
                            "q",
                            "\"The clearest lighting course I have taken.\"",
                            "quote",
                            "left",
                        ),
                        text("a", "— Ada, portrait photographer", "caption", "left"),
                        icon("st", "star", "5 stars"),
                    ],
                ),
            ],
        ),
    );

    // ---- Audio player (5) ----
    add(
        "audio-single",
        "Single track",
        "audio",
        "One track with title, artwork and a buy button.",
        "default",
        root(
            "columns",
            json!({ "gap": 24 }),
            vec![
                image("art", "1:1"),
                stack(
                    "s",
                    0,
                    "",
                    vec![
                        text("h", "Late Night Sessions", "heading", "left"),
                        audio("a"),
                        c(
                            "cart",
                            "add_to_cart",
                            json!({ "product": "", "label": "Buy the album", "style": "primary" }),
                            vec![],
                        ),
                    ],
                ),
            ],
        ),
    );
    add(
        "audio-album",
        "Album grid",
        "audio",
        "Artwork with a grid of six track cards.",
        "night",
        root(
            "stack",
            json!({}),
            vec![
                image("art", "16:9"),
                text("h", "Tracks", "subheading", "left"),
                grid(
                    "g",
                    3,
                    vec![
                        card("c1"),
                        card("c2"),
                        card("c3"),
                        card("c4"),
                        card("c5"),
                        card("c6"),
                    ],
                ),
            ],
        ),
    );
    add(
        "audio-podcast",
        "Podcast episode",
        "audio",
        "Episode player with show notes and a subscribe button.",
        "warm",
        root(
            "stack",
            json!({}),
            vec![
                text("k", "Episode 12", "caption", "left"),
                text("h", "Pricing your creative work", "heading", "left"),
                audio("a"),
                text(
                    "p",
                    "Show notes and links from the episode.",
                    "paragraph",
                    "left",
                ),
                button("b", "Subscribe", "outline"),
            ],
        ),
    );
    add(
        "audio-minimal",
        "Minimal player",
        "audio",
        "Just the player and a title, for sidebars.",
        "default",
        root(
            "stack",
            json!({ "padding": 8 }),
            vec![text("h", "Now playing", "caption", "left"), audio("a")],
        ),
    );
    add(
        "audio-banner",
        "Release banner",
        "audio",
        "Wide artwork, release title, player and two buttons.",
        "night",
        root(
            "stack",
            json!({ "background": "var(--mms-surface)", "padding": 24 }),
            vec![
                image("art", "16:9"),
                text("h", "Out now", "heading", "center"),
                audio("a"),
                c(
                    "row",
                    "container",
                    json!({ "layout": "row", "gap": 12, "padding": 0, "align": "center" }),
                    vec![
                        button("b1", "Buy", "primary"),
                        button("b2", "Preview", "outline"),
                    ],
                ),
            ],
        ),
    );

    // ---- Image gallery (6) ----
    add(
        "gallery-grid",
        "Three-column grid",
        "gallery",
        "Six images in a tidy grid.",
        "default",
        root(
            "stack",
            json!({}),
            vec![grid(
                "g",
                3,
                (1..=6)
                    .map(|i| {
                        anim(
                            image(&format!("i{i}"), "1:1"),
                            "zoom",
                            "in-view",
                            (i as i64 - 1) * 60,
                        )
                    })
                    .collect(),
            )],
        ),
    );
    add(
        "gallery-masonry",
        "Two and one",
        "gallery",
        "A large image beside two stacked ones.",
        "default",
        root(
            "columns",
            json!({ "gap": 12 }),
            vec![
                image("big", "3:4"),
                stack("s", 0, "", vec![image("a", "4:3"), image("b", "4:3")]),
            ],
        ),
    );
    add(
        "gallery-captioned",
        "Captioned pairs",
        "gallery",
        "Two images with captions and a title above.",
        "warm",
        root(
            "stack",
            json!({}),
            vec![
                text("h", "Coastal textures", "heading", "left"),
                columns(
                    "cols",
                    vec![
                        stack(
                            "s1",
                            0,
                            "",
                            vec![
                                image("i1", "4:3"),
                                text("c1", "Salt-worn timber", "caption", "left"),
                            ],
                        ),
                        stack(
                            "s2",
                            0,
                            "",
                            vec![
                                image("i2", "4:3"),
                                text("c2", "Tide-line stone", "caption", "left"),
                            ],
                        ),
                    ],
                ),
            ],
        ),
    );
    add("gallery-protected", "Protected preview", "gallery", "Four protected images with a licence note and buy button.", "default",
        root("stack", json!({}), vec![grid("g", 4, (1..=4).map(|i| c(&format!("i{i}"), "image", json!({ "media": "", "ratio": "1:1", "protect": true, "radius": 6 }), vec![])).collect()), text("n", "Previews are watermarked. Purchased files are delivered clean.", "caption", "center"), c("cart", "add_to_cart", json!({ "product": "", "label": "Buy the pack", "style": "primary" }), vec![])]));
    add(
        "gallery-hero-strip",
        "Hero strip",
        "gallery",
        "One wide image with a row of four thumbnails.",
        "night",
        root(
            "stack",
            json!({ "gap": 8 }),
            vec![
                image("hero", "16:9"),
                grid(
                    "g",
                    4,
                    (1..=4).map(|i| image(&format!("t{i}"), "4:3")).collect(),
                ),
            ],
        ),
    );
    add(
        "gallery-single",
        "Single feature",
        "gallery",
        "One image, title, description and price.",
        "default",
        root(
            "columns",
            json!({ "gap": 32 }),
            vec![
                image("i", "4:3"),
                stack(
                    "s",
                    0,
                    "",
                    vec![
                        text("h", "Golden hour, Lofoten", "heading", "left"),
                        text(
                            "p",
                            "Fine-art print, signed and numbered.",
                            "paragraph",
                            "left",
                        ),
                        c(
                            "pr",
                            "price",
                            json!({ "product": "", "size": "huge" }),
                            vec![],
                        ),
                        c(
                            "cart",
                            "add_to_cart",
                            json!({ "product": "", "label": "Order print", "style": "primary" }),
                            vec![],
                        ),
                    ],
                ),
            ],
        ),
    );

    // ---- PDF viewer (3) ----
    add(
        "pdf-reader",
        "In-page reader",
        "pdf",
        "A tall PDF reader with a title and download note.",
        "default",
        root(
            "stack",
            json!({}),
            vec![
                text("h", "The Freelance Contract Kit", "heading", "left"),
                c(
                    "pdf",
                    "pdf",
                    json!({ "product": "", "media": "", "height": 720 }),
                    vec![],
                ),
                text("n", "Buyers can download and print.", "caption", "left"),
            ],
        ),
    );
    add(
        "pdf-preview-buy",
        "Preview and buy",
        "pdf",
        "Short preview beside a description and buy button.",
        "warm",
        root(
            "columns",
            json!({ "gap": 32 }),
            vec![
                c(
                    "pdf",
                    "pdf",
                    json!({ "product": "", "media": "", "height": 480 }),
                    vec![],
                ),
                stack(
                    "s",
                    0,
                    "",
                    vec![
                        text("h", "Read the first three pages", "heading", "left"),
                        text(
                            "p",
                            "Editable agreements and checklists for creative freelancers.",
                            "paragraph",
                            "left",
                        ),
                        c(
                            "pr",
                            "price",
                            json!({ "product": "", "size": "large" }),
                            vec![],
                        ),
                        c(
                            "cart",
                            "add_to_cart",
                            json!({ "product": "", "label": "Buy the kit", "style": "primary" }),
                            vec![],
                        ),
                    ],
                ),
            ],
        ),
    );
    add(
        "pdf-library",
        "Document library",
        "pdf",
        "A grid of four document cards.",
        "default",
        root(
            "stack",
            json!({}),
            vec![
                text("h", "Guides and templates", "heading", "left"),
                grid("g", 4, vec![card("c1"), card("c2"), card("c3"), card("c4")]),
            ],
        ),
    );

    // ---- Product card (5) ----
    add(
        "card-single",
        "Single card",
        "card",
        "One product card, centred.",
        "default",
        root("stack", json!({ "align": "center" }), vec![card("c1")]),
    );
    add(
        "card-pair",
        "Two cards",
        "card",
        "Two product cards side by side.",
        "default",
        root(
            "stack",
            json!({}),
            vec![grid("g", 2, vec![card("c1"), card("c2")])],
        ),
    );
    add(
        "card-featured-row",
        "Featured row",
        "card",
        "Heading, four cards and a link to the full store.",
        "default",
        root(
            "stack",
            json!({}),
            vec![
                text("h", "Featured this week", "heading", "left"),
                grid("g", 4, vec![card("c1"), card("c2"), card("c3"), card("c4")]),
                button("b", "See everything", "link"),
            ],
        ),
    );
    add(
        "card-spotlight",
        "Spotlight",
        "card",
        "A large card with an icon list of what is included.",
        "warm",
        root(
            "columns",
            json!({ "gap": 32 }),
            vec![
                card("c1"),
                stack(
                    "s",
                    0,
                    "",
                    vec![
                        text("h", "What you get", "subheading", "left"),
                        icon("i1", "check", "Lifetime access"),
                        icon("i2", "download", "Downloadable files"),
                        icon("i3", "heart", "Free updates"),
                    ],
                ),
            ],
        ),
    );
    add(
        "card-dark",
        "Dark row",
        "card",
        "Three cards on a dark background.",
        "night",
        root(
            "stack",
            json!({ "background": "var(--mms-surface)", "padding": 24 }),
            vec![grid("g", 3, vec![card("c1"), card("c2"), card("c3")])],
        ),
    );

    // ---- Hero / CTA (4) ----
    add(
        "hero-classic",
        "Classic hero",
        "hero",
        "Big headline, supporting line and two buttons.",
        "default",
        root(
            "stack",
            json!({ "align": "center", "padding": 48 }),
            vec![
                anim(
                    text("h", "Sell your media, your way", "heading", "center"),
                    "fade",
                    "load",
                    0,
                ),
                text(
                    "p",
                    "Video, audio, images and downloads from your own site.",
                    "paragraph",
                    "center",
                ),
                spacer("sp", 8),
                c(
                    "row",
                    "container",
                    json!({ "layout": "row", "gap": 12, "padding": 0, "align": "center" }),
                    vec![
                        button("b1", "Browse the store", "primary"),
                        button("b2", "Learn more", "outline"),
                    ],
                ),
            ],
        ),
    );
    add(
        "hero-image",
        "Image hero",
        "hero",
        "Headline over a large image with one button.",
        "default",
        root(
            "columns",
            json!({ "gap": 32 }),
            vec![
                stack(
                    "s",
                    0,
                    "",
                    vec![
                        text("h", "Coastal light, captured", "heading", "left"),
                        text(
                            "p",
                            "Prints, packs and courses from the studio.",
                            "paragraph",
                            "left",
                        ),
                        button("b", "Explore", "primary"),
                    ],
                ),
                anim(image("i", "4:3"), "slide-left", "in-view", 0),
            ],
        ),
    );
    add(
        "hero-announcement",
        "Announcement bar",
        "hero",
        "A slim bar with an icon, one line and a button.",
        "warm",
        root(
            "row",
            json!({ "align": "center", "padding": 12, "background": "var(--mms-surface)" }),
            vec![
                icon("i", "star", ""),
                text(
                    "t",
                    "New: the Studio Lighting Masterclass is out now.",
                    "paragraph",
                    "left",
                ),
                button("b", "Watch", "secondary"),
            ],
        ),
    );
    add(
        "hero-countdown",
        "Launch countdown",
        "hero",
        "Headline, countdown and a notify button.",
        "night",
        root(
            "stack",
            json!({ "align": "center", "padding": 40, "background": "var(--mms-surface)" }),
            vec![
                text("h", "Something new is coming", "heading", "center"),
                c(
                    "cd",
                    "countdown",
                    json!({ "until": "2026-12-31 12:00", "label": "Launching in", "expired": "It's live" }),
                    vec![],
                ),
                button("b", "Notify me", "primary"),
            ],
        ),
    );

    // ---- Pricing / site pass (3) ----
    add(
        "pricing-pass",
        "Site pass",
        "pricing",
        "One pass with what is included and the price.",
        "default",
        root(
            "stack",
            json!({ "align": "center", "padding": 32, "background": "var(--mms-surface)", "radius": 16 }),
            vec![
                text("h", "All-Access Pass", "heading", "center"),
                c(
                    "pr",
                    "price",
                    json!({ "product": "", "size": "huge" }),
                    vec![],
                ),
                icon("i1", "check", "Every video and download"),
                icon("i2", "check", "New releases included"),
                icon("i3", "check", "Cancel any time"),
                c(
                    "cart",
                    "add_to_cart",
                    json!({ "product": "", "label": "Get the pass", "style": "primary" }),
                    vec![],
                ),
            ],
        ),
    );
    add("pricing-tiers", "Three tiers", "pricing", "Three plans side by side.", "default",
        root("stack", json!({}), vec![grid("g", 3, (1..=3).map(|i| stack(&format!("t{i}"), 24, "var(--mms-surface)", vec![text(&format!("h{i}"), ["Starter", "Creator", "Studio"][i - 1], "subheading", "center"), c(&format!("p{i}"), "price", json!({ "product": "", "size": "large" }), vec![]), icon(&format!("f{i}"), "check", "Full library"), c(&format!("b{i}"), "add_to_cart", json!({ "product": "", "label": "Choose", "style": if i == 2 { "primary" } else { "outline" } }), vec![])])).collect())]));
    add(
        "pricing-compare",
        "Buy or pass",
        "pricing",
        "A single product beside the site pass.",
        "warm",
        root(
            "columns",
            json!({ "gap": 24 }),
            vec![
                stack(
                    "a",
                    24,
                    "var(--mms-surface)",
                    vec![
                        text("ha", "Just this item", "subheading", "center"),
                        c(
                            "pa",
                            "price",
                            json!({ "product": "", "size": "large" }),
                            vec![],
                        ),
                        c(
                            "ba",
                            "add_to_cart",
                            json!({ "product": "", "label": "Buy", "style": "outline" }),
                            vec![],
                        ),
                    ],
                ),
                stack(
                    "b",
                    24,
                    "var(--mms-surface)",
                    vec![
                        text("hb", "Everything, all year", "subheading", "center"),
                        c(
                            "pb",
                            "price",
                            json!({ "product": "", "size": "large" }),
                            vec![],
                        ),
                        c(
                            "bb",
                            "add_to_cart",
                            json!({ "product": "", "label": "Get the pass", "style": "primary" }),
                            vec![],
                        ),
                    ],
                ),
            ],
        ),
    );

    // ---- Live & meeting (3) ----
    add(
        "live-event",
        "Live event",
        "live",
        "Poster, countdown, description and a ticket button.",
        "night",
        root(
            "columns",
            json!({ "gap": 32 }),
            vec![
                image("i", "16:9"),
                stack(
                    "s",
                    0,
                    "",
                    vec![
                        text("k", "Live Q&A", "caption", "left"),
                        text("h", "Pricing your work", "heading", "left"),
                        c(
                            "cd",
                            "countdown",
                            json!({ "until": "2026-10-03 19:00", "label": "Starts in", "expired": "Live now" }),
                            vec![],
                        ),
                        c(
                            "cart",
                            "add_to_cart",
                            json!({ "product": "", "label": "Get a ticket", "style": "primary" }),
                            vec![],
                        ),
                    ],
                ),
            ],
        ),
    );
    add(
        "live-meeting",
        "Book a call",
        "live",
        "Consultation card with duration, what to expect and a booking button.",
        "default",
        root(
            "stack",
            json!({ "padding": 24, "background": "var(--mms-surface)", "radius": 16 }),
            vec![
                icon("i", "clock", "45 minutes"),
                text("h", "One-to-one portfolio review", "heading", "left"),
                text(
                    "p",
                    "Send ten images ahead of the call and leave with a plan.",
                    "paragraph",
                    "left",
                ),
                c(
                    "pr",
                    "price",
                    json!({ "product": "", "size": "large" }),
                    vec![],
                ),
                c(
                    "cart",
                    "add_to_cart",
                    json!({ "product": "", "label": "Book a time", "style": "primary" }),
                    vec![],
                ),
            ],
        ),
    );
    add(
        "live-schedule",
        "Upcoming sessions",
        "live",
        "Three upcoming live products in a row.",
        "warm",
        root(
            "stack",
            json!({}),
            vec![
                text("h", "Upcoming sessions", "heading", "left"),
                grid("g", 3, vec![card("c1"), card("c2"), card("c3")]),
            ],
        ),
    );

    debug_assert_eq!(t.len(), 35);
    t
}

pub fn widget_template(slug: &str) -> Option<WidgetTemplate> {
    widget_templates().into_iter().find(|t| t.slug == slug)
}

// ---------- colour schemes ----------

#[derive(Debug, Clone, Serialize)]
pub struct ColourScheme {
    pub slug: String,
    pub name: String,
    pub vars: Vec<(String, String)>,
    pub builtin: bool,
}

#[allow(clippy::too_many_arguments)]
fn scheme(
    slug: &str,
    name: &str,
    accent: &str,
    accent2: &str,
    bg: &str,
    surface: &str,
    text: &str,
    muted: &str,
) -> ColourScheme {
    ColourScheme {
        slug: slug.into(),
        name: name.into(),
        vars: vec![
            ("accent".into(), accent.into()),
            ("accent-2".into(), accent2.into()),
            ("bg".into(), bg.into()),
            ("surface".into(), surface.into()),
            ("text".into(), text.into()),
            ("muted".into(), muted.into()),
        ],
        builtin: true,
    }
}

pub fn builtin_schemes() -> Vec<ColourScheme> {
    vec![
        scheme(
            "default",
            "Studio blue",
            "#1f3a5f",
            "#2f5a8c",
            "#f6f7f9",
            "#ffffff",
            "#1b1f24",
            "#5b6470",
        ),
        scheme(
            "night", "Night", "#8fb4e6", "#b7d0f2", "#0f1318", "#171c23", "#e6e9ee", "#9aa4b1",
        ),
        scheme(
            "warm",
            "Warm sand",
            "#a8552b",
            "#c97a4e",
            "#faf6f1",
            "#ffffff",
            "#2b2118",
            "#7a6a5c",
        ),
        scheme(
            "forest", "Forest", "#1f6b46", "#2f8f60", "#f3f7f4", "#ffffff", "#15211a", "#5d6f64",
        ),
        scheme(
            "plum", "Plum", "#5b2a86", "#7e46b0", "#f7f4fa", "#ffffff", "#211a2b", "#6c5f78",
        ),
        scheme(
            "mono",
            "Monochrome",
            "#111111",
            "#444444",
            "#fafafa",
            "#ffffff",
            "#111111",
            "#666666",
        ),
    ]
}

/// Relative luminance contrast ratio between two hex colours (WCAG).
pub fn contrast_ratio(a: &str, b: &str) -> Option<f64> {
    fn lum(hex: &str) -> Option<f64> {
        let h = hex.trim().trim_start_matches('#');
        if h.len() != 6 {
            return None;
        }
        let ch = |i: usize| {
            u8::from_str_radix(&h[i..i + 2], 16)
                .ok()
                .map(|v| v as f64 / 255.0)
        };
        let f = |c: f64| {
            if c <= 0.03928 {
                c / 12.92
            } else {
                ((c + 0.055) / 1.055).powf(2.4)
            }
        };
        Some(0.2126 * f(ch(0)?) + 0.7152 * f(ch(2)?) + 0.0722 * f(ch(4)?))
    }
    let (la, lb) = (lum(a)?, lum(b)?);
    let (hi, lo) = if la > lb { (la, lb) } else { (lb, la) };
    Some((hi + 0.05) / (lo + 0.05))
}

/// A dark variant derived from a light scheme (or vice versa) for theme switching.
pub fn auto_dark(vars: &[(String, String)]) -> Vec<(String, String)> {
    let get = |k: &str| {
        vars.iter()
            .find(|(n, _)| n == k)
            .map(|(_, v)| v.clone())
            .unwrap_or_default()
    };
    let lighten = |hex: &str| -> String {
        let h = hex.trim_start_matches('#');
        if h.len() != 6 {
            return hex.to_string();
        }
        let p = |i: usize| u8::from_str_radix(&h[i..i + 2], 16).unwrap_or(0) as u32;
        let (r, g, b) = (p(0), p(2), p(4));
        format!(
            "#{:02x}{:02x}{:02x}",
            (r + (255 - r) * 45 / 100).min(255),
            (g + (255 - g) * 45 / 100).min(255),
            (b + (255 - b) * 45 / 100).min(255)
        )
    };
    vec![
        ("accent".into(), lighten(&get("accent"))),
        ("accent-2".into(), lighten(&get("accent-2"))),
        ("bg".into(), "#0f1318".into()),
        ("surface".into(), "#171c23".into()),
        ("text".into(), "#e6e9ee".into()),
        ("muted".into(), "#9aa4b1".into()),
    ]
}

// ---------- site templates ----------

#[derive(Debug, Clone, Serialize)]
pub struct SiteTemplate {
    pub slug: String,
    pub name: String,
    pub industry: String,
    pub description: String,
    pub scheme: String,
    /// (page name, widget template slugs placed on that page, in order)
    pub pages: Vec<(String, Vec<String>)>,
}

pub fn site_templates() -> Vec<SiteTemplate> {
    let st = |slug: &str,
              name: &str,
              industry: &str,
              desc: &str,
              scheme: &str,
              pages: Vec<(&str, Vec<&str>)>| SiteTemplate {
        slug: slug.into(),
        name: name.into(),
        industry: industry.into(),
        description: desc.into(),
        scheme: scheme.into(),
        pages: pages
            .into_iter()
            .map(|(p, w)| (p.to_string(), w.into_iter().map(String::from).collect()))
            .collect(),
    };
    vec![
        st(
            "photographer",
            "Photographer",
            "Photography",
            "Print sales, packs and a gallery-led home page.",
            "warm",
            vec![
                (
                    "Home",
                    vec!["hero-image", "gallery-grid", "card-featured-row"],
                ),
                ("Prints", vec!["gallery-single", "gallery-protected"]),
                ("Store", vec![]),
            ],
        ),
        st(
            "videographer",
            "Videographer",
            "Video",
            "Showreel first, courses and downloads second.",
            "night",
            vec![
                ("Home", vec!["video-hero", "video-trio"]),
                ("Courses", vec!["video-playlist", "pricing-pass"]),
                ("Store", vec![]),
            ],
        ),
        st(
            "musician",
            "Musician / podcaster",
            "Music",
            "Releases, episodes and an album grid.",
            "night",
            vec![
                ("Home", vec!["audio-banner", "audio-album"]),
                ("Podcast", vec!["audio-podcast"]),
                ("Store", vec![]),
            ],
        ),
        st(
            "course",
            "Online course",
            "Education",
            "Lessons in playlists with a site pass.",
            "default",
            vec![
                ("Home", vec!["hero-classic", "video-trio", "pricing-pass"]),
                ("Lessons", vec!["video-playlist"]),
                ("Store", vec![]),
            ],
        ),
        st(
            "consultant",
            "Consultant / coach",
            "Services",
            "Book calls and sell guides.",
            "default",
            vec![
                ("Home", vec!["hero-classic", "live-meeting", "pdf-library"]),
                ("Book", vec!["live-meeting"]),
                ("Store", vec![]),
            ],
        ),
        st(
            "fitness",
            "Fitness",
            "Health",
            "Workout videos on a pass, with a launch countdown.",
            "forest",
            vec![
                (
                    "Home",
                    vec!["hero-countdown", "video-trio", "pricing-tiers"],
                ),
                ("Programs", vec!["video-playlist"]),
                ("Store", vec![]),
            ],
        ),
        st(
            "stock",
            "Stock media",
            "Media",
            "Packs and protected previews in grids.",
            "mono",
            vec![
                (
                    "Home",
                    vec!["hero-announcement", "gallery-grid", "card-featured-row"],
                ),
                ("Packs", vec!["gallery-protected", "pricing-compare"]),
                ("Store", vec![]),
            ],
        ),
        st(
            "publisher",
            "Publisher / e-books",
            "Publishing",
            "Readers, previews and a document library.",
            "warm",
            vec![
                (
                    "Home",
                    vec!["hero-classic", "pdf-preview-buy", "pdf-library"],
                ),
                ("Library", vec!["pdf-reader"]),
                ("Store", vec![]),
            ],
        ),
        st(
            "community",
            "Faith / community",
            "Community",
            "Sermons, sessions and a members pass.",
            "plum",
            vec![
                ("Home", vec!["video-hero", "live-schedule", "pricing-pass"]),
                ("Sessions", vec!["video-playlist"]),
                ("Store", vec![]),
            ],
        ),
        st(
            "events",
            "Event / live stream",
            "Events",
            "Ticketed live events with countdowns.",
            "night",
            vec![
                ("Home", vec!["live-event", "live-schedule"]),
                ("Tickets", vec!["pricing-compare"]),
                ("Store", vec![]),
            ],
        ),
        st(
            "agency",
            "Agency",
            "Agency",
            "Case-study videos, testimonials and a call booking.",
            "default",
            vec![
                (
                    "Home",
                    vec!["hero-image", "video-testimonial", "live-meeting"],
                ),
                ("Work", vec!["gallery-hero-strip", "video-trio"]),
                ("Store", vec![]),
            ],
        ),
        st(
            "generic",
            "Generic store",
            "General",
            "A clean store front for any mix of media.",
            "default",
            vec![
                (
                    "Home",
                    vec!["hero-classic", "card-featured-row", "pricing-pass"],
                ),
                ("Store", vec![]),
            ],
        ),
    ]
}

pub fn site_template(slug: &str) -> Option<SiteTemplate> {
    site_templates().into_iter().find(|t| t.slug == slug)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::render::{render, ProductInfo, RenderContext};

    #[test]
    fn thirty_five_unique_widget_templates_all_render() {
        let all = widget_templates();
        assert_eq!(all.len(), 35);
        let mut slugs: Vec<&str> = all.iter().map(|t| t.slug.as_str()).collect();
        slugs.sort();
        slugs.dedup();
        assert_eq!(slugs.len(), 35, "slugs are unique");
        let mut htmls = std::collections::HashSet::new();
        for cat in CATEGORIES {
            assert!(
                all.iter().any(|t| t.category == cat.0),
                "category {} has templates",
                cat.0
            );
        }
        let media = |_: &str| None;
        let product = |s: &str| {
            (!s.is_empty()).then(|| ProductInfo {
                slug: s.into(),
                title: "P".into(),
                description: String::new(),
                price: "USD 1.00".into(),
                thumb: None,
                kind: "Video".into(),
            })
        };
        for t in &all {
            let json = serde_json::to_string(&t.definition).unwrap();
            let def = Definition::parse(&json).expect(&t.slug);
            let vars = builtin_schemes()
                .into_iter()
                .find(|s| s.slug == t.scheme)
                .expect("scheme exists")
                .vars;
            let out = render(
                &def,
                &RenderContext {
                    uuid: "t",
                    base: "/mms",
                    site: "s",
                    theme: "auto",
                    scheme_vars: &vars,
                    custom_css: "",
                    media_url: &media,
                    product: &product,
                },
            );
            assert!(out.html.contains("mms-widget"));
            assert!(
                htmls.insert(out.html.clone()),
                "template {} renders identically to another",
                t.slug
            );
        }
    }

    #[test]
    fn twelve_site_templates_reference_real_widget_templates() {
        let sites = site_templates();
        assert_eq!(sites.len(), 12);
        for s in &sites {
            assert!(
                builtin_schemes().iter().any(|c| c.slug == s.scheme),
                "{} scheme",
                s.slug
            );
            for (_, widgets) in &s.pages {
                for w in widgets {
                    assert!(
                        widget_template(w).is_some(),
                        "{} references missing widget template {}",
                        s.slug,
                        w
                    );
                }
            }
        }
    }

    #[test]
    fn contrast_and_dark_variant() {
        assert!(contrast_ratio("#ffffff", "#000000").unwrap() > 20.0);
        assert!(contrast_ratio("#1f3a5f", "#ffffff").unwrap() > 7.0);
        assert!(contrast_ratio("#777777", "#888888").unwrap() < 1.5);
        let dark = auto_dark(&builtin_schemes()[0].vars);
        assert_eq!(dark.iter().find(|(k, _)| k == "bg").unwrap().1, "#0f1318");
        assert_ne!(
            dark.iter().find(|(k, _)| k == "accent").unwrap().1,
            "#1f3a5f",
            "accent is lightened"
        );
    }
}
