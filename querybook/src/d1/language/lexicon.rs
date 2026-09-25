//! Closed-class vocabulary, irregular verb forms and verb classes: the fixed
//! linguistic knowledge the pipeline starts from. Deterministic data only.

pub const DETERMINERS: &[&str] = &[
    "a", "an", "the", "this", "that", "these", "those", "my", "your", "his", "her", "its", "our", "their", "some", "any", "no",
    "every", "each", "either", "neither", "another", "such", "what", "which", "whose", "all", "both", "much", "many", "few",
    "several", "enough",
];
pub const PRONOUNS: &[&str] = &[
    "i", "me", "you", "he", "him", "she", "her", "it", "we", "us", "they", "them", "myself", "yourself", "himself", "herself",
    "itself", "ourselves", "themselves", "who", "whom", "someone", "somebody", "anyone", "anybody", "everyone", "everybody",
    "nobody", "nothing", "something", "anything", "everything", "one", "mine", "yours", "hers", "ours", "theirs",
];
pub const PREPOSITIONS: &[&str] = &[
    "of", "in", "on", "at", "by", "for", "with", "about", "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "to", "from", "up", "down", "over", "under", "again", "near", "towards", "toward", "upon", "within",
    "without", "among", "across", "behind", "beyond", "beside", "besides", "around", "along", "off", "onto", "via", "per",
    "throughout", "till", "until", "since", "like", "unlike", "despite", "inside", "outside", "beneath", "amid",
];
pub const COORD: &[&str] = &["and", "but", "or", "nor", "yet", "so"];
pub const SUBORD: &[&str] = &[
    "because", "although", "though", "while", "whereas", "when", "whenever", "where", "wherever", "if", "unless", "since",
    "until", "till", "after", "before", "once", "as", "that", "whether", "lest",
];
pub const RELATIVE: &[&str] = &["who", "whom", "whose", "which", "that"];
pub const AUX: &[&str] = &[
    "be", "am", "is", "are", "was", "were", "been", "being", "have", "has", "had", "having", "do", "does", "did", "will",
    "would", "shall", "should", "may", "might", "must", "can", "could",
];
pub const COPULA: &[&str] = &["be", "am", "is", "are", "was", "were", "been", "being", "become", "became", "seem", "seemed", "remain", "remained"];
pub const NEGATION: &[&str] = &["not", "never", "n't", "no"];
pub const ADVERBS: &[&str] = &[
    "very", "so", "too", "quite", "rather", "almost", "also", "only", "just", "even", "still", "already", "always", "never",
    "often", "sometimes", "soon", "then", "now", "here", "there", "thus", "therefore", "however", "indeed", "perhaps", "again",
    "once", "twice", "ever", "yet", "far", "much", "more", "most", "less", "least", "well", "instead", "together", "away",
    "back", "home", "abroad", "afterwards", "presently", "immediately", "entirely", "certainly", "really", "hardly", "scarcely",
];
pub const MONTHS: &[&str] = &[
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
];
pub const KIN: &[&str] = &[
    "father", "mother", "sister", "brother", "wife", "husband", "daughter", "son", "aunt", "uncle", "cousin", "niece",
    "nephew", "grandfather", "grandmother", "grandson", "granddaughter", "parent", "child", "heir", "widow",
];
pub const ORG_WORDS: &[&str] = &[
    "company", "corporation", "university", "college", "society", "church", "army", "navy", "regiment", "parliament", "council",
    "institute", "academy", "bank", "museum", "school", "government", "party", "court", "league", "union", "ministry", "empire",
];

