# Cloud Key Manager

A small local app that replaces the Cloud Console's **APIs & Services → Credentials**
pages. Create, view, copy, rename, restrict, delete and restore Google API keys,
turn APIs on, see per-API traffic, and keep every API key you own (Google,
Anthropic, AWS, anything) in one encrypted vault.

Dependency-free PHP 8.1+ (needs the `curl`, `openssl` and `sodium` extensions,
which most PHP installs already have).

## Start it

```bash
php -S 127.0.0.1:8090 -t key-manager
```

Open <http://127.0.0.1:8090> and:

1. **Create your vault.** Choose a passphrase of 10 or more characters. Everything is
   encrypted with it, and it can't be recovered if you forget it.
2. **Connect Google** (Connection tab). The easiest way:
   - Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install).
   - Run `gcloud auth login` once in a terminal and pick your Google Developer
     account.
   - Choose **Use my Google sign-in** and click **Save & test connection**.
3. Pick a project from the drop-down at the top, and you're in.

## What each tab does

| Tab | What you can do |
| --- | --- |
| 🔑 Google API keys | List keys with plain-English restrictions, **Show key** (copies into your vault), **Edit** (rename, limit to websites, IPs, or Android/iOS apps, limit to chosen APIs), **Delete** (restorable for 30 days), **Restore**, and **Create** new keys. Unrestricted keys are flagged. |
| 📊 APIs & traffic | The Console's *Requests / Errors (%) / Latency median / Latency 95%* table for every enabled API, over the last hour, day, 7 days or 30 days. Turn on another API by name. |
| 🗄️ Vault | Every stored key: Google keys are saved automatically, and you can add keys from any other service. Show, copy, edit, remove. Removing an entry never touches Google. |
| ⚙️ Connection | How the app signs in to Google, your default project, and the vault passphrase. |

If an API the app needs (such as the API Keys API) is turned off in a project,
the page tells you and offers a **Turn it on** button.

## Signing in to Google

Managing keys needs a real Google sign-in. **An API key can't create or change
other keys.** There are three options:

- **Your gcloud sign-in** (recommended). The app runs `gcloud auth print-access-token`
  whenever it needs a token, and can do whatever your account can do.
- **A service account key file**, for unattended use. Give the account the
  *API Keys Admin* and *Service Usage Admin* roles, plus *Monitoring Viewer* for
  the traffic table. The JWT is signed locally and sent only to
  `oauth2.googleapis.com`.
- **A pasted access token** from `gcloud auth print-access-token`. It expires after
  about an hour.

## Security

- The vault is a single file, by default `~/.cloud-key-manager/vault.json`,
  which is outside the web root. Set `KEY_MANAGER_VAULT=/path/vault.json` to put
  it somewhere else.
- The file key comes from your passphrase via Argon2id. Contents are sealed with
  XSalsa20-Poly1305 (libsodium), and the file is written with `0600` permissions
  and atomic replace. A tampered file refuses to open.
- While the vault is unlocked, its key is split between the server session and
  an HttpOnly cookie, so neither half alone opens it. The vault locks itself after
  20 idle minutes, or when you click 🔒 Lock.
- The app only answers requests from `127.0.0.1` / `::1`. To expose it anyway
  (not recommended), set `KEY_MANAGER_ALLOW_REMOTE=1`. Every form is
  CSRF-protected, and pages are sent with a strict Content-Security-Policy and
  `no-store`.
- It is **not** part of the Book Intelligence Studio hosting package, so it
  never gets uploaded to shared hosting.

## Tests

```bash
php key-manager/tests/key-manager-contract.php
```

The tests run offline against a fake Google. They cover vault encryption and
tamper detection, the service-account JWT, request shapes for create, update
and list, operation polling, pagination, disabled-API errors, path-injection
guards, the restrictions round trip, and traffic aggregation.
