# Feature Matrix — vibes.ai vs vibes-api

This document compares every feature exposed by the vibes.ai web UI
against what our `vibes-api` Python client currently supports. Use this
as the backlog for v1.2.0 and beyond.

> Legend:
> - ✅ **Implemented** — fully working in `vibes-api`
> - 🟡 **Partial** — basic version exists, but missing options or polish
> - ❌ **Missing** — vibes.ai has it, we don't
> - ⚪ **N/A** — not applicable for an API client (UI-only feature)

---

---

## 0. Live-site audit — November 2026 (v1.6.0)

A full logged-in walkthrough of vibes.ai (plus static analysis of all 31
production JS chunks) produced a complete inventory of **78 API routes**.
Result: 70 were already covered by this client. The remaining 8 plus
several payload corrections shipped in **v1.6.0**:

| Route / behavior | Method | Status |
|---|---|---|
| `GET /api/revisions?entityType&entityId` | `list_revisions()` | ✅ new in 1.6.0 |
| `POST /api/revisions` (session snapshot) | `save_revision()` | ✅ new in 1.6.0 |
| `GET /api/media-library/{id}` | `get_media_item()` | ✅ new in 1.6.0 |
| `DELETE /api/media-library/{id}` | `delete_media_item()` | ✅ new in 1.6.0 |
| `GET /api/media-library/{id}/projects` | `list_media_item_projects()` | ✅ new in 1.6.0 |
| `GET /api/studio/ingredients/{id}/projects` | `list_ingredient_projects()` | ✅ new in 1.6.0 |
| `POST /api/studio/ingredients/bulk-delete` | `bulk_delete_ingredients()` | ✅ new in 1.6.0 |
| `POST /api/analytics` | `log_analytics()` / `log_analytics_event()` | ✅ new in 1.6.0 |
| `GET /api/projects/{id}/timeline/export` | `get_last_export()` | ✅ new in 1.6.0 |
| `mg_request_id` + `projectId` on all `/api/generate/*` | all generate methods | ✅ fixed in 1.6.0 |
| `POST /api/content-items/{id}/favorite` (toggle, no body) | `favorite_content_item()` | ✅ fixed in 1.6.0 |
| Settings deletions use `DELETE` | `delete_account()` etc. | ✅ fixed in 1.6.0 |
| `upload-profile-picture` is multipart (`file`) | `upload_profile_picture()` | ✅ fixed in 1.6.0 |
| `bug-report` is multipart form | `report_bug()` | ✅ fixed in 1.6.0 |
| `meta-music` `tab` param (popular/original) | `search_music(tab=...)` | ✅ fixed in 1.6.0 |
| `studio/voices` `limit` param | `list_voices(limit=...)` | ✅ fixed in 1.6.0 |
| Timeline clip/track IDs use base36 suffix | `Composition` | ✅ aligned in 1.6.0 |

Known server-side quirks (not client bugs, verified Nov 2026):

- `POST /api/studio/playai/tts` intermittently returns
  `502 {"error":"TTS error: 403 Facebook expired access token"}` — the
  upstream Facebook token rotates; retry after a few minutes.
- `GET /api/sync/stream` currently returns 500 from vibes.ai; the web app
  falls back to polling `GET /api/sync`. `stream_sync_updates_resilient()`
  already implements the same fallback.
- `/api/playables` returns `403 {"error":"Playables not enabled"}` for
  accounts without the playables feature flag.

---

## 1. Authentication & Account

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Meta OIDC login (browser redirect) | ✅ | ⚪ | N/A | Browser-only; we use cookie auth |
| Cookie-based session (`meta_session`) | ✅ | ✅ | ✅ | |
| Get current user (`/api/auth/me`) | ✅ | ✅ | ✅ | `get_me()` |
| Logout (`/api/auth/logout`) | ✅ | ✅ | ✅ | `logout()` |
| Token validation (`/api/auth/check-token`) | ✅ | ❌ | ❌ | Not exposed; trivial to add |
| Cookie consent (`/api/consent/record`) | ✅ | ✅ | ✅ | `record_consent()` |
| System status banner | ✅ | ✅ | ✅ | `get_system_status()` |
| Account deletion | ✅ | ✅ | ✅ | `delete_account()` |
| Delete all media | ✅ | ✅ | ✅ | `delete_all_media()` |
| Remove all public posts | ✅ | ✅ | ✅ | `remove_all_posts()` |
| Profile picture upload | ✅ | ✅ | ✅ | `upload_profile_picture()` / `_file()` |
| Username editing | ✅ | ❌ | ❌ | No endpoint found — uses Meta profile |
| Account status (active/disabled/pending) | ✅ | 🟡 | 🟡 | Returned by `get_me()` but no dedicated check |
| Teen Safety Settings | ✅ | ❌ | ❌ | Meta-side feature; via `/api/meta-graphql` |
| Family Center | ✅ | ❌ | ❌ | Meta-side feature; via `/api/meta-graphql` |
| Accounts Center | ✅ | ❌ | ❌ | Meta-side feature; via `/api/meta-graphql` |

---

