# HeyGen — media provider (avatar / talking-head video, API v3)

Second media engine behind the shared `Engine` protocol (alongside MUapi). Used for
avatar / talking-head video from a script.

## Keys (global infra, FastAPI Cloud secrets)

- `HEYGEN_API_KEY` — the account API key (`sk_V2_…`), sent as `X-Api-Key`. Set as a cloud
  secret + local `.env`.
- `HEYGEN_WEBHOOK_SECRET` — the endpoint signing secret (`whsec_…`) for verifying webhook
  deliveries. **Shown only once**, when the webhook endpoint is created or its secret is
  rotated. Until set, `POST /webhooks/heygen` fails closed (503) — we never trust unverified
  events.

## Engine (`media/generation/engines/heygen.py`)

Async submit→poll, same contract as MUapi:

- submit: `POST https://api.heygen.com/v3/videos` → `{data:{video_id}}`
- poll:   `GET  https://api.heygen.com/v3/videos/{id}` → `{data:{status, video_url}}`

`Engine.generate(model, prompt, *, params)` maps: `model` → `avatar_id`, `prompt` →
`input_text` (script), `params` → merged into the body (`voice_id` is expanded to the nested
`voice` object; `aspect_ratio`, `resolution`, `title`, `callback_id`, … pass through).

Select it per call: `POST /internal/media/generate {recipe, inputs, engine: "heygen"}`
(default engine is `muapi`). Resolve in code via `engines.get_engine("heygen")`.

## Webhook (`POST /webhooks/heygen`)

Registered on HeyGen → `https://api.meshpilot.app/webhooks/heygen`
(endpoint id `903cc106770943118974f87728486f0f`). Not gated by origin-auth (public path) and
exempt from the app rate limiter (provider retries).

Verification (fail-closed): `Heygen-Signature` = hex HMAC-SHA256 of the **raw body** with
`HEYGEN_WEBHOOK_SECRET`; reject if the secret is unset (503), headers missing (400),
`Heygen-Timestamp` older than ~5 min (400), or the signature mismatches (401). Dedup on
`Heygen-Event-Id` (best-effort, per worker), then ack `200` fast. Completion is currently
obtained by the engine's own poll; the receiver verifies + logs and is the hook point for
push-based completion later.

### Managing the endpoint (with the API key)

- list:   `GET  /v3/webhooks/endpoints`
- create: `POST /v3/webhooks/endpoints {url, events}` → returns `secret` (once)
- rotate: `POST /v3/webhooks/endpoints/{id}/rotate-secret` → returns a new `secret`
  (invalidates the old immediately)
