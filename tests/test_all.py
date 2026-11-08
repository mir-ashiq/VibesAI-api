"""
Comprehensive test suite for the vibes_api package.

Run with:
    cd /home/z/my-project/download/vibes-api
    PYTHONPATH=. python3 -m pytest tests/test_all.py -v
    # OR without pytest:
    PYTHONPATH=. python3 tests/test_all.py

These tests do NOT hit the live API — they verify:
- Package imports cleanly
- All 127+ methods exist on VibesClient
- Composition class works (add/remove/resize/split clips, text overlays, etc.)
- Ingredient builders produce correct payload shapes
- Frame handle builder works
- Midjourney parameter parser extracts all parameters
- Validation helpers reject invalid inputs
- CLI parser builds without errors
- All endpoints discovered in JS bundles are covered by methods
"""

import os
import sys
import unittest
import unittest.mock

# Add the package to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vibes_api import (
    VibesClient, VibesAPIError, Composition,
    AspectRatio, Resolution, VideoModel, ImageModel, PromptModel,
    IngredientType, OwnerFilter, GenerationType, EntityType,
    SyncMode, TextOverlayPreset, TextOverlayPosition,
    IngredientRef, CreateIngredient, build_ingredient_payload,
)
from vibes_api.client import _uuid_v7, _coerce, _ms_now


class TestImports(unittest.TestCase):
    def test_all_exports_available(self):
        import vibes_api
        for name in vibes_api.__all__:
            self.assertTrue(hasattr(vibes_api, name), f"Missing export: {name}")

    def test_version_is_1_6_0(self):
        import vibes_api
        self.assertEqual(vibes_api.__version__, "1.6.0")

    def test_no_syntax_errors(self):
        import vibes_api.client
        import vibes_api.cli
        import vibes_api.models
        import vibes_api.ingredients
        import vibes_api.composition


class TestUUIDv7(unittest.TestCase):
    def test_uuid_v7_format(self):
        u = _uuid_v7()
        self.assertEqual(len(u), 36)

    def test_uuid_v7_encodes_timestamp(self):
        import time
        before = int(time.time() * 1000)
        u = _uuid_v7()
        after = int(time.time() * 1000)
        ts = int(u.replace("-", "")[:12], 16)
        self.assertGreaterEqual(ts, before - 1000)
        self.assertLessEqual(ts, after + 1000)

    def test_uuid_v7_version_nibble(self):
        self.assertEqual(_uuid_v7().replace("-", "")[12], "7")

    def test_uuid_v7_uniqueness(self):
        uuids = {_uuid_v7() for _ in range(100)}
        self.assertEqual(len(uuids), 100)


class TestCoerce(unittest.TestCase):
    def test_coerce_enum(self):
        self.assertEqual(_coerce(AspectRatio.LANDSCAPE), "16:9")

    def test_coerce_string(self):
        self.assertEqual(_coerce("16:9"), "16:9")