## 2. Projects

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| List projects | ✅ | ✅ | ✅ | `list_projects(limit, offset, sort, search)` |
| Create project | ✅ | ✅ | ✅ | `create_project(name, composition)` |
| Get project | ✅ | ✅ | ✅ | `get_project(id)` |
| Update project (name/composition) | ✅ | ✅ | ✅ | `update_project(id, name, composition)` |
| Delete project | ✅ | ✅ | ✅ | `delete_project(id, delete_assets)` |
| Duplicate project | ✅ | ✅ | ✅ | `duplicate_project(id)` |
| Save composition | ✅ | ✅ | ✅ | `save_composition(id, composition)` |
| Bulk upload media to project | ✅ | ❌ | ❌ | `POST /api/projects/{id}/upload` not exposed |
| Sort by newest/oldest | ✅ | ✅ | ✅ | via `sort` param |
| Search projects by name | ✅ | ✅ | ✅ | via `search` param |
| Project name validation (255 char max) | ✅ | ❌ | ❌ | Client-side validation missing |
| Auto-save (debounced) | ✅ | ⚪ | N/A | UI-only convenience |
| Unsaved-changes warning | ✅ | ⚪ | N/A | UI-only |
| Collaborative editing indicators | ✅ | 🟡 | 🟡 | We have `stream_sync_updates()` but no conflict-resolution logic |

---

## 3. Video Generation (t2v)

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Text-to-video (t2v) | ✅ | ✅ | ✅ | `generate_video()` |
| Aspect ratios: 1:1, 9:16, 16:9 | ✅ | ✅ | ✅ | Server-enforced — only these 3 |
| Resolutions: 480p, 720p | ✅ | ✅ | ✅ | "Advanced" panel in UI |
| 1-4 variations per generation | ✅ | ✅ | ✅ | via `variations` param |
| Models: midjen-short | ✅ | ✅ | ✅ | Default |
| Prompt model: gemini-2.5-flash | ✅ | ✅ | ✅ | |
| Prompt length validation (10k char) | ✅ | ❌ | ❌ | No client-side check |
| Batch variation mode | ✅ | ✅ | ✅ | `batchVariation: True` in config |
| Direct generation mode | ✅ | ✅ | ✅ | `directGeneration: True` |
| Polling with retry on transient 500 | ✅ | ✅ | ✅ | `poll_batch(max_retries=3)` |
| SSE batch streaming (alternative to polling) | ✅ | ✅ | ✅ | `stream_batch_updates()` |

---

## 4. Image Generation (t2i)

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Text-to-image (t2i) | ✅ | ✅ | ✅ | `generate_image()` |
| Synchronous response (no polling) | ✅ | ✅ | ✅ | |
| Aspect ratios: 1:1, 9:16, 16:9 | ✅ | ✅ | ✅ | |
| 1-4 variations | ✅ | ✅ | ✅ | |
| Dimensions returned (e.g., 1280x720) | ✅ | ✅ | ✅ | In response |
| sref/oref values returned | ✅ | ✅ | ✅ | In response |
| Image model: midjen-base | ✅ | ✅ | ✅ | |

---

## 5. 🆕 Video Extend (auto + manual) — v1.1.0

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Auto extend (no prompt) | ✅ | ✅ | ✅ | `auto_extend_video()` |
| Manual extend (with directive) | ✅ | ✅ | ✅ | `manual_extend_video(prompt=...)` |
| Model: midjen-extend | ✅ | ✅ | ✅ | Auto-selected by `extend_video()` |
| Source video handle extraction | ✅ | ✅ | ✅ | From `videoHandle` + `data.videoGenEntId` |
| Source video URL carry-over | ✅ | ✅ | ✅ | |
| Audio source carry-over (for lipsync extend) | ✅ | ✅ | ✅ | `audioSourceEntId` |
| Reuse original audio flag | ✅ | 🟡 | 🟡 | Auto-detected from source; not configurable |
| ExtendDirective in input body | ✅ | ✅ | ✅ | |
| Batch ID format `extend-{ts}-{rand}` | ✅ | ✅ | ✅ | |
| sourceContentItemIds tracking | ✅ | ✅ | ✅ | `[{id, source: "extend_video"}]` |

---

## 6. 🆕 Video-to-Video Edit (v2v) — v1.1.0

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Video-to-video edit with prompt | ✅ | ✅ | ✅ | `edit_video()` |
| Model: midjen-video-edit | ✅ | ✅ | ✅ | Auto-selected |
| editType: "v2v" | ✅ | ✅ | ✅ | |
| generationType: "v2v" | ✅ | ✅ | ✅ | |
| Start frame carry-over | ✅ | ✅ | ✅ | From `directPromptImageHandle` |
| Strip end frame / loop fields | ✅ | ✅ | ✅ | |
| Studio composition exports rejected | ✅ | ❌ | ❌ | No client-side check (server enforces) |
| Batch ID format `video2video-{ts}-{rand}` | ✅ | ✅ | ✅ | |

---

