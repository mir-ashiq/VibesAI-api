"""FastAPI server exposing VibesClient as a REST API."""
from __future__ import annotations
import os, sys, threading
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vibes_api import VibesClient, VibesAPIError
from vibes_api.tts_fallback import (
    EDGE_VOICE_CATALOG,
    GTTS_LANGUAGES,
    synthesize_speech_async,
)

_client: Optional[VibesClient] = None
_lock = threading.Lock()

def get_client() -> VibesClient:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                ms = os.environ.get("VIBES_META_SESSION")
                if not ms:
                    raise HTTPException(500, "VIBES_META_SESSION env var not set.")
                cf = os.environ.get("VIBES_COOKIE_FILE")
                if cf and os.path.exists(cf):
                    try:
                        with open(cf) as f: ms = f.read().strip()
                    except: pass
                def save(c):
                    if cf:
                        try:
                            with open(cf, "w") as f: f.write(c)
                        except: pass
                amc = os.environ.get("AUTH_META_COOKIES", "").strip()
                _client = VibesClient(meta_session=ms, auto_refresh=True,
                    background_refresh=True,
                    refresh_interval=float(os.environ.get("VIBES_REFRESH_INTERVAL","1500")),
                    on_cookie_refresh=save,
                    auto_relogin=bool(amc),
                    auth_meta_cookies=amc or None)
    return _client

def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
                   authorization: Optional[str] = Header(None)):
    exp = os.environ.get("VIBES_API_KEY")
    if not exp: return
    prov = x_api_key or (authorization[7:] if authorization and authorization.startswith("Bearer ") else None)
    if prov != exp:
        raise HTTPException(401, "Invalid or missing API key.")

def _err(e):
    if isinstance(e, VibesAPIError):
        raise HTTPException(e.status or 500, detail={"error": str(e), "code": e.code, "response": e.response})
    raise HTTPException(500, str(e))

class PC(BaseModel):
    name: str = "Untitled"
    composition: Optional[dict] = None
class PU(BaseModel):
    name: Optional[str] = None
    composition: Optional[dict] = None
class VG(BaseModel):
    project_id: str; prompt: str; aspect_ratio: str = "9:16"; resolution: str = "480p"
    variations: int = 4; video_model: str = "midjen-short"; image_model: str = "midjen-base"
    prompt_model: str = "gemini-2.5-flash"; ingredients: Optional[List[dict]] = None
    create_ingredients: Optional[List[dict]] = None; start_frame: Optional[dict] = None
    end_frame: Optional[dict] = None; moodboard: Optional[dict] = None
    poll: bool = True; poll_timeout: float = 300.0
class IG(BaseModel):
    project_id: str; prompt: str; aspect_ratio: str = "1:1"; resolution: str = "480p"
    variations: int = 1; image_model: str = "midjen-base"; prompt_model: str = "gemini-2.5-flash"
    ingredients: Optional[List[dict]] = None; create_ingredients: Optional[List[dict]] = None
    moodboard: Optional[dict] = None
class IE(BaseModel):
    source_image_ent_id: str; edit_prompt: str; project_id: Optional[str] = None
class PE(BaseModel):
    prompt: str; project_id: Optional[str] = None; batch_type: str = "videos"
class TT(BaseModel):
    text: str; voice: str; output_format: str = "mp3"; language: Optional[str] = None
class LR(BaseModel):
    project_id: str; image_prompt: str; script: str; audio_url: str
    audio_duration_ms: int; engine: str = "midjen"; ingredients: Optional[List[dict]] = None
    aspect_ratio: Optional[str] = None; music_track: Optional[dict] = None
    custom_motion_prompt: Optional[str] = None
class EV(BaseModel):
    project_id: str; batch_id: str; content_id: Optional[str] = None
    prompt: Optional[str] = None; poll: bool = True; poll_timeout: float = 300.0
class EDV(BaseModel):
    project_id: str; batch_id: str; content_id: Optional[str] = None
    prompt: str; poll: bool = True; poll_timeout: float = 300.0
class SL(BaseModel):
    entity_type: str; entity_id: str; expires_at: Optional[str] = None; max_uses: Optional[int] = None
class IC(BaseModel):
    name: str; ingredient_type: str; source_image_ent_id: Optional[str] = None
    image_url: Optional[str] = None; description: Optional[str] = None
class TC(BaseModel):
    input: str; instructions: Optional[str] = None; tools: Optional[List[dict]] = None; composition: Optional[dict] = None
class TE(BaseModel):
    composition: dict