class TestComposition(unittest.TestCase):
    def setUp(self):
        self.comp = Composition.create_empty(duration=5.0)

    def test_empty_composition(self):
        self.assertEqual(self.comp.duration, 5.0)
        self.assertEqual(len(self.comp.tracks), 1)

    def test_add_video_clip(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=5, name="test")
        self.assertEqual(clip["name"], "test")
        self.assertEqual(len(self.comp.video_items), 1)

    def test_add_video_clip_extends_timeline(self):
        self.comp.add_video_clip(src="x", start=5, duration=10)
        self.assertEqual(self.comp.duration, 15.0)

    def test_add_image_clip(self):
        clip = self.comp.add_image_clip(src="img", start=0, duration=3)
        self.assertEqual(clip["mediaType"], "image")

    def test_add_audio_clip_creates_track(self):
        self.comp.add_audio_clip(src="a", start=0, duration=30, track_label="Music")
        self.assertEqual(len(self.comp.tracks), 2)

    def test_add_text_overlay(self):
        clip = self.comp.add_text_overlay(text="Hello", start=0, end=3, preset="fade")
        self.assertEqual(clip["text"], "Hello")
        self.assertEqual(clip["duration"], 3.0)
        self.assertEqual(clip["preset"], "fade")

    def test_add_text_overlay_invalid_times(self):
        with self.assertRaises(ValueError):
            self.comp.add_text_overlay(text="x", start=5, end=3)

    def test_resize_clip(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=5, source_duration=10)
        self.comp.resize_clip(clip_id=clip["id"], new_duration=7)
        self.assertEqual(clip["duration"], 7.0)

    def test_resize_clip_capped(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=5, source_duration=6)
        self.comp.resize_clip(clip_id=clip["id"], new_duration=10)
        self.assertEqual(clip["duration"], 6.0)

    def test_move_clip(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=5)
        self.comp.move_clip(clip_id=clip["id"], start_time=10)
        self.assertEqual(clip["start"], 10.0)

    def test_split_clip(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=10)
        new_id = self.comp.split_clip(clip_id=clip["id"], at_time=4)
        self.assertIsNotNone(new_id)
        self.assertEqual(clip["duration"], 4.0)
        _, new_clip = self.comp.find_clip(new_id)
        self.assertEqual(new_clip["start"], 4.0)
        self.assertEqual(new_clip["duration"], 6.0)

    def test_split_clip_invalid(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=5)
        self.assertIsNone(self.comp.split_clip(clip_id=clip["id"], at_time=-1))
        self.assertIsNone(self.comp.split_clip(clip_id=clip["id"], at_time=10))

    def test_duplicate_clip(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=5)
        new_id = self.comp.duplicate_clip(clip_id=clip["id"])
        self.assertIsNotNone(new_id)
        self.assertEqual(len(self.comp.video_items), 2)

    def test_delete_clip(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=5)
        self.assertTrue(self.comp.delete_clip(clip_id=clip["id"]))
        self.assertEqual(len(self.comp.video_items), 0)

    def test_delete_clip_not_found(self):
        self.assertFalse(self.comp.delete_clip(clip_id="nope"))

    def test_reorder_by_ordered_ids(self):
        c1 = self.comp.add_video_clip(src="1", start=0, duration=2, name="c1")
        c2 = self.comp.add_video_clip(src="2", start=2, duration=2, name="c2")
        c3 = self.comp.add_video_clip(src="3", start=4, duration=2, name="c3")
        self.comp.reorder_clips(ordered_clip_ids=[c3["id"], c2["id"], c1["id"]])
        items = self.comp.video_items
        self.assertEqual(items[0]["name"], "c3")
        self.assertEqual(items[2]["name"], "c1")

    def test_reorder_single_move(self):
        c1 = self.comp.add_video_clip(src="1", start=0, duration=2, name="c1")
        c2 = self.comp.add_video_clip(src="2", start=2, duration=2, name="c2")
        c3 = self.comp.add_video_clip(src="3", start=4, duration=2, name="c3")
        self.comp.reorder_clips(clip_id=c1["id"], to_index=2)
        self.assertEqual(self.comp.video_items[2]["name"], "c1")

    def test_extend_timeline_to(self):
        self.comp.add_video_clip(src="x", start=0, duration=5, source_duration=10)
        self.comp.extend_timeline_to(8.0)
        self.assertEqual(self.comp.duration, 8.0)
        self.assertEqual(self.comp.video_items[-1]["duration"], 8.0)

    def test_extend_timeline_to_shrink(self):
        self.comp.add_video_clip(src="x", start=0, duration=5, source_duration=10)
        self.comp.add_video_clip(src="y", start=5, duration=5, source_duration=10)
        self.comp.extend_timeline_to(7.0)
        self.assertEqual(self.comp.duration, 7.0)
        self.assertEqual(self.comp.video_items[-1]["duration"], 2.0)

    def test_set_fade(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=10)
        self.comp.set_fade(clip_id=clip["id"], fade_in=1.0, fade_out=0.5)
        self.assertEqual(clip["fadeIn"], 1.0)

    def test_set_fade_capped(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=4)
        self.comp.set_fade(clip_id=clip["id"], fade_in=5.0, fade_out=5.0)
        self.assertEqual(clip["fadeIn"], 2.0)

    def test_set_volume(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=5)
        track = self.comp.video_track
        self.comp.set_volume(track_id=track["id"], volume=0.5)
        self.assertEqual(clip["volume"], 0.5)

    def test_set_volume_clamped(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=5)
        track = self.comp.video_track
        self.comp.set_volume(track_id=track["id"], volume=2.0)
        self.assertEqual(clip["volume"], 1.0)

    def test_set_speed(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=10)
        self.comp.set_speed(clip_id=clip["id"], speed=2.0)
        self.assertEqual(clip["speed"], 2.0)
        self.assertEqual(clip["duration"], 5.0)

    def test_set_speed_invalid(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=10)
        self.assertFalse(self.comp.set_speed(clip_id=clip["id"], speed=20.0))
        self.assertFalse(self.comp.set_speed(clip_id=clip["id"], speed=0.0))

    def test_update_text_overlay(self):
        clip = self.comp.add_text_overlay(text="Original", start=0, end=3)
        self.comp.update_text_overlay(clip_id=clip["id"], text="Updated", preset="glow")
        self.assertEqual(clip["text"], "Updated")
        self.assertEqual(clip["preset"], "glow")

    def test_add_and_delete_track(self):
        track = self.comp.add_track("uploaded-audio", label="Music")
        self.assertEqual(len(self.comp.tracks), 2)
        self.assertTrue(self.comp.delete_track(track["id"]))
        self.assertEqual(len(self.comp.tracks), 1)

    def test_rename_track(self):
        track = self.comp.add_track("uploaded-audio", label="Music")
        self.comp.rename_track(track["id"], "Background")
        self.assertEqual(track["label"], "Background")

    def test_mute_track(self):
        track = self.comp.add_track("uploaded-audio", label="Music")
        self.comp.mute_track(track["id"], True)
        self.assertTrue(track.get("muted"))
        self.comp.mute_track(track["id"], False)
        self.assertFalse(track.get("muted"))

    def test_unlink_audio_from_video(self):
        video = self.comp.add_video_clip(src="v", start=0, duration=5)
        audio = self.comp.add_audio_clip(
            src="a", start=0, duration=5,
            linked_item_id=video["id"], link_type="video-audio",
        )
        self.comp.unlink_audio_from_video(audio_clip_id=audio["id"])
        self.assertNotIn("linkedItemId", audio)

    def test_link_audio_to_video(self):
        video = self.comp.add_video_clip(src="v", start=0, duration=5)
        audio = self.comp.add_audio_clip(src="a", start=0, duration=5)
        self.comp.link_audio_to_video(audio_clip_id=audio["id"], video_clip_id=video["id"])
        self.assertEqual(audio["linkedItemId"], video["id"])

    def test_slip_audio(self):
        audio = self.comp.add_audio_clip(src="a", start=0, duration=5, trim_start=2.0)
        self.comp.slip_audio(clip_id=audio["id"], slip_seconds=1.0)
        self.assertEqual(audio["trimStart"], 3.0)

    def test_replace_audio(self):
        audio = self.comp.add_audio_clip(src="old.mp3", start=0, duration=5)
        self.comp.replace_audio(clip_id=audio["id"], new_src="new.mp3", new_duration=10)
        self.assertEqual(audio["src"], "new.mp3")
        self.assertEqual(audio["duration"], 10.0)

    def test_delete_all_clips(self):
        self.comp.add_video_clip(src="x", start=0, duration=5)
        self.comp.add_text_overlay(text="hi", start=0, end=3)
        self.comp.delete_all_clips()
        self.assertEqual(sum(len(t.get("items", [])) for t in self.comp.tracks), 0)

    def test_delete_timeline(self):
        self.comp.add_video_clip(src="x", start=0, duration=5)
        self.comp.delete_timeline()
        self.assertEqual(len(self.comp.tracks), 0)
        self.assertEqual(self.comp.duration, 0.0)

    def test_summary(self):
        self.comp.add_video_clip(src="x", start=0, duration=5)
        s = self.comp.summary()
        self.assertEqual(s["track_count"], 1)
        self.assertEqual(s["total_clips"], 1)

    def test_clone_independence(self):
        self.comp.add_video_clip(src="x", start=0, duration=5)
        clone = self.comp.clone()
        clone.add_video_clip(src="y", start=5, duration=5)
        self.assertEqual(len(self.comp.video_items), 1)
        self.assertEqual(len(clone.video_items), 2)

    def test_to_dict_roundtrip(self):
        self.comp.add_video_clip(src="x", start=0, duration=5)
        d = self.comp.to_dict()
        comp2 = Composition(d)
        self.assertEqual(len(comp2.video_items), 1)

    def test_find_clip_by_name(self):
        clip = self.comp.add_video_clip(src="x", start=0, duration=5, name="my-clip")
        _, found = self.comp.find_clip_by_name("my-clip")
        self.assertEqual(found["id"], clip["id"])


