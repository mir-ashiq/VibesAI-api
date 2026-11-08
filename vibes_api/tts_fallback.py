"""TTS fallback engines for :mod:`vibes_api`.

vibes.ai's PlayAI TTS backend (``/api/studio/playai/tts``) periodically goes
down server-side with ``403 Facebook expired access token`` — during those
outages even the vibes.ai website itself cannot synthesize audio. This
module provides two keyless fallback engines so ``client.tts()`` (and the
REST server's ``POST /api/v1/tts``) always return audio:

1. **Edge TTS** (Microsoft "Read Aloud") — 400+ neural voices, via the
   optional :pypi:`edge-tts` package (``pip install VibesAI-api[tts]``).
   Falls back silently to Google Translate TTS when not installed.
2. **Google Translate TTS** — keyless, ~100 languages, built on plain
   ``requests`` (always available). Text is chunked to ~190 chars per
   request and the MP3 frames are concatenated.

Voice handling mirrors the TypeScript sibling repo
(``VibesAI-openai/src/tts``): OpenAI voice names (``alloy``, ``echo``, …)
map to vibes PlayAI ids *and* Edge neural voices; explicit Edge voice ids
(``en-US-JennyNeural``) and GTTS ids (``gtts-ja``) bypass vibes.ai.

The engine that produced the audio is reported in the ``engine`` key of the
returned dict: ``"vibes"``, ``"edge-tts"`` or ``"gtts"``.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional

import requests

__all__ = [
    "synthesize_speech",
    "synthesize_speech_async",
    "resolve_tts_voice",
    "is_edge_voice",
    "parse_gtts_voice",
    "edge_tts_available",
    "GTTS_LANGUAGES",
    "EDGE_VOICE_CATALOG",
]

# ---------------------------------------------------------------------------
# Voice tables
# ---------------------------------------------------------------------------

#: OpenAI voice names → (vibes PlayAI id, Edge neural voice).
OPENAI_VOICE_MAP: Dict[str, Dict[str, str]] = {
    "alloy": {"vibes": "play_ai_Marisol", "edge": "en-US-JennyNeural"},
    "echo": {"vibes": "play_ai_Nigel", "edge": "en-US-EricNeural"},
    "fable": {"vibes": "play_ai_1P_Abraham_Lincoln", "edge": "en-GB-RyanNeural"},
    "onyx": {"vibes": "play_ai_Thunder", "edge": "en-US-ChristopherNeural"},
    "nova": {"vibes": "play_ai_Celeste", "edge": "en-US-AriaNeural"},
    "shimmer": {"vibes": "play_ai_1P_Seraphine", "edge": "en-US-MichelleNeural"},
    "coral": {"vibes": "play_ai_Scarlett", "edge": "en-AU-NatashaNeural"},
    "sage": {"vibes": "play_ai_Jacile", "edge": "en-GB-SoniaNeural"},
    "ash": {"vibes": "play_ai_Conor", "edge": "en-AU-WilliamNeural"},
    "ballad": {"vibes": "play_ai_Giulia", "edge": "en-GB-LibbyNeural"},
    "verse": {"vibes": "play_ai_Rumi", "edge": "en-US-AnaNeural"},
}

#: vibes PlayAI ids → Edge neural equivalents (used when vibes.ai is down).
PLAYAI_TO_EDGE: Dict[str, str] = {
    v["vibes"]: v["edge"] for v in OPENAI_VOICE_MAP.values()
}

#: Curated Edge neural voices (also used by the REST server's /api/v1/voices).
EDGE_VOICE_CATALOG: List[Dict[str, str]] = [
    {"id": "en-US-JennyNeural", "name": "Jenny", "locale": "en-US", "gender": "female"},
    {"id": "en-US-AriaNeural", "name": "Aria", "locale": "en-US", "gender": "female"},
    {"id": "en-US-MichelleNeural", "name": "Michelle", "locale": "en-US", "gender": "female"},
    {"id": "en-US-AnaNeural", "name": "Ana (child)", "locale": "en-US", "gender": "female"},
    {"id": "en-US-EricNeural", "name": "Eric", "locale": "en-US", "gender": "male"},
    {"id": "en-US-ChristopherNeural", "name": "Christopher", "locale": "en-US", "gender": "male"},
    {"id": "en-US-GuyNeural", "name": "Guy", "locale": "en-US", "gender": "male"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia", "locale": "en-GB", "gender": "female"},
    {"id": "en-GB-LibbyNeural", "name": "Libby", "locale": "en-GB", "gender": "female"},
    {"id": "en-GB-RyanNeural", "name": "Ryan", "locale": "en-GB", "gender": "male"},
    {"id": "en-GB-ThomasNeural", "name": "Thomas", "locale": "en-GB", "gender": "male"},
    {"id": "en-AU-NatashaNeural", "name": "Natasha", "locale": "en-AU", "gender": "female"},
    {"id": "en-AU-WilliamNeural", "name": "William", "locale": "en-AU", "gender": "male"},
    {"id": "en-IN-NeerjaNeural", "name": "Neerja", "locale": "en-IN", "gender": "female"},
    {"id": "en-IN-PrabhatNeural", "name": "Prabhat", "locale": "en-IN", "gender": "male"},
    {"id": "hi-IN-SwaraNeural", "name": "Swara", "locale": "hi-IN", "gender": "female"},
    {"id": "hi-IN-MadhurNeural", "name": "Madhur", "locale": "hi-IN", "gender": "male"},
    {"id": "es-ES-ElviraNeural", "name": "Elvira", "locale": "es-ES", "gender": "female"},
    {"id": "es-ES-AlvaroNeural", "name": "Alvaro", "locale": "es-ES", "gender": "male"},
    {"id": "fr-FR-DeniseNeural", "name": "Denise", "locale": "fr-FR", "gender": "female"},
    {"id": "fr-FR-HenriNeural", "name": "Henri", "locale": "fr-FR", "gender": "male"},
    {"id": "de-DE-KatjaNeural", "name": "Katja", "locale": "de-DE", "gender": "female"},
    {"id": "de-DE-ConradNeural", "name": "Conrad", "locale": "de-DE", "gender": "male"},
    {"id": "pt-BR-FranciscaNeural", "name": "Francisca", "locale": "pt-BR", "gender": "female"},
    {"id": "pt-BR-AntonioNeural", "name": "Antonio", "locale": "pt-BR", "gender": "male"},
    {"id": "ru-RU-SvetlanaNeural", "name": "Svetlana", "locale": "ru-RU", "gender": "female"},
    {"id": "ru-RU-DmitryNeural", "name": "Dmitry", "locale": "ru-RU", "gender": "male"},
    {"id": "ja-JP-NanamiNeural", "name": "Nanami", "locale": "ja-JP", "gender": "female"},
    {"id": "ja-JP-KeitaNeural", "name": "Keita", "locale": "ja-JP", "gender": "male"},
    {"id": "zh-CN-XiaoxiaoNeural", "name": "Xiaoxiao", "locale": "zh-CN", "gender": "female"},
    {"id": "zh-CN-YunxiNeural", "name": "Yunxi", "locale": "zh-CN", "gender": "male"},
    {"id": "ko-KR-SunHiNeural", "name": "Sun-Hi", "locale": "ko-KR", "gender": "female"},
    {"id": "ko-KR-InJoonNeural", "name": "InJoon", "locale": "ko-KR", "gender": "male"},
    {"id": "it-IT-ElsaNeural", "name": "Elsa", "locale": "it-IT", "gender": "female"},
    {"id": "it-IT-DiegoNeural", "name": "Diego", "locale": "it-IT", "gender": "male"},
    {"id": "ar-EG-SalmaNeural", "name": "Salma", "locale": "ar-EG", "gender": "female"},
    {"id": "ar-EG-ShakirNeural", "name": "Shakir", "locale": "ar-EG", "gender": "male"},
]

#: Language codes/names → Google Translate TTS `tl` values.
GTTS_LANGUAGE_MAP: Dict[str, str] = {
    "eng": "en", "en": "en", "english": "en",
    "spa": "es", "es": "es", "spanish": "es",
    "fre": "fr", "fra": "fr", "fr": "fr", "french": "fr",
    "ger": "de", "deu": "de", "de": "de", "german": "de",
    "hin": "hi", "hi": "hi", "hindi": "hi",
    "jpn": "ja", "ja": "ja", "japanese": "ja",
    "por": "pt", "pt": "pt", "portuguese": "pt",
    "rus": "ru", "ru": "ru", "russian": "ru",
    "chi": "zh-CN", "zho": "zh-CN", "zh-cn": "zh-CN", "zh": "zh-CN", "chinese": "zh-CN",
    "kor": "ko", "ko": "ko", "korean": "ko",
    "ita": "it", "it": "it", "italian": "it",
    "ara": "ar", "ar": "ar", "arabic": "ar",
    "ben": "bn", "bn": "bn", "bengali": "bn",
    "tam": "ta", "ta": "ta", "tamil": "ta",
    "tel": "te", "te": "te", "telugu": "te",
    "mar": "mr", "mr": "mr", "marathi": "mr",
    "guj": "gu", "gu": "gu", "gujarati": "gu",
    "kan": "kn", "kn": "kn", "kannada": "kn",
    "mal": "ml", "ml": "ml", "malayalam": "ml",
    "pun": "pa", "pa": "pa", "punjabi": "pa",
    "urd": "ur", "ur": "ur", "urdu": "ur",
    "tur": "tr", "tr": "tr", "turkish": "tr",
    "dut": "nl", "nld": "nl", "nl": "nl", "dutch": "nl",
    "pol": "pl", "pl": "pl", "polish": "pl",
    "swe": "sv", "sv": "sv", "swedish": "sv",
    "dan": "da", "da": "da", "danish": "da",
    "nor": "no", "no": "no", "norwegian": "no",
    "fin": "fi", "fi": "fi", "finnish": "fi",
    "cze": "cs", "ces": "cs", "cs": "cs", "czech": "cs",
    "gre": "el", "ell": "el", "el": "el", "greek": "el",
    "heb": "he", "he": "he", "hebrew": "he",
    "tha": "th", "th": "th", "thai": "th",
    "vie": "vi", "vi": "vi", "vietnamese": "vi",
    "ind": "id", "id": "id", "indonesian": "id",
    "msa": "ms", "ms": "ms", "malay": "ms",
    "fil": "tl", "tl": "tl", "filipino": "tl",
    "ukr": "uk", "uk": "uk", "ukrainian": "uk",
    "ron": "ro", "ro": "ro", "romanian": "ro",
    "hun": "hu", "hu": "hu", "hungarian": "hu",
}

#: Languages offered by the GTTS fallback.
GTTS_LANGUAGES: List[Dict[str, str]] = [
    {"id": f"gtts-{code}", "language": name}
    for code, name in [
        ("en", "English"), ("es", "Spanish"), ("fr", "French"), ("de", "German"),
        ("hi", "Hindi"), ("ja", "Japanese"), ("pt", "Portuguese"), ("ru", "Russian"),
        ("zh-CN", "Chinese (Mandarin)"), ("ko", "Korean"), ("it", "Italian"),
        ("ar", "Arabic"),
    ]
]

_EDGE_VOICE_RE = re.compile(r"^[a-z]{2,3}-[A-Za-z]{2,}-[A-Za-z]+Neural$")
_GTTS_VOICE_RE = re.compile(r"^gtts-[a-zA-Z]{2,3}(-[A-Za-z]{2,4})?$")

_EDGE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
_GTTS_URL = "https://translate.google.com/translate_tts"


def is_edge_voice(voice: Optional[str]) -> bool:
    """True when *voice* is an explicit Edge neural voice id."""
    return bool(voice) and bool(_EDGE_VOICE_RE.match(voice.strip()))


def parse_gtts_voice(voice: Optional[str]) -> Optional[str]:
    """Extract the language from an explicit GTTS voice id (``gtts-ja`` → ``ja``)."""
    if not voice:
        return None
    v = voice.strip()
    if v.lower() == "gtts":
        return "en"
    if _GTTS_VOICE_RE.match(v):
        return v[5:]
    return None


def resolve_tts_voice(voice: Optional[str]) -> Dict[str, str]:
    """Resolve any requested voice to per-engine voice ids.

    Returns ``{"openai"?, "vibes", "edge"}``.
    """
    if not voice:
        d = OPENAI_VOICE_MAP["alloy"]
        return {"openai": "alloy", "vibes": d["vibes"], "edge": d["edge"]}
    v = voice.strip()
    if is_edge_voice(v):
        return {"vibes": OPENAI_VOICE_MAP["alloy"]["vibes"], "edge": v}
    if v in PLAYAI_TO_EDGE:
        return {"vibes": v, "edge": PLAYAI_TO_EDGE[v]}
    mapped = OPENAI_VOICE_MAP.get(v.lower())
    if mapped:
        return {"openai": v.lower(), "vibes": mapped["vibes"], "edge": mapped["edge"]}
    # Unknown name — try it as a vibes voice, default Edge voice for fallback.
    return {"vibes": v, "edge": OPENAI_VOICE_MAP["alloy"]["edge"]}


def _to_gtts_language(language: Optional[str]) -> str:
    if not language:
        return "en"
    key = language.strip().lower()
    return GTTS_LANGUAGE_MAP.get(key, key if len(key) <= 5 else "en")


def _chunk_text(text: str, max_len: int) -> List[str]:
    """Split *text* into chunks of at most *max_len* characters."""
    clean = text.strip()
    if not clean:
        return []
    if len(clean) <= max_len:
        return [clean]
    chunks: List[str] = []
    rest = clean
    while len(rest) > max_len:
        window = rest[:max_len]
        cut = -1
        for pattern in (r"[.!?…。！？]\s", r"[,;:—–]\s", r"\s"):
            matches = list(re.finditer(pattern, window))
            if matches:
                cut = matches[-1].end()
                break
        if cut <= 0:
            cut = max_len
        chunks.append(rest[:cut])
        rest = rest[cut:]
    if rest.strip():
        chunks.append(rest.strip())
    return chunks


# ---------------------------------------------------------------------------
# Engine: Edge TTS (optional edge-tts package)
# ---------------------------------------------------------------------------

def edge_tts_available() -> bool:
    """True when the optional :pypi:`edge-tts` package is importable."""
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


async def _edge_tts_async(text: str, voice: str, rate: str = "+0%") -> bytes:
    """Synthesize MP3 bytes with Edge TTS. Raises when edge-tts is missing."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate)
    parts: List[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            parts.append(chunk["data"])
    if not parts:
        raise RuntimeError("Edge TTS returned no audio")
    return b"".join(parts)


def edge_tts_sync(text: str, voice: str, rate: str = "+0%") -> bytes:
    """Synchronous wrapper around the async Edge TTS API."""
    return asyncio.run(_edge_tts_async(text, voice, rate))


# ---------------------------------------------------------------------------
# Engine: Google Translate TTS (requests-based, always available)
# ---------------------------------------------------------------------------

def gtts_sync(text: str, language: Optional[str] = None, slow: bool = False) -> bytes:
    """Synthesize MP3 bytes via Google Translate TTS (chunked)."""
    tl = _to_gtts_language(language)
    chunks = _chunk_text(text, 190)
    if not chunks:
        raise ValueError("TTS input text is empty")
    parts: List[bytes] = []
    for i, chunk in enumerate(chunks):
        params = {
            "ie": "UTF-8",
            "q": chunk,
            "tl": tl,
            "client": "tw-ob",
            "total": len(chunks),
            "idx": i,
            "textlen": len(chunk),
        }
        if slow:
            params["ttsspeed"] = "0.24"
        resp = requests.get(
            _GTTS_URL,
            params=params,
            headers={"User-Agent": _EDGE_UA, "Referer": "https://translate.google.com/"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Google Translate TTS failed (HTTP {resp.status_code})")
        parts.append(resp.content)
    return b"".join(parts)


async def gtts_async(text: str, language: Optional[str] = None, slow: bool = False) -> bytes:
    """Async wrapper — runs the blocking requests call in a thread."""
    return await asyncio.to_thread(gtts_sync, text, language, slow)


# ---------------------------------------------------------------------------
# Orchestration: vibes → edge → gtts
# ---------------------------------------------------------------------------

def _parse_mode(mode: Any) -> str:
    m = str(mode or "auto").lower()
    if m in ("off", "none", "false", "0"):
        return "off"
    if m in ("only", "fallback", "always"):
        return "only"
    return "auto"


def synthesize_speech(
    client: Any,
    text: str,
    voice: Optional[str],
    output_format: str = "mp3",
    language: Optional[str] = None,
    mode: Any = "auto",
) -> Dict[str, Any]:
    """Synthesize speech with the full engine chain (synchronous).

    Parameters
    ----------
    client : VibesClient
        Client used for the primary vibes.ai attempt.
    voice : str, optional
        Any voice: OpenAI name, ``play_ai_*`` id, Edge neural id, or
        ``gtts-<lang>``.
    mode : str
        ``"auto"`` (default) — vibes.ai, then fallbacks; ``"off"`` —
        vibes.ai only; ``"only"`` — skip vibes.ai.

    Returns
    -------
    dict
        ``{"audioBase64", "contentType", "engine", "voice"}`` — the same
        shape as :meth:`VibesClient.tts` plus the ``engine``/``voice`` keys.
    """
    import base64

    m = _parse_mode(mode)
    resolved = resolve_tts_voice(voice)
    explicit_fallback = is_edge_voice(voice) or parse_gtts_voice(voice) is not None

    if m != "only" and not explicit_fallback:
        try:
            resp = client._tts_raw(text, resolved["vibes"], output_format, language)
            resp.setdefault("engine", "vibes")
            resp.setdefault("voice", resolved["vibes"])
            return resp
        except Exception:
            if m == "off":
                raise

    errors: List[str] = []
    gtts_voice = parse_gtts_voice(voice)
    if gtts_voice is None:
        if edge_tts_available():
            try:
                audio = edge_tts_sync(text, resolved["edge"])
                return {
                    "audioBase64": base64.b64encode(audio).decode("ascii"),
                    "contentType": "audio/mpeg",
                    "engine": "edge-tts",
                    "voice": resolved["edge"],
                }
            except Exception as e:  # pragma: no cover - network dependent
                errors.append(f"edge-tts: {e}")
        else:
            errors.append("edge-tts: package not installed (pip install VibesAI-api[tts])")

    lang = language or gtts_voice or (resolved["edge"].split("-")[0] or "en")
    try:
        audio = gtts_sync(text, lang)
        return {
            "audioBase64": base64.b64encode(audio).decode("ascii"),
            "contentType": "audio/mpeg",
            "engine": "gtts",
            "voice": f"gtts-{lang}",
        }
    except Exception as e:  # pragma: no cover - network dependent
        errors.append(f"gtts: {e}")

    raise RuntimeError("all TTS engines failed — " + " | ".join(errors))


async def synthesize_speech_async(
    client: Any,
    text: str,
    voice: Optional[str],
    output_format: str = "mp3",
    language: Optional[str] = None,
    mode: Any = "auto",
) -> Dict[str, Any]:
    """Async variant of :func:`synthesize_speech` (for the FastAPI server).

    The vibes.ai attempt runs in a thread (requests is blocking); the Edge
    engine runs its native asyncio API.
    """
    import base64

    m = _parse_mode(mode)
    resolved = resolve_tts_voice(voice)
    explicit_fallback = is_edge_voice(voice) or parse_gtts_voice(voice) is not None

    if m != "only" and not explicit_fallback:
        try:
            resp = await asyncio.to_thread(
                client._tts_raw, text, resolved["vibes"], output_format, language
            )
            resp.setdefault("engine", "vibes")
            resp.setdefault("voice", resolved["vibes"])
            return resp
        except Exception:
            if m == "off":
                raise

    errors: List[str] = []
    gtts_voice = parse_gtts_voice(voice)
    if gtts_voice is None:
        if edge_tts_available():
            try:
                audio = await _edge_tts_async(text, resolved["edge"])
                return {
                    "audioBase64": base64.b64encode(audio).decode("ascii"),
                    "contentType": "audio/mpeg",
                    "engine": "edge-tts",
                    "voice": resolved["edge"],
                }
            except Exception as e:  # pragma: no cover - network dependent
                errors.append(f"edge-tts: {e}")
        else:
            errors.append("edge-tts: package not installed (pip install VibesAI-api[tts])")

    lang = language or gtts_voice or (resolved["edge"].split("-")[0] or "en")
    try:
        audio = await gtts_async(text, lang)
        return {
            "audioBase64": base64.b64encode(audio).decode("ascii"),
            "contentType": "audio/mpeg",
            "engine": "gtts",
            "voice": f"gtts-{lang}",
        }
    except Exception as e:  # pragma: no cover - network dependent
        errors.append(f"gtts: {e}")

    raise RuntimeError("all TTS engines failed — " + " | ".join(errors))