class PR(BaseModel):
    content_item_id: str; batch_id: Optional[str] = None; caption: Optional[str] = None
    audio_types: Optional[List[str]] = None; prompt: Optional[str] = None
    image_prompt: Optional[str] = None; video_prompt: Optional[str] = None
class PM(BaseModel):
    prompt: str
class UI(BaseModel):
    image_base64: str

app = FastAPI(title="VibesAI API", version="1.3.0", docs_url="/docs", redoc_url="/redoc")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
AUTH = [Depends(verify_api_key)]

@app.get("/", tags=["Health"])
async def root(): return {"name": "VibesAI API", "version": "1.3.0", "docs": "/docs"}

@app.get("/health", tags=["Health"])
async def health():
    try:
        u = get_client().get_me(); return {"status": "healthy", "user": u.get("username")}
    except Exception as e: return {"status": "unhealthy", "error": str(e)}

@app.get("/api/v1/me", tags=["Auth"], dependencies=AUTH)
async def me():
    try: return get_client().get_me()
    except Exception as e: _err(e)

@app.get("/api/v1/check-token", tags=["Auth"], dependencies=AUTH)
async def check_token():
    try: return {"valid": get_client().check_token()}
    except Exception as e: _err(e)

@app.get("/api/v1/current-cookie", tags=["Auth"], dependencies=AUTH)
async def current_cookie(): return {"meta_session": get_client().get_current_cookie()}

@app.get("/api/v1/projects", tags=["Projects"], dependencies=AUTH)
async def list_projects(limit: int = 25, offset: int = 0, sort: str = "newest", search: Optional[str] = None):
    try: return get_client().list_projects(limit=limit, offset=offset, sort=sort, search=search)
    except Exception as e: _err(e)

@app.post("/api/v1/projects", tags=["Projects"], dependencies=AUTH)
async def create_project(b: PC):
    try: return get_client().create_project(name=b.name, composition=b.composition)
    except Exception as e: _err(e)

@app.get("/api/v1/projects/{pid}", tags=["Projects"], dependencies=AUTH)
async def get_project(pid: str):
    try: return get_client().get_project(pid)
    except Exception as e: _err(e)

@app.put("/api/v1/projects/{pid}", tags=["Projects"], dependencies=AUTH)
async def update_project(pid: str, b: PU):
    try: return get_client().update_project(pid, name=b.name, composition=b.composition)
    except Exception as e: _err(e)

@app.delete("/api/v1/projects/{pid}", tags=["Projects"], dependencies=AUTH)
async def delete_project(pid: str, delete_assets: bool = False):
    try: get_client().delete_project(pid, delete_assets=delete_assets); return {"success": True}
    except Exception as e: _err(e)

@app.post("/api/v1/videos/generate", tags=["Videos"], dependencies=AUTH)
async def gen_video(b: VG):
    try: return get_client().generate_video(project_id=b.project_id, prompt=b.prompt,
        aspect_ratio=b.aspect_ratio, resolution=b.resolution, variations=b.variations,
        video_model=b.video_model, image_model=b.image_model, prompt_model=b.prompt_model,
        ingredients=b.ingredients, create_ingredients=b.create_ingredients,
        start_frame=b.start_frame, end_frame=b.end_frame, moodboard=b.moodboard,
        poll=b.poll, poll_timeout=b.poll_timeout)
    except Exception as e: _err(e)

@app.post("/api/v1/videos/extend", tags=["Videos"], dependencies=AUTH)
async def ext_video(b: EV):
    try:
        c = get_client(); batch = c.get_batch(b.batch_id)
        src = next((x for x in batch.get("content",[]) if x["id"]==b.content_id), None) or (batch["content"][0] if batch.get("content") else None)
        if not src: raise HTTPException(404, "No content item found")
        return c.extend_video(project_id=b.project_id, source_video=src, prompt=b.prompt, poll=b.poll, poll_timeout=b.poll_timeout)
    except HTTPException: raise
    except Exception as e: _err(e)

@app.post("/api/v1/videos/edit", tags=["Videos"], dependencies=AUTH)
async def edit_video(b: EDV):
    try:
        c = get_client(); batch = c.get_batch(b.batch_id)
        src = next((x for x in batch.get("content",[]) if x["id"]==b.content_id), None) or (batch["content"][0] if batch.get("content") else None)
        if not src: raise HTTPException(404, "No content item found")
        return c.edit_video(project_id=b.project_id, source_video=src, prompt=b.prompt, poll=b.poll, poll_timeout=b.poll_timeout)
    except HTTPException: raise
    except Exception as e: _err(e)

