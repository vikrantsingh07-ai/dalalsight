# Deployment: Vercel dashboard + always-on backend

## The short version

| Piece | Where | Why |
|---|---|---|
| Dashboard (`web/`) | **Vercel** | a static React build; fast, free tier, preview deployments |
| Backend (`backend/` + `packages/tradingagents`) | **an always-on server** (VPS or Docker host, ideally in India) | runs a continuous monitor loop, holds WebSocket connections, stores SQLite data, runs 10-minute AI jobs |

The dashboard calls the backend over HTTPS with your access token.

```mermaid
flowchart LR
    U[You in the browser] -->|"https://your-app.vercel.app"| V["Vercel<br/>static dashboard"]
    U -->|"REST + WebSocket, X-Access-Token"| B["Backend server<br/>python -m cc (HTTPS)"]
    B --> NSE[NSE public API] & Y[Yahoo Finance] & O[OpenRouter]
    B --- D[("data/ volume<br/>SQLite")]
```

## Why the backend can't run on Vercel

These points come from Vercel's documentation as of August 2026 (Functions limits, the Python runtime, WebSockets, and
Docker on Vercel).

| The backend needs | Vercel Functions (including container images) |
|---|---|
| A market monitor that runs every 30 s all day | Request-scoped: "each instance takes a request, returns a response, and keeps nothing between calls"; scales to zero after 5 min without traffic; no background processes |
| AI agent runs of about 10 min per analyst | Max duration 300 s on Hobby; 800 s on Pro (1800 s beta) |
| One in-memory event bus pushing to all dashboards over WebSocket | WebSockets are pinned to one function for its max duration; later connections may reach another instance |
| SQLite on disk (signals, alerts, runs, paper orders) | Stateless; state must live in an external database |
| Reliable NSE access | Default region `iad1` (US). NSE's public site often rejects cloud/overseas IPs |

Running the backend there would need a rewrite: an external database and queue, and a separate scheduler for the
monitor. Hosting the backend on an always-on server keeps the code as it is.

---

## Step 1: deploy the backend

Pick **one** option.

### Option A: VPS in India (recommended for NSE data)

Any Ubuntu VPS with 2 GB+ RAM in a Mumbai/Bangalore region.

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv git caddy
git clone https://github.com/vikrantsingh07-ai/dalalsight.git /opt/cc
cd /opt/cc
python3.12 -m venv .venv
.venv/bin/pip install -e packages/tradingagents -e .
cp .env.example .env
```

Edit `/opt/cc/.env`:

```ini
CC_HOST=127.0.0.1            # Caddy in front terminates HTTPS
CC_PORT=8765
CC_DEV_MODE=false
CC_ACCESS_TOKEN=<paste output of: python3 -c "import secrets; print(secrets.token_urlsafe(32))">
CC_CORS_ORIGINS=https://your-app.vercel.app
OPENROUTER_API_KEY=<your key>
TRADINGAGENTS_MARKET=india
```

Run it as a service, `/etc/systemd/system/cc.service`:

```ini
[Unit]
Description=DalalSight
After=network-online.target

[Service]
WorkingDirectory=/opt/cc
ExecStart=/opt/cc/.venv/bin/python -m cc
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

Point a domain (e.g. `api.yourdomain.com`) at the VPS. Caddy provides HTTPS and WebSocket upgrades automatically,
`/etc/caddy/Caddyfile`:

```text
api.yourdomain.com {
    reverse_proxy 127.0.0.1:8765
}
```

```bash
sudo chown -R www-data /opt/cc && sudo systemctl enable --now cc && sudo systemctl reload caddy
curl -H "X-Access-Token: <token>" https://api.yourdomain.com/api/status
```

### Option B: Docker host (Render, Railway, Fly.io, …)

The repository's `Dockerfile` builds the API and the dashboard into one image.

> **Not tested yet:** the image hasn't been built on the development PC because Docker isn't installed there. The first build runs on the host.

1. Create a web service from the GitHub repo using the root `Dockerfile`. Choose an Asia/India region if offered.
2. Environment variables:
   - `CC_ACCESS_TOKEN` (long random), `CC_CORS_ORIGINS=https://your-app.vercel.app`
   - `OPENROUTER_API_KEY`, `TRADINGAGENTS_MARKET=india`
   - Leave `CC_PORT` empty; the platform's `PORT` is used.
3. Attach a **persistent disk at `/app/data`**, otherwise signals, alerts and runs are lost on every deploy.
4. Health check path: `/api/health` (send the token header if the platform allows; otherwise use a TCP check).

The container binds `0.0.0.0` and refuses to start without `CC_ACCESS_TOKEN`.

## Step 2: deploy the dashboard on Vercel

**Dashboard (easiest):**
1. vercel.com → **Add New… → Project** → import `vikrantsingh07-ai/dalalsight`. The repo is private, so allow
   the Vercel GitHub app to access it.
2. **Root Directory:** `web`. The framework (Vite), build command and output come from `web/vercel.json`.
3. **Environment Variables:**
   - `VITE_API_BASE_URL` = `https://api.yourdomain.com` (your backend, no trailing slash)
   - Optional: `VITE_WS_URL` = `wss://api.yourdomain.com/ws`. Only needed if WebSockets use a different host.
4. **Deploy.** Note the URL, e.g. `https://your-app.vercel.app`.

**CLI alternative:**

```bash
npm i -g vercel
cd web
vercel link
vercel env add VITE_API_BASE_URL production
vercel --prod
```

> `VITE_*` values are compiled into public JavaScript. Put **only** the backend URL there, never an API key or the
> access token.

## Step 3: connect them

1. On the backend, set `CC_CORS_ORIGINS` to the exact Vercel URL(s), comma-separated, including any custom domain. Restart.
2. Open the Vercel URL. The first API call returns 401 and the dashboard asks for the **access token**. Paste
   `CC_ACCESS_TOKEN`. It's stored in that browser only.
3. Check **System Health**: API server, database, market data, AI model and WebSocket should be ONLINE.

## Alternative: one server, no Vercel

The backend already serves the built dashboard. With Option A, run `cd web && npm ci && npm run build` on the VPS, or
use the Docker image, which includes `web/dist`. Then open `https://api.yourdomain.com` directly: one URL and no CORS setup.

## Security checklist

- [ ] HTTPS everywhere (Caddy / platform TLS). Never expose port 8765 directly.
- [ ] `CC_ACCESS_TOKEN` is long and random; `CC_DEV_MODE=false`.
- [ ] `CC_CORS_ORIGINS` lists only your dashboard URLs.
- [ ] `LIVE_EXECUTION_ENABLED=false` (live execution is not implemented and stays refused).
- [ ] `.env` is not committed; the OpenRouter key has been rotated if it was ever shared.
- [ ] Back up the `data/` directory or volume.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Browser console: CORS error | `CC_CORS_ORIGINS` must match the dashboard origin exactly (scheme + host, no trailing slash); restart the backend |
| Token prompt keeps coming back | wrong token, or the backend restarted with a different `CC_ACCESS_TOKEN` |
| "Live updates disconnected" | the proxy must allow WebSocket upgrades (Caddy does); check `VITE_API_BASE_URL` / `VITE_WS_URL` |
| "Data unavailable: NSE …" on the server | NSE is rejecting the server's IP; try an Indian region, or add a broker feed adapter |
| Agent runs stop at the daily budget | raise `AI_DAILY_CALL_BUDGET`, or use a paid model |
