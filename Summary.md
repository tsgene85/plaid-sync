# plaid-sync — Safety & Capability Review

**Review date:** 2026-05-20  
**Workspace:** Local clone at `c:\LCode\plaid-sync`  
**Stated upstream:** [https://github.com/mbafford/plaid-sync](https://github.com/mbafford/plaid-sync) (`origin` remote matches)

## Table of Contents

- [Executive summary](#executive-summary)
- [What this project is](#what-this-project-is)
- [Capability review](#capability-review)
  - [Core workflows](#core-workflows)
  - [Data stored locally](#data-stored-locally)
  - [Network exposure](#network-exposure)
- [Security findings](#security-findings)
  - [Positive indicators](#positive-indicators)
  - [Risks and limitations (expected for this class of tool)](#risks-and-limitations-expected-for-this-class-of-tool)
  - [Code hygiene (not malicious, but worth knowing)](#code-hygiene-not-malicious-but-worth-knowing)
- [Malware / backdoor assessment](#malware--backdoor-assessment)
- [Is it safe to use?](#is-it-safe-to-use)
- [Recommended setup checklist](#recommended-setup-checklist)
- [File map (reviewed)](#file-map-reviewed)
- [References](#references)

---

## Executive summary

**Verdict: Reasonably safe to use for its stated purpose**, assuming you cloned from the legitimate `mbafford/plaid-sync` repository (or a fork you trust), run it in a virtual environment with pinned dependencies, and treat the config file and SQLite database as highly sensitive secrets.

This is a small, readable Python CLI (~12 source files) that talks only to **Plaid’s official API** (via the official `plaid-python` SDK) and stores results **locally**. The review found **no signs of malware, credential exfiltration to unknown endpoints, obfuscated code, or hidden backdoors**. Risk is dominated by **normal operational security** (Plaid access tokens on disk, third-party financial aggregation, and running a short-lived local web server during account linking)—not by suspicious code in this repo.

---

## What this project is

| Aspect | Detail |
|--------|--------|
| **Purpose** | Sync bank/credit card transactions from Plaid into a local **SQLite** database for personal finance workflows (e.g. export to Beancount). |
| **Author / license** | Matthew Bafford; **MIT License** (2023). |
| **Language** | Python 3.7+ (README); core logic in plain modules, not a packaged pip app. |
| **Primary dependency** | `plaid-python>=30.0.0` (official Plaid SDK). |
| **Optional dependency** | `tqdm` (progress bars only). |

---

## Capability review

### Core workflows

1. **Sync (default)** — Cursor-based `/transactions/sync` per linked account; persists transactions, item metadata, and sync cursor in SQLite.
2. **Sync (legacy)** — `--date-range-sync` with `-s` / `-e` date range via `/transactions/get`.
3. **Link new account** — `--link-account 'Friendly Name'` starts a **localhost-only** HTTP server and opens Plaid Link in the browser; exchanges public token for access token and appends to INI config (with timestamped backup).
4. **Refresh credentials** — `--update-account 'Friendly Name'` (README sometimes says `--update`; see quirks below).
5. **Balances (optional)** — `-b` / `--balances` fetches account balances (slower).
6. **Inspect data** — `show_recent.sh` prints the 10 most recent rows from the DB via `sqlite3`.

### Data stored locally

| Location | Contents |
|----------|----------|
| INI config (`config/*.ini`, gitignored) | Plaid `client_id`, `secret`, per-account **`access_token`** (long-lived). |
| SQLite `dbfile` (gitignored) | Full Plaid JSON blobs for transactions, balances, items; sync cursors. |
| Config backups (`*.bkp`) | Copy of config before account add. |

**Not stored by this app:** Bank usernames/passwords. Those are entered only inside **Plaid Link** (iframe to Plaid’s CDN), which is the intended Plaid security model.

### Network exposure

| When | Destination | Notes |
|------|-------------|--------|
| Sync / API calls | Plaid API (`sandbox` or `production` per config) | Via `plaid-python` only. |
| Link / update | `127.0.0.1:4583` | Binds **localhost only**; serves `html/link.html` and accepts `POST /api/success`. |
| Link UI in browser | `https://cdn.plaid.com/link/...` | Official Plaid Link JS. |
| Link UI styling | `https://unpkg.com/sakura.css/...` | Third-party CSS CDN (cosmetic only). |

No analytics, telemetry, or unknown “phone home” URLs were found in the codebase.

---

## Security findings

### Positive indicators

- **Small, auditable codebase** — All behavior is in a handful of Python files; no compiled blobs or minified scripts in-repo.
- **No dangerous patterns** — No `eval`, `exec`, `pickle`, `subprocess` shell-outs, or dynamic imports of untrusted code.
- **SQL parameterization** — `transactionsdb.py` uses `?` placeholders for IDs and dates (good practice).
- **Local Link server** — `webserver.py` listens on `127.0.0.1`, not `0.0.0.0`, limiting exposure to the local machine.
- **Secrets excluded from git** — `.gitignore` covers `config/*.ini`, `*.db`, backups, `.venv`.
- **Official Plaid SDK** — API client is the maintained `plaid-python` package, not hand-rolled HTTP to random hosts.
- **Bank credentials** — Handled by Plaid Link in the browser, not written into this project’s config or DB.

### Risks and limitations (expected for this class of tool)

1. **Plaintext secrets on disk** — `client_id`, `secret`, and per-account `access_token` live in an INI file. Protect file permissions, backups, and cloud sync folders.
2. **Sensitive local database** — Transaction and balance JSON includes merchant names, amounts, account masks, etc.
3. **Trust in Plaid** — Linking grants Plaid (and your configured Plaid app) access to financial data under [Plaid’s terms](https://plaid.com/legal/). This tool does not reduce that trust boundary; it consumes it.
4. **Supply chain during Link** — Browser loads JS/CSS from Plaid CDN and unpkg. Use only when linking; pin or vendor assets if you want stricter control.
5. **No dependency lockfile** — `requirements.txt` only specifies `plaid-python>=30.0.0`. Pin exact versions in your venv for reproducibility (`pip freeze > requirements-lock.txt`).
6. **Local POST handler** — Any process on your machine could POST to `http://127.0.0.1:4583/api/success` while the server is up; impact is limited to completing/shutting down the Link flow, not remote attackers.
7. **`show_recent.sh`** — Passes the DB path to `sqlite3` unquoted; safe if you pass a normal path, but avoid untrusted filenames with shell metacharacters.

### Code hygiene (not malicious, but worth knowing)

- **Debug prints** in `plaidapi.py` (`print(start_date)`, `print(total_transactions)`) during date-range sync.
- **Bare `except`** in `try_get_tqdm()` swallows import errors silently.
- **README vs CLI mismatch** — README shows `--update 'Account'`; implementation uses `--update-account`. Error messages still suggest `--update`.
- **Possible Link integration bug** — `html/link.html` `onSuccess` receives `public_token` but POSTs only `metadata` to `/api/success`, while Python checks `plaid_response["public_token"]`. Linking may fail unless you recover the token manually from the browser (README acknowledges this fallback). Worth verifying after clone before relying on unattended linking.

---

## Malware / backdoor assessment

| Check | Result |
|-------|--------|
| Obfuscated or encoded payloads | None found |
| Unexpected outbound network (beyond Plaid + Link CDNs) | None found |
| Credential harvesting to non-Plaid endpoints | None found |
| Persistence mechanisms (cron, registry, startup) | None |
| Large or unrelated binaries | None in repo |

**Clone integrity:** Verify `git remote -v` points to the repo you intend (e.g. `https://github.com/mbafford/plaid-sync.git`) and compare commit history to GitHub if the download was a ZIP without `.git`.

---

## Is it safe to use?

**Yes, with standard precautions**, if you want a self-hosted Plaid → SQLite sync for personal finance:

1. Confirm **provenance** (official repo or trusted fork).
2. Use a **Python venv** and **pin** `plaid-python` (and optional `tqdm`).
3. Start in **Plaid Sandbox** (`config/sandbox.example`) before production keys.
4. Lock down **config and `.db` files** (permissions, no public sync, encrypted disk if needed).
5. Understand you are trusting **Plaid** and storing **long-lived access tokens** locally.
6. Run Link only when needed; the local server is temporary and localhost-bound.

This is **not** a audited security product, hosted service, or enterprise-grade secret manager. It is a personal utility script collection suitable for a technical user who accepts those tradeoffs.

---

## Recommended setup checklist

- [ ] `python -m venv .venv` and activate
- [ ] `pip install -r requirements.txt` (optionally `pip install tqdm`)
- [ ] Copy `config/sandbox.example` → `config/sandbox` (or your path); add Plaid sandbox credentials from [Plaid Dashboard](https://dashboard.plaid.com/)
- [ ] Sandbox link: `python plaid-sync.py -c config/sandbox --link-account 'Test'`
- [ ] Sandbox sync: `python plaid-sync.py -c config/sandbox -v`
- [ ] Only move to `environment = production` after sandbox behavior is understood
- [ ] Back up config and DB; never commit them to git

---

## File map (reviewed)

| File | Role |
|------|------|
| `plaid-sync.py` | CLI entry, sync orchestration, link/update flows |
| `plaidapi.py` | Plaid API wrapper (tokens, sync, balances) |
| `transactionsdb.py` | SQLite schema and persistence |
| `config.py` | INI config read/write and account sections |
| `webserver.py` | Localhost HTTP server for Plaid Link callback |
| `html/link.html` | Plaid Link UI |
| `show_recent.sh` | Quick DB inspection helper |
| `requirements.txt` | Python dependencies |

---

## References

- Upstream README: [README.md](README.md)
- Plaid API docs: [https://plaid.com/docs/api/](https://plaid.com/docs/api/)
- Plaid Link: [https://plaid.com/docs/link/](https://plaid.com/docs/link/)