class TestIngredients(unittest.TestCase):
    def test_ingredient_ref_by_id(self):
        ref = IngredientRef.by_id(
            ingredient_id="123", ingredient_type=IngredientType.CHARACTER,
            name="Test", image_url="x",
        )
        self.assertEqual(ref["ingredientId"], "123")
        self.assertEqual(ref["ingredientType"], "CHARACTER")

    def test_ingredient_ref_string_type(self):
        ref = IngredientRef.by_id(
            ingredient_id="123", ingredient_type="STYLE",
            name="Test", image_url="x",
        )
        self.assertEqual(ref["ingredientType"], "STYLE")

    def test_create_by_image_ent_id(self):
        ref = CreateIngredient.by_image_ent_id(
            image_ent_id="456", ingredient_type=IngredientType.STYLE,
            name="Cyberpunk", image_url="y",
        )
        self.assertEqual(ref["sourceImageEntId"], "456")

    def test_create_by_name(self):
        ref = CreateIngredient.by_name(ingredient_type=IngredientType.SETTING, name="Forest")
        self.assertEqual(ref["name"], "Forest")
        self.assertNotIn("sourceImageEntId", ref)

    def test_build_payload_routes(self):
        char = IngredientRef.by_id(ingredient_id="1", ingredient_type=IngredientType.CHARACTER,
                                    name="A", image_url="x")
        style = CreateIngredient.by_image_ent_id(image_ent_id="2", ingredient_type=IngredientType.STYLE,
                                                  name="B", image_url="y")
        payload = build_ingredient_payload(character=char, style=style)
        self.assertEqual(payload["ingredients"], [char])
        self.assertEqual(payload["createIngredients"], [style])

    def test_build_payload_empty(self):
        self.assertEqual(build_ingredient_payload(), {})


class TestFrameHandle(unittest.TestCase):
    def test_build_from_upload(self):
        h = VibesClient.build_frame_handle({
            "mediaEntId": "789", "imageUrl": "x", "imageHandle": "oil://abc",
        })
        self.assertEqual(h["oil_handle"], "oil://abc")
        self.assertEqual(h["image_ent_id"], "789")
        self.assertEqual(h["source"], "upload")

    def test_build_with_source(self):
        h = VibesClient.build_frame_handle({"mediaEntId": "1", "imageUrl": "x"}, source="asset")
        self.assertEqual(h["source"], "asset")


class TestEntityExtraction(unittest.TestCase):
    def test_video_ent_id_dict(self):
        self.assertEqual(
            VibesClient._extract_video_gen_ent_id({"data": {"videoGenEntId": "X"}}), "X"
        )

    def test_video_ent_id_json_string(self):
        self.assertEqual(
            VibesClient._extract_video_gen_ent_id({"data": '{"videoGenEntId": "X"}'}), "X"
        )

    def test_image_ent_id(self):
        self.assertEqual(
            VibesClient._extract_image_ent_id({"data": {"imageEntId": "Y"}}), "Y"
        )

    def test_returns_none_when_missing(self):
        self.assertIsNone(VibesClient._extract_video_gen_ent_id({}))
        self.assertIsNone(VibesClient._extract_image_ent_id({}))