/// Irregular verbs: (base, past, past participle).
pub const IRREGULAR: &[(&str, &str, &str)] = &[
    ("be", "was", "been"), ("have", "had", "had"), ("do", "did", "done"), ("go", "went", "gone"), ("come", "came", "come"),
    ("see", "saw", "seen"), ("take", "took", "taken"), ("give", "gave", "given"), ("make", "made", "made"),
    ("find", "found", "found"), ("leave", "left", "left"), ("tell", "told", "told"), ("think", "thought", "thought"),
    ("feel", "felt", "felt"), ("know", "knew", "known"), ("bring", "brought", "brought"), ("send", "sent", "sent"),
    ("begin", "began", "begun"), ("write", "wrote", "written"), ("run", "ran", "run"), ("sit", "sat", "sat"),
    ("stand", "stood", "stood"), ("speak", "spoke", "spoken"), ("hear", "heard", "heard"), ("meet", "met", "met"),
    ("keep", "kept", "kept"), ("lose", "lost", "lost"), ("hold", "held", "held"), ("lead", "led", "led"),
    ("fall", "fell", "fallen"), ("rise", "rose", "risen"), ("become", "became", "become"), ("buy", "bought", "bought"),
    ("catch", "caught", "caught"), ("fight", "fought", "fought"), ("seek", "sought", "sought"), ("teach", "taught", "taught"),
    ("win", "won", "won"), ("draw", "drew", "drawn"), ("throw", "threw", "thrown"), ("grow", "grew", "grown"),
    ("choose", "chose", "chosen"), ("break", "broke", "broken"), ("forget", "forgot", "forgotten"), ("forgive", "forgave", "forgiven"),
    ("hide", "hid", "hidden"), ("shake", "shook", "shaken"), ("strike", "struck", "struck"), ("swear", "swore", "sworn"),
    ("tear", "tore", "torn"), ("wear", "wore", "worn"), ("wake", "woke", "woken"), ("ride", "rode", "ridden"),
    ("drive", "drove", "driven"), ("fly", "flew", "flown"), ("sing", "sang", "sung"), ("spend", "spent", "spent"),
    ("get", "got", "got"), ("put", "put", "put"), ("read", "read", "read"), ("let", "let", "let"), ("set", "set", "set"),
    ("shut", "shut", "shut"), ("cut", "cut", "cut"), ("hurt", "hurt", "hurt"), ("pay", "paid", "paid"), ("lay", "laid", "laid"),
    ("say", "said", "said"), ("mean", "meant", "meant"), ("sleep", "slept", "slept"), ("weep", "wept", "wept"),
    ("understand", "understood", "understood"), ("build", "built", "built"), ("eat", "ate", "eaten"), ("drink", "drank", "drunk"),
    ("sell", "sold", "sold"), ("lie", "lay", "lain"), ("bear", "bore", "born"), ("bind", "bound", "bound"),
    ("light", "lit", "lit"), ("shoot", "shot", "shot"), ("show", "showed", "shown"), ("prove", "proved", "proven"),
    ("steal", "stole", "stolen"), ("freeze", "froze", "frozen"), ("dig", "dug", "dug"), ("feed", "fed", "fed"),
    ("flee", "fled", "fled"), ("hang", "hung", "hung"), ("slide", "slid", "slid"), ("spin", "spun", "spun"),
    ("stick", "stuck", "stuck"), ("swim", "swam", "swum"), ("undertake", "undertook", "undertaken"), ("withdraw", "withdrew", "withdrawn"),
];

/// Frequent regular verbs (base forms) that suffix rules alone would miss.
pub const COMMON_VERBS: &[&str] = &[
    "ask", "answer", "arrive", "call", "cry", "decide", "describe", "discover", "dance", "die", "enter", "explain", "follow",
    "happen", "help", "hope", "invite", "join", "laugh", "like", "live", "look", "love", "marry", "move", "need", "offer",
    "open", "own", "pass", "play", "please", "prefer", "promise", "receive", "refuse", "remain", "remember", "reply", "return",
    "seem", "smile", "start", "stay", "stop", "suppose", "talk", "travel", "try", "turn", "use", "visit", "wait", "walk",
    "want", "wish", "wonder", "work", "accept", "admire", "agree", "allow", "appear", "attend", "believe", "belong", "change",
    "consider", "contain", "continue", "create", "declare", "deny", "depend", "design", "develop", "dislike", "expect", "fail",
    "fear", "form", "hate", "imagine", "include", "inherit", "introduce", "invent", "involve", "learn", "measure", "mention",
    "notice", "observe", "occur", "order", "pay", "plan", "prepare", "produce", "propose", "provide", "publish", "reach",
    "realize", "recommend", "reject", "repair", "represent", "require", "resolve", "rule", "settle", "sign", "study", "suggest",
    "support", "surprise", "trust", "wander", "watch",
];

/// Verb classes used for predicate classification (Stage 3).
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize)]
pub enum VerbClass {
    Copula,
    Communication,
    Motion,
    Perception,
    Cognition,
    Emotion,
    Possession,
    Social,
    Creation,
    Change,
    Action,
}