## 7. 🆕 Image-to-Video Animate (auto + manual) — v1.1.0

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Auto animate (no prompt) | ✅ | ✅ | ✅ | `auto_animate_image()` |
| Manual animate (with directive) | ✅ | ✅ | ✅ | `manual_animate_image(prompt=...)` |
| Model: midjen-short | ✅ | ✅ | ✅ | |
| generationType: "i2v" | ✅ | ✅ | ✅ | |
| animateDirective in input body | ✅ | ✅ | ✅ | |
| Source image handle extraction | ✅ | ✅ | ✅ | From `imageHandle` / `directPromptImageHandle` |
| Batch ID format `image2video-{ts}-{rand}` | ✅ | ✅ | ✅ | |

---

## 8. 🆕 Start/End Frame (image-to-video with keyframes) — v1.1.0

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Add start frame (uploaded image) | ✅ | ✅ | ✅ | `start_frame=` param + `build_frame_handle()` |
| Add end frame | ✅ | ✅ | ✅ | `end_frame=` param |
| Start frame from media library | ✅ | 🟡 | 🟡 | Need to fetch content item first; no shortcut |
| Start frame from another project | ✅ | ❌ | ❌ | No "Add from projects" shortcut |
| End frame from media library | ✅ | 🟡 | 🟡 | Same as above |
| Remove start/end frame | ✅ | ⚪ | N/A | Just omit the param |
| Start frame preview | ✅ | ⚪ | N/A | UI-only |
| End frame preview | ✅ | ⚪ | N/A | UI-only |
| Cannot use frames with ingredients | ✅ | ❌ | ❌ | No client-side guard (server enforces) |
| Aspect ratio determined by first frame | ✅ | ❌ | ❌ | No client-side note |

---

## 9. 🆕 Batch Regeneration (re-roll) — v1.1.0

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Regenerate with original prompt | ✅ | ✅ | ✅ | `regenerate_batch(prompt=None)` |
| Regenerate with new prompt | ✅ | ✅ | ✅ | `regenerate_batch(prompt=...)` |
| Reuse original config | ✅ | ✅ | ✅ | |
| Strips sourceContentItemIds | ✅ | ✅ | ✅ | |
| Retry individual failed content item | ✅ | ✅ | ✅ | `retry_content_item(id)` |

---

## 10. 🆕 Ingredients (Character / Style / Scene) — v1.1.0

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| List ingredients (LIBRARY or VIEWER) | ✅ | ✅ | ✅ | `list_ingredients(owner_filter)` |
| Filter by type (CHARACTER/STYLE/SETTING) | ✅ | ✅ | ✅ | `list_characters()`, `list_styles()`, `list_scenes()` |
| Apply existing ingredient (by ID) | ✅ | ✅ | ✅ | `IngredientRef.by_id()` |
| Apply ingredient by uploaded image | ✅ | ✅ | ✅ | `CreateIngredient.by_image_ent_id()` |
| Apply ingredient by name only | ✅ | ✅ | ✅ | `CreateIngredient.by_name()` |
| Combine character + style + scene | ✅ | ✅ | ✅ | `build_ingredient_payload()` |
| Create ingredient via API | ✅ | ✅ | ✅ | `create_ingredient(name, type, ...)` |
| Delete ingredient | ✅ | ✅ | ✅ | `delete_ingredient(id)` |
| Character description fields (personality, backstory, core beliefs) | ✅ | ✅ | ✅ | All optional params on `create_ingredient()` |
| Auto-fill description via LLM | ✅ | ❌ | ❌ | UI uses LLM to write backstory; we don't |
| Ingredient pills in prompt (prompt segments) | ✅ | 🟡 | 🟡 | Sent in `promptSegments` field; no builder helper |
| Create ingredient from timeline clip | ✅ | ❌ | ❌ | No `create_ingredient_from_clip()` method (chat-only tool) |
| "Create new characters from your projects" UI flow | ✅ | ❌ | ❌ | No equivalent bulk-create |
| Ingredient scope selector (mine vs library) | ✅ | ✅ | ✅ | via `owner_filter` |
| Update ingredient | ✅ | ❌ | ❌ | Endpoint not found in JS bundles (uses GraphQL) |
| Ingredient image fallback icons | ✅ | ⚪ | N/A | UI-only |
| srefValues / orefValues parsing | ✅ | ❌ | ❌ | No parser for these Midjourney-style strings |

---

## 11. Moodboards (Style References)

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| List moodboards | ✅ | ✅ | ✅ | `list_moodboards()` |
| Get moodboard | ✅ | ✅ | ✅ | `get_moodboard(id)` |
| Create moodboard | ✅ | ✅ | ✅ | `create_moodboard(name, code, images)` |
| Delete moodboard | ✅ | ✅ | ✅ | `delete_moodboard(id)` |
| **Update moodboard (PATCH)** | ✅ | ❌ | ❌ | `PATCH /api/moodboards/{id}` not exposed |
| Add images to moodboard | ✅ | ❌ | ❌ | via PATCH; not exposed |
| Remove images from moodboard | ✅ | ❌ | ❌ | via PATCH; not exposed |
| Apply moodboard to generation | ✅ | ✅ | ✅ | `generate_video(moodboard=...)` |
| Moodboard lookup by code | ✅ | ❌ | ❌ | UI uses `e9()` helper; we don't expose |
| Moodboard thumbnail URL | ✅ | ✅ | ✅ | In `moodboard_thumbnail_url` field |
| Moodboard selector modal | ✅ | ⚪ | N/A | UI-only |

