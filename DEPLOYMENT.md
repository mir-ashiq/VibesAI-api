# Deployment

## Quick start
```bash
pip install -e ".[server]"
export VIBES_META_SESSION="your-cookie"
python -m server  # Open http://localhost:8000/docs
```

## Docker
```bash
export VIBES_META_SESSION="your-cookie"
docker compose up -d
```

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `VIBES_META_SESSION` | **Yes** | vibes.ai `meta_session` cookie value. Grab from DevTools → Application → Cookies → `vibes.ai`. |
| `AUTH_META_COOKIES` | No (recommended) | auth.meta.com cookie string — enables automatic OIDC re-login on session expiry. Grab from DevTools → Application → Cookies → `auth.meta.com`. |
| `VIBES_API_KEY` | No | If set, REST clients must send it as `X-API-Key` (or `Authorization: Bearer`). |
| `VIBES_COOKIE_FILE` | No | File the latest `meta_session` is persisted to and reloaded from on restart (compose wires `/data/.vibes_cookie`). |
| `VIBES_REFRESH_INTERVAL` | No | Keep-alive ping interval in seconds (default `1500` = 25 min). |

> 🍪 **Not sure how to get the cookies?** **[COOKIES.md](COOKIES.md)** walks you through grabbing both `VIBES_META_SESSION` and `AUTH_META_COOKIES` from your browser's DevTools, step by step, with format examples and troubleshooting.

Example with auto re-login armed:

```bash
export VIBES_META_SESSION="e60e910a-242a-....fGg"
export AUTH_META_COOKIES="ps_n=1; ps_l=1; datr=Bxxx...; fs=1; locale=en_GB"
python -m server
```

## Cookie auto-refresh
- Intercepts Set-Cookie headers on every API response (sliding session)
- Background thread calls /api/auth/me every 25 minutes (`VIBES_REFRESH_INTERVAL`)
- Persists to VIBES_COOKIE_FILE for restart survival
- With `AUTH_META_COOKIES` set: a 401 replays the Meta OIDC login chain and mints a fresh `meta_session` automatically (see [COOKIES.md](COOKIES.md))

## Auth
Set VIBES_API_KEY env var. Clients send X-API-Key header.

## Free hosting options
The included `Dockerfile` deploys anywhere containers run:

- **Render** (free tier): Docker deploy, set `VIBES_META_SESSION` (+ `AUTH_META_COOKIES`) as env vars
- **Railway / Fly.io**: same Dockerfile, add a persistent volume mounted at `/data` for `VIBES_COOKIE_FILE`
- **Any VPS**: `docker compose up -d`

For a serverless TypeScript variant (OpenAI-compatible, free on Cloudflare Workers), see the sibling repo **[VibesAI-openai](https://github.com/mir-ashiq/VibesAI-openai)**.
