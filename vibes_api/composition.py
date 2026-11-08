"""
Timeline Composition helpers — manipulate the composition JSON that
Vibes uses to represent a video timeline (tracks, clips, text overlays,
audio, effects).

The web app does all of these operations **client-side** before saving
the composition via ``PUT /api/projects/{id}`` (or
``POST /api/projects/{id}/timeline/download`` for export). This module
mirrors that behavior so you can build / edit timelines programmatically.

Composition structure
---------------------
A composition is a dict shaped like::

    {
        "id": "studio-composition",
        "tracks": [
            {
                "id": "video-track",
                "type": "video",
                "label": "Video",
                "items": [
                    {
                        "id": "clip-1",
                        "trackId": "video-track",
                        "name": "sunset",
                        "src": "https://.../sunset.mp4",
                        "start": 0.0,
                        "duration": 5.0,
                        "sourceDuration": 5.0,
                        "mediaType": "video",
                        "trimStart": 0.0,
                        "trimEnd": 0.0,
                        "fadeIn": 0.0,
                        "fadeOut": 0.0,
                        "volume": 1.0,
                        "speed": 1.0,
                        "muted": False,
                    },
                    ...
                ],
            },
            {
                "id": "text-track",
                "type": "text",
                "label": "Text",
                "items": [
                    {
                        "id": "text-1",
                        "trackId": "text-track",
                        "text": "Hello world",
                        "start": 0.0,
                        "duration": 3.0,
                        "fontSize": 48,
                        "color": "#FFFFFF",
                        "position": "center",
                        "preset": "fade",
                    },
                ],
            },
            {
                "id": "music-track",
                "type": "uploaded-audio",
                "label": "Music",
                "items": [
                    {
                        "id": "music-1",
                        "trackId": "music-track",
                        "name": "Lofi beat",
                        "src": "https://.../music.mp3",
                        "start": 0.0,
                        "duration": 30.0,
                        "sourceDuration": 30.0,
                        "volume": 0.5,
                        "fadeIn": 0.5,
                        "fadeOut": 1.0,
                    },
                ],
            },
        ],
        "duration": 30.0,
    }

Example
-------
    from vibes_api import VibesClient
    from vibes_api.composition import Composition

    client = VibesClient(meta_session="...")
    project = client.get_project("...")
    comp = Composition(project["composition"])

    # Add a video clip at 5s
    comp.add_video_clip(src="https://.../clip.mp4", start=5.0, duration=5.0, name="intro")

    # Add a text overlay from 0-3s with fade preset
    comp.add_text_overlay(text="Welcome!", start=0.0, end=3.0, preset="fade")

    # Resize the first video clip to 4 seconds
    comp.resize_clip(clip_id=comp.video_track["items"][0]["id"], new_duration=4.0)

    # Save back to the project
    client.save_composition(project["id"], comp.to_dict())
"""

from __future__ import annotations

import copy
import secrets
import string
import time
from typing import Any, Dict, List, Optional, Tuple, Union


_BASE36 = string.ascii_lowercase + string.digits


def _new_id(prefix: str = "clip") -> str:
    """Generate a unique clip/track ID.

    Matches the web app format: ``{prefix}-{ms}-{base36(7)}``
    (e.g. ``video-track-1794116980657-lyqa0p9``).
    """
    rand = "".join(secrets.choice(_BASE36) for _ in range(7))
    return f"{prefix}-{int(time.time() * 1000)}-{rand}"


