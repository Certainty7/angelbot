# Security threat model — Angel bot + static website

Scope: the `angelbot` repository at `master`, its production deployment on the bot host, the website
build inside `website/`, and the CI that produces both.
Method: assets → trust boundaries → threats → controls → residual risk. OWASP ASVS 5.0 is used for
the parts that apply; controls written for authenticated applications are explicitly **not** applied
to a static site that has no authentication, no forms, and no state.

## 1. Assets

| Asset | Where it lives | Why it matters |
|---|---|---|
| Discord bot token | `angelbot/.env` on the bot host, never in git | full control of the bot identity |
| Message archive (`chat_history.db`) | bot host, gitignored | member messages, names, ids |
| Pinned memory (`user_preferences.pinned_facts`, `angel/memory.py`) | member-written, host only | only what the member typed into `/memory pin` |
| AI provider keys (OpenRouter/others) | bot host `.env` | cost and abuse |
| Git push rights | `GITHUB_TOKEN` on the agent host | can rewrite the product |
| Cloudflare account | token held on the agent host, never in git | DNS and hosting control |
| Deploy pipeline | `.github/workflows/*` | code that runs with repo access |
| Published website | CDN, public | brand and factual accuracy |
| Owner identity and persona notes | bot host, private | privacy of the owner |

## 2. Trust boundaries

```
Internet ──▶ Discord gateway ──▶ bot process ──▶ SQLite (host)
   │                                   │
   │                                   └──▶ outbound: AI APIs, media sources, yt-dlp
   └──▶ CDN (static site)  ── no callback into any origin server

GitHub ──▶ Actions runner ──▶ build artifact ──▶ Cloudflare Pages
                                  ▲
                          generator reads bot source (never the reverse)
```

Four boundaries matter: (a) untrusted Discord input into the bot, (b) untrusted URLs the bot fetches,
(c) untrusted pull-request code into CI, (d) untrusted web input into the static site — where the only
server-side processing is the build.

## 3. Threats and controls

| ID | Threat | Control in place | Evidence |
|---|---|---|---|
| T-01 | Prompt injection through member messages steers the AI layer into destructive actions | natural-language actions are gated: moderation paths require explicit confirmation and re-check the invoker's permission at execution time, not only at parse time | `angel/nl_router.py`, `angel/guard.py` |
| T-02 | SSRF from member-supplied media URLs into cloud metadata or loopback | every outbound request goes through `angel/net.py`: strict URL syntax (no userinfo, control chars or non-canonical IPv4), every resolved address must be public, `SafeAsyncResolver` re-checks at connect time, redirects are followed manually with each hop validated, and FFmpeg gets `-protocol_whitelist` | `angel/net.py`, `angel/media.py`, `angel/voice_engine.py` |
| T-03 | Secret leakage into git | `.env`, `*.db`, `cookies.txt`, `venv/`, `backups/`, `stage/` are gitignored; gitleaks reports 0 findings across the full history | `.gitignore` |
| T-04 | Supply-chain compromise of CI | both third-party actions pinned to commit SHAs, `permissions: contents: read` on both workflows, no deploy token in CI | `.github/workflows/checks.yml`, `website.yml` |
| T-05 | Website build leaking private data into `dist/` | the generator reads only command metadata and emits no snowflake ids beyond the public application id; a CI step gates the JSON for host paths and credential shapes | `tools/website-data-generator/`, `website.yml` catalogue job |
| T-06 | Public metrics/status surface exposing internals | no metrics API is part of the website; a legacy status service is disabled and retired (`docs/DECISIONS.md`) | service state on the bot host |
| T-07 | Member data published by mistake | the site publishes no member names, ids, message content or counts; `website/src/data/*.json` is generated from command metadata only | `website/src/data/*.json` scan, `tools/website-data-generator/` |
| T-08 | Privilege escalation inside a guild through role commands | permission re-checked at execution; owner-only commands marked as such in the catalogue copy | `cogs/admin.py`, `descriptions_ar.json` («للمالكة فقط») |
| T-09 | Denial of service by resource exhaustion on a small VM | the unit caps memory and CPU, and `tools/selftest.py` runs as a deploy gate before restart | `deploy/angelbot.service` |
| T-10 | Malicious content served from the CDN | Cloudflare Pages applies `website/public/_headers`: CSP with `frame-ancestors 'none'`, HSTS, `nosniff`, COOP and Permissions-Policy; self-hosted fonts and assets, no third-party scripts | `website/public/_headers`, `docs/WEBSITE_SECURITY.md` |

## 4. Out of scope

- Discord's own platform security.
- The AI providers' internal handling of prompts.
- The hosting providers' hypervisor layers.
- Legal review of the privacy text (flagged for the owner).

## 5. Residual risk that is accepted, not fixed

| Risk | Reason | Mitigation |
|---|---|---|
| `hashlib.md5` used as a content-dedupe key (`angel/media.py:772`) | not a security primitive here; it compares image bytes inside one process | documented, `usedforsecurity=False` is the honest label if the file is next touched |
| Video transcode writes under a private temp dir | fixed: `tempfile.mkdtemp` with mode 0700 per transcode, removed in `finally` | none |
| Bot has 16 Discord permissions including `manage_roles` | functional requirement (autorole, reaction roles) | justified call-site by call-site in `invite.json`; no Administrator |
| The URL guard resolves the name and the HTTP client resolves it again | fixed for aiohttp by `SafeAsyncResolver` (checked at connect); FFmpeg/yt-dlp still resolve on their own, so the host egress firewall remains the second line of defence | keep the RFC1918 egress rule in `09_DEPLOYMENT_AND_OPS.md` |

## 6. What this model does not claim

This is a threat model, not a proof. It lists what was looked for and what was found. Any statement of
"no known unresolved critical or high-severity vulnerability within the tested scope" is bounded by the
tool list, versions and commands in `docs/SECURITY/STATIC_ANALYSIS.md` and `DEPENDENCIES.md`.
