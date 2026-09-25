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
    /// Authorise this server to keep backups in your Google Drive (one time).
    DriveAuth,
    /// Encrypted snapshot of the whole store (facts, index, ledger keys), optionally uploaded to Google Drive.
    Backup {
        /// Local folder for backup files
        #[arg(long, default_value = "backups")]
        out: PathBuf,
        /// Upload to Google Drive (folder "QueryBook backups"); the local copy is removed after a verified upload
        #[arg(long)]
        drive: bool,
        /// Keep this many backups (in Drive with --drive, locally otherwise)
        #[arg(long, default_value_t = 7)]
        keep: usize,
        /// Keep the local file even after uploading
        #[arg(long)]
        keep_local: bool,
        /// List the backups in Drive and exit
        #[arg(long)]
        list: bool,
    },
    /// Restore a backup into a new, empty data directory.
    Restore {
        /// A local .qbk file
        #[arg(long)]
        file: Option<PathBuf>,
        /// A backup in Google Drive: its file name, or "latest"
        #[arg(long)]
        from_drive: Option<String>,
        /// Target data directory (must not exist or be empty)
        #[arg(long)]
        into: PathBuf,
    },
    /// Knowledge lattice: structure first, predict every cell, harvest only what is open, confirm.
    Lattice {
        #[arg(long, default_value = "config/lattice/knowledge-lattice.toml")]
        lattice: PathBuf,
        #[command(subcommand)]
        cmd: LatticeCmd,
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

#[derive(Subcommand)]
enum LatticeCmd {
    /// Structural checks; with --live every Q-id and P-id is checked against Wikidata.
    Validate {
        #[arg(long)]
        live: bool,
    },
    /// Members of each class and the fill rate of each slot (conceptual expectations).
    Census {
        /// domains, subdomains or class ids (comma-separated); prefix* allowed
        #[arg(long, default_value = "")]
        only: String,
        #[arg(long, default_value_t = 2000)]
        max_members: usize,
        #[arg(long)]
        force: bool,
        /// also write "X is a <class>" envelopes here
        #[arg(long, default_value = "data/harvest/lattice")]
        out: PathBuf,
    },
    /// Predict cell values from the invariant rules and class modes.
    Expect,
    /// Harvest only the open cells, highest-priority columns first.
    Fill {
        #[arg(long, default_value = "")]
        only: String,
        /// maximum SPARQL queries this run
        #[arg(long, default_value_t = 200)]
        budget: usize,
        #[arg(long, default_value = "data/harvest/lattice")]
        out: PathBuf,
        /// import the envelopes afterwards with this mapping, then confirm
        #[arg(long)]
        import: Option<PathBuf>,
    },
    /// Confirm or refute every expectation against admitted facts; attribute errors; calibrate.
    Confirm,
    /// Coverage, rule precision, calibration findings and remaining work.
    Report {
        #[arg(long)]
        json: bool,
        /// rows of the per-class table to print
        #[arg(long, default_value_t = 40)]
        top: usize,
    },
    /// Ask a model engine to recall values for open cells (stored as predictions, never facts).
    Predict {
        #[arg(long)]
        engine: String,
        #[arg(long, default_value = "")]
        only: String,
        /// maximum cells to ask about
        #[arg(long, default_value_t = 200)]
        limit: usize,
    },
    /// Ask a model engine to propose new classes and slots for a domain (written for review).
    Propose {
        #[arg(long)]
        engine: String,
        #[arg(long)]
        domain: String,
        #[arg(long)]
        out: PathBuf,
    },
}

const DRIVE_FOLDER: &str = "QueryBook backups";

fn backup_passphrase() -> anyhow::Result<String> {
    std::env::var("QB_BACKUP_PASSPHRASE").ok().filter(|p| !p.is_empty()).ok_or_else(|| {
        anyhow::anyhow!(
            "set QB_BACKUP_PASSPHRASE (12+ characters); keep a copy somewhere safe — without it no backup can be restored"
        )
    })
}

/// UTC "YYYYMMDD-HHMMSS" (sortable) from Unix seconds.
fn stamp(secs: i64) -> String {
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    // civil-from-days (Howard Hinnant)
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + (m <= 2) as i64;
    format!("{y:04}{m:02}{d:02}-{:02}{:02}{:02}", rem / 3600, rem % 3600 / 60, rem % 60)
}

fn backup_cmd(cfg: Config, out: &Path, to_drive: bool, keep: usize, keep_local: bool, list: bool) -> anyhow::Result<()> {
    let keys = cfg.server.data_dir.join("keys");
    if list {
        let d = querybook::d12::drive::Drive::new(&keys)?;
        let folder = d.folder(DRIVE_FOLDER)?;
        for f in d.list(&folder)? {
            println!("{}  {:>8.2} GB  {}", f.name, f.size as f64 / 1e9, f.created);
        }
        return Ok(());
    }
    let pass = backup_passphrase()?;
    // fail before snapshotting if Drive is not usable
    let drive = if to_drive { Some(querybook::d12::drive::Drive::new(&keys)?) } else { None };
    let folder = match &drive {
        Some(d) => Some(d.folder(DRIVE_FOLDER)?),
        None => None,
    };
    let qb = QueryBook::open(cfg)?;
    let file = out.join(format!("querybook-{}.qbk", stamp(querybook::util::now_secs())));
    eprintln!("snapshotting to {}", file.display());
    let r = querybook::d2::backup::create(&qb.store, &file, &pass, &qb.cfg.operator.name)?;
    eprintln!("  {} files, {} facts, {:.2} GB encrypted, {:.1}s", r.files, r.facts, r.bytes as f64 / 1e9, r.seconds);
    if let (Some(d), Some(folder)) = (&drive, &folder) {
        let up = d.upload(&file, folder, &|m: &str| eprintln!("{m}"))?;
        anyhow::ensure!(up.size == r.bytes, "uploaded size differs from the local file");
        // retention in Drive: newest `keep` backups
        let all = d.list(folder)?;
        for old in all.iter().skip(keep.max(1)) {
            d.delete(&old.id)?;
            eprintln!("  removed old backup {}", old.name);
        }
        qb.store.ledger_append(
            &qb.cfg.operator.name,
            "store.backup.upload",
            "D2->D12 ALLOW",
            &serde_json::json!({"file": up.name, "drive_id": up.id, "sha256": r.sha256}).to_string(),
            "operations",
        )?;
        if !keep_local {
            std::fs::remove_file(&file)?;
        }
        println!("backup {} uploaded to Google Drive / {DRIVE_FOLDER} (sha256 {})", up.name, &r.sha256[..16]);
    } else {
        // local retention
        let mut local: Vec<PathBuf> = std::fs::read_dir(out)?
            .flatten()
            .map(|e| e.path())
            .filter(|p| p.extension().map(|e| e == "qbk").unwrap_or(false))
            .collect();
        local.sort();
        local.reverse();
        for old in local.iter().skip(keep.max(1)) {
            std::fs::remove_file(old)?;
        }
        println!("backup written to {} (sha256 {})", r.file, &r.sha256[..16]);
    }
    Ok(())
}

fn csv_list(s: &str) -> Vec<String> {
    s.split(',').map(|x| x.trim().to_string()).filter(|x| !x.is_empty()).collect()
}

fn lattice_cmd(cfg: Config, path: &Path, cmd: LatticeCmd) -> anyhow::Result<()> {
    use querybook::d3::lattice::{Lattice, register};
    use querybook::d5::expect;
    use querybook::d12::lattice as wl;
    let l = Lattice::load(path)?;
    let errs = l.check();
    let say = |m: &str| eprintln!("{m}");
    if let LatticeCmd::Validate { live } = cmd {
        println!(
            "{}: {} domains, {} subdomains, {} classes, {} slots, {} rules; {} cells per member row",
            l.title,
            l.domain.len(),
            l.sub.len(),
            l.class.len(),
            l.slot.len(),
            l.rule.len(),
            l.cells_per_member()
        );
        for e in &errs {
            println!("  error: {e}");
        }
        if live {
            let r = wl::validate_live(&l, &say)?;
            println!("live: {} items, {} properties checked", r.items, r.properties);
            for e in &r.errors {
                println!("  error: {e}");
            }
            for d in &r.label_differs {
                println!("  review: {d}");
            }
            anyhow::ensure!(r.errors.is_empty(), "{} live validation error(s)", r.errors.len());
        }
        anyhow::ensure!(errs.is_empty(), "{} structural error(s)", errs.len());
        println!("ok");
        return Ok(());
    }
    anyhow::ensure!(errs.is_empty(), "the lattice has {} structural error(s); run `qb lattice validate`", errs.len());
    let qb = QueryBook::open(cfg)?;
    expect::ensure_tables(&qb)?;
    let digest = register(&qb.store, &l, &qb.cfg.operator.name)?;
    match cmd {
        LatticeCmd::Validate { .. } => unreachable!(),
        LatticeCmd::Census { only, max_members, force, out } => {
            let rows = wl::census(&qb, &l, &csv_list(&only), max_members, force, Some(&out), &say)?;
            let ok = rows.iter().filter(|r| r.status == "ok").count();
            let members: usize = rows.iter().map(|r| r.enumerated).sum();
            println!(
                "census: {ok}/{} classes, {members} members enumerated (membership envelopes in {})",
                rows.len(),
                out.display()
            );
        }
        LatticeCmd::Expect => {
            let r = expect::expect(&qb, &l, &digest)?;
            println!("{}", serde_json::to_string_pretty(&r)?);
            let c = expect::confirm(&qb, &l)?;
            println!("measured at once: {:?}", c.status);
        }
        LatticeCmd::Fill { only, budget, out, import } => {
            let r = wl::fill(&qb, &l, &csv_list(&only), budget, &out, &say)?;
            println!(
                "fill: {} queries, {} cells checked, {} filled, {} envelopes, {} forecasts tested, {:.1}s -> {}",
                r.queries, r.cells_checked, r.cells_filled, r.envelopes, r.predictions_tested, r.seconds, r.out
            );
            if let Some(mapping) = import {
                let ir = querybook::d1::ufcs::import(&qb, &mapping, Some(&out), 0, false, &|m: &str| eprintln!("  {m}"))?;
                println!("import: {} admitted, {} unchanged, {} refused", ir.admitted, ir.unchanged, ir.refused);
                let c = expect::confirm(&qb, &l)?;
                println!("confirm: {:?}", c.status);
            }
        }
        LatticeCmd::Confirm => {
            let r = expect::confirm(&qb, &l)?;
            println!("{}", serde_json::to_string_pretty(&r)?);
        }
        LatticeCmd::Report { json, top } => {
            let r = expect::report(&qb, &l, &digest)?;
            if json {
                println!("{}", serde_json::to_string_pretty(&r)?);
                return Ok(());
            }
            println!("{} — lattice {}", l.title, &digest[..16]);
            println!(
                "structure: {} domains · {} classes · {} slots · {} rules;  censused {} classes, {} members, {} cells",
                r.domains, r.classes, r.slots, r.rules, r.classes_censused, r.members, r.cells
            );
            let pct = |a: i64, b: i64| if b > 0 { 100.0 * a as f64 / b as f64 } else { 0.0 };
            println!(
                "cells: {} filled ({:.1}%), {} absent in Wikidata, {} open  ->  ~{} targeted queries to finish",
                r.filled,
                pct(r.filled, r.cells),
                r.absent,
                r.open,
                r.remaining_fill_queries
            );
            println!(
                "value predictions: {}  confirmed {}  refuted {}  precision {}",
                r.value_predictions,
                r.confirmed,
                r.refuted,
                r.precision.map(|p| format!("{:.1}%", p * 100.0)).unwrap_or_else(|| "—".into())
            );
            println!(
                "
{:<24} {:>7} {:>6} {:>8} {:>7} {:>7} {:>8} {:>8}",
                "class", "members", "slots", "filled%", "open", "fcast", "confirm", "refute"
            );
            let mut cov: Vec<_> = r.coverage.iter().collect();
            cov.sort_by(|a, b| b.cells.cmp(&a.cells).then(a.class.cmp(&b.class)));
            for c in cov.iter().take(top) {
                println!(
                    "{:<24} {:>7} {:>6} {:>7.1}% {:>7} {:>7} {:>8} {:>8}",
                    c.class,
                    c.enumerated,
                    c.slots,
                    pct(c.filled, c.cells),
                    c.open,
                    c.predicted_open,
                    c.confirmed,
                    c.refuted
                );
            }
            if !r.rule_stats.is_empty() {
                println!(
                    "
{:<40} {:>9} {:>8} {:>10} {:>11}",
                    "rule / basis", "confirmed", "refuted", "precision", "reliability"
                );
                for s in &r.rule_stats {
                    println!(
                        "{:<40} {:>9} {:>8} {:>10} {:>11.3}",
                        s.basis,
                        s.confirmed,
                        s.refuted,
                        s.precision.map(|p| format!("{:.1}%", p * 100.0)).unwrap_or_else(|| "—".into()),
                        s.reliability
                    );
                }
            }
            for f in &r.findings {
                println!("finding {f}");
            }
        }
        LatticeCmd::Predict { engine, only, limit } => {
            let r = wl::predict(&qb, &l, &engine, &csv_list(&only), limit, &digest, &say)?;
            println!("{}", serde_json::to_string_pretty(&r)?);
        }
        LatticeCmd::Propose { engine, domain, out } => {
            let n = wl::propose(&qb, &l, &engine, &domain, &out, &say)?;
            println!("{n} proposed classes written to {} for review", out.display());
        }
    }
    Ok(())
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
            let profile = qb.cfg.engine(&engine).ok_or_else(|| anyhow::anyhow!("engine {engine} is not registered in your config (-c file); copy its [[engines]] block from config/querybook.example.toml"))?.clone();
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
        Cmd::Lattice { lattice, cmd } => lattice_cmd(cfg, &lattice, cmd)?,
        Cmd::DriveAuth => {
            let drive = querybook::d12::drive::Drive::new(&cfg.server.data_dir.join("keys"))?;
            drive.authorize(&|m: &str| eprintln!("{m}"))?;
        }
        Cmd::Backup { out, drive, keep, keep_local, list } => backup_cmd(cfg, &out, drive, keep, keep_local, list)?,
        Cmd::Restore { file, from_drive, into } => {
            let pass = backup_passphrase()?;
            let r = match (file, from_drive) {
                (Some(f), None) => {
                    querybook::d2::backup::restore(std::io::BufReader::new(std::fs::File::open(&f)?), &into, &pass)?
                }
                (None, Some(name)) => {
                    let d = querybook::d12::drive::Drive::new(&cfg.server.data_dir.join("keys"))?;
                    let folder = d.folder(DRIVE_FOLDER)?;
                    let files = d.list(&folder)?;
                    let f = if name == "latest" { files.first() } else { files.iter().find(|f| f.name == name) }
                        .ok_or_else(|| anyhow::anyhow!("no backup '{name}' in Drive"))?;
                    eprintln!("restoring {} ({:.2} GB) from Drive", f.name, f.size as f64 / 1e9);
                    querybook::d2::backup::restore(std::io::BufReader::with_capacity(1 << 20, d.download(&f.id)?), &into, &pass)?
                }
                _ => anyhow::bail!("give exactly one of --file or --from-drive"),
            };
            // prove the restored store is whole: open it and verify the ledger
            let mut c2 = cfg.clone();
            c2.server.data_dir = into.clone();
            let qb = QueryBook::open(c2)?;
            let v = qb.store.verify_ledger()?;
            println!("{}", serde_json::to_string_pretty(&r)?);
            let ok = v.first_failure.is_none() && v.verified == v.nodes;
            println!(
                "ledger: {} of {} nodes verified{}",
                v.verified,
                v.nodes,
                v.first_failure.as_deref().map(|f| format!(", first failure: {f}")).unwrap_or_default()
            );
            anyhow::ensure!(ok, "the restored ledger does not verify");
            println!("point data_dir at {} to use it", into.display());
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
            querybook::util::clip(if c.quote.is_empty() { &c.rendered } else { &c.quote }, 110)
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
