#!/usr/bin/env python3
"""
qb_mailer.py — hourly health email for QueryBook (stdlib only).

Emails a sys admin, on a schedule, a single digest containing:
  • FAIL ALERTS      — self-test failures, blocked/errored agents, backup errors
  • ERROR CODES      — every error/blocked/warn log entry since the last send
  • APPLICATION LOGS — a tail of the recent event log + the store's data_events.log

No external packages: smtplib + email from the standard library. Credentials live
ONLY in a LOCAL, git-ignored file (~/.querybook/mail.json) or env QB_MAIL_JSON —
never hard-coded, never committed, never logged. Everything is best-effort and
exception-guarded: a mail failure is recorded and never crashes the app.

Gmail note: use an APP PASSWORD (Google Account → Security → App passwords),
not your normal password, with smtp.gmail.com:587 (STARTTLS) or :465 (SSL).
"""
import os, json, ssl, time, smtplib, threading, traceback
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

HOME = os.path.expanduser("~")
MAIL_CFG = os.path.join(HOME, ".querybook", "mail.json")

DEFAULT_CFG = {
    "enabled": False,
    "to": "ghowardbiz777@gmail.com",          # sys admin (change as needed)
    "from": "",                                # defaults to username
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "use_tls": True,                           # STARTTLS on 587; port 465 = implicit SSL
    "username": "",                            # the sending Gmail address
    "password": "",                            # a Gmail APP PASSWORD (16 chars), not your login
    "interval_minutes": 60,                    # hourly
    "subject_prefix": "[QueryBook]",
    "only_when_problems": False,               # True = skip the email when nothing is failing
    "_README": ("LOCAL secrets — never commit. Set username+password (Gmail APP "
                "password), set enabled=true, then restart QueryBook. Test anytime: "
                "python qb_api.py mail-test"),
}

# shared, redacted status for the UI
STATE = {"enabled": False, "to": "", "last_attempt": None, "last_ok": None,
         "last_error": None, "sends": 0, "interval_minutes": 60, "next_due": None}
_LOCK = threading.Lock()
_STOP = threading.Event()


def _cfg_path():
    return os.environ.get("QB_MAIL_JSON") or MAIL_CFG


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        p = _cfg_path()
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                cfg.update({k: v for k, v in (json.load(f) or {}).items()})
    except Exception:
        pass
    return cfg


def save_cfg(cfg):
    p = _cfg_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp.%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, p)
        try:
            os.chmod(p, 0o600)   # secrets: owner-only where the OS supports it
        except Exception:
            pass
        return True
    except Exception:
        return False


def status():
    with _LOCK:
        return dict(STATE)


def ensure_template():
    """Create the git-ignored mail.json with the admin recipient prefilled, once."""
    p = _cfg_path()
    if not os.path.isfile(p):
        save_cfg(dict(DEFAULT_CFG))
    return p


# ---------------------------------------------------------------------------
def _tail_file(path, max_lines=120):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:]).strip()
    except Exception:
        return ""


def compose(report, cfg):
    """Build (subject, text, html) from a report dict. Pure; no I/O."""
    host = report.get("host", "this machine")
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    st = report.get("selftest") or {}
    alerts = report.get("alerts") or []
    errors = report.get("errors") or []
    logs = report.get("logs") or []
    data_events = report.get("data_events") or ""
    backup = report.get("backup") or {}

    ok = (not alerts) and (st.get("all_ok") is not False)
    flag = "OK" if ok else "ATTENTION"
    subject = "%s %s — %d alert(s), %d error(s) — %s" % (
        cfg.get("subject_prefix", "[QueryBook]"), flag, len(alerts), len(errors), when)

    L = []
    L.append("QueryBook health digest")
    L.append("Host: %s    Generated: %s" % (host, when))
    L.append("Store: %s" % report.get("store", "?"))
    L.append("Build: %s" % report.get("build", "?"))
    L.append("")
    L.append("SELF-TEST: %s (%s/%s checks)" % (
        "PASS" if st.get("all_ok") else ("FAIL" if st.get("all_ok") is False else "unknown"),
        st.get("passed", "?"), st.get("total", "?")))
    for c in (st.get("checks") or []):
        if not c.get("ok"):
            L.append("   [FAIL] %s — %s" % (c.get("name", "?"), c.get("detail", "")))
    L.append("")
    L.append("FAIL ALERTS (%d):" % len(alerts))
    L += ["   • " + a for a in alerts] or ["   (none)"]
    L.append("")
    L.append("BACKUP: last run %s; authoritative %s (%s facts)" % (
        backup.get("last_run", "—"), backup.get("authoritative", "—"),
        format(backup.get("authoritative_facts", 0), ",")))
    if backup.get("error"):
        L.append("   backup error: %s" % backup["error"])
    L.append("")
    L.append("ERROR CODES / errors & warnings since last send (%d):" % len(errors))
    for e in errors[:200]:
        L.append("   [%s] %-10s %s  %s" % (e.get("t", ""), e.get("level", ""),
                                           e.get("source", ""), e.get("msg", "")))
    if not errors:
        L.append("   (none)")
    L.append("")
    L.append("APPLICATION LOG (recent %d events):" % len(logs))
    for e in logs[:300]:
        L.append("   [%s] %-6s %-12s %s" % (e.get("t", ""), e.get("level", ""),
                                            e.get("source", ""), e.get("msg", "")))
    L.append("")
    L.append("DATA EVENTS LOG (store, tail):")
    L.append(data_events or "   (none)")
    text = "\n".join(L)

    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    color = "#2e9e78" if ok else "#b23b3b"
    html = (
        "<div style='font:14px/1.5 -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a'>"
        "<h2 style='margin:0 0 4px'>QueryBook health digest "
        "<span style='color:%s'>%s</span></h2>"
        "<div style='color:#64748b'>Host %s · %s · build %s</div>"
        "<pre style='background:#0e1310;color:#cfe8dd;padding:14px;border-radius:10px;"
        "overflow:auto;font:12.5px/1.6 ui-monospace,Consolas,monospace;white-space:pre-wrap'>%s</pre>"
        "</div>" % (color, flag, esc(host), esc(when), esc(report.get("build", "?")), esc(text))
    )
    return subject, text, html


