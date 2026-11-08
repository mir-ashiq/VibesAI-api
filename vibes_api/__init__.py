"""
Vibes AI - Unofficial Python API Client
=======================================

A Python wrapper around the vibes.ai private REST API. Supports:

  - Project management (list / create / get / update / delete / duplicate)
  - Text-to-video generation (midjen-short, 9:16/16:9/1:1, 480p/720p)
  - Text-to-image generation (midjen-base, multiple aspect ratios)
  - **Video extend (auto + manual)** — extend a video by ~5 seconds
  - **Video-to-video editing (v2v)** — re-render with a directive
  - **Image-to-video animate (auto + manual)** — animate a still image
  - **Batch regeneration** — re-roll with same or new prompt
  - **Start/end frame** support (image-to-video with keyframes)
  - **Ingredients** (characters, styles, scenes) — apply, create inline,
    or CRUD via the studio API
  - **Moodboards** — apply style references
  - Image editing (prompt-driven)
  - Prompt enhancement (returns 4 AI-rewritten variations)
  - Lip sync / animation generation
  - Text-to-speech (TTS) with 41 preset voices
  - Media library (list / favorite / delete / download)
  - Generation batch polling & **SSE streaming**
  - Share links
  - Studio ingredients (characters, styles, settings)
  - Timeline chat (streaming AI assistant)
  - Music / audio clip extraction
  - Direct file uploads (image / video / audio / profile picture)
  - Timeline export to MP4 (sync + async SurfGuard)
  - **Real-time sync** (SSE for collaborative editing)
  - Account settings (delete account / media / posts)
  - Quota & upsell info
  - Bug reports & consent

Authentication
--------------
This client uses cookie-based auth. Provide your `meta_session` cookie value
(obtained from your browser after logging in at https://vibes.ai). Cookies
rotate, so refresh when needed.

Example
-------
    from vibes_api import VibesClient, AspectRatio, Resolution, IngredientType
    from vibes_api.ingredients import IngredientRef, CreateIngredient

    client = VibesClient(meta_session="e60e910a-...-K54E")
    project = client.create_project(name="My first video")

    # Apply a saved character ingredient
    character = IngredientRef.by_id(
        ingredient_id="800957099700717",
        ingredient_type=IngredientType.CHARACTER,
        name="Valdrin",
        image_url="https://...",
    )

    batch = client.generate_video(
        project_id=project["id"],
        prompt="A serene mountain landscape at sunset",
        aspect_ratio=AspectRatio.LANDSCAPE,
        resolution=Resolution.P720,
        variations=4,
        ingredients=[character],
    )

    # Auto-extend the first variation by ~5 seconds
    extended = client.extend_video(
        project_id=project["id"],
        source_video=batch["content"][0],
    )

    client.download_video(extended["content"][0]["id"], "sunset.mp4")
"""

from .client import VibesClient, VibesAPIError
from .models import (
    AspectRatio,
    EntityType,
    GenerationType,
    ImageModel,
    IngredientType,
    OwnerFilter,
    PromptModel,
    Resolution,
    SyncMode,
    TextOverlayPosition,
    TextOverlayPreset,
    VideoModel,
)
from .ingredients import (
    IngredientRef,
    CreateIngredient,
    build_ingredient_payload,
)
from .composition import Composition

__version__ = "1.6.0"
__all__ = [
    # Client
    "VibesClient",
    "VibesAPIError",
    # Enums
    "AspectRatio",
    "EntityType",
    "GenerationType",
    "ImageModel",
    "IngredientType",
    "OwnerFilter",
    "PromptModel",
    "Resolution",
    "SyncMode",
    "TextOverlayPosition",
    "TextOverlayPreset",
    "VideoModel",
    # Ingredient helpers
    "IngredientRef",
    "CreateIngredient",
    "build_ingredient_payload",
    # Composition helper
    "Composition",
]