@app.post("/api/v1/images/generate", tags=["Images"], dependencies=AUTH)
async def gen_image(b: IG):
    try: return get_client().generate_image(project_id=b.project_id, prompt=b.prompt,
        aspect_ratio=b.aspect_ratio, resolution=b.resolution, variations=b.variations,
        image_model=b.image_model, prompt_model=b.prompt_model, ingredients=b.ingredients,
        create_ingredients=b.create_ingredients, moodboard=b.moodboard)
    except Exception as e: _err(e)

@app.post("/api/v1/images/edit", tags=["Images"], dependencies=AUTH)
async def edit_image(b: IE):
    try: return get_client().edit_image(source_image_ent_id=b.source_image_ent_id, edit_prompt=b.edit_prompt, project_id=b.project_id)
    except Exception as e: _err(e)

@app.post("/api/v1/upload/image", tags=["Uploads"], dependencies=AUTH)
async def upload_image(b: UI):
    try: return get_client().upload_image(b.image_base64)
    except Exception as e: _err(e)

@app.post("/api/v1/prompts/enhance", tags=["Prompts"], dependencies=AUTH)
async def enhance_prompt(b: PE):
    try: return {"variations": get_client().enhance_prompt(prompt=b.prompt, project_id=b.project_id, batch_type=b.batch_type)}
    except Exception as e: _err(e)

@app.get("/api/v1/voices", tags=["TTS"], dependencies=AUTH)
async def list_voices():
    """Voice catalog across every TTS engine.

    Each entry carries an ``engine`` field: ``vibes`` (vibes.ai PlayAI —
    primary), ``edge-tts`` (Microsoft neural fallback), ``gtts`` (Google
    Translate fallback). When vibes.ai is unreachable the fallback voices
    are still listed.
    """
    fallback = (
        [{**v, "engine": "edge-tts"} for v in EDGE_VOICE_CATALOG]
        + [{**v, "engine": "gtts"} for v in GTTS_LANGUAGES]
    )
    try:
        voices = get_client().list_voices()
        return {
            "voices": [{"id": v.get("id"), "name": v.get("name"),
                        "description": v.get("description"),
                        "sample": v.get("sample"), "engine": "vibes"} for v in voices]
            + fallback,
        }
    except Exception:
        return {"voices": fallback}

@app.post("/api/v1/tts", tags=["TTS"], dependencies=AUTH)
async def tts(b: TT):
    """Synthesize speech with the fallback chain (env ``VIBES_TTS_FALLBACK``).

    ``VIBES_TTS_FALLBACK=auto`` (default): vibes.ai → Edge TTS → Google
    Translate TTS. ``off``: vibes.ai only. ``only``: skip vibes.ai. The
    engine used is in the ``engine`` field of the response.
    """
    mode = os.environ.get("VIBES_TTS_FALLBACK", "auto")
    try:
        return await synthesize_speech_async(
            get_client(), text=b.text, voice=b.voice,
            output_format=b.output_format, language=b.language, mode=mode,
        )
    except Exception as e:
        _err(e)

@app.get("/api/v1/media", tags=["Media"], dependencies=AUTH)
async def list_media(limit: int = 50, offset: int = 0, type: Optional[str] = None, search: Optional[str] = None):
    try: return get_client().list_media(limit=limit, offset=offset, type=type, search=search)
    except Exception as e: _err(e)

@app.get("/api/v1/media/{item_id}/download", tags=["Media"], dependencies=AUTH)
async def download_media(item_id: str, type: str = "video"):
    from fastapi import Response; import tempfile
    try:
        c = get_client(); suffix = ".mp4" if type=="video" else ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f: path = f.name
        if type=="video": c.download_video(item_id, path)
        else: c.download_image(item_id, path)
        with open(path,"rb") as f: content = f.read()
        os.unlink(path)
        return Response(content=content, media_type="video/mp4" if type=="video" else "image/png")
    except Exception as e: _err(e)

@app.delete("/api/v1/media/{item_id}", tags=["Media"], dependencies=AUTH)
async def del_media(item_id: str):
    try: get_client().delete_content_item(item_id); return {"success": True}
    except Exception as e: _err(e)

@app.get("/api/v1/batches", tags=["Batches"], dependencies=AUTH)
async def list_batches(limit: int = 12, offset: int = 0, project_id: Optional[str] = None):
    try: return get_client().list_batches(limit=limit, offset=offset, project_id=project_id)
    except Exception as e: _err(e)

@app.get("/api/v1/batches/{bid}", tags=["Batches"], dependencies=AUTH)
async def get_batch(bid: str):
    try: return get_client().get_batch(bid)
    except Exception as e: _err(e)