---

## 12. Image Editing

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Prompt-driven image edit | ✅ | ✅ | ✅ | `edit_image(source_image_ent_id, edit_prompt)` |
| Edit creates new content item | ✅ | ✅ | ✅ | Returns `contentItem` |
| Source image ent ID required | ✅ | ✅ | ✅ | |
| "Edit image" button on gallery | ✅ | ⚪ | N/A | UI-only |

---

## 13. Prompt Enhancement

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Generate 4 prompt variations | ✅ | ✅ | ✅ | `enhance_prompt(prompt)` |
| Each variation has image + video prompt | ✅ | ✅ | ✅ | |
| Batch type filter (videos/images) | ✅ | ✅ | ✅ | `batch_type=` param |
| Midjourney-style params (--ar, --v, etc.) | ✅ | ❌ | ❌ | We pass through but don't parse |
| Random sref support | ✅ | ❌ | ❌ | `--sref random` not specially handled |
| sref_weight, oref_weight, chaos, stylize | ✅ | ❌ | ❌ | Advanced Midjourney params not exposed |

---

## 14. Lip Sync / Animation

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Lip sync from image + script + audio | ✅ | ✅ | ✅ | `generate_lipsync()` |
| TTS audio pipeline | ✅ | ✅ | ✅ | `tts()` + `upload_audio_direct()` + `generate_lipsync()` |
| HeyGen avatar animation | ✅ | ❌ | ❌ | `heygen-avatar-iv` model not exposed |
| Avatar lipsync (midjen-lipsync variants) | ✅ | 🟡 | 🟡 | Models in enum; no dedicated method |
| Sync to voice (audio-driven lipsync) | ✅ | ❌ | ❌ | Different from script-driven; not exposed |
| Custom motion prompt | ✅ | ✅ | ✅ | `custom_motion_prompt=` param |
| Music track attached | ✅ | ✅ | ✅ | `music_track=` param |
| Aspect ratio | ✅ | ✅ | ✅ | |
| Video orientation (portrait/landscape) | ✅ | ✅ | ✅ | Auto-derived from aspect ratio |
| Reuse original audio | ✅ | 🟡 | 🟡 | Detected but not configurable |
| Regenerate lip sync with same audio | ✅ | ❌ | ❌ | No `regenerate_lipsync()` method |
| Lipsync direct mode (midjen-lipsync-direct) | ✅ | ❌ | ❌ | Not exposed as separate method |

---

## 15. Text-to-Speech (TTS)

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| List 41 preset voices | ✅ | ✅ | ✅ | `list_voices()` |
| Synthesize speech | ✅ | ✅ | ✅ | `tts(text, voice)` |
| Save audio to file | ✅ | ✅ | ✅ | `save_tts_audio()` |
| Output format (mp3) | ✅ | ✅ | ✅ | |
| Language selection | ✅ | ✅ | ✅ | `language=` param |
| Voice search/filter | ✅ | ⚪ | N/A | Client can filter locally |
| Voice preview playback | ✅ | ⚪ | N/A | UI-only |
| Server-side FB token (rotates) | ✅ | 🟡 | 🟡 | Documented; no auto-retry |

---

## 16. Uploads

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| **Image upload (base64)** | ✅ | ✅ | ✅ | `upload_image(b64)` |
| **Image upload from file** | ✅ | ✅ | ✅ | `upload_image_file(path)` |
| Video upload (multipart) | ✅ | ✅ | ✅ | `upload_video_direct(path)` |
| Audio upload (multipart) | ✅ | ✅ | ✅ | `upload_audio_direct(path)` |
| Generic media upload (multipart) | ✅ | ✅ | ✅ | `upload_media(path)` |
| Profile picture upload | ✅ | ✅ | ✅ | `upload_profile_picture()` |
| **Resumable upload (rupload)** for large files | ✅ | ❌ | ❌ | Not exposed; useful for >50MB files |
| Image size validation (max 10MB, ≤4096px) | ✅ | ❌ | ❌ | No client-side check |
| Auto-resize/re-encode large images | ✅ | ❌ | ❌ | UI does canvas resize; we don't |
| PNG/JPG/WebP accepted | ✅ | ❌ | ❌ | No type check |
| Multi-file upload (up to 12) | ✅ | ❌ | ❌ | No batch upload helper |
| Bulk upload to project (`/api/projects/{id}/upload`) | ✅ | ❌ | ❌ | Endpoint not exposed |

---

