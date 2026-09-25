//! `qb` — QueryBook command line: ingest a library, import UFCS facts,
//! query from the terminal, verify the ledger, and serve the reader app.

use clap::{Parser, Subcommand};
use querybook::app::QueryBook;
use querybook::config::Config;
use querybook::d0::Trace;
use querybook::d1::pipeline::{IngestOptions, ingest_file};
use querybook::d4::{Request, answer};
use querybook::d8::{self, ScopeRequest, User};
use std::path::{Path, PathBuf};

#[derive(Parser)]
#[command(name = "qb", version, about = "QueryBook prototype: grounded, cited answers from a book's own Fact Units")]
struct Cli {
    /// Config file (TOML). Defaults to built-in settings with ./data as the data directory.
    #[arg(long, short, global = true, env = "QB_CONFIG")]
    config: Option<PathBuf>,
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Ingest books (EPUB, DOCX, HTML, TXT, MD). Directories are walked.
    Ingest {
        paths: Vec<PathBuf>,
        /// Rights declaration: public-domain | author-owned | licensed | publisher-licensed
        #[arg(long, default_value = "")]
        rights: String,
        #[arg(long, default_value = "")]
        rights_note: String,
        /// Comma-separated registered engine ids, e.g. language,claude,local
        #[arg(long, default_value = "language")]
        engines: String,
        /// Override the work id (single file only)
        #[arg(long)]
        id: Option<String>,
        #[arg(long, default_value = "")]
        genre: String,
        /// Supersede an already-ingested work with the same id
        #[arg(long)]
        replace: bool,
        /// CSV manifest: path,rights,rights_note,genre,id (header row optional)
        #[arg(long)]
        manifest: Option<PathBuf>,
        /// Keep going when one book fails
        #[arg(long, default_value_t = true)]
        keep_going: bool,
    },
    /// Estimate extraction requests, tokens and cost before spending anything.
    Estimate {
        paths: Vec<PathBuf>,
        #[arg(long, default_value = "claude")]
        engine: String,
        #[arg(long)]
        manifest: Option<PathBuf>,
    },
    /// Ask a question (or run a mode) from the terminal.
    Ask {
        work: String,
        #[arg(default_value = "")]
        query: String,
        /// ask | summary | recap | who | timeline | explore | flashcards | quiz
        #[arg(long, default_value = "ask")]
        mode: String,
        /// Reading position (spoiler bound). Default: end of book.
        #[arg(long)]
        at: Option<u64>,
        #[arg(long)]
        chapter: Option<u32>,
        #[arg(long)]
        focus: Option<String>,
        /// Include imported UFCS corpora
        #[arg(long)]
        world: bool,
        #[arg(long)]
        json: bool,
    },
    /// Import UFCS Fact Envelopes from an API or NDJSON file through a field mapping.
    ImportUfcs {
        #[arg(long)]
        mapping: PathBuf,
        /// NDJSON / JSON file instead of the API in the mapping
        #[arg(long)]
        file: Option<PathBuf>,
        /// Stop after this many records (0 = no limit)
        #[arg(long, default_value_t = 0)]
        limit: u64,
        /// Validate and report without admitting anything
        #[arg(long)]
        dry_run: bool,
    },
    /// Show the language pipeline (stages 1-5) on a book: tokens, POS, clauses, trees, dependencies, entities, facts.
    Analyze {
        file: PathBuf,
        /// Analyse this sentence instead of the book's passages (the book still supplies its named entities)
        #[arg(long)]
        sentence: Option<String>,
        /// First passage position to analyse
        #[arg(long, default_value_t = 0)]
        from: u64,
        /// Number of sentences to show
        #[arg(long, default_value_t = 3)]
        limit: usize,
        #[arg(long)]
        json: bool,
    },
    /// Harvest facts from Wikidata with a SPARQL query pack (resumable), optionally importing them.
    HarvestWikidata {
        #[arg(long, default_value = "config/harvest/wikidata-basics.toml")]
        pack: PathBuf,
        #[arg(long, default_value = "data/harvest/wikidata")]
        out: PathBuf,
        /// Only these domains or query ids (comma-separated), e.g. geography,science
        #[arg(long, default_value = "")]
        only: String,
        /// Re-run queries that already finished
        #[arg(long)]
        force: bool,
        /// Import the harvested files afterwards with this mapping
        #[arg(long)]
        import: Option<PathBuf>,
    },
    /// Generate synthetic UFCS-shaped records to measure ingest and query at scale.
    BenchSynthetic {
        #[arg(long, default_value_t = 1_000_000)]
        facts: u64,
        #[arg(long, default_value_t = 50_000)]
        batch: usize,
    },
    /// Export a work's records as a QBF frame stream (compact, offline-capable).
    ExportQbf { work: String, out: PathBuf },
    /// Verify the whole provenance ledger (hash links, keyed checksums, signatures).
    Verify,
    /// Store and library statistics.
    Stats,
    /// Create or update a user.
    User {
        username: String,
        #[arg(long)]
        password: String,
        /// comma-separated: reader, author, instructor, researcher, operator
        #[arg(long, default_value = "reader")]
        roles: String,
        #[arg(long, default_value = "default")]
        tenant: String,
    },
    /// Entitle a user to a work.
    Grant { username: String, work: String },
    /// Run the web app (Kindle-style reader + QueryBook panel).
    Serve {
        #[arg(long)]
        bind: Option<String>,
    },
}

