"""Google Cloud for the QueryBook applications — standard library only, nothing to install.

Services used (all optional; each app works fully without them):
    Cloud Storage        an off-site copy of every verified backup (resumable upload, MD5-checked)
    Cloud Monitoring     health metrics after every diagnostics run, and a one-click alert policy
    Speech-to-Text       transcripts with word timings and confidence (Language Builder)
    Text-to-Speech       (the Language Builder's voices use the same API key)
    YouTube Data API v3  videos as "reported by" sources (History & News)

Credentials live only in the data folder (google.json, owner-only) and are never shown, logged or
sent anywhere except to Google:
    * an API key        — Speech-to-Text, Text-to-Speech, YouTube
    * a service account  — Cloud Storage and Cloud Monitoring (a JSON key file from the Cloud console).
      Its requests are signed here with RS256 (RSA PKCS#1 v1.5 + SHA-256, implemented below), exchanged
      for a one-hour access token, which is cached.

Every endpoint can be pointed elsewhere with QB_GCP_BASE_<SERVICE> (used by the self-tests' stand-in server).
"""
import base64, hashlib, json, os, re, socket, threading, time, urllib.error, urllib.parse, urllib.request

SCOPE = "https://www.googleapis.com/auth/devstorage.read_write https://www.googleapis.com/auth/monitoring.write https://www.googleapis.com/auth/monitoring"
DEFAULTS = {"storage": "https://storage.googleapis.com", "monitoring": "https://monitoring.googleapis.com",
            "speech": "https://speech.googleapis.com", "youtube": "https://www.googleapis.com", "token": None}
CHUNK = 8 * 256 * 1024          # resumable upload chunk (2 MiB, a multiple of 256 KiB)


class GoogleError(Exception):
    pass


def base(svc):
    return (os.environ.get("QB_GCP_BASE_" + svc.upper()) or DEFAULTS[svc] or "").rstrip("/")


def now_rfc3339(t=None):
    t = time.time() if t is None else t
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%02dZ" % int((t % 1) * 100)