## 17. Media Library

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| List media (paginated) | ✅ | ✅ | ✅ | `list_media(limit, offset)` |
| Filter by type (video/image/audio) | ✅ | ✅ | ✅ | `type=` param |
| Sort by newest | ✅ | ✅ | ✅ | `sort=` param |
| Search by prompt | ✅ | ✅ | ✅ | `search=` param |
| Favorite / unfavorite | ✅ | ✅ | ✅ | `favorite_content_item(id, bool)` |
| Delete single item | ✅ | ✅ | ✅ | `delete_content_item(id)` |
| Bulk delete | ✅ | ✅ | ✅ | `delete_content_items([ids])` |
| Retry failed item | ✅ | ✅ | ✅ | `retry_content_item(id)` |
| Submit feedback on item | ✅ | ✅ | ✅ | `feedback_content_item(id, data)` |
| Grid view / Row view | ✅ | ⚪ | N/A | UI-only |
| Show favorites only | ✅ | ⚪ | N/A | Client can filter locally |
| Multiselect mode | ✅ | ⚪ | N/A | UI-only |
| Filter by ingredient (created-with) | ✅ | ❌ | ❌ | Not exposed |

---

## 18. Downloads

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Download video as MP4 | ✅ | ✅ | ✅ | `download_video(id, path)` |
| Download image as PNG | ✅ | ✅ | ✅ | `download_image(id, path)` |
| Generic download (`/api/download/{type}`) | ✅ | ❌ | ❌ | Only video/png exposed |
| Streaming download (large files) | ✅ | ✅ | ✅ | Uses `iter_content(64KB)` |
| Filename from Content-Disposition | ✅ | ❌ | ❌ | We use provided path; don't parse |

---

## 19. Generation Batches

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| List batches (workspace-wide) | ✅ | ✅ | ✅ | `list_batches()` |
| List batches in a project | ✅ | ✅ | ✅ | `list_project_batches(id)` |
| Get batch by ID | ✅ | ✅ | ✅ | `get_batch(id)` |
| Delete batch | ✅ | ✅ | ✅ | `delete_batch(id)` |
| Update batch (PUT) | ✅ | ❌ | ❌ | Not exposed (used internally by UI for optimistic updates) |
| Poll until complete | ✅ | ✅ | ✅ | `poll_batch(id, timeout)` with retry |
| Stream batch updates (SSE) | ✅ | ✅ | ✅ | `stream_batch_updates(id)` |
| Filter by type | ✅ | ✅ | ✅ | `type=` param |

---

## 20. Share Links

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Create share link | ✅ | ✅ | ✅ | `create_share_link(type, id, expires_at?, max_uses?)` |
| List share links for entity | ✅ | ✅ | ✅ | `list_share_links(type, id)` |
| Revoke share link | ✅ | ✅ | ✅ | `revoke_share_link(id)` |
| Reset share link (revoke + create new) | ✅ | ❌ | ❌ | No `reset_share_link()` convenience method |
| Expiration time | ✅ | ✅ | ✅ | `expires_at` param |
| Max uses | ✅ | ✅ | ✅ | `max_uses` param |
| Copy link to clipboard | ✅ | ⚪ | N/A | UI-only |

---

## 21. Collaborators

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| List collaborators | ✅ | ✅ | ✅ | `list_collaborators(type, id)` |
| Remove collaborator | ✅ | ✅ | ✅ | `remove_collaborator(id)` |
| Add collaborator (via share link) | ✅ | ⚪ | N/A | No direct add — invite flow only |
| Owner identification | ✅ | ✅ | ✅ | `isOwner` in response |
| Invite via link | ✅ | ⚪ | N/A | UI flow only |

---

## 22. Timeline Composition (Client-Side Operations)

These operations are done **client-side** in the web app (they manipulate
the composition JSON before saving). Our client doesn't have dedicated
methods for these — you'd manipulate the composition dict directly and
call `save_composition()`.

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Add clip to timeline | ✅ | ❌ | ❌ | No `add_clip()` helper |
| Resize clip (set absolute duration) | ✅ | ❌ | ❌ | |
| Move clip (change start time) | ✅ | ❌ | ❌ | |
| Split clip at time | ✅ | ❌ | ❌ | |
| Duplicate clip | ✅ | ❌ | ❌ | |
| Delete clip | ✅ | ❌ | ❌ | |
| Reorder clips (single call) | ✅ | ❌ | ❌ | |
| Extend timeline to target duration | ✅ | ❌ | ❌ | |
| Add text overlay | ✅ | ❌ | ❌ | |
| Update text overlay (preset, color, size, position) | ✅ | ❌ | ❌ | |
| Apply fade in/out | ✅ | ❌ | ❌ | |
| Set track volume | ✅ | ❌ | ❌ | |
| Set clip playback speed | ✅ | ❌ | ❌ | |
| Mute/unmute track | ✅ | ❌ | ❌ | |
| Rename track | ✅ | ❌ | ❌ | |
| Delete track | ✅ | ❌ | ❌ | |
| Delete entire timeline | ✅ | ❌ | ❌ | |
| Unlink audio from video | ✅ | ❌ | ❌ | |
| Slip audio | ✅ | ❌ | ❌ | |
| Replace audio | ✅ | ❌ | ❌ | |
| Edit music track | ✅ | ❌ | ❌ | |
| Snap to other clips | ✅ | ❌ | ❌ | UI snapping behavior |
| Drag-and-drop reordering | ✅ | ⚪ | N/A | UI-only |
| Multi-track support | ✅ | ❌ | ❌ | Composition structure is opaque |
| Composition fingerprint (for conflict detection) | ✅ | ❌ | ❌ | Returned by `update_project()` but unused |