@app.post("/api/v1/batches/{bid}/poll", tags=["Batches"], dependencies=AUTH)
async def poll_batch(bid: str, timeout: float = 180.0):
    try: return get_client().poll_batch(bid, timeout=timeout)
    except Exception as e: _err(e)

@app.get("/api/v1/ingredients", tags=["Ingredients"], dependencies=AUTH)
async def list_ingredients(owner_filter: str = "LIBRARY", ingredient_type: Optional[str] = None):
    try: return {"ingredients": get_client().list_ingredients(owner_filter=owner_filter, ingredient_type=ingredient_type)}
    except Exception as e: _err(e)

@app.post("/api/v1/ingredients", tags=["Ingredients"], dependencies=AUTH)
async def create_ingredient(b: IC):
    try: return get_client().create_ingredient(name=b.name, ingredient_type=b.ingredient_type,
        source_image_ent_id=b.source_image_ent_id, image_url=b.image_url, description=b.description)
    except Exception as e: _err(e)

@app.delete("/api/v1/ingredients/{iid}", tags=["Ingredients"], dependencies=AUTH)
async def del_ingredient(iid: str):
    try: get_client().delete_ingredient(iid); return {"success": True}
    except Exception as e: _err(e)

@app.post("/api/v1/share-links", tags=["Share"], dependencies=AUTH)
async def create_share(b: SL):
    try: return get_client().create_share_link(b.entity_type, b.entity_id, expires_at=b.expires_at, max_uses=b.max_uses)
    except Exception as e: _err(e)

@app.get("/api/v1/share-links", tags=["Share"], dependencies=AUTH)
async def list_shares(entity_type: str, entity_id: str):
    try: return {"shareLinks": get_client().list_share_links(entity_type, entity_id)}
    except Exception as e: _err(e)

@app.post("/api/v1/timeline/chat", tags=["Timeline"], dependencies=AUTH)
async def timeline_chat(b: TC):
    try:
        events = []
        for ev in get_client().timeline_chat(b.input, instructions=b.instructions, tools=b.tools, composition=b.composition):
            events.append(ev)
            if ev.get("type") in ("completed","error"): break
        return {"events": events}
    except Exception as e: _err(e)

@app.post("/api/v1/timeline/export", tags=["Timeline"], dependencies=AUTH)
async def export_timeline(project_id: str, b: TE):
    from fastapi import Response
    try:
        mp4 = get_client().export_timeline(project_id, b.composition)
        return Response(content=mp4, media_type="video/mp4")
    except Exception as e: _err(e)

@app.post("/api/v1/publish", tags=["Publishing"], dependencies=AUTH)
async def publish(b: PR):
    try: return get_client().publish_to_vibes(content_item_id=b.content_item_id, batch_id=b.batch_id,
        caption=b.caption, audio_types=b.audio_types, prompt=b.prompt, image_prompt=b.image_prompt, video_prompt=b.video_prompt)
    except Exception as e: _err(e)

@app.post("/api/v1/lipsync", tags=["LipSync"], dependencies=AUTH)
async def lipsync(b: LR):
    try: return get_client().generate_lipsync(project_id=b.project_id, image_prompt=b.image_prompt,
        script=b.script, audio_url=b.audio_url, audio_duration_ms=b.audio_duration_ms, engine=b.engine,
        ingredients=b.ingredients, aspect_ratio=b.aspect_ratio, music_track=b.music_track, custom_motion_prompt=b.custom_motion_prompt)
    except Exception as e: _err(e)

@app.get("/api/v1/music/search", tags=["Music"], dependencies=AUTH)
async def search_music(q: str = "", limit: int = 30, cursor: Optional[str] = None):
    try: return get_client().search_music_filtered(query=q, limit=limit, cursor=cursor)
    except Exception as e: _err(e)

@app.get("/api/v1/moodboards", tags=["Moodboards"], dependencies=AUTH)
async def moodboards():
    try: return {"moodboards": get_client().list_moodboards()}
    except Exception as e: _err(e)

@app.post("/api/v1/utils/parse-midjourney", tags=["Utils"])
async def parse_mj(b: PM): return VibesClient.parse_midjourney_params(b.prompt)

@app.post("/api/v1/utils/validate-prompt", tags=["Utils"])
async def validate_p(b: PM): return VibesClient.validate_prompt_length(b.prompt)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.app:app", host=os.environ.get("HOST","0.0.0.0"), port=int(os.environ.get("PORT","8000")))