fn book_files(paths: &[PathBuf]) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for p in paths {
        if p.is_dir() {
            let mut entries: Vec<PathBuf> = walk(p);
            entries.sort();
            out.extend(entries);
        } else {
            out.push(p.clone());
        }
    }
    out
}

fn walk(dir: &Path) -> Vec<PathBuf> {
    let mut v = Vec::new();
    if let Ok(rd) = std::fs::read_dir(dir) {
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                v.extend(walk(&p));
            } else if matches!(
                p.extension().and_then(|e| e.to_str()).map(|e| e.to_lowercase()).as_deref(),
                Some("epub" | "docx" | "html" | "htm" | "xhtml" | "txt" | "md" | "pdf")
            ) {
                v.push(p);
            }
        }
    }
    v
}

struct ManifestRow {
    path: PathBuf,
    rights: String,
    note: String,
    genre: String,
    id: Option<String>,
}

fn read_manifest(p: &Path) -> anyhow::Result<Vec<ManifestRow>> {
    let base = p.parent().unwrap_or(Path::new("."));
    let text = std::fs::read_to_string(p)?;
    let mut rows = Vec::new();
    for (i, line) in text.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') || (i == 0 && line.to_lowercase().starts_with("path")) {
            continue;
        }
        let cols = split_csv(line);
        let path = PathBuf::from(cols.first().cloned().unwrap_or_default());
        rows.push(ManifestRow {
            path: if path.is_absolute() { path } else { base.join(path) },
            rights: cols.get(1).cloned().unwrap_or_default(),
            note: cols.get(2).cloned().unwrap_or_default(),
            genre: cols.get(3).cloned().unwrap_or_default(),
            id: cols.get(4).cloned().filter(|s| !s.is_empty()),
        });
    }
    Ok(rows)
}

fn split_csv(line: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut quoted = false;
    let mut chars = line.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '"' if quoted && chars.peek() == Some(&'"') => {
                cur.push('"');
                chars.next();
            }
            '"' => quoted = !quoted,
            ',' if !quoted => out.push(std::mem::take(&mut cur).trim().to_string()),
            _ => cur.push(c),
        }
    }
    out.push(cur.trim().to_string());
    out
}

