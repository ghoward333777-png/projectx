//! vw/router.py
use crate::core::{has_any, has_phrase, lower, words};

const ROUTES: [&str; 8] = ["answer", "code", "text", "image", "video", "audio", "open", "chat"];
const MAKE: &[&str] = &["make", "build", "create", "code", "write", "generate", "program", "develop", "design", "produce", "compose",
    "draft", "give me", "i want", "i need", "can you make", "show me"];
const CODE_NOUNS: &[&str] = &["app", "application", "website", "web site", "web page", "webpage", "landing page", "game", "program",
    "script", "function", "calculator", "to do", "todo", "tracker", "dashboard", "tool", "cli", "api", "code", "html", "javascript",
    "python", "stopwatch", "timer", "converter", "quiz app", "notes app", "class", "component"];
const IMAGE_WORDS: &[&str] = &["image", "picture", "drawing", "draw", "paint", "painting", "illustration", "illustrate", "logo",
    "poster", "icon", "sketch", "artwork", "wallpaper", "photo", "landscape picture", "portrait"];
const VIDEO_WORDS: &[&str] = &["video", "animation", "animate", "movie", "film", "clip", "trailer", "slideshow", "storyboard"];
const AUDIO_WORDS: &[&str] = &["audio", "sound", "music", "song", "melody", "tune", "jingle", "speech", "narrate", "narration", "voice",
    "say", "read aloud", "podcast", "sound effect", "ringtone", "beat", "rain sounds", "ocean sounds"];
const TEXT_WORDS: &[&str] = &["story", "poem", "essay", "article", "blog", "email", "letter", "summary", "summarize", "summarise",
    "list", "description", "speech text", "report", "outline", "haiku", "limerick", "tweet", "post", "paragraph", "bio",
    "cover letter", "toast", "slogan", "tagline", "recipe"];
const OPEN_WORDS: &[&str] = &["open", "show", "go to", "switch to", "take me to", "launch"];
const SCREEN_WORDS: &[&str] = &["language lab", "stem", "history", "video studio", "control panel", "book writer", "book lab",
    "workspace", "feature registry", "registry", "harvest", "translate", "formulas", "timeline", "elements", "querybook"];
const GREETINGS: &[&str] = &["hi", "hello", "hey", "thanks", "thank you", "good morning", "good evening", "help", "who are you",
    "what can you do", "what are you"];

pub fn explicit(message: &str) -> &'static str {
    let t = message.trim_start_matches(|c: char| c.is_whitespace());
    if !t.starts_with('/') { return ""; }
    let name = lower(t[1..].split(' ').next().unwrap_or(""));
    ROUTES.iter().find(|r| **r == name).copied().unwrap_or("")
}

pub fn route(message: &str) -> &'static str {
    let e = explicit(message);
    if !e.is_empty() { return e; }
    let ws = words(message);
    if ws.is_empty() { return "chat"; }
    if has_any(&ws, OPEN_WORDS) && has_any(&ws, SCREEN_WORDS) && ws.len() <= 8 { return "open"; }
    let making = has_any(&ws, MAKE);
    if making && has_any(&ws, CODE_NOUNS) { return "code"; }
    if has_any(&ws, &["draw", "paint", "sketch", "illustrate"]) || (making && has_any(&ws, IMAGE_WORDS)) { return "image"; }
    if has_any(&ws, &["animate"]) || (making && has_any(&ws, VIDEO_WORDS)) { return "video"; }
    if has_any(&ws, &["narrate", "read aloud"]) || (has_any(&ws, &["say"]) && ws.len() <= 3) || (making && has_any(&ws, AUDIO_WORDS)) {
        return "audio";
    }
    if making && has_any(&ws, TEXT_WORDS) { return "text"; }
    if ws.len() <= 4 && has_any(&ws, GREETINGS) { return "chat"; }
    "answer"
}

pub fn screen_for(message: &str) -> &'static str {
    const TABLE: &[(&str, &str)] = &[("language lab", "lang-learn"), ("translate", "lang-translate"), ("video studio", "video-studio"),
        ("control panel", "ctl-overview"), ("book writer", "book-writer"), ("book lab", "book-lab"), ("feature registry", "vw-features"),
        ("registry", "vw-features"), ("workspace", "vw-workspace"), ("harvest", "ctl-bulk"), ("formulas", "stem-formulas"),
        ("elements", "stem-elements"), ("timeline", "hist-timeline"), ("history", "hist-search"), ("stem", "stem-ask"),
        ("querybook", "qb-shell")];
    let ws = words(message);
    TABLE.iter().find(|(p, _)| has_phrase(&ws, &words(p))).map(|(_, id)| *id).unwrap_or("")
}
