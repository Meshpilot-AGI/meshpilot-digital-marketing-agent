# Vendor runbook — Cloudflare (edge + origin hardening)

Cloudflare fronts **meshpilot.app**: the web app, the R2 CDN, and — as of CF-HARDEN
(2026-08-29) — the **API**. It gives us the WAF, DDoS protection, and global rate-limit
edge, plus an origin-lockdown so the FastAPI Cloud origin can't be hit directly on the
sensitive paths. Mirrors the ClauseLens/LeaseLens pattern (SEC #30 / ADR-010). Operating
guide — validate against the Cloudflare dashboard/API when unsure.

## Zone & DNS

- Zone: **`meshpilot.app`** (id `eee851a8a79aa5f84041adf5ae6d6ce7`, Free plan).
- **SSL/TLS mode: `full`** — required for the proxy → FastAPI Cloud origin (CF encrypts to
  the origin without pinning a CF-trusted cert; the origin serves a valid LE cert anyway).
- Proxied (orange-cloud) records:
  - `api.meshpilot.app` → FastAPI Cloud edge (`…custom-d…`) — **proxied** (the API).
  - `meshpilot.app` → CF Pages (`…pages.dev`) — proxied (the web).
  <!-- cdn.meshpilot.app (R2 custom domain on bucket meshpilot-creatives) removed
       2026-08-30 — pre-SaaS binding for serving MUapi-generated media from R2, no
       longer used. Bucket + objects kept; only the custom-domain binding was unbound. -->

- DNS-only (grey) records: mail (MX/privateemail), DKIM/SPF/DMARC TXT, docs (Mintlify),
  verification TXTs. Leave these grey.

## Token

- API token lives in **`~/.cloudflare/Master.env`** on the Mac, exported by `.zshrc` as
  `CLOUDFLARE_API_TOKEN` + `CF_API_TOKEN` (Wrangler/Terraform/flarectl/SDK). Load it:
  `set -a; . ~/.cloudflare/Master.env; set +a`. Never commit or print it.

## Origin lockdown (the key hardening)

Sensitive API paths (`/internal/*`, `/jobs/*`) must be reached **through Cloudflare**;
a direct hit to the FastAPI Cloud origin (bypassing the WAF) is 403'd.

1. **CF Transform Rule** (phase `http_request_late_transform`, entrypoint ruleset) injects
   a shared secret header on the API host — `operation: set`, so a client can't smuggle a
   guessed value through the edge (CF overwrites it):
   ```
   action: rewrite
   headers: { "x-origin-auth": { operation: "set", value: "<secret>" } }
   expression: (http.host eq "api.meshpilot.app")
   ```
2. **App middleware** `OriginAuthMiddleware` (`src/glitch_signal/middleware/originauth.py`)
   requires that header on `/internal` + `/jobs`. **Fail-open**: unset secret ⇒ gate
   disabled (no outage risk). `/healthz` (FastAPI Cloud probes hit the origin directly),
   `/oauth/*` (browser callbacks), and `/media/fetch` (HMAC-signed) are **not** gated.
3. **Secret** = cloud env `ORIGIN_SHARED_SECRET` (global infra secret) — MUST equal the
   Transform Rule value. Set both together; changing one without the other 403s all
   through-CF `/internal` traffic. `origin_auth_header` defaults to `x-origin-auth`.

**Verified 2026-08-29:** through CF `/internal` → 200; direct to
`meshpilot-social-media-agent.fastapicloud.dev/internal` → **403**; both `/healthz` → 200.

## App-level hardening (CF-HARDEN Part A)

`src/glitch_signal/middleware/` (wired in `server.py`, inner→outer):
`SecurityHeaders` (HSTS/nosniff/X-Frame-Options DENY/Referrer-Policy) → CORS →
`TrustedHost` → `RateLimit` (per-IP + global sliding window; CF-aware client IP via
`CF-Connecting-IP`) → `BodySizeLimit` (2 MiB) → `OriginAuth`. Config knobs in `config.py`:
`trusted_hosts`, `cors_allow_origins`, `max_request_body_bytes`, `rate_limit_*`,
`origin_shared_secret`, `origin_auth_header`. The in-app rate limit is a per-instance
speed bump — the **real global enforcer is the CF WAF** now that the API is proxied.

## Common ops (with the token loaded)

```bash
ZID=eee851a8a79aa5f84041adf5ae6d6ce7; RID=c86f3fdd2a583120693b3099933f3017
# toggle API proxy (revert to DNS-only if CF ever breaks the origin):
curl -s -X PATCH "https://api.cloudflare.com/client/v4/zones/$ZID/dns_records/$RID" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -d '{"proxied": false}'   # or true
# view the origin-auth transform rule:
curl -s "https://api.cloudflare.com/client/v4/zones/$ZID/rulesets/phases/http_request_late_transform/entrypoint" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN"
```

## Rollback (nothing-breaks path)

Origin-auth is fail-open, so the safe disable order is: **unset `ORIGIN_SHARED_SECRET`**
(redeploy → gate off) — the app stops requiring the header immediately. Flipping the API
back to DNS-only (`proxied:false`) removes CF from the path entirely. Both are reversible.

## Notes

- FastAPI Cloud **is** fine behind the CF proxy (verified: `cf-ray` present, 200s). The
  proxy flip was done live with an auto-revert-if-broken guard — it stuck.
- Free plan: WAF managed rules are limited vs paid; the origin-auth + app rate-limit +
  body cap are the substantive controls. Upgrade the zone for full WAF/rate-limit rules.
- Config (proxy state, Transform Rule, SSL mode) lives in Cloudflare, **not git** — this
  doc is the source of truth for reproducing it.