fn cli_user() -> User {
    User { id: 0, username: "cli".into(), roles: vec!["operator".into()], tenant: "default".into() }
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    let cfg = Config::load(cli.config.as_deref())?;
    match cli.cmd {
        Cmd::Ingest { paths, rights, rights_note, engines, id, genre, replace, manifest, keep_going } => {
            let qb = QueryBook::open(cfg)?;
            let engines: Vec<String> = engines.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
            let mut jobs: Vec<ManifestRow> = match &manifest {
                Some(m) => read_manifest(m)?,
                None => book_files(&paths)
                    .into_iter()
                    .map(|p| ManifestRow {
                        path: p,
                        rights: rights.clone(),
                        note: rights_note.clone(),
                        genre: genre.clone(),
                        id: None,
                    })
                    .collect(),
            };
            if jobs.len() == 1 && id.is_some() {
                jobs[0].id = id.clone();
            }
            anyhow::ensure!(!jobs.is_empty(), "no book files given");
            let (mut ok, mut failed) = (0, 0);
            let total = jobs.len();
            for (i, j) in jobs.iter().enumerate() {
                eprintln!("[{}/{}] {}", i + 1, total, j.path.display());
                let opts = IngestOptions {
                    id: j.id.clone(),
                    rights: if j.rights.is_empty() { rights.clone() } else { j.rights.clone() },
                    rights_note: j.note.clone(),
                    engines: engines.clone(),
                    replace,
                    genre: j.genre.clone(),
                    actor: qb.cfg.operator.name.clone(),
                };
                match ingest_file(&qb, &j.path, &opts, &|m: &str| eprintln!("    {m}")) {
                    Ok(r) => {
                        ok += 1;
                        println!("{}", serde_json::to_string(&r)?);
                    }
                    Err(e) => {
                        failed += 1;
                        eprintln!("    FAILED: {e:#}");
                        if !keep_going {
                            return Err(e);
                        }
                    }
                }
            }
            eprintln!("done: {ok} ingested, {failed} failed");
        }
        Cmd::Estimate { paths, engine, manifest } => {
            let qb = QueryBook::open(cfg)?;
            let profile = qb.cfg.engine(&engine).ok_or_else(|| anyhow::anyhow!("engine {engine} not in config"))?.clone();
            let files: Vec<PathBuf> = match manifest {
                Some(m) => read_manifest(&m)?.into_iter().map(|r| r.path).collect(),
                None => book_files(&paths),
            };
            let catalog = qb.catalog.read().unwrap().clone();
            let (mut reqs, mut tin, mut tout, mut words) = (0usize, 0u64, 0u64, 0usize);
            for f in &files {
                match querybook::d1::parse::parse_file(f, None) {
                    Ok(b) => {
                        let (r, i, o) = querybook::d1::engines::llm::estimate(&b, &catalog, &profile);
                        println!("{:>6} words  {:>4} requests  {}", b.words(), r, b.title);
                        reqs += r;
                        tin += i;
                        tout += o;
                        words += b.words();
                    }
                    Err(e) => println!("  skip {}: {e}", f.display()),
                }
            }
            let cost = tin as f64 / 1e6 * profile.input_price + tout as f64 / 1e6 * profile.output_price;
            println!(
                "\n{} books, {} words -> {} requests, ~{:.1}M input tokens, ~{:.1}M output tokens, ~${:.2} at ${}/${} per MTok ({})",
                files.len(),
                words,
                reqs,
                tin as f64 / 1e6,
                tout as f64 / 1e6,
                cost,
                profile.input_price,
                profile.output_price,
                profile.id
            );
            println!("Estimates are approximate (±30%); `rules` costs nothing.");
        }
        Cmd::Ask { work, query, mode, at, chapter, focus, world, json } => {
            let qb = QueryBook::open(cfg)?;
            let user = cli_user();
            let mut trace = Trace::default();
            // "world" asks the imported knowledge (UFCS feeds, harvests) with no book
            let scope = if work == "world" {
                let feeds = d8::world_feeds(&qb)?;
                anyhow::ensure!(!feeds.is_empty(), "no imported knowledge yet (qb harvest-wikidata / qb import-ufcs)");
                d8::world_scope(&feeds)
            } else {
                d8::scope_for(
                    &qb,
                    &user,
                    &ScopeRequest { work: &work, include_world: world, at_pos: Some(at.unwrap_or(u64::MAX)) },
                    &mut trace,
                )?
            };
            let req = Request { mode, query, chapter, focus, device: "cli".into() };
            let a = answer(&qb, &scope, &req, trace)?;
            if json {
                println!("{}", serde_json::to_string_pretty(&a)?);
            } else {
                print_answer(&a);
            }
        }
        Cmd::ImportUfcs { mapping, file, limit, dry_run } => {
            let qb = QueryBook::open(cfg)?;
            let r = querybook::d1::ufcs::import(&qb, &mapping, file.as_deref(), limit, dry_run, &|m: &str| eprintln!("  {m}"))?;
            println!("{}", serde_json::to_string_pretty(&r)?);
        }
        Cmd::Analyze { file, sentence, from, limit, json } => {
            use querybook::d1::language::{analyze_sentence, construct::Discourse};
            let book = querybook::d1::parse::parse_file(&file, None)?;
            let ents = querybook::d3::entities::detect(&book);
            let empty = std::collections::BTreeMap::new();
            let mut todo: Vec<(u64, u32, String, Option<String>)> = Vec::new();
            match sentence {
                Some(s) => todo.push((0, 0, s, None)),
                None => {
                    for p in book.passages.iter().filter(|p| p.pos >= from && p.kind == "p") {
                        for s in querybook::d1::segment::sentences(&p.text) {
                            todo.push((p.pos, p.chapter, s, p.anchor.as_ref().map(|a| a.cfi())));
                        }
                        if todo.len() >= limit {
                            break;
                        }
                    }
                    todo.truncate(limit);
                }
            }
            let mut dis = Discourse::default();
            for (pos, ch, s, cfi) in todo {
                let (_, a) = analyze_sentence(&s, &ents, &book.id, "language", pos, ch, 0, &empty, &mut dis, None);
                if json {
                    println!("{}", serde_json::to_string_pretty(&a)?);
                    continue;
                }
                println!("\n━━ p{pos}{}  {}", cfi.map(|c| format!("  {c}")).unwrap_or_default(), a.text);
                println!("  tokens  {}", a.tokens.iter().map(|(t, p, _)| format!("{t}/{p}")).collect::<Vec<_>>().join(" "));
                for (k, t) in &a.clauses {
                    println!("  clause  [{k}] {t}");
                }
                for t in &a.trees {
                    println!("  tree    {t}");
                }
                println!(
                    "  deps    {}",
                    a.dependencies.iter().map(|(d, r, h)| format!("{r}({h}, {d})")).collect::<Vec<_>>().join(" ")
                );
                println!(
                    "  ents    {}",
                    a.mentions.iter().map(|(t, k, c)| format!("{t}:{k}={c}")).collect::<Vec<_>>().join("  ")
                );
                println!("  preds   {}", a.predicate.iter().map(|(l, c)| format!("{l}:{c}")).collect::<Vec<_>>().join("  "));
                for (ty, s, p, o) in &a.facts {
                    println!("  FU      <{ty}> {s} · {p} · {o}");
                }
            }
        }
        Cmd::HarvestWikidata { pack, out, only, force, import } => {
            let only: Vec<String> = only.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
            let r = querybook::d12::wikidata::harvest(&pack, &out, &only, force, &|m: &str| eprintln!("{m}"))?;
            let failed = r.queries.iter().filter(|q| q.status.starts_with("failed")).count();
            eprintln!("harvested {} facts from {} queries into {} ({failed} failed)", r.envelopes, r.queries.len(), r.out);
            if let Some(mapping) = import {
                let qb = QueryBook::open(cfg)?;
                let ir = querybook::d1::ufcs::import(&qb, &mapping, Some(&out), 0, false, &|m: &str| eprintln!("  {m}"))?;
                println!("{}", serde_json::to_string_pretty(&ir)?);
            }
        }
        Cmd::BenchSynthetic { facts, batch } => {
            let qb = QueryBook::open(cfg)?;
            querybook::d1::ufcs::bench_synthetic(&qb, facts, batch)?;
        }
        Cmd::ExportQbf { work, out } => {
            let qb = QueryBook::open(cfg)?;
            let n = querybook::d1::ufcs::export_qbf(&qb, &work, &out)?;
            println!("wrote {n} QBF frames to {}", out.display());
        }
        Cmd::Verify => {
            let qb = QueryBook::open(cfg)?;
            let v = qb.store.verify_ledger()?;
            println!("{}", serde_json::to_string_pretty(&v)?);
            if v.first_failure.is_some() {
                std::process::exit(2);
            }
        }
        Cmd::Stats => {
            let qb = QueryBook::open(cfg)?;
            let works = d8::all_works(&qb)?;
            println!(
                "records: {}  indexed: {}  store version: {}",
                qb.store.fact_count()?,
                qb.store.index.num_docs(),
                &qb.store.version()[..16.min(qb.store.version().len())]
            );
            for w in works {
                println!("  {:<44} {:>7} facts  {:>6} passages  {}  [{}]", w.id, w.facts, w.positions, w.rights, w.engines);
            }
        }
        Cmd::User { username, password, roles, tenant } => {
            let qb = QueryBook::open(cfg)?;
            let roles: Vec<&str> = roles.split(',').map(|s| s.trim()).collect();
            let id = d8::create_user(&qb, &username, &password, &roles, &tenant)?;
            println!("user {username} (id {id}) roles {:?}", roles);
        }
        Cmd::Grant { username, work } => {
            let qb = QueryBook::open(cfg)?;
            let id: i64 =
                qb.store.read(|c| Ok(c.query_row("SELECT id FROM users WHERE username=?1", [&username], |r| r.get(0))?))?;
            d8::grant(&qb, id, &work, "grant")?;
            println!("granted {work} to {username}");
        }
        Cmd::Serve { bind } => {
            let mut cfg = cfg;
            if let Some(b) = bind {
                cfg.server.bind = b;
            }
            let qb = QueryBook::open(cfg)?;
            tokio::runtime::Runtime::new()?.block_on(querybook::d9::serve(qb))?;
        }
    }
    Ok(())
}

