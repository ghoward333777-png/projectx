"""Verbatim table definitions from the QueryBook suite (claude/lucid-brahmagupta-ak4f6m, querybook/apps/_core:
qbbulk.SCHEMA for a bulk shard, the first part of qbcommons.SCHEMA for commons.sqlite), used to build a miniature
D:\\QB for tests. Regenerate if the suite's schema changes."""

SHARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (fp BLOB PRIMARY KEY, s TEXT NOT NULL, p INTEGER NOT NULL, o TEXT NOT NULL, part INTEGER NOT NULL,
  row INTEGER NOT NULL) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS facts_s ON facts(s);
CREATE TABLE IF NOT EXISTS predicates (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, rule TEXT);
CREATE TABLE IF NOT EXISTS parts (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, url TEXT, version TEXT, rows INTEGER NOT NULL DEFAULT 0,
  facts INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0, started TEXT, finished TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS progress (at REAL PRIMARY KEY, facts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS links (fp BLOB PRIMARY KEY, url TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS slots (series TEXT NOT NULL, year INTEGER NOT NULL, filled INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (series, year)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS stage (fp BLOB NOT NULL, s TEXT NOT NULL, p INTEGER NOT NULL, o TEXT NOT NULL, part INTEGER NOT NULL, row INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS stage_links (fp BLOB NOT NULL, url TEXT NOT NULL);
"""

COMMONS_SCHEMA = """
CREATE TABLE facts (
  id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, domain TEXT NOT NULL, subject TEXT NOT NULL,
  predicate TEXT NOT NULL, object TEXT NOT NULL, statement TEXT, origin_app TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unsourced', confidence REAL NOT NULL DEFAULT 0.2, created TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE INDEX facts_domain ON facts(domain, status);
CREATE INDEX facts_sp ON facts(subject, predicate);
CREATE TABLE evidence (
  id INTEGER PRIMARY KEY, fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE, app TEXT NOT NULL, agent TEXT NOT NULL,
  method TEXT NOT NULL, source TEXT NOT NULL, licence TEXT, url TEXT, quote TEXT, verdict TEXT NOT NULL, detail TEXT,
  at TEXT NOT NULL, UNIQUE (fact_id, app, method, source)
);
CREATE INDEX evidence_fact ON evidence(fact_id);
CREATE TABLE reasoning (
  id INTEGER PRIMARY KEY, fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE, app TEXT NOT NULL, agent TEXT NOT NULL,
  step INTEGER NOT NULL, text TEXT NOT NULL, at TEXT NOT NULL, UNIQUE (fact_id, app, agent, text)
);
CREATE INDEX reasoning_fact ON reasoning(fact_id);
CREATE TABLE requests (
  id INTEGER PRIMARY KEY, fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE, kind TEXT NOT NULL, payload TEXT NOT NULL,
  fingerprint TEXT NOT NULL UNIQUE, from_app TEXT NOT NULL, to_app TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
  verdict TEXT, detail TEXT, created TEXT NOT NULL, answered TEXT
);
CREATE INDEX requests_open ON requests(to_app, status);
CREATE TABLE team (
  app TEXT NOT NULL, role TEXT NOT NULL, last_run TEXT, last_status TEXT, last_summary TEXT, last_ms INTEGER,
  runs INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (app, role)
);
CREATE TABLE strategies (id INTEGER PRIMARY KEY, app TEXT NOT NULL, created TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE plans (id INTEGER PRIMARY KEY, app TEXT NOT NULL, strategy_id INTEGER, created TEXT NOT NULL, status TEXT NOT NULL, summary TEXT);
CREATE TABLE tasks (
  id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE, app TEXT NOT NULL, step INTEGER NOT NULL,
  action TEXT NOT NULL, title TEXT NOT NULL, target TEXT, status TEXT NOT NULL DEFAULT 'queued', items INTEGER, started TEXT,
  finished TEXT, detail TEXT
);
CREATE INDEX tasks_plan ON tasks(plan_id);
CREATE TABLE agent_log (id INTEGER PRIMARY KEY, at TEXT NOT NULL, app TEXT NOT NULL, role TEXT NOT NULL, message TEXT NOT NULL, ms INTEGER);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)
"""