class TestValidation(unittest.TestCase):
    def test_prompt_ok(self):
        self.assertTrue(VibesClient.validate_prompt_length("short")["success"])

    def test_prompt_too_long(self):
        self.assertFalse(VibesClient.validate_prompt_length("x" * 20000)["success"])

    def test_prompt_empty(self):
        self.assertTrue(VibesClient.validate_prompt_length("")["success"])

    def test_project_name_ok(self):
        self.assertTrue(VibesClient.validate_project_name("My Video")["success"])

    def test_project_name_too_long(self):
        self.assertFalse(VibesClient.validate_project_name("x" * 300)["success"])

    def test_username_short(self):
        self.assertFalse(VibesClient.validate_username("ab")["success"])

    def test_username_long(self):
        self.assertFalse(VibesClient.validate_username("x" * 40)["success"])

    def test_username_ok(self):
        self.assertTrue(VibesClient.validate_username("ashiq")["success"])

    def test_music_duration_ok(self):
        self.assertTrue(VibesClient.validate_music_clip_duration(0, 30000)["success"])

    def test_music_duration_too_long(self):
        self.assertFalse(VibesClient.validate_music_clip_duration(0, 90000)["success"])

    def test_music_duration_invalid(self):
        self.assertFalse(VibesClient.validate_music_clip_duration(30000, 10000)["success"])

    def test_image_size_not_found(self):
        self.assertFalse(VibesClient.validate_image_size("/nonexistent.png")["success"])

    def test_image_size_small_file(self):
        # Create a small valid PNG (1x1 pixel)
        import tempfile
        try:
            from PIL import Image
            img = Image.new("RGB", (1, 1), color="red")
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                img.save(f.name, "PNG")
                path = f.name
            try:
                result = VibesClient.validate_image_size(path)
                self.assertTrue(result["success"])
            finally:
                os.unlink(path)
        except ImportError:
            # PIL not available — skip
            self.skipTest("PIL not available")


class TestMidjourneyParser(unittest.TestCase):
    def test_sref_random(self):
        r = VibesClient.parse_midjourney_params("a cat --sref random")
        self.assertTrue(r["parameters"]["sref_random"])
        self.assertEqual(r["cleanPrompt"], "a cat")

    def test_sref_numeric(self):
        r = VibesClient.parse_midjourney_params("a cat --sref 12345 67890")
        self.assertEqual(r["parameters"]["sref_ids"], [12345, 67890])

    def test_oref(self):
        r = VibesClient.parse_midjourney_params("a cat --oref 12345")
        self.assertEqual(r["parameters"]["oref_ids"], [12345])

    def test_weights(self):
        r = VibesClient.parse_midjourney_params("a cat --sw 500 --ow 200")
        self.assertEqual(r["parameters"]["sref_weight"], 500.0)
        self.assertEqual(r["parameters"]["oref_weight"], 200.0)

    def test_seed(self):
        r = VibesClient.parse_midjourney_params("a cat --seed 42")
        self.assertEqual(r["parameters"]["seed"], 42)

    def test_chaos(self):
        r = VibesClient.parse_midjourney_params("a cat --chaos 50")
        self.assertEqual(r["parameters"]["chaos"], 50)

    def test_stylize(self):
        r = VibesClient.parse_midjourney_params("a cat --stylize 1000")
        self.assertEqual(r["parameters"]["stylize"], 1000)

    def test_aspect_ratio(self):
        r = VibesClient.parse_midjourney_params("a cat --ar 16:9")
        self.assertEqual(r["parameters"]["aspect_ratio"], "16:9")

    def test_version(self):
        r = VibesClient.parse_midjourney_params("a cat --v 5.2")
        self.assertEqual(r["parameters"]["version"], 5.2)

    def test_boolean_flags(self):
        r = VibesClient.parse_midjourney_params("a cat --niji --raw --tile --loop")
        self.assertTrue(r["parameters"]["niji"])
        self.assertTrue(r["parameters"]["raw"])
        self.assertTrue(r["parameters"]["tile"])
        self.assertTrue(r["parameters"]["loop"])

    def test_combined(self):
        prompt = "city --sref random --ar 16:9 --v 5.2 --chaos 75 --stylize 1000 --seed 42 --raw"
        r = VibesClient.parse_midjourney_params(prompt)
        self.assertEqual(r["cleanPrompt"], "city")
        self.assertTrue(r["parameters"]["sref_random"])
        self.assertEqual(r["parameters"]["aspect_ratio"], "16:9")

    def test_no_params(self):
        r = VibesClient.parse_midjourney_params("plain prompt")
        self.assertEqual(r["cleanPrompt"], "plain prompt")
        self.assertEqual(r["parameters"], {})