---

## 23. Timeline AI Chat (Streaming)

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Stream AI chat responses (SSE) | ✅ | ✅ | ✅ | `timeline_chat(input)` |
| 20 default tools (generate, edit, music, text, etc.) | ✅ | ✅ | ✅ | `DEFAULT_TOOLS` list |
| Custom tools override | ✅ | ✅ | ✅ | `tools=` param |
| Custom instructions | ✅ | ✅ | ✅ | `instructions=` param |
| Pass current composition | ✅ | ✅ | ✅ | `composition=` param |
| Event types: message_delta, message_done, tool_call, tool_response, reasoning_delta, reasoning_done, completed, error | ✅ | ✅ | ✅ | All yielded as dicts |
| Conversation history (multi-turn) | ✅ | ❌ | ❌ | Single-turn only; no `conversation_id` reuse |
| Tool result submission | ✅ | ❌ | ❌ | No `submit_tool_result()` method |
| Display tool call reasoning | ✅ | ⚪ | N/A | UI-only |

---

## 24. Timeline Export

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Sync export to MP4 | ✅ | ✅ | ✅ | `export_timeline(id, composition)` returns bytes |
| Async export (SurfGuard) | ✅ | ✅ | ✅ | `export_timeline_async(id, composition)` |
| Poll export status | ✅ | ✅ | ✅ | `check_export_status(id, export_id)` |
| Cancel export | ✅ | ✅ | ✅ | `cancel_export(id, export_id)` |
| Check pending export on load | ✅ | ❌ | ❌ | `GET /api/projects/{id}/timeline/export/pending` not exposed |
| WebGPU client-side export | ✅ | ⚪ | N/A | Browser-only (uses GPU) |
| Export progress reporting | ✅ | 🟡 | 🟡 | Available via polling but no callback/streaming |
| Export phase reporting | ✅ | 🟡 | 🟡 | In status response; not exposed as event |

---

## 25. Music Library

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Search Meta music library | ✅ | ✅ | ✅ | `search_music(query, limit, cursor)` |
| Pagination cursor | ✅ | ✅ | ✅ | |
| Lookup music thumbnail | ✅ | ✅ | ✅ | `lookup_music_thumbnail(id, title)` |
| Original audio check (oa-check) | ✅ | ❌ | ❌ | `POST /api/meta-music/oa-check` not exposed |
| Clip music segment | ✅ | ✅ | ✅ | `clip_music(cluster_id, preview_url, start, end)` returns bytes |
| Clip audio segment | ✅ | ✅ | ✅ | `clip_audio(url, start, end)` returns bytes |
| Music track max 60s per song | ✅ | ❌ | ❌ | No client-side check |
| Music clip max 9s (MUSIC_CLIP_MAX_DURATION_MS) | ✅ | ❌ | ❌ | No client-side check |
| Proxy audio via Vibes CDN | ✅ | ❌ | ❌ | `/api/proxy-audio` not exposed |
| Resolve audio URLs (batch) | ✅ | ❌ | ❌ | `/api/resolve-audio-urls` not exposed |
| Background music in composition | ✅ | ❌ | ❌ | No composition helper |
| "Sync to music" feature | ✅ | ❌ | ❌ | No equivalent |

---

## 26. 🆕 Real-time Sync (SSE) — v1.1.0

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Get last-updated timestamp | ✅ | ✅ | ✅ | `get_sync_status(type, id)` |
| Stream updates via SSE | ✅ | ✅ | ✅ | `stream_sync_updates(type, id)` |
| Event types: snapshot, update, bye | ✅ | ✅ | ✅ | All yielded as dicts |
| Auto-reconnect with backoff | ✅ | ❌ | ❌ | UI does exponential backoff; we don't |
| Fallback to polling when SSE fails | ✅ | ❌ | ❌ | UI falls back to GET polling after 3 SSE failures |
| Visibility-change handling | ✅ | ❌ | ❌ | UI pauses stream when tab hidden |

---

## 27. Quota & Rate Limiting

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Get quota upsell info | ✅ | ✅ | ✅ | `get_quota_upsell()` |
| Rate limit detection (429) | ✅ | ❌ | ❌ | No client-side cooldown |
| Rate limit cooldown tracking | ✅ | ❌ | ❌ | UI tracks `rateLimitSecondsLeft` |
| Capacity error handling (503) | ✅ | ❌ | ❌ | No special handling |
| Daily limit message | ✅ | ❌ | ❌ | UI shows toast; we raise exception |
| Generation limit message | ✅ | ❌ | ❌ | Same |

---

