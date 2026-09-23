//! MediaMarketplace Studio server binary.
//!
//! Subcommands:
//!   init     write a config file and create the data directory
//!   migrate  apply database migrations
//!   admin    create an administrator account
//!   health   print the health report as JSON
//!   serve    run the HTTP server (default)

mod app;
mod auth;
mod errors;
mod routes;
mod templates;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use mms_core::config::Config;
use mms_core::db::Db;
use std::path::{Path, PathBuf};

#[derive(Parser)]
#[command(name = "mms-server", version, about = "MediaMarketplace Studio server")]
struct Cli {
    /// Path to the configuration file.
    #[arg(
        short,
        long,
        global = true,
        default_value = "mms.toml",
        env = "MMS_CONFIG"
    )]
    config: PathBuf,
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    /// Create a configuration file and data directory.
    Init {
        #[arg(long, default_value = "./data")]
        data_dir: PathBuf,
        #[arg(long, default_value = "127.0.0.1:8090")]
        bind: String,
        #[arg(long, default_value = "http://127.0.0.1:8090")]
        public_url: String,
        /// Overwrite an existing configuration file.
        #[arg(long)]
        force: bool,
    },
    /// Apply pending database migrations.
    Migrate,
    /// Create an administrator. Prompts for the password unless --password is given.
    Admin {
        #[arg(long)]
        email: String,
        #[arg(long, default_value = "Administrator")]
        name: String,
        #[arg(long, env = "MMS_ADMIN_PASSWORD", hide_env_values = true)]
        password: Option<String>,
    },
    /// Print the health report as JSON.
    Health,
    /// Run the HTTP server.
    Serve,
    /// Identify the viewer a leaked image or screenshot was issued to.
    Identify { file: PathBuf },
    /// Write a backup archive (database snapshot, config, media) into a folder.
    Backup {
        #[arg(long)]
        out: Option<PathBuf>,
    },
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,sqlx=warn".into()),
        )
        .init();

    let cli = Cli::parse();
    match cli.command.unwrap_or(Command::Serve) {
        Command::Init {
            data_dir,
            bind,
            public_url,
            force,
        } => {
            if cli.config.exists() && !force {
                anyhow::bail!(
                    "{} already exists; pass --force to overwrite",
                    cli.config.display()
                );
            }
            let data_dir = if data_dir.is_absolute() {
                data_dir
            } else {
                std::env::current_dir()?.join(data_dir)
            };
            let cfg = Config::generate(data_dir.clone(), &bind, &public_url);
            std::fs::create_dir_all(cfg.media_public_dir())?;
            std::fs::create_dir_all(cfg.media_private_dir())?;
            cfg.save(&cli.config)?;
            let db = Db::connect(&cfg.database_url()).await?;
            db.migrate().await?;
            println!(
                "Wrote {} and initialised {}",
                cli.config.display(),
                data_dir.display()
            );
            println!("Next: mms-server admin --email you@example.com, then mms-server serve");
        }
        Command::Migrate => {
            let (_, db) = open(&cli.config).await?;
            db.migrate().await?;
            println!("Migrations applied: {:?}", db.applied_migrations().await?);
        }
        Command::Admin {
            email,
            name,
            password,
        } => {
            let (_, db) = open(&cli.config).await?;
            let password = match password {
                Some(p) => p,
                None => {
                    let p = rpassword::prompt_password("Password (10+ characters): ")?;
                    let again = rpassword::prompt_password("Repeat password: ")?;
                    anyhow::ensure!(p == again, "passwords do not match");
                    p
                }
            };
            let user = mms_core::users::Users::new(db)
                .create(&email, &name, Some(&password), "admin")
                .await?;
            println!("Created administrator {} ({})", user.email, user.uuid);
        }
        Command::Health => {
            let (cfg, db) = open(&cli.config).await?;
            let report = mms_core::health::run(&cfg, &db).await;
            println!("{}", serde_json::to_string_pretty(&report)?);
            if report.status == mms_core::health::Status::Fail {
                std::process::exit(1);
            }
        }
        Command::Identify { file } => {
            let (_cfg, db) = open(&cli.config).await?;
            let bytes =
                std::fs::read(&file).with_context(|| format!("reading {}", file.display()))?;
            match mms_core::protection::Protection::new(db.clone())
                .identify(&bytes)
                .await?
            {
                Some((s, how)) => {
                    let email: Option<String> = match s.user_id {
                        Some(u) => {
                            sqlx::query_scalar("SELECT email FROM users WHERE id = ?")
                                .bind(u)
                                .fetch_optional(&db.pool)
                                .await?
                        }
                        None => None,
                    };
                    println!(
                        "{}",
                        serde_json::json!({ "found": true, "how": how, "session": s.uuid, "code": s.code, "user_id": s.user_id, "email": email, "media_id": s.media_id, "created_at": s.created_at })
                    );
                }
                None => {
                    println!("{}", serde_json::json!({ "found": false }));
                    std::process::exit(2);
                }
            }
        }
        Command::Backup { out } => {
            let (cfg, db) = open(&cli.config).await?;
            let dir = out.unwrap_or_else(|| cfg.data_dir.join("backups"));
            let path = mms_core::backup::create(&db.pool, &cfg.data_dir, &dir).await?;
            println!("{}", path.display());
        }
        Command::Serve => {
            let (cfg, db) = open(&cli.config).await?;
            db.migrate().await?;
            let state = app::AppState::new(cfg.clone(), db)?;
            let synced = routes::bridges::sync_from_config(&state).await?;
            if synced > 0 {
                tracing::info!("registered {synced} bridge site(s) from the config file");
            }
            routes::worker::spawn(state.clone());
            let router = app::router(state);
            let listener = tokio::net::TcpListener::bind(&cfg.server.bind)
                .await
                .with_context(|| format!("binding {}", cfg.server.bind))?;
            tracing::info!(
                "MediaMarketplace Studio {} listening on {} (public url {})",
                mms_core::version(),
                cfg.server.bind,
                cfg.server.public_url
            );
            axum::serve(listener, router)
                .with_graceful_shutdown(shutdown())
                .await?;
        }
    }
    Ok(())
}

async fn open(path: &Path) -> Result<(Config, Db)> {
    let cfg = Config::load(path)?;
    let db = Db::connect(&cfg.database_url()).await?;
    Ok((cfg, db))
}

async fn shutdown() {
    let _ = tokio::signal::ctrl_c().await;
    tracing::info!("shutting down");
}
