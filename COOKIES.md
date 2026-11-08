# 🍪 Cookies & Authentication Guide

This repo talks to [vibes.ai](https://vibes.ai) using **browser cookies** — vibes.ai has no official API, no API keys, and no OAuth client you can register. Everything authenticates with the session cookies your browser got when you logged in.

There are **two credentials** you may need to supply:

| Variable | Domain it comes from | Required? | What it does |
|---|---|---|---|
| `VIBES_META_SESSION` | `vibes.ai` | **Yes** | Your vibes.ai session (`meta_session` cookie). Authenticates every API call. |
| `AUTH_META_COOKIES` | `auth.meta.com` | No (recommended) | Meta login cookies. Enable **automatic re-login** when the vibes session expires. |

> 📌 **Short version:** `VIBES_META_SESSION` gets you in the door; `AUTH_META_COOKIES` keeps you in when the first one expires.

---

## Part 1 — `VIBES_META_SESSION` (required)

### What it is

vibes.ai authenticates you with a single cookie named `meta_session`. Its value is a long token that looks like:

```
e60e910a-242a-4a5c-9d0c-a41b52d9f8ae.b6XqfLm2RtYw3nKj8vHs5zEe9wQq4rTt7uIi6oPp0aSd1fGg
```

(a UUID, a dot, then a ~40-character signature — one single line, no spaces or quotes).

### How to get it (DevTools — Application tab)

1. Log in at **[vibes.ai](https://vibes.ai)** in Chrome / Edge / Firefox (it currently requires a Meta/Facebook account).
2. Press **F12** (or right-click → *Inspect*) to open DevTools.
3. Go to the **Application** tab (Firefox: **Storage** tab).
4. In the left sidebar expand **Cookies** → click **`https://vibes.ai`**.
5. Find the row named **`meta_session`** in the table.
6. Double-click the **Value** cell, select the whole value, and copy it (Ctrl/Cmd+C).
   <br>⚠️ Copy the **Value** column, not the Name column. The value is one long string — make sure you got all of it (scroll/resize the cell if needed).
7. That string **is** your `VIBES_META_SESSION`.

### Alternative: Network tab (handy if the Application tab hides long values)

1. With vibes.ai open, open DevTools → **Network** tab.
2. Refresh the page (F5), then click any request sent to `vibes.ai/api/...` (e.g. `me` or `projects`).
3. In the request details open **Headers** → **Request Headers** → find the **`Cookie:`** header.
4. Copy just the part after `meta_session=` up to the first `;` (or to the end if it's the last cookie):

   ```
   Cookie: meta_session=e60e910a-242a-....fGg; cookie_ack=true
                        └────────────── copy this part ──────────────┘
   ```

### How to set it

**In Python code:**

```python
from vibes_api import VibesClient

client = VibesClient(meta_session="e60e910a-242a-....fGg")
```

**As an environment variable** (used by the CLI and the FastAPI server):

```bash
export VIBES_META_SESSION="e60e910a-242a-....fGg"   # Linux / macOS
set VIBES_META_SESSION=e60e910a-242a-....fGg        # Windows (cmd)
$env:VIBES_META_SESSION = "e60e910a-242a-....fGg"   # Windows (PowerShell)
```

**In a `.env` file** (gitignored — never commit it):

```bash
# .env — load with your shell, direnv, or python-dotenv before starting the server
VIBES_META_SESSION="e60e910a-242a-....fGg"
AUTH_META_COOKIES="ps_n=1;datr=xxxx...;fs=xxxx...;locale=en_GB;ps_l=1"
```

**On the CLI:**

```bash
vibes-api --cookie "e60e910a-242a-....fGg" me
# or rely on the env var:
vibes-api me
```

**With the FastAPI server:**

```bash
export VIBES_META_SESSION="e60e910a-242a-....fGg"
python -m server          # http://localhost:8000/docs
```

**With Docker:**

```bash
export VIBES_META_SESSION="e60e910a-242a-....fGg"
docker compose up -d
```

---

## Part 2 — `AUTH_META_COOKIES` (optional, enables auto re-login)

### What it is

Your vibes.ai session expires (~30 min idle). The web app silently re-authenticates through Meta's OIDC flow (vibes.ai → auth.meta.com → back). This library can **replay that same flow** — but to do it, it needs your **auth.meta.com cookies** (the Meta login session of the same browser profile).

With `AUTH_META_COOKIES` set, a `401 Unauthorized` triggers an automatic re-login instead of an error, and the fresh `meta_session` is picked up (and persisted via `VIBES_COOKIE_FILE` if configured).

### How to get it (DevTools — Application tab)

1. **Same browser, still logged in to vibes.ai** (the Meta cookies must belong to the same session).
2. Open DevTools (F12) → **Application** tab → **Cookies**.
3. This time click **`https://auth.meta.com`** in the left sidebar.
   <br>*(If you don't see it: visit `https://auth.meta.com` once in that browser, then reopen the tab.)*
4. You'll see several cookies, typically including `ps_n`, `ps_l`, `datr`, `fs`, `locale` (exact set varies by account).
5. Build a single string `name=value` pairs joined by `; ` (semicolon + space), e.g.:

   ```
   ps_n=1; ps_l=1; datr=Bxxxxxxx...; fs=1; locale=en_GB
   ```

   Double-click each **Value** cell to copy it exactly. Watch out — `datr` values are long; make sure the cell is fully selected.

### Easier alternative: Network tab (recommended — one copy-paste)

1. Open vibes.ai, DevTools → **Network** tab.
2. Refresh the page (F5) and let it load.
3. Look for a request whose domain is **`auth.meta.com`** (filter by "auth" if needed — it appears during the login/refresh redirect chain; if nothing shows, log out and back in to vibes.ai while the Network tab records).
4. Click that request → **Headers** → **Request Headers** → **`Cookie:`**.
5. Right-click the cookie header value → **Copy value**. That entire string is exactly what `AUTH_META_COOKIES` wants:

   ```
   Cookie: ps_n=1; ps_l=1; datr=Bxxx...; fs=1; locale=en_GB
           └──────────── copy the whole thing after "Cookie: " ───────────┘
   ```

   Because the library replays your browser's exact `Cookie` header against `auth.meta.com`, the raw header copy is the most reliable format.

### Format rules

- One line, `name=value` pairs separated by `; ` (semicolons).
- **No** `Cookie:` prefix, **no** quotes in the value itself (quotes around the whole string in a shell/.env file are fine).
- If you copied it from a request header, keep it byte-for-byte.

### How to set it

**In Python code:**

```python
from vibes_api import VibesClient

client = VibesClient(
    meta_session="e60e910a-242a-....fGg",
    auth_meta_cookies="ps_n=1; ps_l=1; datr=Bxxx...; fs=1; locale=en_GB",
    auto_relogin=True,          # implied if you use set_auth_meta_cookies()
)

# or later, at runtime:
client.set_auth_meta_cookies("ps_n=1; ps_l=1; datr=Bxxx...; fs=1; locale=en_GB")
```

**As an environment variable** (FastAPI server / CLI / Docker):

```bash
export VIBES_META_SESSION="e60e910a-242a-....fGg"
export AUTH_META_COOKIES="ps_n=1; ps_l=1; datr=Bxxx...; fs=1; locale=en_GB"

python -m server              # auto re-login now armed
docker compose up -d          # docker-compose.yml passes it through
```

Setting `AUTH_META_COOKIES` automatically enables `auto_relogin` in the server.

### How the auto re-login works (what you're enabling)

When a vibes.ai call returns `401`:

1. The client hits `GET /api/meta-oidc/start` on vibes.ai → gets a redirect to `auth.meta.com` (+ a CSRF cookie).
2. It follows that redirect **sending your `AUTH_META_COOKIES` as the Cookie header** → Meta answers with an auth-code redirect (302).
3. It exchanges the code at `auth.meta.ai/ecto` → redirect back to `vibes.ai`.
4. vibes.ai sets a **fresh `meta_session`** cookie → the client swaps it in, retries your original call, and (if `VIBES_COOKIE_FILE` is set) persists the new value to disk.

If Meta's cookies are themselves expired or rate-limited (a `400` from auth.meta.com), the re-login quietly gives up and the normal `401` surfaces — re-grab cookies from the browser then.

---

## Environment variable reference

| Variable | Used by | Default | Purpose |
|---|---|---|---|
| `VIBES_META_SESSION` | CLI, server, Docker | — (required) | vibes.ai `meta_session` cookie value. |
| `AUTH_META_COOKIES` | server, Docker | — (optional) | auth.meta.com cookie string; enables auto re-login. |
| `VIBES_COOKIE_FILE` | server, Docker | — (optional) | File the latest `meta_session` is persisted to / booted from (survives restarts). |
| `VIBES_REFRESH_INTERVAL` | server | `1500` (25 min) | Seconds between keep-alive pings to `/api/auth/me`. |
| `VIBES_API_KEY` | server | — (optional) | If set, REST clients must send it as `X-API-Key` / `Authorization: Bearer`. |

Precedence note: if `VIBES_COOKIE_FILE` exists and is readable, its contents **override** `VIBES_META_SESSION` at server startup (it holds the freshest cookie from the last refresh).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401 Unauthorized` right away | Bad/typo'd `meta_session` | Re-copy from DevTools; watch for truncated values. |
| `401` after ~30 min idle, no `AUTH_META_COOKIES` set | Session expired | Re-grab `meta_session`, or set `AUTH_META_COOKIES` for auto re-login. |
| `401` even with `AUTH_META_COOKIES` set | Meta cookies also expired (re-login got `400`) or auth.meta.com rate-limited | Log in to vibes.ai again in the browser, re-copy **both** credentials. Re-login is retried at most 3× and never hammered. |
| Works locally, fails in Docker | Env var not passed into the container | `docker compose` reads `VIBES_META_SESSION` / `AUTH_META_COOKIES` from your shell — make sure they're exported in the same shell that runs `docker compose up`. |
| Server restarted into `401` | Fresh cookie lost on restart | Set `VIBES_COOKIE_FILE` (compose already wires `/data/.vibes_cookie`). |
| `403 Facebook expired access token` (TTS only) | vibes.ai server-side FB token rotating | Unrelated to your cookies — wait a few minutes and retry. |

## Security notes

- Treat both values as **passwords** — they grant full access to your vibes.ai/Meta session.
- Never commit them. `.env` and `cookies.txt` are already in `.gitignore`; keep it that way.
- Prefer the server's `VIBES_API_KEY` mode when exposing the REST API, so your real cookie never leaves the server.
- Rotate both after sharing anything, and log out of unused sessions via `client.logout()`.