class TestMethodCoverage(unittest.TestCase):
    EXPECTED_METHODS = [
        # Auth
        "get_me", "get_system_status", "logout", "check_token",
        # Projects
        "list_projects", "get_project", "create_project", "update_project",
        "delete_project", "duplicate_project", "save_composition",
        # Batches
        "list_batches", "list_project_batches", "get_batch", "delete_batch",
        "poll_batch", "update_batch", "stream_batch_updates",
        "stream_batch_updates_resilient",
        # Video gen
        "generate_video", "extend_video", "auto_extend_video",
        "manual_extend_video", "edit_video", "animate_image",
        "auto_animate_image", "manual_animate_image", "regenerate_batch",
        # Image gen
        "generate_image", "edit_image", "enhance_prompt",
        # Lip sync
        "generate_lipsync", "generate_heygen_avatar", "regenerate_lipsync",
        # TTS
        "list_voices", "tts", "save_tts_audio",
        # Uploads
        "upload_image", "upload_image_file", "upload_video_direct",
        "upload_audio_direct", "upload_media", "upload_profile_picture",
        "upload_profile_picture_file", "upload_video_resumable",
        "upload_images_batch", "bulk_upload_to_project",
        # Media library
        "list_media", "list_media_by_ingredient", "favorite_content_item",
        "delete_content_item", "delete_content_items", "retry_content_item",
        "feedback_content_item", "get_media_item", "delete_media_item",
        "list_media_item_projects",
        # Download
        "download_video", "download_image", "download_content",
        # Share
        "create_share_link", "list_share_links", "revoke_share_link",
        "reset_share_link",
        # Ingredients
        "list_ingredients", "list_characters", "list_styles", "list_scenes",
        "create_ingredient", "delete_ingredient", "update_ingredient",
        "list_ingredient_projects", "bulk_delete_ingredients",
        # Moodboards
        "list_moodboards", "get_moodboard", "create_moodboard",
        "delete_moodboard", "update_moodboard", "lookup_moodboard_by_code",
        # Music
        "search_music", "search_music_filtered", "lookup_music_thumbnail",
        "clip_music", "clip_audio", "check_original_audio",
        "resolve_audio_urls", "proxy_audio_url", "proxy_audio_url_signed",
        # Timeline chat
        "timeline_chat", "timeline_chat_multi_turn", "submit_tool_result",
        # Timeline export
        "export_timeline", "export_timeline_async", "check_export_status",
        "cancel_export", "get_pending_export", "get_last_export",
        # Revision history
        "list_revisions", "save_revision",
        # Project assets
        "list_project_assets", "add_project_asset", "remove_project_asset",
        "import_project_assets", "list_available_assets",
        # Collaborators
        "list_collaborators", "remove_collaborator",
        # Sync
        "get_sync_status", "stream_sync_updates", "stream_sync_updates_resilient",
        # Account
        "delete_account", "delete_all_media", "remove_all_posts",
        # Quota & rate limit
        "get_quota_upsell", "get_rate_limit_status",
        # Bug reports
        "report_bug", "record_consent", "log_analytics", "log_analytics_event",
        # Playables
        "list_playables", "get_playable", "create_playable",
        "update_playable", "delete_playable", "duplicate_playable",
        "generate_playable_thumbnail",
        # Publishing
        "publish_to_vibes",
        # Composition helpers
        "get_composition", "save_composition_obj", "build_frame_handle",
        # Validation
        "validate_prompt_length", "validate_project_name", "validate_username",
        "validate_image_size", "validate_music_clip_duration",
        "validate_music_clip_short",
        # Midjourney
        "parse_midjourney_params",
        # One-shot
        "create_video_from_prompt",
    ]

    def test_all_methods_exist(self):
        missing = [m for m in self.EXPECTED_METHODS if not hasattr(VibesClient, m)]
        self.assertEqual(missing, [], f"Missing methods: {missing}")

    def test_method_count(self):
        methods = [m for m in dir(VibesClient) if not m.startswith("_") and callable(getattr(VibesClient, m))]
        self.assertGreaterEqual(len(methods), 120, f"Got {len(methods)} methods")


class TestV160Features(unittest.TestCase):
    """Tests for v1.6.0 additions (2026-11 vibes.ai parity updates)."""

    def test_mg_request_id_format(self):
        from vibes_api.client import _mg_request_id
        rid = _mg_request_id()
        self.assertTrue(rid.startswith("www-"))
        rest = rid[4:]
        self.assertEqual(len(rest), 36)
        self.assertEqual(rest[14], "7")  # UUID v7 version nibble
        self.assertIn(rest[19], "89ab")  # variant

    def test_base36_id_format(self):
        from vibes_api.client import _base36_id
        s = _base36_id(7)
        self.assertEqual(len(s), 7)
        self.assertTrue(all(c in "abcdefghijklmnopqrstuvwxyz0123456789" for c in s))

    def test_composition_id_matches_ui_format(self):
        from vibes_api.composition import _new_id
        cid = _new_id("video-track")
        ms, rand = cid.split("-")[-2:]
        self.assertTrue(cid.startswith("video-track-"))
        self.assertTrue(ms.isdigit())
        self.assertEqual(len(rand), 7)
        self.assertTrue(all(c in "abcdefghijklmnopqrstuvwxyz0123456789" for c in rand))

    def test_new_media_methods_exist(self):
        for m in ("get_media_item", "delete_media_item", "list_media_item_projects"):
            self.assertTrue(hasattr(VibesClient, m))

    def test_new_ingredient_methods_exist(self):
        for m in ("list_ingredient_projects", "bulk_delete_ingredients"):
            self.assertTrue(hasattr(VibesClient, m))

    def test_revision_methods_exist(self):
        for m in ("list_revisions", "save_revision"):
            self.assertTrue(hasattr(VibesClient, m))

    def test_analytics_methods_exist(self):
        for m in ("log_analytics", "log_analytics_event"):
            self.assertTrue(hasattr(VibesClient, m))

    def test_get_last_export_exists(self):
        self.assertTrue(hasattr(VibesClient, "get_last_export"))

    def test_favorite_is_toggle(self):
        # v1.6.0: favorite_content_item is a pure toggle (no body),
        # mirroring the web app's heart icon.
        import inspect
        sig = inspect.signature(VibesClient.favorite_content_item)
        params = list(sig.parameters)
        self.assertEqual(params, ["self", "content_item_id"])

    def test_search_music_accepts_tab(self):
        import inspect
        sig = inspect.signature(VibesClient.search_music)
        self.assertIn("tab", sig.parameters)

    def test_list_voices_accepts_limit(self):
        import inspect
        sig = inspect.signature(VibesClient.list_voices)
        self.assertIn("limit", sig.parameters)

    def test_generate_video_source_has_mg_request_id(self):
        # All /api/generate/* payloads now carry mg_request_id + projectId.
        import vibes_api.client as cm
        source = open(cm.__file__).read()
        self.assertIn("mg_request_id", source)
        count = source.count('"mg_request_id": _mg_request_id()')
        self.assertGreaterEqual(count, 6, f"expected >=6 generate call sites, got {count}")

    def test_settings_use_delete_method(self):
        # v1.6.0: the three destructive settings endpoints use DELETE.
        import vibes_api.client as cm
        source = open(cm.__file__).read()
        self.assertIn('self._delete("/api/settings/delete-account")', source)
        self.assertIn('self._delete("/api/settings/delete-all-media")', source)
        self.assertIn('self._delete("/api/settings/remove-all-posts")', source)

    def test_report_bug_signature(self):
        import inspect
        sig = inspect.signature(VibesClient.report_bug)
        self.assertIn("description", sig.parameters)
        self.assertIn("product", sig.parameters)


