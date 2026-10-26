# WorkKit — personal automation hub for a Windows work PC

[![test](https://github.com/smh86278-stack/swbins-kit/actions/workflows/test.yml/badge.svg)](https://github.com/smh86278-stack/swbins-kit/actions/workflows/test.yml)

A self-hosted, tray-resident automation hub that runs repetitive office work on one Windows 10/11 PC.
Company-specific values live in a single `config.local.json`, so the same kit works at any company.
The UI and docs are in Korean — see [README.md](README.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

![Hub home — today's summary, failure banner, automation table](docs/images/ui-hub-light.png)

## What it does

- **Scheduled jobs** without Task Scheduler — recurring mail, folder tidy, backups, site/port/certificate/disk monitors,
  credential-expiry warnings, morning brief. Failures alert via mail, Slack, Teams, Discord, Google Chat or signed webhooks.
- **UI automation** — record or script web (Playwright) and desktop (pywinauto) tasks; trigger on time, interval,
  window appearance (`SetWinEventHook`) or process start. Dry-run mode, failure screenshots, workflows (automations and AI steps in order, with an optional human check), recorded passwords
  are extracted into encrypted secrets automatically.
- **AI integration** — pick Claude Code, Codex, Gemini CLI or local Ollama for "ask in plain words" automation building;
  a read-only MCP server exposes hub status to AI tools; optional mail-based dispatch lets Claude Code work on requests sent from a phone.
- **"My apps"** — build small local web apps/games with AI from 6 templates, verified in a real browser, versioned,
  and exportable as zip / single HTML / exe.

## Architecture in one paragraph

A watchdog launcher (`launcher.py` → `WorkKit.exe`) keeps the tray app alive; the tray process hosts the hub
(`macrohub.py`, stdlib `ThreadingHTTPServer` on `127.0.0.1:8630`, JSON API + SSE). Every automation runs in its own
child process (`runner.py`), long-running services are launched detached and re-adopted after hub restarts (`extsvc.py`),
and user apps are served from a separate port with one browser origin per app (`<id>.localhost:8631`). Phone ↔ PC
communication goes through the company mail server (IMAP/SMTP) instead of a direct connection, which works behind corporate firewalls.

## Security highlights (all in code)

- Every HTTP server binds to `127.0.0.1` only; Host-header check against DNS rebinding.
- Per-start random token required for state-changing requests, embedded only in the served page (never written to disk); Origin check.
- Clickjacking headers (`X-Frame-Options: DENY`, CSP `frame-ancestors 'none'`).
- App isolation via per-app origins, `X-App` header + same-origin API, CSP `connect-src 'self'`, user-granted permissions and hourly limits.
- Secrets encrypted with Windows DPAPI; audit log of who changed what, from where, when (keys only, never values).
- Mail dispatch is off by default, sender allow-list, per-address pass words compared with `hmac.compare_digest`,
  Claude Code `PreToolUse` hooks that fail closed.

## Quick start

```
git clone https://github.com/smh86278-stack/swbins-kit.git
python setup_gui.py                       # or: python setup.py
tools\macro-hub\setup.bat                 # once: creates .venv with Playwright/pywinauto/pystray/Pillow
tools\macro-hub\start_app.bat             # tray icon + http://127.0.0.1:8630/
```

Windows 10/11, Python 3.10+, no admin rights. An offline single-file installer with an embedded Python can be built with `installer/build_installer.py`.

## Tests

```
python -X utf8 -m unittest discover -s tests
powershell -ExecutionPolicy Bypass -File tests\verify.ps1
```

565 tests in 30 files (stdlib `unittest`; fake IMAP/SMTP and a fake Claude CLI — no network, no real mail).
CI runs `tests\verify.ps1` on GitHub Actions `windows-latest` with real-browser tests skipped (`KIT_BROWSER_TESTS=0`).

## License

MIT — [LICENSE](LICENSE). Bundled third-party libraries keep their own licenses (`tools/macro-hub/apps-lib/LICENSE-*.txt`).