# ---------------------------------------------------------------------------- settings
class Settings:
    def __init__(self, folder):
        self.folder = folder
        self.path = os.path.join(folder, "google.json")
        self._lock = threading.Lock()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f) or {}
        except (OSError, ValueError):
            return {}

    def _write(self, cfg):
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)

    def api_key(self):
        return self.load().get("api_key") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""

    def service_account(self):
        sa = self.load().get("service_account")
        if not sa and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            try:
                with open(os.environ["GOOGLE_APPLICATION_CREDENTIALS"], encoding="utf-8") as f:
                    sa = json.load(f)
            except (OSError, ValueError):
                sa = None
        return sa or None

    def save(self, values):
        cfg = self.load()
        v = values or {}
        if v.get("api_key"):
            cfg["api_key"] = str(v["api_key"]).strip()
        if v.get("service_account_json"):
            try:
                sa = json.loads(v["service_account_json"]) if isinstance(v["service_account_json"], str) else v["service_account_json"]
            except ValueError:
                raise ValueError("The service account file is not valid JSON.")
            if sa.get("type") != "service_account" or not sa.get("private_key") or not sa.get("client_email"):
                raise ValueError("That is not a service account key file (it needs type, client_email and private_key).")
            parse_private_key(sa["private_key"])                 # fail now, not at the first backup
            cfg["service_account"] = sa
            cfg.setdefault("project_id", sa.get("project_id"))
        for k in ("bucket", "project_id"):
            if k in v and v[k] is not None:
                cfg[k] = re.sub(r"^gs://", "", str(v[k]).strip()).strip("/")
        for k in ("storage_on", "monitoring_on", "stt_on"):
            if k in v:
                cfg[k] = v[k] in (True, "true", "1", 1, "on")
        if "keep" in v and v["keep"]:
            cfg["keep"] = max(1, min(100, int(v["keep"])))
        self._write(cfg)

    def forget(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def public(self):
        cfg = self.load()
        sa = self.service_account()
        return {"api_key_set": bool(self.api_key()), "api_key_from_environment": bool(not cfg.get("api_key") and self.api_key()),
                "service_account": {"client_email": sa.get("client_email"), "project_id": sa.get("project_id")} if sa else None,
                "project_id": cfg.get("project_id") or (sa or {}).get("project_id"), "bucket": cfg.get("bucket") or "",
                "storage_on": bool(cfg.get("storage_on")), "monitoring_on": bool(cfg.get("monitoring_on")),
                "stt_on": cfg.get("stt_on", True), "keep": cfg.get("keep", 10)}

    def secrets(self):
        sa = self.service_account() or {}
        return [s for s in (self.api_key(), sa.get("private_key"), sa.get("private_key_id")) if s and len(s) > 6]

    def scrub(self, text):
        t = str(text)
        for s in self.secrets():
            t = t.replace(s, "<secret>")
        t = re.sub(r"(?i)(key=)[A-Za-z0-9_\-]{8,}", r"\1<key>", t)
        t = re.sub(r"ya29\.[A-Za-z0-9_\-\.]+", "<token>", t)
        return t


# ---------------------------------------------------------------------------- RS256 (RSA PKCS#1 v1.5, SHA-256), pure Python
def _der(b, i):
    tag = b[i]; i += 1
    ln = b[i]; i += 1
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(b[i:i + n], "big"); i += n
    return tag, b[i:i + ln], i + ln


def _der_seq(b):
    out, i = [], 0
    while i < len(b):
        tag, val, i = _der(b, i)
        out.append((tag, val))
    return out


def parse_private_key(pem):
    """PEM (PKCS#8 'PRIVATE KEY' or PKCS#1 'RSA PRIVATE KEY') → dict of the RSA integers."""
    body = re.sub(r"-----[^-]+-----", "", pem or "")
    der = base64.b64decode("".join(body.split()))
    tag, top, _ = _der(der, 0)
    items = _der_seq(top)
    if len(items) >= 3 and items[1][0] == 0x30 and items[2][0] == 0x04:           # PKCS#8 wrapper
        tag, inner, _ = _der(items[2][1], 0)
        items = _der_seq(inner)
    ints = [int.from_bytes(v, "big") for t, v in items if t == 0x02]
    if len(ints) < 9:
        raise ValueError("unsupported private key format")
    names = ("version", "n", "e", "d", "p", "q", "dp", "dq", "qi")
    return dict(zip(names, ints[:9]))


_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def rs256(msg, key):
    k = (key["n"].bit_length() + 7) // 8
    t = _SHA256_PREFIX + hashlib.sha256(msg).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    m = int.from_bytes(em, "big")
    m1, m2 = pow(m, key["dp"], key["p"]), pow(m, key["dq"], key["q"])        # Chinese remainder theorem
    h = (key["qi"] * (m1 - m2)) % key["p"]
    return (m2 + h * key["q"]).to_bytes(k, "big")


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# ---------------------------------------------------------------------------- HTTP and auth
class Google:
    def __init__(self, settings, log=None):
        self.s = settings
        self.log = log or (lambda *a: None)
        self._tok = None
        self._lock = threading.Lock()
        self.last = {}               # service → {ok, at, seconds, detail}

    def _note(self, svc, ok, t0, detail=""):
        self.last[svc] = {"ok": ok, "at": now_rfc3339(), "seconds": round(time.time() - t0, 2), "detail": self.s.scrub(detail)[:300]}

    def http(self, method, url, body=None, headers=None, timeout=60):
        req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            try:
                txt = json.loads(txt).get("error", {}).get("message") or txt
            except (ValueError, AttributeError):
                pass
            if e.code == 308:                               # resumable upload: "resume incomplete"
                return 308, b"", dict(e.headers)
            raise GoogleError("HTTP %s: %s" % (e.code, self.s.scrub(txt)[:300]))
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            raise GoogleError("cannot reach Google: %s" % self.s.scrub(getattr(e, "reason", e)))

    def token(self):
        sa = self.s.service_account()
        if not sa:
            raise GoogleError("no service account — add its JSON key file on the Diagnostics page")
        with self._lock:
            if self._tok and self._tok[1] > time.time() + 60:
                return self._tok[0]
            t0 = time.time()
            key = parse_private_key(sa["private_key"])
            iat = int(time.time())
            aud = base("token") or sa.get("token_uri") or "https://oauth2.googleapis.com/token"
            if base("token"):
                aud = base("token") + "/token"
            hdr = {"alg": "RS256", "typ": "JWT"}
            if sa.get("private_key_id"):
                hdr["kid"] = sa["private_key_id"]
            claims = {"iss": sa["client_email"], "scope": SCOPE, "aud": aud, "iat": iat, "exp": iat + 3600}
            signing = _b64u(json.dumps(hdr, separators=(",", ":")).encode()) + "." + _b64u(json.dumps(claims, separators=(",", ":")).encode())
            jwt = signing + "." + _b64u(rs256(signing.encode(), key))
            body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt}).encode()
            try:
                st, raw, _ = self.http("POST", aud, body, {"Content-Type": "application/x-www-form-urlencoded"}, 30)
                tok = json.loads(raw)
                self._tok = (tok["access_token"], time.time() + int(tok.get("expires_in", 3600)))
                self._note("auth", True, t0, "token for %s" % sa["client_email"])
            except Exception as e:
                self._note("auth", False, t0, str(e))
                raise
            return self._tok[0]

    def _auth(self, extra=None):
        h = {"Authorization": "Bearer " + self.token()}
        h.update(extra or {})
        return h

    # ------------------------------------------------------------------ Cloud Storage
    def _bucket(self):
        b = self.s.load().get("bucket")
        if not b:
            raise GoogleError("no bucket name — create one in Cloud Storage and enter its name")
        return b

    def bucket_info(self):
        t0 = time.time()
        try:
            st, raw, _ = self.http("GET", base("storage") + "/storage/v1/b/%s" % urllib.parse.quote(self._bucket(), safe=""), None, self._auth(), 30)
            info = json.loads(raw)
            self._note("storage", True, t0, "bucket %s (%s)" % (info.get("name"), info.get("location")))
            return info
        except Exception as e:
            self._note("storage", False, t0, str(e))
            raise

    def upload(self, path, name, progress=None):
        """Resumable upload in 2 MiB chunks; returns the object's metadata after its MD5 is checked against the file."""
        t0 = time.time()
        size = os.path.getsize(path)
        md5 = hashlib.md5()
        try:
            url = base("storage") + "/upload/storage/v1/b/%s/o?uploadType=resumable&name=%s" % (
                urllib.parse.quote(self._bucket(), safe=""), urllib.parse.quote(name, safe=""))
            st, raw, hd = self.http("POST", url, json.dumps({"name": name, "contentType": "application/octet-stream"}).encode(),
                                    self._auth({"Content-Type": "application/json", "X-Upload-Content-Length": str(size)}), 60)
            session = hd.get("Location") or hd.get("location")
            if not session:
                raise GoogleError("Google did not open an upload session")
            sent, meta = 0, None
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(CHUNK)
                    md5.update(chunk)
                    end = sent + len(chunk) - 1
                    rng = "bytes %d-%d/%d" % (sent, end, size) if chunk else "bytes */%d" % size
                    st, raw, hd = self.http("PUT", session, chunk, {"Content-Range": rng, **self._auth()}, 120)
                    sent += len(chunk)
                    if progress:
                        progress(sent, size)
                    if st in (200, 201):
                        meta = json.loads(raw)
                        break
                    if not chunk:
                        raise GoogleError("upload ended without confirmation")
            want = base64.b64encode(md5.digest()).decode()
            if meta.get("md5Hash") != want:
                raise GoogleError("the copy in Cloud Storage does not match the file (MD5 %s vs %s)" % (meta.get("md5Hash"), want))
            self._note("storage", True, t0, "uploaded %s (%d bytes, MD5 matched)" % (name, size))
            return meta
        except Exception as e:
            self._note("storage", False, t0, str(e))
            raise

    def list(self, prefix):
        st, raw, _ = self.http("GET", base("storage") + "/storage/v1/b/%s/o?prefix=%s" % (urllib.parse.quote(self._bucket(), safe=""), urllib.parse.quote(prefix, safe="")),
                               None, self._auth(), 30)
        items = json.loads(raw).get("items", [])
        return sorted(({"name": i["name"], "bytes": int(i.get("size", 0)), "updated": i.get("updated"), "md5": i.get("md5Hash")} for i in items),
                      key=lambda x: x["name"], reverse=True)

    def download(self, name, dest):
        t0 = time.time()
        st, raw, _ = self.http("GET", base("storage") + "/storage/v1/b/%s/o/%s?alt=media" % (urllib.parse.quote(self._bucket(), safe=""), urllib.parse.quote(name, safe="")),
                               None, self._auth(), 300)
        meta = [i for i in self.list(name) if i["name"] == name]
        if meta and meta[0]["md5"] != base64.b64encode(hashlib.md5(raw).digest()).decode():
            raise GoogleError("the downloaded copy does not match Cloud Storage's MD5")
        with open(dest + ".part", "wb") as f:
            f.write(raw)
        os.replace(dest + ".part", dest)
        self._note("storage", True, t0, "downloaded %s" % name)
        return dest

    def delete(self, name):
        self.http("DELETE", base("storage") + "/storage/v1/b/%s/o/%s" % (urllib.parse.quote(self._bucket(), safe=""), urllib.parse.quote(name, safe="")),
                  None, self._auth(), 30)

    # ------------------------------------------------------------------ Cloud Monitoring
    def project(self):
        p = self.s.public()["project_id"]
        if not p:
            raise GoogleError("no project id")
        return p

    def write_metrics(self, app_id, host, values):
        """values: {name: number}. Written as custom.googleapis.com/querybook/<name> with app and host labels."""
        t0 = time.time()
        end = now_rfc3339()
        series = []
        for name, v in values.items():
            val = {"int64Value": str(int(v))} if isinstance(v, (int, bool)) else {"doubleValue": float(v)}
            series.append({"metric": {"type": "custom.googleapis.com/querybook/" + name, "labels": {"app": app_id, "host": host}},
                           "resource": {"type": "global", "labels": {"project_id": self.project()}},
                           "points": [{"interval": {"endTime": end}, "value": val}]})
        try:
            self.http("POST", base("monitoring") + "/v3/projects/%s/timeSeries" % self.project(), json.dumps({"timeSeries": series}).encode(),
                      self._auth({"Content-Type": "application/json"}), 30)
            self._note("monitoring", True, t0, "%d metrics written" % len(series))
        except Exception as e:
            self._note("monitoring", False, t0, str(e))
            raise

    def create_alert(self, app_id, app_name):
        flt = 'metric.type="custom.googleapis.com/querybook/health" AND resource.type="global" AND metric.label.app="%s"' % app_id
        agg = [{"alignmentPeriod": "3600s", "perSeriesAligner": "ALIGN_MAX"}]
        body = {"displayName": "QueryBook %s — silent or failing" % app_name, "combiner": "OR",
                "documentation": {"content": "Raised when %s stops reporting for 3 hours, or reports a failed check. Open its Diagnostics page." % app_name},
                "conditions": [
                    {"displayName": "no health report for 3 hours", "conditionAbsent": {"filter": flt, "duration": "10800s", "aggregations": agg}},
                    {"displayName": "a check failed", "conditionThreshold": {"filter": flt, "comparison": "COMPARISON_GT", "thresholdValue": 1.5,
                                                                             "duration": "0s", "aggregations": agg}}]}
        st, raw, _ = self.http("POST", base("monitoring") + "/v3/projects/%s/alertPolicies" % self.project(), json.dumps(body).encode(),
                               self._auth({"Content-Type": "application/json"}), 30)
        return json.loads(raw)

    # ------------------------------------------------------------------ Speech-to-Text (API key)
    def recognize(self, wav, lang="en-US", alt_langs=None):
        """Transcribe up to ~55 s of WAV audio. Returns {transcript, confidence, words:[{word, start_s, end_s, confidence}]}."""
        key = self.s.api_key()
        if not key:
            raise GoogleError("no Google API key")
        import io, wave
        with wave.open(io.BytesIO(wav), "rb") as w:
            ch, width, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
            pcm = w.readframes(min(w.getnframes(), int(55 * sr)))
        if width != 2:
            raise GoogleError("Speech-to-Text needs 16-bit audio")
        cfg = {"encoding": "LINEAR16", "sampleRateHertz": sr, "audioChannelCount": ch, "languageCode": lang,
               "enableWordTimeOffsets": True, "enableWordConfidence": True, "enableAutomaticPunctuation": True, "model": "latest_long"}
        if alt_langs:
            cfg["alternativeLanguageCodes"] = alt_langs[:3]
        t0 = time.time()
        try:
            st, raw, _ = self.http("POST", base("speech") + "/v1/speech:recognize", json.dumps({"config": cfg, "audio": {"content": base64.b64encode(pcm).decode()}}).encode(),
                                   {"Content-Type": "application/json", "X-Goog-Api-Key": key}, 90)
            res = json.loads(raw).get("results", [])
            words, text, confs = [], [], []
            for r in res:
                a = (r.get("alternatives") or [{}])[0]
                text.append(a.get("transcript", "").strip())
                if a.get("confidence") is not None:
                    confs.append(a["confidence"])
                for w in a.get("words", []):
                    words.append({"word": w.get("word"), "start_s": float(str(w.get("startTime", "0s")).rstrip("s") or 0),
                                  "end_s": float(str(w.get("endTime", "0s")).rstrip("s") or 0), "confidence": w.get("confidence")})
            out = {"transcript": " ".join(t for t in text if t), "confidence": round(sum(confs) / len(confs), 3) if confs else None,
                   "words": words, "language": (res[0].get("languageCode") if res else lang), "seconds": round(time.time() - t0, 2)}
            self._note("speech", True, t0, "%d words" % len(words))
            return out
        except Exception as e:
            self._note("speech", False, t0, str(e))
            raise

    # ------------------------------------------------------------------ YouTube Data API v3 (API key)
    def youtube_search(self, q, n=10):
        key = self.s.api_key()
        if not key:
            raise GoogleError("no Google API key")
        t0 = time.time()
        try:
            st, raw, _ = self.http("GET", base("youtube") + "/youtube/v3/search?" + urllib.parse.urlencode(
                {"part": "snippet", "type": "video", "q": q, "maxResults": max(1, min(25, int(n))), "order": "relevance"}), None, {"X-Goog-Api-Key": key}, 30)
            ids = [i["id"]["videoId"] for i in json.loads(raw).get("items", []) if i.get("id", {}).get("videoId")]
            out = self.youtube_videos(ids) if ids else []
            self._note("youtube", True, t0, "%d videos" % len(out))
            return out
        except Exception as e:
            self._note("youtube", False, t0, str(e))
            raise

    def youtube_videos(self, ids):
        key = self.s.api_key()
        st, raw, _ = self.http("GET", base("youtube") + "/youtube/v3/videos?" + urllib.parse.urlencode(
            {"part": "snippet,contentDetails,statistics", "id": ",".join(ids)}), None, {"X-Goog-Api-Key": key}, 30)
        out = []
        for v in json.loads(raw).get("items", []):
            sn, cd, sts = v.get("snippet", {}), v.get("contentDetails", {}), v.get("statistics", {})
            out.append({"id": v["id"], "url": "https://www.youtube.com/watch?v=" + v["id"], "title": sn.get("title"), "channel": sn.get("channelTitle"),
                        "channel_id": sn.get("channelId"), "published": sn.get("publishedAt"), "description": (sn.get("description") or "")[:600],
                        "duration": cd.get("duration"), "views": int(sts.get("viewCount", 0) or 0), "captions": cd.get("caption") == "true"})
        return out