## 28. Bug Reports & Analytics

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Submit bug report | ✅ | ✅ | ✅ | `report_bug(data)` |
| Bug report with reproduction steps | ✅ | 🟡 | 🟡 | Free-form; no schema enforcement |
| Analytics tracking (`/api/analytics`) | ✅ | ❌ | ❌ | UI fire-and-forget; we don't |
| Session revisions (`/api/revisions`) | ✅ | ❌ | ❌ | UI sends on visibilitychange; we don't |
| Sentry error tracking | ✅ | ❌ | ❌ | UI posts to Sentry; we don't (intentional) |

---

## 29. Playables (Interactive Posts)

> **Note:** Playables appear to be a Meta-side feature for interactive
> AI-generated posts. The endpoint exists in the JS bundles but returns
> `"Playables not enabled"` for most accounts.

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| List playables | ✅ | ❌ | ❌ | Full CRUD class exists in JS; not exposed |
| Get playable | ✅ | ❌ | ❌ | |
| Create playable | ✅ | ❌ | ❌ | |
| Update playable | ✅ | ❌ | ❌ | |
| Delete playable | ✅ | ❌ | ❌ | |
| Duplicate playable | ✅ | ❌ | ❌ | |
| Generate thumbnail | ✅ | ❌ | ❌ | |
| Asset manifest | ✅ | ❌ | ❌ | |

---

## 30. Publishing / Posting

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Post to Vibes | ✅ | ❌ | ❌ | `POST /api/meta-profiles/publish` not exposed |
| Post to Vibes and Meta AI apps | ✅ | ❌ | ❌ | Same endpoint, different distribution |
| Add caption to post | ✅ | ❌ | ❌ | |
| Add audio to post | ✅ | ❌ | ❌ | |
| Add content attribution | ✅ | ❌ | ❌ | |
| Audio types classification | ✅ | ❌ | ❌ | |
| Image prompt required for publishing | ✅ | ❌ | ❌ | Validation missing |

---

## 31. Project Assets (Cross-Project Reuse)

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| List project assets | ✅ | ✅ | ✅ | `list_project_assets(id)` |
| Add asset to project | ✅ | ✅ | ✅ | `add_project_asset(id, asset)` |
| Delete asset from project | ✅ | ❌ | ❌ | `DELETE /api/projects/{id}/assets/{assetId}` not exposed |
| Import assets from another project | ✅ | ✅ | ✅ | `import_project_assets(id, source_id, asset_ids)` |
| List available assets (importable) | ✅ | ✅ | ✅ | `list_available_assets(id, source_id)` |
| Search across project assets | ✅ | 🟡 | 🟡 | via `search_query` param (not exposed as method arg) |

---

## 32. Incognito / Privacy

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Incognito access level (NONE default) | ✅ | ✅ | ✅ | Returned in `get_me()` |
| Incognito mode toggle | ✅ | ❌ | ❌ | No endpoint found |

---

## 33. Mobile App / Cross-Platform

| Feature | vibes.ai | vibes-api | Status | Notes |
|---|---|---|---|---|
| Download Vibes mobile app | ✅ | ⚪ | N/A | UI banner |
| App Store / Play Store links | ✅ | ⚪ | N/A | UI-only |

---

## Summary Statistics

| Category | Total Features | ✅ Implemented | 🟡 Partial | ❌ Missing | ⚪ N/A |
|---|---|---|---|---|---|
| Auth & Account | 15 | 9 | 1 | 5 | 0 |
| Projects | 14 | 11 | 1 | 1 | 1 |
| Video Generation (t2v) | 11 | 11 | 0 | 0 | 0 |
| Image Generation (t2i) | 7 | 7 | 0 | 0 | 0 |
| Video Extend | 10 | 9 | 1 | 0 | 0 |
| Video Edit (v2v) | 7 | 6 | 0 | 1 | 0 |
| Image Animate | 7 | 7 | 0 | 0 | 0 |
| Start/End Frame | 10 | 5 | 2 | 2 | 1 |
| Batch Regeneration | 5 | 5 | 0 | 0 | 0 |
| Ingredients | 17 | 12 | 1 | 4 | 0 |
| Moodboards | 10 | 5 | 0 | 4 | 1 |
| Image Editing | 4 | 3 | 0 | 0 | 1 |
| Prompt Enhancement | 6 | 3 | 0 | 3 | 0 |
| Lip Sync | 12 | 6 | 2 | 4 | 0 |
| TTS | 8 | 6 | 1 | 0 | 1 |
| Uploads | 11 | 6 | 0 | 5 | 0 |
| Media Library | 14 | 9 | 0 | 1 | 4 |
| Downloads | 5 | 3 | 0 | 1 | 1 |
| Generation Batches | 9 | 7 | 0 | 1 | 1 |
| Share Links | 7 | 5 | 0 | 1 | 1 |
| Collaborators | 6 | 3 | 0 | 0 | 3 |
| Timeline Composition | 24 | 0 | 0 | 24 | 0 |
| Timeline AI Chat | 9 | 7 | 0 | 1 | 1 |
| Timeline Export | 8 | 5 | 2 | 1 | 0 |
| Music Library | 10 | 5 | 0 | 5 | 0 |
| Real-time Sync | 6 | 3 | 0 | 3 | 0 |
| Quota & Rate Limiting | 6 | 1 | 0 | 5 | 0 |
| Bug Reports & Analytics | 5 | 1 | 1 | 3 | 0 |
| Playables | 8 | 0 | 0 | 8 | 0 |
| Publishing / Posting | 7 | 0 | 0 | 7 | 0 |
| Project Assets | 6 | 4 | 1 | 1 | 0 |
| Incognito / Privacy | 2 | 1 | 0 | 1 | 0 |
| Mobile App | 2 | 0 | 0 | 0 | 2 |
| **TOTAL** | **292** | **156** | **18** | **82** | **21** |