class Composition:
    """A builder/manipulator for a Vibes timeline composition.

    Wrap an existing composition dict (from ``client.get_project(id)["composition"]``)
    or start from scratch with ``Composition.create_empty()``.

    All operations mutate the composition in place; call ``to_dict()`` to
    serialize for saving.
    """

    # ---- Construction ----
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self._data: Dict[str, Any] = copy.deepcopy(data) if data else self.create_empty()._data

    @classmethod
    def create_empty(cls, duration: float = 5.0) -> "Composition":
        """Create a fresh empty composition with one video track."""
        return cls({
            "id": "studio-composition",
            "tracks": [
                {
                    "id": "video-track",
                    "type": "video",
                    "label": "Video",
                    "items": [],
                }
            ],
            "duration": duration,
        })

    @classmethod
    def from_project(cls, project: Dict[str, Any]) -> "Composition":
        """Build a Composition from a project dict returned by ``get_project()``."""
        return cls(project.get("composition"))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict (for ``client.save_composition()``)."""
        return copy.deepcopy(self._data)

    def clone(self) -> "Composition":
        """Return a deep copy of this composition."""
        return Composition(self.to_dict())

    # ---- Properties ----
    @property
    def tracks(self) -> List[Dict[str, Any]]:
        return self._data.get("tracks", [])

    @property
    def duration(self) -> float:
        return float(self._data.get("duration", 0.0))

    @duration.setter
    def duration(self, value: float) -> None:
        self._data["duration"] = float(value)

    @property
    def video_track(self) -> Optional[Dict[str, Any]]:
        """First track of type 'video' (creates one if missing)."""
        for t in self.tracks:
            if t.get("type") == "video":
                return t
        # Create one
        return self.add_track(track_type="video", label="Video", track_id="video-track")

    @property
    def text_track(self) -> Optional[Dict[str, Any]]:
        for t in self.tracks:
            if t.get("type") == "text":
                return t
        return self.add_track(track_type="text", label="Text", track_id="text-track")

    @property
    def video_items(self) -> List[Dict[str, Any]]:
        """All clips in the video track."""
        vt = self.video_track
        return vt["items"] if vt else []

    @property
    def total_video_duration(self) -> float:
        """End time of the last video clip."""
        if not self.video_items:
            return 0.0
        return max(item.get("start", 0) + item.get("duration", 0)
                   for item in self.video_items)

    # ---- Track operations ----
    def add_track(
        self,
        track_type: str,
        label: Optional[str] = None,
        track_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a new track.

        Parameters
        ----------
        track_type : str
            "video", "text", "uploaded-audio", "library-music", or custom.
        label : str, optional
            Display name for the track.
        track_id : str, optional
            Stable ID; auto-generated if omitted.
        """
        track_id = track_id or _new_id("track")
        label = label or track_type.capitalize()
        track = {"id": track_id, "type": track_type, "label": label, "items": []}
        self._data.setdefault("tracks", []).append(track)
        return track

    def get_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        for t in self.tracks:
            if t["id"] == track_id:
                return t
        return None

    def delete_track(self, track_id: str) -> bool:
        """Delete an entire track and all its clips. Returns True if found."""
        before = len(self.tracks)
        self._data["tracks"] = [t for t in self.tracks if t["id"] != track_id]
        return len(self.tracks) < before

    def rename_track(self, track_id: str, label: str) -> bool:
        """Rename a track. Returns True if found."""
        t = self.get_track(track_id)
        if t:
            t["label"] = label
            return True
        return False

    def mute_track(self, track_id: str, muted: bool = True) -> bool:
        """Mute or unmute a track. Returns True if found."""
        t = self.get_track(track_id)
        if t:
            t["muted"] = muted
            return True
        return False

    # ---- Clip lookup helpers ----
    def find_clip(self, clip_id: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Find a clip by ID across all tracks.

        Returns ``(track, clip)`` or ``(None, None)`` if not found.
        """
        for t in self.tracks:
            for c in t.get("items", []):
                if c.get("id") == clip_id:
                    return t, c
        return None, None

    def find_clip_by_name(self, name: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Find the first clip with a matching name. Returns ``(track, clip)``."""
        for t in self.tracks:
            for c in t.get("items", []):
                if c.get("name") == name:
                    return t, c
        return None, None

    # ---- Adding clips ----
    def add_video_clip(
        self,
        *,
        src: str,
        start: float,
        duration: Optional[float] = None,
        source_duration: Optional[float] = None,
        name: Optional[str] = None,
        track_id: Optional[str] = None,
        media_type: str = "video",
        content_item_id: Optional[str] = None,
        trim_start: float = 0.0,
        trim_end: float = 0.0,
        volume: float = 1.0,
        speed: float = 1.0,
        muted: bool = False,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
    ) -> Dict[str, Any]:
        """Add a video clip to the timeline.

        Parameters
        ----------
        src : str
            URL of the video file.
        start : float
            Start time in seconds on the timeline.
        duration : float, optional
            Clip duration in seconds. Defaults to ``source_duration``.
        source_duration : float, optional
            Original duration of the source video (for trim calculations).
        name : str, optional
            Display name (defaults to first 50 chars of ``src``).
        track_id : str, optional
            Track to add to (defaults to the video track).
        media_type : str
            "video" (default) or "image" for image clips.
        content_item_id : str, optional
            Reference to the source content item (from ``generate_video``).
        trim_start, trim_end : float
            Trim offsets in seconds from source start/end.
        volume : float
            0.0 (silent) to 1.0 (full).
        speed : float
            0.1 to 10.0 (1.0 = normal).
        muted : bool
            Mute the clip's audio.
        fade_in, fade_out : float
            Fade durations in seconds (must not exceed half the clip duration).
        """
        if duration is None:
            duration = source_duration or 5.0
        if source_duration is None:
            source_duration = duration

        track = self.get_track(track_id) if track_id else self.video_track
        if track is None:
            track = self.add_track("video", label="Video", track_id=track_id)

        clip = {
            "id": _new_id("clip"),
            "trackId": track["id"],
            "name": name or (src[:50] if src else "Untitled"),
            "src": src,
            "start": float(start),
            "duration": float(duration),
            "sourceDuration": float(source_duration),
            "mediaType": media_type,
            "trimStart": float(trim_start),
            "trimEnd": float(trim_end),
            "volume": float(volume),
            "speed": float(speed),
            "muted": bool(muted),
            "fadeIn": float(fade_in),
            "fadeOut": float(fade_out),
        }
        if content_item_id:
            clip["contentItemId"] = content_item_id

        track["items"].append(clip)
        # Extend timeline duration if needed
        end = clip["start"] + clip["duration"]
        if end > self.duration:
            self.duration = end
        return clip

    def add_image_clip(
        self,
        *,
        src: str,
        start: float,
        duration: float = 5.0,
        name: Optional[str] = None,
        track_id: Optional[str] = None,
        content_item_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a still image clip to the timeline."""
        return self.add_video_clip(
            src=src, start=start, duration=duration, source_duration=duration,
            name=name, track_id=track_id, media_type="image",
            content_item_id=content_item_id,
        )

    def add_audio_clip(
        self,
        *,
        src: str,
        start: float,
        duration: float,
        source_duration: Optional[float] = None,
        name: Optional[str] = None,
        track_id: Optional[str] = None,
        track_type: str = "uploaded-audio",
        track_label: Optional[str] = None,
        volume: float = 1.0,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        trim_start: float = 0.0,
        trim_end: float = 0.0,
        linked_item_id: Optional[str] = None,
        link_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add an audio clip (uploaded audio or library music).

        Parameters
        ----------
        src : str
            URL of the audio file.
        track_type : str
            "uploaded-audio" (default) or "library-music".
        linked_item_id : str, optional
            If this audio is linked to a video clip (e.g., lip sync audio),
            pass the video clip ID and ``link_type="video-audio"``.
        """
        if source_duration is None:
            source_duration = duration

        track = self.get_track(track_id) if track_id else None
        if track is None:
            track = self.add_track(track_type, label=track_label or "Audio", track_id=track_id)

        clip = {
            "id": _new_id("audio"),
            "trackId": track["id"],
            "name": name or "Audio clip",
            "src": src,
            "start": float(start),
            "duration": float(duration),
            "sourceDuration": float(source_duration),
            "trimStart": float(trim_start),
            "trimEnd": float(trim_end),
            "volume": float(volume),
            "fadeIn": float(fade_in),
            "fadeOut": float(fade_out),
        }
        if linked_item_id:
            clip["linkedItemId"] = linked_item_id
        if link_type:
            clip["linkType"] = link_type

        track["items"].append(clip)
        end = clip["start"] + clip["duration"]
        if end > self.duration:
            self.duration = end
        return clip

    def add_text_overlay(
        self,
        *,
        text: str,
        start: float,
        end: float,
        preset: Optional[str] = None,
        font_size: int = 48,
        color: str = "#FFFFFF",
        position: str = "center",
        track_id: Optional[str] = None,
        clip_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a text overlay to the timeline.

        Parameters
        ----------
        text : str
            Text content.
        start, end : float
            Start and end times in seconds.
        preset : str, optional
            Effect preset: "fade", "slide-up", "surround", "strange", "flash",
            "slide", "cinefade", "glow", "typewriter", "highlight", "glitch".
        font_size : int
            Font size in pixels (default 48).
        color : str
            Hex color (e.g., "#FF0000").
        position : str
            "center" (default), "top", "bottom", "left", "right", "top-left",
            "top-right", "bottom-left", "bottom-right".
        """
        duration = float(end) - float(start)
        if duration <= 0:
            raise ValueError(f"end ({end}) must be greater than start ({start})")

        track = self.get_track(track_id) if track_id else self.text_track
        if track is None:
            track = self.add_track("text", label="Text", track_id=track_id)

        clip = {
            "id": clip_id or _new_id("text"),
            "trackId": track["id"],
            "text": text,
            "start": float(start),
            "duration": duration,
            "fontSize": int(font_size),
            "color": color,
            "position": position,
        }
        if preset:
            clip["preset"] = preset

        track["items"].append(clip)
        end_t = clip["start"] + clip["duration"]
        if end_t > self.duration:
            self.duration = end_t
        return clip

    # ---- Clip editing ----
    def resize_clip(self, *, clip_id: str, new_duration: float,
                    clip_name: Optional[str] = None) -> bool:
        """Set the ABSOLUTE duration of a clip.

        ``new_duration`` is the final duration (not a delta).
        Cannot exceed the clip's ``sourceDuration`` (maxDur).
        """
        _, clip = self.find_clip(clip_id)
        if clip is None and clip_name:
            _, clip = self.find_clip_by_name(clip_name)
        if clip is None:
            return False
        max_dur = clip.get("sourceDuration", float("inf"))
        if new_duration > max_dur:
            new_duration = max_dur
        clip["duration"] = float(new_duration)
        return True

    def move_clip(self, *, clip_id: str, start_time: float,
                  clip_name: Optional[str] = None) -> bool:
        """Move a clip to a new start time on its track."""
        _, clip = self.find_clip(clip_id)
        if clip is None and clip_name:
            _, clip = self.find_clip_by_name(clip_name)
        if clip is None:
            return False
        clip["start"] = float(start_time)
        # Extend timeline if needed
        end = clip["start"] + clip["duration"]
        if end > self.duration:
            self.duration = end
        return True

    def split_clip(self, *, clip_id: str, at_time: float,
                   clip_name: Optional[str] = None) -> Optional[str]:
        """Split a clip at ``at_time`` (absolute timeline time).

        Returns the new (second) clip's ID, or None if split failed.
        """
        track, clip = self.find_clip(clip_id)
        if clip is None and clip_name:
            track, clip = self.find_clip_by_name(clip_name)
        if clip is None or track is None:
            return None

        clip_start = clip.get("start", 0)
        clip_duration = clip.get("duration", 0)
        clip_end = clip_start + clip_duration

        # Validate split time is within the clip
        if at_time <= clip_start or at_time >= clip_end:
            return None

        # Calculate new durations
        first_duration = at_time - clip_start
        second_duration = clip_end - at_time

        # Update the original clip's duration
        clip["duration"] = float(first_duration)

        # Create the new (second) clip
        new_clip = copy.deepcopy(clip)
        new_clip["id"] = _new_id("clip")
        new_clip["start"] = float(at_time)
        new_clip["duration"] = float(second_duration)
        # Adjust trimStart if it's a video/audio clip
        if "trimStart" in clip:
            new_clip["trimStart"] = float(clip.get("trimStart", 0)) + first_duration

        track["items"].append(new_clip)
        # Re-sort items by start time
        track["items"].sort(key=lambda x: x.get("start", 0))
        return new_clip["id"]

    def duplicate_clip(self, *, clip_id: str,
                       clip_name: Optional[str] = None) -> Optional[str]:
        """Duplicate a clip in place on the same track.

        Returns the new clip's ID, or None if not found.
        """
        track, clip = self.find_clip(clip_id)
        if clip is None and clip_name:
            track, clip = self.find_clip_by_name(clip_name)
        if clip is None or track is None:
            return None

        new_clip = copy.deepcopy(clip)
        new_clip["id"] = _new_id("clip")
        # Place the duplicate right after the original
        new_clip["start"] = clip.get("start", 0) + clip.get("duration", 0)
        track["items"].append(new_clip)
        # Extend timeline duration
        end = new_clip["start"] + new_clip["duration"]
        if end > self.duration:
            self.duration = end
        return new_clip["id"]

    def delete_clip(self, *, clip_id: str,
                    clip_name: Optional[str] = None) -> bool:
        """Delete a clip by ID (or name fallback). Returns True if deleted."""
        track, clip = self.find_clip(clip_id)
        if clip is None and clip_name:
            track, clip = self.find_clip_by_name(clip_name)
        if clip is None or track is None:
            return False
        track["items"] = [c for c in track["items"] if c.get("id") != clip["id"]]
        return True

    def reorder_clips(self, *, ordered_clip_ids: Optional[List[str]] = None,
                      clip_id: Optional[str] = None,
                      to_index: Optional[int] = None) -> bool:
        """Reorder clips on the video track.

        Two modes:
        1. Pass ``ordered_clip_ids`` (preferred) — list ALL video clip IDs
           in the desired final order. Single call.
        2. Pass ``clip_id`` + ``to_index`` — move a single clip to a 0-based index.
        """
        track = self.video_track
        if track is None:
            return False

        if ordered_clip_ids is not None:
            # Reorder by the given list
            by_id = {c["id"]: c for c in track["items"]}
            new_items = []
            for cid in ordered_clip_ids:
                if cid in by_id:
                    new_items.append(by_id[cid])
            # Append any clips not in the list at the end (preserve their relative order)
            for c in track["items"]:
                if c["id"] not in ordered_clip_ids:
                    new_items.append(c)
            track["items"] = new_items
            return True
        elif clip_id is not None and to_index is not None:
            items = track["items"]
            idx = next((i for i, c in enumerate(items) if c["id"] == clip_id), None)
            if idx is None:
                return False
            item = items.pop(idx)
            items.insert(to_index, item)
            return True
        return False

    def extend_timeline_to(self, target_duration: float) -> bool:
        """Extend or shrink the entire video track to a target total duration.

        The system handles clip math precisely. If the target is longer,
        the last clip is extended (up to its maxDur). If shorter, clips
        are trimmed from the end.
        """
        if target_duration <= 0:
            return False

        current = self.total_video_duration
        if current == 0:
            self.duration = float(target_duration)
            return True

        diff = target_duration - current
        if diff > 0:
            # Extend: add the diff to the last video clip (if it has room)
            track = self.video_track
            if track and track["items"]:
                last = max(track["items"], key=lambda c: c.get("start", 0))
                max_dur = last.get("sourceDuration", float("inf"))
                new_duration = last["duration"] + diff
                if new_duration > max_dur:
                    new_duration = max_dur
                last["duration"] = float(new_duration)
        elif diff < 0:
            # Shrink: trim clips from the end
            track = self.video_track
            if track:
                # Sort by start time, then trim from the end
                items = sorted(track["items"], key=lambda c: c.get("start", 0))
                remaining = target_duration
                for item in items:
                    clip_end = item["start"] + item["duration"]
                    if item["start"] >= target_duration:
                        # Clip starts after target — remove entirely
                        item["duration"] = 0
                    elif clip_end > target_duration:
                        # Clip straddles the target — trim it
                        item["duration"] = target_duration - item["start"]
                # Remove zero-duration clips
                track["items"] = [c for c in track["items"] if c.get("duration", 0) > 0]

        self.duration = float(target_duration)
        return True

    # ---- Effects / properties ----
    def set_fade(self, *, clip_id: str, fade_in: float = 0.0, fade_out: float = 0.0,
                 clip_name: Optional[str] = None) -> bool:
        """Set fade-in and/or fade-out on a clip.

        Typical values: 0.3-1.0s. Must not exceed half the clip duration.
        """
        _, clip = self.find_clip(clip_id)
        if clip is None and clip_name:
            _, clip = self.find_clip_by_name(clip_name)
        if clip is None:
            return False
        half = clip.get("duration", 0) / 2
        clip["fadeIn"] = float(min(fade_in, half))
        clip["fadeOut"] = float(min(fade_out, half))
        return True

    def set_volume(self, *, track_id: str, volume: float) -> bool:
        """Set the volume of a track from 0.0 (silent) to 1.0 (full)."""
        track = self.get_track(track_id)
        if track is None:
            return False
        for c in track.get("items", []):
            c["volume"] = float(max(0.0, min(1.0, volume)))
        return True

    def set_speed(self, *, clip_id: str, speed: float,
                  clip_name: Optional[str] = None) -> bool:
        """Set playback speed of a clip (0.1 to 10.0).

        Increasing speed makes the clip SHORTER on the timeline;
        decreasing makes it LONGER.
        """
        if speed < 0.1 or speed > 10.0:
            return False
        _, clip = self.find_clip(clip_id)
        if clip is None and clip_name:
            _, clip = self.find_clip_by_name(clip_name)
        if clip is None:
            return False
        old_speed = clip.get("speed", 1.0)
        old_duration = clip.get("duration", 0)
        # New duration = old_duration * (old_speed / new_speed)
        # (faster speed → shorter clip)
        new_duration = old_duration * (old_speed / speed)
        clip["speed"] = float(speed)
        clip["duration"] = float(new_duration)
        return True

    # ---- Text overlay editing ----
    def update_text_overlay(
        self,
        *,
        clip_id: str,
        text: Optional[str] = None,
        preset: Optional[str] = None,
        font_size: Optional[int] = None,
        color: Optional[str] = None,
        position: Optional[str] = None,
        clip_name: Optional[str] = None,
    ) -> bool:
        """Update an existing text overlay. Only set fields are updated."""
        _, clip = self.find_clip(clip_id)
        if clip is None and clip_name:
            _, clip = self.find_clip_by_name(clip_name)
        if clip is None:
            return False
        if text is not None:
            clip["text"] = text
        if preset is not None:
            clip["preset"] = preset
        if font_size is not None:
            clip["fontSize"] = int(font_size)
        if color is not None:
            clip["color"] = color
        if position is not None:
            clip["position"] = position
        return True

    # ---- Audio linking ----
    def unlink_audio_from_video(self, *, audio_clip_id: str) -> bool:
        """Unlink an audio clip from its associated video clip."""
        _, clip = self.find_clip(audio_clip_id)
        if clip is None:
            return False
        clip.pop("linkedItemId", None)
        clip.pop("linkType", None)
        return True

    def link_audio_to_video(self, *, audio_clip_id: str, video_clip_id: str,
                            link_type: str = "video-audio") -> bool:
        """Link an audio clip to a video clip (e.g., lip sync audio)."""
        _, audio_clip = self.find_clip(audio_clip_id)
        if audio_clip is None:
            return False
        audio_clip["linkedItemId"] = video_clip_id
        audio_clip["linkType"] = link_type
        return True

    def slip_audio(self, *, clip_id: str, slip_seconds: float) -> bool:
        """Slip an audio clip's trim point without changing its timeline position.

        ``slip_seconds`` shifts the in-point forward (positive) or backward (negative).
        """
        _, clip = self.find_clip(clip_id)
        if clip is None:
            return False
        clip["trimStart"] = float(max(0, clip.get("trimStart", 0) + slip_seconds))
        return True

    def replace_audio(self, *, clip_id: str, new_src: str,
                      new_duration: Optional[float] = None) -> bool:
        """Replace the audio source URL of an audio clip."""
        _, clip = self.find_clip(clip_id)
        if clip is None:
            return False
        clip["src"] = new_src
        if new_duration is not None:
            clip["duration"] = float(new_duration)
            clip["sourceDuration"] = float(new_duration)
        return True

    # ---- Bulk operations ----
    def delete_all_clips(self) -> None:
        """Remove every clip from every track (keeps the track structure)."""
        for t in self.tracks:
            t["items"] = []
        self.duration = 0.0

    def delete_timeline(self) -> None:
        """Remove all tracks AND clips (full reset)."""
        self._data["tracks"] = []
        self.duration = 0.0

    # ---- Summary ----
    def summary(self) -> Dict[str, Any]:
        """Return a brief summary of the composition."""
        track_summaries = []
        for t in self.tracks:
            track_summaries.append({
                "id": t["id"],
                "type": t.get("type"),
                "label": t.get("label"),
                "item_count": len(t.get("items", [])),
                "duration": sum(c.get("duration", 0) for c in t.get("items", [])),
            })
        return {
            "duration": self.duration,
            "track_count": len(self.tracks),
            "total_clips": sum(len(t.get("items", [])) for t in self.tracks),
            "tracks": track_summaries,
        }

    def __repr__(self) -> str:
        s = self.summary()
        return (f"<Composition duration={s['duration']:.1f}s "
                f"tracks={s['track_count']} clips={s['total_clips']}>")