def youtube_id(text):
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_\-]{11})", text or "")
    return m.group(1) if m else (text if re.fullmatch(r"[A-Za-z0-9_\-]{11}", text or "") else None)


# ---------------------------------------------------------------------------- one-paste setup (Google Cloud Shell)
# Pasted into Cloud Shell (the >_ button in the Cloud console, already signed in as the user). It uses only Google's
# own command-line tool, changes nothing outside the user's project, can be run again safely (it reuses what exists),
# and prints ONE setup code to paste into a QueryBook application.
SETUP_SCRIPT = r"""set -u
echo "QueryBook — Google setup (safe to run again)"; echo
P=$(gcloud config get-value project 2>/dev/null)
if [ -z "$P" ] || [ "$P" = "(unset)" ]; then P=$(gcloud projects list --format='value(projectId)' --limit=1); fi
if [ -z "$P" ]; then echo "No Google Cloud project found. Create one in the console first."; return 1 2>/dev/null || exit 1; fi
gcloud config set project "$P" >/dev/null 2>&1; echo "1/6 Project: $P"
echo "2/6 Switching on the APIs (about a minute)…"
gcloud services enable texttospeech.googleapis.com speech.googleapis.com youtube.googleapis.com generativelanguage.googleapis.com \
  storage.googleapis.com monitoring.googleapis.com apikeys.googleapis.com iam.googleapis.com >/dev/null
echo "3/6 API key restricted to Text-to-Speech, Speech-to-Text, YouTube and Gemini voices…"
K=$(gcloud services api-keys list --filter='displayName=QueryBook' --format='value(name)' --limit=1 2>/dev/null)
if [ -z "$K" ]; then
  gcloud services api-keys create --display-name=QueryBook --api-target=service=texttospeech.googleapis.com \
    --api-target=service=speech.googleapis.com --api-target=service=youtube.googleapis.com \
    --api-target=service=generativelanguage.googleapis.com >/dev/null 2>&1
  K=$(gcloud services api-keys list --filter='displayName=QueryBook' --format='value(name)' --limit=1)
fi
KEY=$(gcloud services api-keys get-key-string "$K" --format='value(keyString)')
B="querybook-backups-$P"
echo "4/6 Backup bucket gs://$B …"
gcloud storage buckets describe "gs://$B" >/dev/null 2>&1 || gcloud storage buckets create "gs://$B" --uniform-bucket-level-access >/dev/null
SA="querybook-apps@$P.iam.gserviceaccount.com"
echo "5/6 Service account $SA (backups and health reports only)…"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || gcloud iam service-accounts create querybook-apps --display-name="QueryBook apps" >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$B" --member="serviceAccount:$SA" --role=roles/storage.objectAdmin >/dev/null 2>&1
gcloud projects add-iam-policy-binding "$P" --member="serviceAccount:$SA" --role=roles/monitoring.editor --condition=None >/dev/null 2>&1
F=$(mktemp); rm -f "$F"
if ! gcloud iam service-accounts keys create "$F" --iam-account="$SA" >/dev/null 2>&1; then
  echo "   (your organisation does not allow service-account keys — backups to Google and health reports stay off; everything else works)"; F=""
fi
echo "6/6 Your setup code:"; echo
python3 - "$P" "$KEY" "$B" "$F" <<'PY'
import base64, json, os, sys
p, key, b, f = sys.argv[1:5]
sa = json.load(open(f)) if f and os.path.exists(f) else None
code = {"v": 1, "project_id": p, "api_key": key, "bucket": b if sa else "", "service_account": sa}
print("QBSETUP-" + base64.b64encode(json.dumps(code).encode()).decode())
PY
[ -n "$F" ] && rm -f "$F"
echo; echo "Copy the whole line that starts with QBSETUP- and paste it into QueryBook → Diagnostics → Google Cloud → Paste setup code."
echo "It contains your keys — paste it only there."
"""


def decode_setup_code(code):
    """The QBSETUP-… line printed by SETUP_SCRIPT → the settings to save."""
    c = "".join(str(code or "").split())
    i = c.find("QBSETUP-")
    if i < 0:
        raise ValueError("That is not a QueryBook setup code (it starts with QBSETUP-).")
    try:
        d = json.loads(base64.b64decode(c[i + 8:]).decode("utf-8"))
    except Exception:
        raise ValueError("The setup code is incomplete — copy the whole line again.")
    if d.get("v") != 1 or not d.get("api_key"):
        raise ValueError("The setup code has no API key.")
    vals = {"api_key": d["api_key"], "project_id": d.get("project_id") or ""}
    if d.get("service_account"):
        vals.update({"service_account_json": json.dumps(d["service_account"]), "bucket": d.get("bucket") or "", "storage_on": True, "monitoring_on": True})
    return vals