fn print_answer(a: &querybook::d4::Answer) {
    println!("[{}] {} ({} ms, {})", a.status, a.mode, a.ms, a.served_from);
    if !a.message.is_empty() {
        println!("{}", a.message);
    }
    if let Some(c) = &a.clarify {
        println!("{}", c.question);
        for o in &c.options {
            println!("  - {} ({})", o.label, o.concept);
        }
    }
    let line =
        |l: &querybook::d4::query::Line| format!("{} {}", l.text, l.cites.iter().map(|c| format!("[{c}]")).collect::<String>());
    for l in &a.lines {
        println!("  {}", line(l));
    }
    for s in &a.sections {
        println!("  == {}", s.title);
        for l in &s.lines {
            println!("     {}", line(l));
        }
    }
    for c in &a.cards {
        println!("  Q: {}\n  A: {} [{}]", c.front, c.back, c.cite);
    }
    for q in &a.quiz {
        println!("  {}  {:?}  -> {}", q.prompt, q.options, q.answer);
    }
    for n in &a.neighbors {
        println!("  ~ {} ({})", n.label, n.strength);
    }
    for c in &a.citations {
        println!(
            "  [{}] p{} ch{} conf {:.2} trust {:.2} div {:.1} {} {} — “{}”",
            c.n,
            c.pos,
            c.chapter,
            c.confidence,
            c.trust,
            c.diversity,
            c.engine,
            if c.verified { "verified" } else { "UNVERIFIED" },
            querybook::util::clip(&c.quote, 110)
        );
    }
    if let Some(cv) = &a.convergence {
        println!(
            "  convergence: {} units, {} iterations, residual {:.1e}, retained {}, ‖W‖ {:.3}",
            cv.units, cv.iterations, cv.residual, cv.retained, cv.weight_norm
        );
    }
    println!("  regime: {}\n  context key: {}\n  output hash: {}", a.regime, &a.context_key[..16], &a.output_hash[..16]);
}