class TestCLI(unittest.TestCase):
    def test_cli_import(self):
        from vibes_api import cli
        self.assertTrue(hasattr(cli, "build_parser"))

    def test_cli_builds(self):
        from vibes_api.cli import build_parser
        self.assertIsNotNone(build_parser())

    def test_cli_subcommands(self):
        from vibes_api.cli import build_parser
        parser = build_parser()
        subparsers = [a for a in parser._actions if hasattr(a, "choices") and isinstance(a.choices, dict)]
        self.assertTrue(len(subparsers) > 0)
        choices = subparsers[0].choices
        for cmd in ["me", "projects", "videos", "images", "voices", "tts",
                    "media", "prompts", "ingredients", "share", "batches",
                    "music", "chat", "one-shot", "sync", "quota",
                    # v1.2.0
                    "publish", "moodboard-update", "moodboard-lookup",
                    "share-reset", "playables", "ingredients-update",
                    "audio-resolve", "audio-proxy", "check-token",
                    "rate-limit", "pending-export", "parse-midjourney",
                    "validate-prompt"]:
            self.assertIn(cmd, choices, f"Missing subcommand: {cmd}")


class TestEnums(unittest.TestCase):
    def test_aspect_ratio(self):
        self.assertEqual(AspectRatio.LANDSCAPE.value, "16:9")

    def test_resolution(self):
        self.assertEqual(Resolution.P720.value, "720p")

    def test_video_model(self):
        self.assertEqual(VideoModel.SHORT.value, "midjen-short")

    def test_ingredient_type(self):
        self.assertEqual(IngredientType.CHARACTER.value, "CHARACTER")

    def test_generation_type(self):
        self.assertEqual(GenerationType.TEXT_TO_VIDEO.value, "t2v")

    def test_text_overlay_preset(self):
        self.assertEqual(TextOverlayPreset.FADE.value, "fade")

    def test_text_overlay_position(self):
        self.assertEqual(TextOverlayPosition.TOP_LEFT.value, "top-left")

    def test_entity_type(self):
        self.assertEqual(EntityType.PROJECT.value, "project")

    def test_sync_mode(self):
        self.assertEqual(SyncMode.SSE.value, "sse")


class TestClientConstruction(unittest.TestCase):
    def test_construct(self):
        c = VibesClient(meta_session="x")
        self.assertEqual(c.base_url, "https://vibes.ai")

    def test_construct_with_options(self):
        c = VibesClient(meta_session="x", base_url="https://staging.vibes.ai", timeout=120)
        self.assertEqual(c.base_url, "https://staging.vibes.ai")
        self.assertEqual(c.timeout, 120)

    def test_headers_set(self):
        c = VibesClient(meta_session="my-cookie")
        self.assertIn("meta_session=my-cookie", c.session.headers["Cookie"])


class TestRateLimit(unittest.TestCase):
    def test_initial_status(self):
        c = VibesClient(meta_session="x")
        self.assertFalse(c.get_rate_limit_status()["is_rate_limited"])

    def test_set_cooldown(self):
        c = VibesClient(meta_session="x")
        c._set_rate_limit_cooldown(seconds=60)
        s = c.get_rate_limit_status()
        self.assertTrue(s["is_rate_limited"])
        self.assertGreater(s["rate_limit_seconds_left"], 50)

    def test_check_raises_when_limited(self):
        c = VibesClient(meta_session="x")
        c._set_rate_limit_cooldown(seconds=60)
        with self.assertRaises(VibesAPIError) as ctx:
            c._check_rate_limit()
        self.assertEqual(ctx.exception.status, 429)


class TestEndpointCoverage(unittest.TestCase):
    ALL_ENDPOINTS = [
        "/api/analytics", "/api/animate/generate", "/api/auth/check-token",
        "/api/auth/logout", "/api/auth/me", "/api/bug-report",
        "/api/collaborators", "/api/consent/record",
        "/api/content-items/bulk-delete",
        "/api/download/png", "/api/download/video",
        "/api/generate/image-edit", "/api/generate/images",
        "/api/generate/prompts", "/api/generate/videos",
        "/api/generation-batches", "/api/media-library",
        "/api/media/audio/clip", "/api/media/music/clip",
        "/api/meta-graphql", "/api/meta-music", "/api/meta-music/lookup",
        "/api/meta-music/oa-check", "/api/meta-profiles/publish",
        "/api/moodboards", "/api/playables", "/api/projects",
        "/api/proxy-audio", "/api/quota/upsell", "/api/resolve-audio-urls",
        "/api/revisions", "/api/settings/delete-account",
        "/api/settings/delete-all-media", "/api/settings/remove-all-posts",
        "/api/share-links", "/api/studio/ingredients",
        "/api/studio/ingredients/bulk-delete", "/api/studio/playai/tts",
        "/api/studio/voices", "/api/sync", "/api/sync/stream",
        "/api/system-status", "/api/timeline/chat/stream",
        "/api/upload-asset", "/api/upload-audio-direct", "/api/upload-image",
        "/api/upload-media", "/api/upload-profile-picture",
        "/api/upload-video-direct",
    ]

    def test_all_endpoints_in_source(self):
        import vibes_api.client as cm
        source = open(cm.__file__).read()
        missing = [e for e in self.ALL_ENDPOINTS if e not in source]
        self.assertEqual(missing, [], f"Endpoints not in source: {missing}")


