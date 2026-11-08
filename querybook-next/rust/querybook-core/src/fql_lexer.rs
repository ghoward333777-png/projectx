//! Port of `querybook/core/fql/lexer.py`. Positions are character offsets,
//! matching Python string indices, so error positions agree across engines.

#[derive(Debug, Clone, PartialEq)]
pub enum Tok {
    Int(i64),
    Float(f64),
    Str(String),
    Ident(String),
    Op(&'static str),
    Eof,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Token {
    pub tok: Tok,
    pub pos: usize,
    /// A newline precedes this token (same rule as Python's `Token.nl`).
    pub nl: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct FqlError {
    pub code: &'static str,
    pub message: String,
    pub pos: usize,
}

const SYMBOLS: [&str; 26] = ["=>", "==", "!=", "<=", ">=", "&&", "||", "<", ">", "!", "+", "-", "*", "/", "%",
                             ".", ",", "(", ")", "[", "]", "{", "}", ":", ";", "="];

fn err(message: impl Into<String>, pos: usize) -> FqlError {
    FqlError { code: "syntax_error", message: message.into(), pos }
}

pub fn tokenize(src: &str) -> Result<Vec<Token>, FqlError> {
    let s: Vec<char> = src.chars().collect();
    let n = s.len();
    let starts_with = |i: usize, lit: &str| -> bool {
        let lit: Vec<char> = lit.chars().collect();
        i + lit.len() <= n && s[i..i + lit.len()] == lit[..]
    };
    let mut toks: Vec<Token> = Vec::new();
    let mut nl = false;
    let push = |toks: &mut Vec<Token>, tok: Tok, pos: usize, nl: &mut bool| {
        toks.push(Token { tok, pos, nl: *nl });
        *nl = false;
    };
    let mut i = 0;
    while i < n {
        let ch = s[i];
        if ch.is_whitespace() {
            nl = nl || ch == '\n';
            i += 1;
            continue;
        }
        if starts_with(i, "//") {
            while i < n && s[i] != '\n' {
                i += 1;
            }
            continue;
        }
        if ch.is_ascii_digit() {
            let start = i;
            while i < n && (s[i].is_ascii_digit() || s[i] == '_') {
                i += 1;
            }
            let mut is_float = false;
            if i + 1 < n && s[i] == '.' && s[i + 1].is_ascii_digit() {
                is_float = true;
                i += 1;
                while i < n && s[i].is_ascii_digit() {
                    i += 1;
                }
            }
            if i < n && (s[i] == 'e' || s[i] == 'E') {
                let mut j = i + 1;
                if j < n && (s[j] == '+' || s[j] == '-') {
                    j += 1;
                }
                if j < n && s[j].is_ascii_digit() {
                    is_float = true;
                    i = j;
                    while i < n && s[i].is_ascii_digit() {
                        i += 1;
                    }
                }
            }
            let text: String = s[start..i].iter().filter(|c| **c != '_').collect();
            let tok = if is_float {
                Tok::Float(text.parse().map_err(|_| err("Bad number", start))?)
            } else {
                Tok::Int(text.parse().map_err(|_| err("Bad number", start))?)
            };
            push(&mut toks, tok, start, &mut nl);
            continue;
        }
        if ch == '"' || ch == '\'' {
            let (quote, start) = (ch, i);
            i += 1;
            let mut buf = String::new();
            loop {
                if i >= n {
                    return Err(err("Unterminated string", start));
                }
                let c = s[i];
                if c == quote {
                    i += 1;
                    break;
                }
                if c == '\\' {
                    if i + 1 >= n {
                        return Err(err("Unterminated escape", i));
                    }
                    let e = s[i + 1];
                    if e == 'u' {
                        let hex: String = s.get(i + 2..i + 6).map(|h| h.iter().collect()).unwrap_or_default();
                        let c = u32::from_str_radix(&hex, 16).ok().and_then(char::from_u32).ok_or_else(|| err("Bad \\u escape", i))?;
                        buf.push(c);
                        i += 6;
                        continue;
                    }
                    buf.push(match e {
                        'n' => '\n', 't' => '\t', 'r' => '\r', 'b' => '\u{8}', 'f' => '\u{c}',
                        '/' => '/', '\\' => '\\', '"' => '"', '\'' => '\'',
                        other => return Err(err(format!("Unknown escape \\{other}"), i)),
                    });
                    i += 2;
                    continue;
                }
                buf.push(c);
                i += 1;
            }
            push(&mut toks, Tok::Str(buf), start, &mut nl);
            continue;
        }
        if ch.is_alphabetic() || ch == '_' {
            let start = i;
            while i < n && (s[i].is_alphanumeric() || s[i] == '_') {
                i += 1;
            }
            push(&mut toks, Tok::Ident(s[start..i].iter().collect()), start, &mut nl);
            continue;
        }
        match SYMBOLS.iter().find(|sym| starts_with(i, sym)) {
            Some(sym) => {
                push(&mut toks, Tok::Op(sym), i, &mut nl);
                i += sym.chars().count();
            }
            None => return Err(err(format!("Unexpected character {ch:?}"), i)),
        }
    }
    push(&mut toks, Tok::Eof, n, &mut nl);
    Ok(toks)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lexes_a_query_like_python() {
        let toks = tokenize(r#"History.where(.start_year <= 1850 && .era != "Modern").take(5) // c"#).unwrap();
        let kinds: Vec<Tok> = toks.iter().map(|t| t.tok.clone()).collect();
        assert_eq!(kinds[0], Tok::Ident("History".into()));
        assert_eq!(kinds[1], Tok::Op("."));
        assert!(kinds.contains(&Tok::Op("<=")));
        assert!(kinds.contains(&Tok::Int(1850)));
        assert!(kinds.contains(&Tok::Str("Modern".into())));
        assert_eq!(kinds.last(), Some(&Tok::Eof));
        assert_eq!(toks.iter().find(|t| t.tok == Tok::Op("&&")).unwrap().pos, 34);
    }

    #[test]
    fn errors_carry_positions() {
        assert_eq!(tokenize("\"open").unwrap_err().pos, 0);
        assert_eq!(tokenize("a # b").unwrap_err().pos, 2);
        assert_eq!(tokenize("1_000 2.5e3").unwrap()[1].tok, Tok::Float(2500.0));
        let t = tokenize("let k = 10\n[1]").unwrap();
        assert!(t[4].nl && !t[3].nl);
    }
}