def send(cfg, subject, text, html=None):
    """Send one email via SMTP. Raises on failure (caller logs/records)."""
    to = (cfg.get("to") or "").strip()
    user = (cfg.get("username") or "").strip()
    pwd = cfg.get("password") or ""
    host = (cfg.get("smtp_host") or "smtp.gmail.com").strip()
    port = int(cfg.get("smtp_port") or 587)
    sender = (cfg.get("from") or user or to).strip()
    if not to:
        raise RuntimeError("no recipient configured (set 'to' in mail.json)")
    if not (user and pwd):
        raise RuntimeError("SMTP username/password not set in mail.json "
                           "(Gmail: use an App Password)")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="querybook.local")
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=ctx) as s:
            s.login(user, pwd)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            if cfg.get("use_tls", True):
                s.starttls(context=ctx)
                s.ehlo()
            s.login(user, pwd)
            s.send_message(msg)
    return True


def send_report(report, cfg=None):
    """Compose + send a report now. Returns {'ok':bool,...}. Best-effort (no raise)."""
    cfg = cfg or load_cfg()
    with _LOCK:
        STATE["enabled"] = bool(cfg.get("enabled"))
        STATE["to"] = cfg.get("to", "")
        STATE["interval_minutes"] = int(cfg.get("interval_minutes") or 60)
        STATE["last_attempt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # optionally skip a clean run
    clean = (not (report.get("alerts") or report.get("errors"))) and \
            ((report.get("selftest") or {}).get("all_ok") is not False)
    if cfg.get("only_when_problems") and clean:
        with _LOCK:
            STATE["last_error"] = None
        return {"ok": True, "skipped": "no problems to report"}
    try:
        subject, text, html = compose(report, cfg)
        send(cfg, subject, text, html)
        with _LOCK:
            STATE["last_ok"] = STATE["last_attempt"]
            STATE["last_error"] = None
            STATE["sends"] += 1
        return {"ok": True, "subject": subject, "to": cfg.get("to")}
    except Exception as e:
        with _LOCK:
            STATE["last_error"] = str(e)
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
_SCHED = {"thread": None}


def start_scheduler(collect):
    """Start the hourly digest thread. `collect` returns a fresh report dict.
    Idempotent; honours mail.json 'enabled' and 'interval_minutes' live."""
    if _SCHED["thread"] and _SCHED["thread"].is_alive():
        return
    _STOP.clear()

    def _loop():
        # small initial delay so the first digest reflects a warmed-up app
        first = True
        while not _STOP.is_set():
            cfg = load_cfg()
            interval = max(5, int(cfg.get("interval_minutes") or 60)) * 60
            with _LOCK:
                STATE["enabled"] = bool(cfg.get("enabled"))
                STATE["to"] = cfg.get("to", "")
                STATE["interval_minutes"] = int(cfg.get("interval_minutes") or 60)
                STATE["next_due"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + interval))
            # wait the interval (wake early if stopped), then send if enabled
            waited = 0
            step = 15
            start_wait = 120 if first else interval      # first digest ~2 min after boot
            first = False
            while waited < start_wait and not _STOP.is_set():
                time.sleep(step); waited += step
            if _STOP.is_set():
                break
            cfg = load_cfg()
            if not cfg.get("enabled"):
                continue
            try:
                rep = collect()
                send_report(rep, cfg)
            except Exception:
                traceback.print_exc()

    t = threading.Thread(target=_loop, daemon=True)
    _SCHED["thread"] = t
    t.start()


def stop_scheduler():
    _STOP.set()