pub fn verb_class(lemma: &str) -> VerbClass {
    use VerbClass::*;
    match lemma {
        "be" | "become" | "seem" | "remain" | "appear" => Copula,
        "say" | "tell" | "ask" | "answer" | "reply" | "cry" | "speak" | "talk" | "declare" | "explain" | "write" | "mention"
        | "describe" | "call" | "promise" | "suggest" | "propose" | "announce" | "exclaim" | "whisper" => Communication,
        "go" | "come" | "arrive" | "leave" | "return" | "travel" | "walk" | "run" | "enter" | "visit" | "move" | "fly" | "ride"
        | "drive" | "wander" | "flee" | "reach" | "follow" | "cross" | "flow" => Motion,
        "see" | "hear" | "watch" | "notice" | "observe" | "look" | "feel_sense" => Perception,
        "think" | "believe" | "know" | "suppose" | "understand" | "realize" | "remember" | "forget" | "consider" | "expect"
        | "imagine" | "wonder" | "learn" | "decide" | "doubt" => Cognition,
        "love" | "hate" | "like" | "dislike" | "admire" | "fear" | "hope" | "wish" | "prefer" | "feel" | "trust" => Emotion,
        "have" | "own" | "possess" | "inherit" | "receive" | "buy" | "sell" | "keep" | "lose" | "give" | "get" | "win" => Possession,
        "marry" | "meet" | "join" | "invite" | "introduce" | "accept" | "refuse" | "reject" | "help" | "serve" | "attend"
        | "dance" | "befriend" => Social,
        "make" | "build" | "create" | "write_work" | "design" | "invent" | "discover" | "found" | "produce" | "compose"
        | "publish" | "develop" => Creation,
        "change" | "grow" | "rise" | "fall" | "begin" | "start" | "end" | "stop" | "die" | "become_change" => Change,
        _ => Action,
    }
}

pub fn is_in(list: &[&str], w: &str) -> bool {
    list.contains(&w)
}

/// Lemma of a verb form: irregular table first, then regular morphology.
pub fn verb_lemma(w: &str) -> String {
    let w = w.to_lowercase();
    for (base, past, part) in IRREGULAR {
        if w == *base || w == *past || w == *part {
            return base.to_string();
        }
    }
    match w.as_str() {
        "is" | "am" | "are" | "was" | "were" | "been" | "being" => return "be".into(),
        "has" | "had" | "having" => return "have".into(),
        "does" | "did" | "done" => return "do".into(),
        _ => {}
    }
    let strip = |s: &str, suf: &str| s.strip_suffix(suf).map(|x| x.to_string());
    if let Some(b) = strip(&w, "ied") {
        return format!("{b}y");
    }
    if let Some(b) = strip(&w, "ies") {
        return format!("{b}y");
    }
    for suf in ["ing", "ed"] {
        if let Some(b) = strip(&w, suf) {
            if b.len() < 2 {
                break;
            }
            // doubled consonant: "stopped" -> "stop"
            let bytes = b.as_bytes();
            if bytes.len() >= 3 && bytes[bytes.len() - 1] == bytes[bytes.len() - 2] && !b"aeiouls".contains(&bytes[bytes.len() - 1]) {
                return b[..b.len() - 1].to_string();
            }
            let with_e = format!("{b}e");
            if COMMON_VERBS.contains(&with_e.as_str()) || b.ends_with(['v', 'z', 'c']) || b.ends_with("dg") || b.ends_with("ur") {
                return with_e;
            }
            if COMMON_VERBS.contains(&b.as_str()) {
                return b;
            }
            // e.g. "arrived" -> "arrive", "refused" -> "refuse", "walked" -> "walk"
            let last = b.chars().last().unwrap_or('x');
            let pre = b.chars().rev().nth(1).unwrap_or('x');
            if !"aeiou".contains(last) && "aeiou".contains(pre) && b.len() <= 5 && suf == "ed" && !b.ends_with('w') && !b.ends_with('x') {
                return with_e;
            }
            return b;
        }
    }
    if let Some(b) = strip(&w, "es") {
        if b.ends_with("sh") || b.ends_with("ch") || b.ends_with('s') || b.ends_with('x') || b.ends_with('z') || b.ends_with('o') {
            return b;
        }
    }
    if let Some(b) = strip(&w, "s") {
        if !b.ends_with('s') {
            return b;
        }
    }
    w
}

pub fn is_known_verb_form(w: &str) -> bool {
    let l = w.to_lowercase();
    IRREGULAR.iter().any(|(b, p, pp)| l == *b || l == *p || l == *pp)
        || COMMON_VERBS.iter().any(|v| {
            l == *v || l == format!("{v}s") || l == format!("{v}ed") || l == format!("{v}d") || l == format!("{}ied", v.trim_end_matches('y'))
                || l == format!("{v}ing") || l == format!("{}ing", v.trim_end_matches('e'))
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn lemmas() {
        for (f, l) in [("refused", "refuse"), ("married", "marry"), ("arrived", "arrive"), ("walked", "walk"), ("stopped", "stop"),
            ("went", "go"), ("was", "be"), ("danced", "dance"), ("visits", "visit"), ("discovered", "discover"), ("loved", "love")]
        {
            assert_eq!(verb_lemma(f), l, "{f}");
        }
        assert_eq!(verb_class("marry"), VerbClass::Social);
        assert_eq!(verb_class("say"), VerbClass::Communication);
    }
}
