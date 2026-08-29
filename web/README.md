# web — marketing / waitlist frontend

The public landing + waitlist site for the agent. **Separate deploy target from
the FastAPI backend** — the Python API (`main.py` + `glitch_signal/`) deploys to
FastAPI Cloud off `production`; this `web/` folder is excluded from that bundle
(`.fastapicloudignore`) and ships on its own.

- **Stack:** Next.js 16 (App Router) + Tailwind + shadcn/ui. Scaffolded from
  [`bundui/waitly-nextjs-waitlist-template`](https://github.com/bundui/waitly-nextjs-waitlist-template).
- **Deploy branch:** `web-production` (fast-forwarded from `production`, never
  developed on — same deploy-branch discipline as the API's `production`). Wire a
  Vercel / Cloudflare Pages project to watch `web-production` with root `web/`.
- **Local dev:** `cd web && npm install && npm run dev` → http://localhost:3000.

The waitlist form is client-only today; wiring it to the backend (a brand-scoped
signup endpoint) is a later lane.

## Get Started

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Edit `app/page.tsx` to start.