**Coverage: 53% fully implemented, 6% partial, 28% missing, 7% N/A**

---

## 🎯 Priority Recommendations for v1.2.0

### 🔥 High Priority (most user impact)

1. **Timeline Composition helpers** (24 missing features)
   - Build a `Composition` class with methods like `add_clip()`, `split_clip()`, `add_text_overlay()`, etc.
   - These manipulate the composition JSON locally, then `save_composition()` persists.
   - This is the biggest gap — the timeline is the core of Vibes.

2. **Publishing / Posting** (7 missing features)
   - `publish_to_vibes(content_item_id, ...)` — `POST /api/meta-profiles/publish`
   - Allows posting generated content publicly to Vibes + Meta AI apps.

3. **Resumable upload (rupload)** for large files
   - Current `upload_video_direct()` may fail on files >50MB.
   - The UI uses chunked resumable uploads via the rupload protocol.

4. **Moodboard PATCH (update)** — add/remove images from existing moodboards.

5. **Reset share link** convenience method (revoke + create new).

### 🟡 Medium Priority

6. **Multi-turn timeline chat** — support `conversation_id` reuse and tool result submission.
7. **Check pending export** on project load (`GET /api/projects/{id}/timeline/export/pending`).
8. **Original audio check** (`POST /api/meta-music/oa-check`) for filtering unavailable tracks.
9. **Rate limit handling** — auto-cooldown after 429, expose `rate_limit_seconds_left`.
10. **HeyGen avatar animation** — separate model for high-quality avatar lipsync.
11. **Auto-reconnect for SSE streams** (sync + batch updates) with exponential backoff.
12. **Playables CRUD** — full client for interactive posts (if your account has access).
13. **Update ingredient** — currently we can create/delete but not update (uses GraphQL).
14. **Bulk upload to project** (`POST /api/projects/{id}/upload`) — register multiple uploaded files at once.

### 🟢 Low Priority / Polish

15. **Client-side validation** — prompt length (10k char), image size (10MB, ≤4096px), project name (255 char), music clip (9s/60s).
16. **Auto-resize large images** before upload (canvas resize in UI).
17. **Multi-file upload** helper (up to 12 images at once).
18. **Audio URL resolution** (`/api/resolve-audio-urls`) for batch resolving.
19. **Audio proxy** (`/api/proxy-audio`) for playing licensed audio.
20. **sref/oref Midjourney parameter parsing** — `--sref random`, `--sref-weight 500`, `--chaos 50`, etc.
21. **Ingredient auto-description via LLM** — UI uses LLM to write character backstory.
22. **Create ingredient from timeline clip** — chat-tool-only feature.
23. **Composition fingerprint** for conflict detection (returned by `update_project` but unused).
24. **Filter media library by ingredient** (was-this-created-with-X).
25. **Token validation** (`/api/auth/check-token`).
26. **Analytics & revisions** endpoints (fire-and-forget).
27. **Teen Safety / Family Center / Accounts Center** (Meta GraphQL features).

### ⚪ Out of Scope (UI-only)

- Drag-and-drop reordering
- Snapping behavior
- Visibility-change handling
- Clipboard copy
- Mobile app download banners
- Voice preview playback
- Grid/Row view toggle
- Modal selectors

---

## ✅ Answer to your specific question

### Is image upload available?

**YES** — image upload is fully implemented with three methods:

```python
# 1. From a base64 string
resp = client.upload_image(image_base64="iVBORw0KG...")
# → {mediaEntId, imageUrl}

# 2. From a file path (convenience)
resp = client.upload_image_file(path="/path/to/image.png")
# → {mediaEntId, imageUrl}

# 3. Generic media upload (auto-detects type, multipart form)
resp = client.upload_media(path="/path/to/image.png")
# → {mediaEntId, imageUrl, dimensions, aspectRatio}
```

All three return `{mediaEntId, imageUrl}` which you can then use as:
- `source_image_ent_id` for `edit_image()` or `create_ingredient()`
- A start/end frame for `generate_video()` (via `build_frame_handle()`)
- An ingredient image for `create_ingredient()`

**Limitations vs the UI:**
- ❌ No client-side size validation (UI blocks files >10MB or >4096px)
- ❌ No auto-resize (UI canvas-resizes oversize images)
- ❌ No multi-file batch upload (UI accepts up to 12 at once)
- ❌ No resumable upload for very large files (UI uses rupload protocol)
- ❌ No PNG/JPG/WebP type checking

These are all marked ❌ in section 16 (Uploads) above and are candidates for v1.2.0.