class TestServerAuthEnv(unittest.TestCase):
    """server/app.py get_client() env wiring: VIBES_META_SESSION + AUTH_META_COOKIES."""

    ENV_KEYS = ("VIBES_META_SESSION", "AUTH_META_COOKIES", "VIBES_COOKIE_FILE",
                "VIBES_REFRESH_INTERVAL", "VIBES_API_KEY")

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.ENV_KEYS}
        # NB: `import server.app` binds the FastAPI instance (server/__init__.py
        # re-exports `app`), so import the module object explicitly:
        import importlib
        self.app_mod = importlib.import_module("server.app")
        self._saved_client = self.app_mod._client
        self.app_mod._client = None

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.app_mod._client = self._saved_client

    def test_missing_meta_session_raises(self):
        os.environ.pop("VIBES_META_SESSION", None)
        os.environ.pop("VIBES_COOKIE_FILE", None)
        with self.assertRaises(Exception) as ctx:
            self.app_mod.get_client()
        msg = getattr(ctx.exception, "detail", str(ctx.exception))
        self.assertIn("VIBES_META_SESSION", str(msg))

    def test_auth_meta_cookies_enables_relogin(self):
        os.environ["VIBES_META_SESSION"] = "test-session-token"
        os.environ["AUTH_META_COOKIES"] = "ps_n=1; ps_l=1; datr=X; locale=en_GB"
        os.environ.pop("VIBES_COOKIE_FILE", None)
        c = self.app_mod.get_client()
        self.assertEqual(c.auth_meta_cookies, "ps_n=1; ps_l=1; datr=X; locale=en_GB")
        self.assertTrue(c.auto_relogin)
        self.assertEqual(c.get_current_cookie(), "test-session-token")
        c.stop_background_refresh()

    def test_no_auth_meta_cookies_leaves_relogin_off(self):
        os.environ["VIBES_META_SESSION"] = "test-session-token"
        os.environ.pop("AUTH_META_COOKIES", None)
        os.environ.pop("VIBES_COOKIE_FILE", None)
        c = self.app_mod.get_client()
        self.assertIsNone(c.auth_meta_cookies)
        self.assertFalse(c.auto_relogin)
        c.stop_background_refresh()

    def test_blank_auth_meta_cookies_is_ignored(self):
        os.environ["VIBES_META_SESSION"] = "test-session-token"
        os.environ["AUTH_META_COOKIES"] = "   "
        os.environ.pop("VIBES_COOKIE_FILE", None)
        c = self.app_mod.get_client()
        self.assertIsNone(c.auth_meta_cookies)
        self.assertFalse(c.auto_relogin)
        c.stop_background_refresh()

    def test_cookie_file_overrides_env_session(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".cookie", delete=False) as f:
            f.write("file-cookie-token")
            path = f.name
        try:
            os.environ["VIBES_META_SESSION"] = "env-session-token"
            os.environ["VIBES_COOKIE_FILE"] = path
            os.environ.pop("AUTH_META_COOKIES", None)
            c = self.app_mod.get_client()
            self.assertEqual(c.get_current_cookie(), "file-cookie-token")
            c.stop_background_refresh()
        finally:
            os.unlink(path)


