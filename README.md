# vibes-api

> **Unofficial** Python API client for [vibes.ai](https://vibes.ai/) — Meta's AI video creation studio. Generate videos, images, TTS, lip-sync, and more, all from a Python script or CLI.

This package was built by reverse-engineering the vibes.ai Next.js bundles and observing real network traffic. It is **not** affiliated with, endorsed by, or officially supported by Meta or Vibes.

---

## ⚡ Quick start

```bash
# 1) Install
pip install VibesAI-api

# 2) Set your cookie (full guide: COOKIES.md)
export VIBES_META_SESSION="e60e910a-242a-...-K54E"

# 3) Generate your first video
vibes-api one-shot \
  --prompt "A serene mountain landscape at sunset" \
  --aspect-ratio 16:9 --resolution 720p --variations 4 \
  --download-dir ./out
```

> 🍪 **Where do I get that cookie?** See **[COOKIES.md](COOKIES.md)** — a step-by-step guide (with screenshots-level detail) for grabbing both `VIBES_META_SESSION` (vibes.ai `meta_session` cookie) and `AUTH_META_COOKIES` (auth.meta.com cookies for automatic re-login) from your browser's DevTools.

Or in Python:

```python
from vibes_api import VibesClient, AspectRatio, Resolution

client = VibesClient(meta_session="...")
project = client.create_project(name="My Video")
batch = client.generate_video(
    project_id=project["id"],
    prompt="A serene mountain landscape at sunset",
    aspect_ratio=AspectRatio.LANDSCAPE,
    resolution=Resolution.P720,
    variations=4,
)
client.download_video(batch["content"][0]["id"], "sunset.mp4")
```

---

## 📦 What's inside

### Core capabilities (v1.6.0 — verified against vibes.ai Nov 2026)

| Feature | Method | Notes |
|---|---|---|
| **Auth** | `get_me()`, `get_system_status()`, `logout()` | Cookie-based |
| **Projects** | `list_projects()`, `create_project()`, `get_project()`, `update_project()`, `delete_project()`, `duplicate_project()` | |
| **Video generation (t2v)** | `generate_video()` | text-to-video, 1-4 variations |
| **Image generation (t2i)** | `generate_image()` | synchronous, returns immediately |
| **🎥 Video extend (auto)** | `auto_extend_video()`, `extend_video(prompt=None)` | extends a video by ~5s, no directive |
| **🎥 Video extend (manual)** | `manual_extend_video()`, `extend_video(prompt=...)` | extends with a directive prompt |
| **🎥 Video edit (v2v)** | `edit_video()` | re-render existing video with a directive |
| **🎥 Image animate (auto)** | `auto_animate_image()` | animate a still image with original prompt |
| **🎥 Image animate (manual)** | `manual_animate_image()` | animate with a directive prompt |
| **🔄 Regenerate batch** | `regenerate_batch()` | re-roll with same or new prompt |
| **🖼️ Image editing** | `edit_image()` | prompt-driven edits |
| **✨ Prompt enhancement** | `enhance_prompt()` | returns 4 AI-rewritten variations |
| **🗣️ Lip sync** | `generate_lipsync()` | image + audio + script → video |
| **🔊 TTS** | `tts()`, `list_voices(limit=...)`, `save_tts_audio()` | 41 preset voices |
| **🎭 Start/end frame** | `generate_video(start_frame=..., end_frame=...)`, `build_frame_handle()` | image-to-video with keyframes |
| **🧙 Ingredients (character/style/scene)** | `list_characters()`, `list_styles()`, `list_scenes()`, `create_ingredient()`, `delete_ingredient()`, `update_ingredient()`, `list_ingredient_projects()`, `bulk_delete_ingredients()` | studio ingredient CRUD + project usage + bulk delete |
| **🧙 Ingredient refs in generation** | `ingredients=[...]`, `create_ingredients=[...]` | apply or inline-create |
| **🎨 Moodboards** | `list_moodboards()`, `get_moodboard()`, `create_moodboard()`, `delete_moodboard()` | |
| **⬆️ Uploads** | `upload_image()`, `upload_image_file()`, `upload_video_direct()`, `upload_audio_direct()`, `upload_media()`, `upload_profile_picture()` | |
| **📚 Media library** | `list_media()`, `get_media_item()`, `delete_media_item()`, `list_media_item_projects()`, `favorite_content_item()`, `delete_content_item()`, `delete_content_items()` | favorite is a toggle |
| **⬇️ Download** | `download_video()`, `download_image()` | |
| **🔗 Share links** | `create_share_link()`, `list_share_links()`, `revoke_share_link()` | |
| **🎵 Music library** | `search_music(tab=...)`, `lookup_music_thumbnail()`, `clip_music()`, `clip_audio()`, `check_original_audio()` | trending / original-audio tabs |
| **💬 Timeline chat** | `timeline_chat()` | streaming AI assistant (SSE) |
| **🎬 Timeline export** | `export_timeline()`, `export_timeline_async()`, `check_export_status()`, `cancel_export()`, `get_last_export()`, `get_pending_export()` | render composition → MP4 |
| **🔄 Real-time sync** | `get_sync_status()`, `stream_sync_updates()`, `stream_batch_updates()` | SSE for collaborative editing |
| **🕘 Revision history** | `list_revisions()`, `save_revision()` | session snapshots (new on vibes.ai) |
| **📊 Analytics** | `log_analytics()`, `log_analytics_event()` | UI event tracking |
| **🐞 Bug reports** | `report_bug()`, `record_consent()` | multipart, like the UI dialogs |
| **📊 Quota** | `get_quota_upsell()` | |
| **⚙️ Account settings** | `delete_account()`, `delete_all_media()`, `remove_all_posts()` | |
| **🐛 Bug reports** | `report_bug()`, `record_consent()` | |
| **🤝 Collaborators** | `list_collaborators()`, `remove_collaborator()` | |
| **📦 Project assets** | `list_project_assets()`, `add_project_asset()`, `import_project_assets()`, `list_available_assets()` | cross-project reuse |
| **⏳ Batch polling** | `poll_batch()`, `list_batches()`, `list_project_batches()`, `get_batch()`, `delete_batch()` | |
| **🚀 One-shot** | `create_video_from_prompt()` | end-to-end convenience |

### CLI

The `vibes-api` CLI exposes every feature as a subcommand. Run `vibes-api --help` for the full list.

```bash
# User
vibes-api me

# Projects
vibes-api projects list
vibes-api projects create --name "My Video"
vibes-api projects get <id>
vibes-api projects delete <id> --delete-assets

# Video generation
vibes-api videos generate --project-id <id> --prompt "sunset over ocean" \
  --aspect-ratio 16:9 --resolution 720p --variations 4 --download-dir ./out

# 🆕 Video extend (auto/manual)
vibes-api videos extend --project-id <id> --batch-id <batch> \
  --content-id <content>  # auto-extend (no --prompt)
vibes-api videos extend --project-id <id> --batch-id <batch> \
  --prompt "camera pans up to reveal the sky"  # manual extend

# 🆕 Video edit (v2v)
vibes-api videos edit --project-id <id> --batch-id <batch> \
  --prompt "change the weather to rain"

# Image generation
vibes-api images generate --project-id <id> --prompt "cyberpunk city"

# 🆕 Image animate (auto/manual)
vibes-api images animate --project-id <id> --content-id <content>
vibes-api images animate --project-id <id> --content-id <content> \
  --prompt "camera zooms in slowly"

# 🆕 Batch regenerate (re-roll)
vibes-api batches regenerate <batch-id> --project-id <id>
vibes-api batches regenerate <batch-id> --project-id <id> --prompt "new prompt"

# 🆕 Ingredient CRUD
vibes-api ingredients list [--type CHARACTER|STYLE|SETTING]
vibes-api ingredients create --name "My Character" --type CHARACTER \
  --image-ent-id <id> --image-url <url>
vibes-api ingredients delete <ingredient_id>

# TTS
vibes-api voices list
vibes-api tts --voice play_ai_Marisol --text "Hello world" --out hello.mp3

# Media library
vibes-api media list --type video --limit 10
vibes-api media download --id <id> --out video.mp4
vibes-api media delete --ids <id1> <id2>

# Prompt enhancement
vibes-api prompts enhance --prompt "a cat"

# Share links
vibes-api share create --entity-type project --entity-id <id>
vibes-api share list --entity-type project --entity-id <id>
vibes-api share revoke <share_link_id>

# Batches
vibes-api batches list --project-id <id>
vibes-api batches get <batch_id>
vibes-api batches poll <batch_id> --timeout 180

# Music
vibes-api music search --query "lofi"

# Timeline AI chat
vibes-api chat "add a 5 second sunset clip"

# 🆕 Real-time sync
vibes-api sync status --entity-type project --entity-id <id>
vibes-api sync stream --entity-type project --entity-id <id>  # Ctrl+C to stop

# 🆕 Quota
vibes-api quota

# End-to-end one-shot
vibes-api one-shot --prompt "sunset over ocean" --download-dir ./out
```

---

## 🎬 Generation flow (under the hood)

Vibes uses a **two-step generation pattern**:

```
1) POST /api/generation-batches    → create a batch shell (with client-generated UUID v7)
2) POST /api/generate/videos       → trigger actual generation
3) GET  /api/generation-batches/{id} → poll until isComplete=true
                                     OR  /api/generation-batches/{id}/stream (SSE)
```

The client abstracts this away behind `generate_video()` (which polls by default) and `generate_image()` (which is synchronous).

### Batch IDs are UUID v7 with `batch-` prefix

The server expects batch IDs to be **UUID v7** (timestamp-ordered) prefixed with `batch-` so it can derive the creation time from the high bits AND so that the download endpoint accepts the content IDs. The client generates these internally via `_uuid_v7()`. Special flows use different prefixes:
- `batch-<uuid_v7>` — normal text/image generation
- `extend-<timestamp>-<random>` — video extension
- `image2video-<timestamp>-<random>` — image-to-video (animate)
- `video2video-<timestamp>-<random>` — video-to-video (edit)

### Aspect ratios & resolutions

Only **3 aspect ratios** are supported (verified live):

| Aspect | Image dimensions | Notes |
|---|---|---|
| `1:1` | 1280×1280 | Square |
| `9:16` | 720×1280 | Portrait (UI default) |
| `16:9` | 1280×720 | Landscape |

Resolutions: `480p` (default, faster) and `720p` (slower but higher quality).

### Models

| Type | Default model | Description |
|---|---|---|
| Image | `midjen-base` | Standard image generation |
| Video (t2v / i2v) | `midjen-short` | ~5 second clips |
| **Video extend** | `midjen-extend` | For extending an existing video |
| **Video edit (v2v)** | `midjen-video-edit` | For re-rendering with a directive |
| Lip sync | `lipsync` / `midjen-lipsync-async` | Lip-sync generation |
| Prompt LLM | `gemini-2.5-flash` | Used for prompt enhancement |

### Generation types

| `generationType` | When to use |
|---|---|
| `t2v` | text → video |
| `t2i` | text → image |
| `i2v` | image (start frame) → video |
| `extend` | extend an existing video |
| `v2v` | video → video (re-render with directive) |
| `lipsync` | lip-sync generation |

---

## 🎭 Ingredients (characters, styles, scenes)

Vibes supports three ingredient types:
- **CHARACTER** (UI: "Character") — applies via `orefImageHandle` internally
- **STYLE** (UI: "Style") — applies via `srefImageHandle` internally
- **SETTING** (UI: "Scene") — applies via `settingImageHandles` internally

There are three ways to reference an ingredient in a generation:

```python
from vibes_api import IngredientType
from vibes_api.ingredients import IngredientRef, CreateIngredient

# 1. By existing ingredient ID (from list_ingredients)
character = IngredientRef.by_id(
    ingredient_id="800957099700717",
    ingredient_type=IngredientType.CHARACTER,
    name="Valdrin",
    image_url="https://...",
)

# 2. By uploaded image entity ID (creates a new ingredient on-the-fly)
style = CreateIngredient.by_image_ent_id(
    image_ent_id="1177...",
    ingredient_type=IngredientType.STYLE,
    name="Cyberpunk neon",
    image_url="https://...",
)

# 3. By name only (uses prompt-generated image)
scene = CreateIngredient.by_name(
    ingredient_type=IngredientType.SETTING,
    name="Misty forest at dawn",
)

# Pass them to generate_video
batch = client.generate_video(
    project_id=project["id"],
    prompt="...",
    ingredients=[character],            # goes in `ingredients[]`
    create_ingredients=[style, scene],  # goes in `createIngredients[]`
)
```

You can also CRUD ingredients directly:
- `client.list_characters()`, `list_styles()`, `list_scenes()`
- `client.create_ingredient(name, ingredient_type, source_image_ent_id, ...)`
- `client.delete_ingredient(ingredient_id)`

---

## 🖼️ Start/end frame (image-to-video with keyframes)

Generate a video that interpolates between two keyframes:

```python
# Generate the start frame image
start_resp = client.generate_image(
    project_id=project["id"],
    prompt="a rose in full bloom",
    aspect_ratio="16:9",
)
# Generate the end frame image
end_resp = client.generate_image(
    project_id=project["id"],
    prompt="a withered, dried rose",
    aspect_ratio="16:9",
)

# Build frame handles
start_frame = client.build_frame_handle({
    "mediaEntId": start_resp["data"][0]["imageEntId"],
    "imageUrl": start_resp["data"][0]["url"],
})
end_frame = client.build_frame_handle({
    "mediaEntId": end_resp["data"][0]["imageEntId"],
    "imageUrl": end_resp["data"][0]["url"],
})

# Generate the video with both keyframes
batch = client.generate_video(
    project_id=project["id"],
    prompt="the rose slowly wilts, time-lapse effect",
    start_frame=start_frame,
    end_frame=end_frame,
    aspect_ratio="16:9",
)
```

For a single start frame (i2v without end frame), just omit `end_frame`.

---

## 🎥 Video extend (auto + manual)

The Vibes UI shows "Auto extend" and "Manual extend" buttons next to each generated video. Both call the same backend — the only difference is whether you supply a directive prompt:

```python
# Get a previously-generated video's full content item
batch = client.get_batch("batch-...")
source_video = batch["content"][0]

# AUTO extend: no prompt, server continues original
extended_auto = client.extend_video(
    project_id=project["id"],
    source_video=source_video,
)

# MANUAL extend: provide a directive
extended_manual = client.manual_extend_video(
    project_id=project["id"],
    source_video=source_video,
    prompt="camera pans up to reveal the sky",
)
```

The `source_video` dict must be the full content item (not just an ID) because extend needs the original `videoHandle`, `videoGenEntId`, and `structuredOutput` from the source.

---

## 🔑 Authentication

Vibes uses a single cookie, `meta_session`, for authentication. The cookie value is a UUID session token.

> **Full step-by-step guide with both cookies: [COOKIES.md](COOKIES.md)**

### The two credentials

| Variable | Required | Purpose |
|---|---|---|
| `VIBES_META_SESSION` | **Yes** | Value of the `meta_session` cookie from `vibes.ai` — authenticates every API call. |
| `AUTH_META_COOKIES` | No (recommended) | Cookie string from `auth.meta.com` — enables automatic re-login when the session expires. |

### How to get your cookie (short version)

1. Log in at [vibes.ai](https://vibes.ai) in your browser (currently requires a Meta/Facebook account).
2. Open DevTools (F12) → Application → Cookies → `https://vibes.ai`.
3. Copy the value of `meta_session` (a long string with a UUID format like `e60e910a-...-K54E`).
4. Pass it to the client:

   ```python
   client = VibesClient(meta_session="e60e910a-...")
   ```

   Or via env var:

   ```bash
   export VIBES_META_SESSION="e60e910a-..."
   ```

### Cookie rotation & auto re-login

Cookies **expire** (~30 min idle). The web app refreshes them silently via `/api/auth/me`, and this client does the same. Two layers of protection:

1. **Passive refresh** — `Set-Cookie` headers are intercepted on every response, and a background thread pings `/api/auth/me` every 25 min (on by default).
2. **Active re-login** — set `AUTH_META_COOKIES` (auth.meta.com cookies, DevTools → Application → Cookies → `auth.meta.com`, joined as `name=value; name=value`) and a `401` triggers a full OIDC re-login that mints a brand-new `meta_session` automatically:

   ```python
   client = VibesClient(
       meta_session="e60e910a-...",
       auth_meta_cookies="ps_n=1; ps_l=1; datr=Bxxx...; fs=1; locale=en_GB",
   )
   # or at runtime:
   client.set_auth_meta_cookies("ps_n=1; ps_l=1; datr=Bxxx...; fs=1; locale=en_GB")
   ```

   Server/Docker: `export AUTH_META_COOKIES="..."` — setting it enables auto re-login.

   Grab-and-go details, format rules, and troubleshooting: **[COOKIES.md](COOKIES.md)**.

### TTS-specific limitation

The TTS endpoint (`/api/studio/playai/tts`) depends on a **server-side Facebook access token** that rotates independently of your `meta_session`. If you see `403 Facebook expired access token`, just wait a few minutes and retry. The Vibes backend auto-refreshes this token on its own schedule.

---

## 📡 API endpoint reference

All endpoints are under `https://vibes.ai/api/`. This list was extracted directly from the Next.js JS bundles.

### Auth & system
- `GET  /api/auth/me` — current user
- `POST /api/auth/logout` — invalidate session
- `POST /api/auth/check-token` — token validation
- `GET  /api/system-status` — system status banner
- `POST /api/analytics` — usage analytics (fire-and-forget)
- `POST /api/bug-report` — bug reporting
- `POST /api/consent/record` — cookie consent
- `GET  /api/quota/upsell` — upsell info

### Projects
- `GET    /api/projects` — list (params: `limit`, `offset`, `sort`, `search`)
- `POST   /api/projects` — create
- `GET    /api/projects/{id}` — get
- `PUT    /api/projects/{id}` — update name/composition
- `DELETE /api/projects/{id}?deleteAssets=true` — delete
- `POST   /api/projects/{id}/duplicate` — duplicate
- `POST   /api/projects/{id}/upload` — bulk upload media
- `GET    /api/projects/{id}/batches?limit=6&offset=0` — list batches in project
- `GET    /api/projects/{id}/assets` — list project assets
- `POST   /api/projects/{id}/assets` — add asset
- `POST   /api/projects/{id}/assets/import` — import from another project
- `GET    /api/projects/{id}/assets/available?sourceProjectId={id}` — list importable
- `POST   /api/projects/{id}/timeline/download` — sync export to MP4
- `POST   /api/projects/{id}/timeline/export-surfguard` — start async export
- `GET    /api/projects/{id}/timeline/export/{exportId}/status` — poll export
- `POST   /api/projects/{id}/timeline/export/{exportId}/cancel` — cancel

### Generation batches
- `GET    /api/generation-batches?limit=12&offset=0` — list (optional `projectId`, `type`)
- `POST   /api/generation-batches` — create (body must include client-generated UUID v7 as `id`)
- `GET    /api/generation-batches/{id}` — get full state
- `PUT    /api/generation-batches/{id}` — update
- `DELETE /api/generation-batches/{id}` — delete
- `GET    /api/generation-batches/{id}/stream` — SSE stream of batch updates

### Generation
- `POST /api/generate/videos` — text-to-video, image-to-video, **extend**, **v2v edit**, **image animate** (all via different `type` and `config` values)
- `POST /api/generate/images` — text-to-image (synchronous)
- `POST /api/generate/image-edit` — edit an existing image
- `POST /api/generate/prompts` — prompt enhancement (returns 4 variations)
- `POST /api/animate/generate` — lip sync / animation

### Studio
- `GET    /api/studio/ingredients?ownerFilter=LIBRARY|VIEWER&ingredientType=...` — list ingredients
- `POST   /api/studio/ingredients` — create ingredient
- `DELETE /api/studio/ingredients/{id}` — delete ingredient
- `GET    /api/studio/voices` — list TTS voices
- `POST   /api/studio/playai/tts` — text-to-speech (body: `{text, voice, outputFormat, language?}`)

### Uploads
- `POST /api/upload-image` — base64 image upload (body: `{image: "<base64>"}`)
- `POST /api/upload-media` — multipart form (`file` + `filename`)
- `POST /api/upload-video-direct` — multipart form (`video`)
- `POST /api/upload-audio-direct` — multipart form (`audio`)
- `POST /api/upload-profile-picture` — profile picture

### Media library & content items
- `GET    /api/media-library?limit=50&offset=0&type=&sort=&search=` — list
- `GET    /api/download/video?id={contentItemId}` — download video MP4
- `GET    /api/download/png?id={contentItemId}` — download image PNG
- `GET    /api/download/{type}?id={id}` — generic download
- `POST   /api/content-items/{id}/favorite` — toggle favorite
- `POST   /api/content-items/{id}/retry` — retry failed item
- `POST   /api/content-items/{id}/feedback` — submit feedback
- `DELETE /api/content-items/{id}` — delete one
- `POST   /api/content-items/bulk-delete` — bulk delete (body: `{ids: [...]}`)

### Audio / music
- `GET  /api/meta-music?q=&limit=&cursor=` — search Meta music library
- `GET  /api/meta-music/lookup?id=&title=` — resolve track thumbnail
- `POST /api/meta-music/oa-check` — check original audio status
- `POST /api/media/music/clip` — clip a music track segment
- `POST /api/media/audio/clip` — clip any audio URL
- `GET  /api/proxy-audio` — proxy audio through Vibes CDN
- `GET  /api/resolve-audio-urls` — resolve audio CDN URLs

### Moodboards & playables
- `GET    /api/moodboards` — list
- `POST   /api/moodboards` — create
- `GET    /api/moodboards/{id}` — get
- `DELETE /api/moodboards/{id}` — delete
- `GET    /api/playables` — list playables (currently disabled: `"Playables not enabled"`)

### Timeline AI
- `POST /api/timeline/chat/stream` — streaming SSE chat (body: `{input, instructions, tools?, composition?}`)
  - Event types: `message_delta`, `message_done`, `tool_call`, `tool_response`, `reasoning_delta`, `reasoning_done`, `completed`, `error`
  - Default tools (sent by the client): `generate_image`, `generate_video`, `add_music`, `add_text_overlay`, `update_text_overlay`, `resize_clip`, `move_clip`, `extend_timeline_to`, `delete_clip`, `delete_track`, `split_clip`, `duplicate_clip`, `set_fade`, `set_volume`, `set_speed`, `mute_track`, `rename_track`, `reorder_clips`, `generate_lipsync`, `create_ingredient_from_clip`

### Share & collaborators
- `POST   /api/share-links` — create (body: `{entityType, entityId, expiresAt?, maxUses?}`)
- `GET    /api/share-links?entityType=&entityId=` — list
- `DELETE /api/share-links/{id}` — revoke
- `GET    /api/collaborators?entityType=&entityId=` — list
- `DELETE /api/collaborators/{id}` — remove

### 🆕 Real-time sync (SSE)
- `GET /api/sync?entityType=&entityId=` — get last-updated timestamp
- `GET /api/sync/stream?entityType=&entityId=` — SSE stream of update events (`snapshot`, `update`, `bye`)

### Settings
- `POST /api/settings/delete-account`
- `POST /api/settings/delete-all-media`
- `POST /api/settings/remove-all-posts`

### Meta integration
- `POST /api/meta-graphql` — Meta GraphQL proxy (body: `{doc_id, variables}`)
- `POST /api/meta-oidc/start` — start OIDC flow
- `POST /api/meta-profiles/publish` — publish profile
- `POST /api/revisions` — session revisions

---

## 🧪 Examples

Ten ready-to-run example scripts in [`examples/`](./examples):

1. **`01_generate_video.py`** — end-to-end video generation
2. **`02_images_and_edits.py`** — image generation + editing + media library
3. **`03_tts_and_lipsync.py`** — TTS → upload → lip sync pipeline
4. **`04_prompts_and_chat.py`** — prompt enhancement + timeline AI chat
5. **`05_ingredients.py`** — using saved characters in generations
6. **`06_extend_video.py`** — 🆕 auto-extend and manual-extend a video
7. **`07_ingredients_full.py`** — 🆕 character + style + scene combos
8. **`08_create_ingredient.py`** — 🆕 create a new ingredient via API
9. **`09_start_end_frame.py`** — 🆕 image-to-video with keyframe interpolation
10. **`10_edit_video.py`** — 🆕 video-to-video editing (re-render with directive)

Run any of them with:

```bash
export VIBES_META_SESSION="..."
python /home/z/my-project/download/vibes-api/examples/01_generate_video.py
```

---

## ⚠️ Limitations & caveats

1. **Cookie rotation** — `meta_session` expires. Re-grab from the browser when 401s appear.
2. **TTS backend token** — `/api/studio/playai/tts` depends on a server-side FB token that rotates independently. If you get `403 Facebook expired access token`, wait and retry.
3. **Generation quotas** — Vibes enforces per-user quotas (visible in the UI). Hit it and you'll get `429` or a `GENERATION_FAILED` with quota detail.
4. **No public API** — All endpoints here are private and could change at any time. Pin to a client version if stability matters.
5. **Content IDs for download** — `download_video(id)` expects the format `batch-{uuid}-content-{n}`. The client uses the `batch-` prefix consistently so this works for client-generated batches.
6. **Rate limiting** — Don't hammer the API. The client uses a single `requests.Session`; if you need parallelism, instantiate multiple clients and rotate cookies.
7. **Aspect ratios** — Only `1:1`, `9:16`, `16:9` are supported (server-enforced). Other values return `GENERATION_FAILED`.
8. **Video extend requires full content item** — `extend_video(source_video=...)` needs the full content item dict (from `get_batch()`), not just an ID. The client extracts `videoHandle`, `videoGenEntId`, and `structuredOutput` from it.
9. **v2v edit may fail on old videos** — `edit_video()` requires `videoHandle` metadata which older videos may not have. You'll get a clear error message in that case.
10. **Sentry analytics** — The web app posts to Sentry for error tracking. This client does **not** replicate that (it's noise for API use).

---

## 🛠️ Development

```bash
# Install in editable mode
pip install VibesAI-api

# Run tests (requires VIBES_META_SESSION env var)
pytest

# Build CLI
python -m vibes_api.cli --help
```

### Project layout

```
vibes-api/
├── pyproject.toml
├── README.md
├── QUICKREF.md
├── TEST_RESULTS.md
├── vibes_api/
│   ├── __init__.py       # Public API surface
│   ├── client.py         # VibesClient main implementation (~2400 lines, 87 methods)
│   ├── cli.py            # Argparse-based CLI
│   ├── models.py         # Enums: AspectRatio, Resolution, VideoModel, etc.
│   └── ingredients.py    # Ingredient payload builders
├── examples/
│   ├── 01_generate_video.py
│   ├── 02_images_and_edits.py
│   ├── 03_tts_and_lipsync.py
│   ├── 04_prompts_and_chat.py
│   ├── 05_ingredients.py
│   ├── 06_extend_video.py        # 🆕
│   ├── 07_ingredients_full.py    # 🆕
│   ├── 08_create_ingredient.py   # 🆕
│   ├── 09_start_end_frame.py     # 🆕
│   └── 10_edit_video.py          # 🆕
└── research/
    └── ... (reversing notes, sample responses, screenshots)
```

---

## 📜 License

MIT. This project is **not affiliated with Meta or Vibes**. Use at your own risk; respect Vibes' Terms of Service.