class TestTtsFallback(unittest.TestCase):
    """vibes_api.tts_fallback — voice resolution, chunking, engine chain."""

    def test_voice_resolution_openai_names(self):
        from vibes_api.tts_fallback import resolve_tts_voice
        r = resolve_tts_voice("alloy")
        self.assertEqual(r["vibes"], "play_ai_Marisol")
        self.assertEqual(r["edge"], "en-US-JennyNeural")
        r2 = resolve_tts_voice(None)
        self.assertEqual(r2["vibes"], "play_ai_Marisol")

    def test_voice_resolution_edge_and_gtts(self):
        from vibes_api.tts_fallback import is_edge_voice, parse_gtts_voice, resolve_tts_voice
        self.assertTrue(is_edge_voice("en-GB-RyanNeural"))
        self.assertFalse(is_edge_voice("play_ai_Marisol"))
        self.assertEqual(parse_gtts_voice("gtts-ja"), "ja")
        self.assertEqual(parse_gtts_voice("gtts"), "en")
        self.assertIsNone(parse_gtts_voice("alloy"))
        r = resolve_tts_voice("en-GB-RyanNeural")
        self.assertEqual(r["edge"], "en-GB-RyanNeural")

    def test_voice_resolution_playai_passthrough(self):
        from vibes_api.tts_fallback import resolve_tts_voice
        r = resolve_tts_voice("play_ai_Thunder")
        self.assertEqual(r["vibes"], "play_ai_Thunder")
        self.assertEqual(r["edge"], "en-US-ChristopherNeural")

    def test_chunk_text(self):
        from vibes_api.tts_fallback import _chunk_text
        self.assertEqual(_chunk_text("short", 100), ["short"])
        long_text = "Sentence one. Sentence two. " * 20
        chunks = _chunk_text(long_text, 50)
        self.assertTrue(all(len(c) <= 50 for c in chunks))
        self.assertEqual("".join(chunks).replace(" ", ""), long_text.replace(" ", ""))

    def test_gtts_language_mapping(self):
        from vibes_api.tts_fallback import _to_gtts_language
        self.assertEqual(_to_gtts_language("eng"), "en")
        self.assertEqual(_to_gtts_language("hin"), "hi")
        self.assertEqual(_to_gtts_language("zh"), "zh-CN")
        self.assertEqual(_to_gtts_language(None), "en")

    def _fake_client(self, raises=False):
        class Fake:
            def __init__(self, raises):
                self.raises = raises
                self.calls = []
            def _tts_raw(self, text, voice, output_format, language):
                self.calls.append((text, voice))
                if self.raises:
                    raise RuntimeError("TTS error: 403 Facebook expired access token")
                return {"audioBase64": "dmlicw==", "contentType": "audio/mpeg"}
        return Fake(raises)

    def test_chain_uses_vibes_when_healthy(self):
        from vibes_api import synthesize_speech
        fake = self._fake_client(raises=False)
        out = synthesize_speech(fake, "hi", "alloy")
        self.assertEqual(out["engine"], "vibes")
        self.assertEqual(fake.calls, [("hi", "play_ai_Marisol")])

    def test_chain_falls_back_when_vibes_down(self):
        from vibes_api import tts_fallback as tf
        fake = self._fake_client(raises=True)
        # Fake both fallback engines (no network in unit tests).
        saved_edge, saved_gtts = tf.edge_tts_sync, tf.gtts_sync
        try:
            tf.edge_tts_sync = lambda text, voice, rate="+0%": b"EDGEMP3"
            out = tf.synthesize_speech(fake, "hi", "alloy")
            self.assertEqual(out["engine"], "edge-tts")
            self.assertEqual(out["contentType"], "audio/mpeg")
            import base64 as b64
            self.assertEqual(b64.b64decode(out["audioBase64"]), b"EDGEMP3")

            tf.edge_tts_sync = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("edge down"))
            tf.gtts_sync = lambda text, language=None, slow=False: b"GTTSMP3"
            out2 = tf.synthesize_speech(fake, "hi", "alloy")
            self.assertEqual(out2["engine"], "gtts")
            self.assertEqual(b64.b64decode(out2["audioBase64"]), b"GTTSMP3")

            # Both engines down -> error mentioning them
            tf.gtts_sync = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gtts down"))
            with self.assertRaises(RuntimeError) as ctx:
                tf.synthesize_speech(fake, "hi", "alloy")
            self.assertIn("all TTS engines failed", str(ctx.exception))
        finally:
            tf.edge_tts_sync, tf.gtts_sync = saved_edge, saved_gtts

    def test_mode_off_reraises_vibes_error(self):
        from vibes_api import synthesize_speech
        fake = self._fake_client(raises=True)
        with self.assertRaises(RuntimeError):
            synthesize_speech(fake, "hi", "alloy", mode="off")

    def test_mode_only_skips_vibes(self):
        from vibes_api import tts_fallback as tf
        fake = self._fake_client(raises=False)
        saved_edge = tf.edge_tts_sync
        try:
            tf.edge_tts_sync = lambda text, voice, rate="+0%": b"EDGEONLY"
            out = tf.synthesize_speech(fake, "hi", "alloy", mode="only")
            self.assertEqual(out["engine"], "edge-tts")
            self.assertEqual(fake.calls, [])  # vibes never called
        finally:
            tf.edge_tts_sync = saved_edge

    def test_explicit_gtts_voice_skips_vibes_and_edge(self):
        from vibes_api import tts_fallback as tf
        fake = self._fake_client(raises=False)
        saved_gtts = tf.gtts_sync
        try:
            tf.gtts_sync = lambda text, language=None, slow=False: b"JA-MP3"
            out = tf.synthesize_speech(fake, "こんにちは", "gtts-ja")
            self.assertEqual(out["engine"], "gtts")
            self.assertEqual(out["voice"], "gtts-ja")
            self.assertEqual(fake.calls, [])
        finally:
            tf.gtts_sync = saved_gtts

    def test_client_tts_delegates(self):
        from vibes_api import VibesClient
        c = VibesClient(meta_session="test-cookie", auto_refresh=False)
        with unittest.mock.patch.object(c, "_tts_raw") as raw:
            raw.return_value = {"audioBase64": "eA==", "contentType": "audio/mpeg"}
            out = c.tts("hi", "alloy")
            self.assertEqual(out["engine"], "vibes")
            raw.assert_called_once_with("hi", "play_ai_Marisol", "mp3", None)
        # allow_fallback=False bypasses the chain entirely
        with unittest.mock.patch.object(c, "_tts_raw") as raw:
            raw.return_value = {"audioBase64": "eA=="}
            out2 = c.tts("hi", "play_ai_Marisol", allow_fallback=False)
            self.assertNotIn("engine", out2)

    def test_server_tts_env_mode(self):
        import importlib
        app_mod = importlib.import_module("server.app")
        self.assertIn("synthesize_speech_async", dir(app_mod))


if __name__ == "__main__":
    unittest.main(verbosity=2)
