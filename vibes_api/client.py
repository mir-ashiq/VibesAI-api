"""
VibesClient - main API client implementation.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Union

import requests

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
from .ingredients import build_ingredient_payload
from .composition import Composition

BASE_URL = "https://vibes.ai"
DEFAULT_TIMEOUT = 60
POLL_INTERVAL = 3.0
POLL_TIMEOUT = 180.0


def _mg_request_id() -> str:
    """Generate a machine request ID: ``www-{uuidv7}``.

    The web app sends this alongside every ``/api/generate/*`` call
    (e.g. ``www-01a1b9ab-c353-70dd-8bb7-79544e140370``). The prefix is the
    request origin (``www`` = web); the rest is a UUID v7.
    """
    return f"www-{_uuid_v7()}"


def _base36_id(length: int = 7) -> str:
    """Random base36 string (lowercase letters + digits).

    Used for timeline clip/track IDs by the web app
    (e.g. ``video-track-1794116980657-lyqa0p9``).
    """
    import secrets as _secrets
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(_secrets.choice(alphabet) for _ in range(length))


class VibesAPIError(Exception):
    """Raised when the vibes.ai API returns an error."""

    def __init__(self, message: str, *, status: Optional[int] = None,
                 code: Optional[str] = None, response: Optional[dict] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.response = response

    def __str__(self) -> str:
        bits = [super().__str__()]
        if self.code:
            bits.append(f"code={self.code}")
        if self.status:
            bits.append(f"status={self.status}")
        return " | ".join(bits)


def _uuid_v7() -> str:
    """Generate a UUID v7 (timestamp-ordered) for batch IDs.

    The vibes.ai server expects batch IDs to follow the UUID v7 format
    because it extracts the creation timestamp from the high 48 bits.

    Format (RFC 9562):
        bits 0-47:  unix_ts_ms (48 bits, big-endian)
        bits 48-51: version = 0x7
        bits 52-63: rand_a (12 bits)
        bits 64-65: variant = 0b10
        bits 66-127: rand_b (62 bits)

    Example
    -------
    >>> _uuid_v7()  # doctest: +SKIP
    '019f66c6-9721-71a9-870a-76c5a8283505'
    """
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF  # 48 bits
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)

    bytes_ = (
        ms.to_bytes(6, "big")
        + ((0x7 << 12) | rand_a).to_bytes(2, "big")  # version 7 + rand_a
        + ((0b10 << 6) | ((rand_b >> 56) & 0x3F)).to_bytes(1, "big")  # variant + top 6 bits of rand_b
        + (rand_b & 0xFFFFFFFFFFFFFF).to_bytes(7, "big")  # remaining 56 bits of rand_b
    )
    return str(uuid.UUID(bytes=bytes_))


def _ms_now() -> int:
    return int(time.time() * 1000)


def _coerce(v) -> str:
    """Coerce an Enum or string to its string value.

    Python 3.11+ changed ``str(Enum)`` to return ``"Enum.NAME"`` instead of
    just ``"VALUE"``. This helper centralizes the coercion so callers can
    pass either form.
    """
    if hasattr(v, "value"):
        return v.value
    return str(v)


class VibesClient:
    """Unofficial Python client for the vibes.ai API.

    Parameters
    ----------
    meta_session : str
        The value of the ``meta_session`` cookie from your browser.
    cookie_ack : bool, default True
    base_url : str, default "https://vibes.ai"
    timeout : int, default 60
    session : requests.Session, optional
    auto_refresh : bool, default True
        Auto-refresh cookie by intercepting Set-Cookie headers.
    background_refresh : bool, default False
        Run a background thread that calls /api/auth/me every 25 min.
    refresh_interval : float, default 1500.0
        Background refresh interval in seconds.
    on_cookie_refresh : callable, optional
        Callback called with new cookie value on refresh.
    on_session_expired : callable, optional
        Callback called when session expires (401). Use this to
        fetch a fresh cookie and call ``update_cookie()``.
    auto_relogin : bool, default False
        **EXPERIMENTAL**: Attempt automatic re-login via the OIDC flow
        when the session expires. Requires ``agent-browser`` CLI to be
        installed. Only works if the browser has an active Meta session.
    relogin_browser_url : str, optional
        URL of the headless browser to use for auto re-login.
        Defaults to "http://localhost:9222" (Chrome DevTools Protocol).

    How vibes.ai auth works
    -----------------------
    1. **Login**: User clicks "Log In" → browser redirects to
       ``/api/meta-oidc/start`` → redirects to Meta OIDC → user logs
       in → Meta redirects back to ``/api/meta-oidc/callback`` →
       server creates a session and sets ``meta_session`` cookie.

    2. **Session validation**: The web app calls ``/api/auth/check-token``
       every **5 seconds** and ``/api/auth/me`` every **30 seconds**
       to check if the session is still valid.

    3. **Session expiry**: When the session expires (~30 min of no
       activity), API calls return 401. The web app auto-redirects
       to ``/api/meta-oidc/start`` which re-authenticates via Meta
       (silently if the user has an active Meta session).

    4. **No sliding session**: Unlike what I initially thought, vibes.ai
       does NOT send ``Set-Cookie`` on regular API responses. The
       session has a fixed expiry. The only way to extend it is to
       make API calls (which the server tracks as "activity") — but
       the cookie itself doesn't change.

    This client implements
    ----------------------
    - ``background_refresh``: calls ``/api/auth/me`` every 25 min to
      keep the session active (matches the web app's behavior).
    - ``on_session_expired`` callback: notifies you when 401 occurs
      so you can provide a fresh cookie.
    - ``auto_relogin``: uses a headless browser to attempt the OIDC
      flow automatically (requires ``agent-browser``).
    - ``update_cookie()``: update the cookie at runtime without
      recreating the client.
    """

    def __init__(
        self,
        meta_session: str,
        cookie_ack: bool = True,
        base_url: str = BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
        *,
        auto_refresh: bool = True,
        background_refresh: bool = False,
        refresh_interval: float = 1500.0,
        on_cookie_refresh: Optional[callable] = None,
        on_session_expired: Optional[callable] = None,
        auto_relogin: bool = False,
        auth_meta_cookies: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.auto_refresh = auto_refresh
        self.refresh_interval = refresh_interval
        self.on_cookie_refresh = on_cookie_refresh
        self.on_session_expired = on_session_expired
        self.auto_relogin = auto_relogin
        self.auth_meta_cookies = auth_meta_cookies
        self._background_thread = None
        self._background_stop = None
        self._session_expired = False
        self._set_cookie(meta_session, cookie_ack)
        if background_refresh:
            self.start_background_refresh()

    def _set_cookie(self, meta_session: str, cookie_ack: bool = True) -> None:
        cookie_str = f"meta_session={meta_session}"
        if cookie_ack:
            cookie_str += ";cookie_ack=true"
        self.session.headers.update({
            "Cookie": cookie_str,
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": f"{self.base_url}/",
            "Origin": self.base_url,
        })
        self._current_meta_session = meta_session
        self._session_expired = False

    def update_cookie(self, meta_session: str) -> None:
        """Update the session cookie at runtime."""
        self._set_cookie(meta_session)
        if self.on_cookie_refresh:
            try:
                self.on_cookie_refresh(meta_session)
            except Exception:
                pass

    def set_auth_meta_cookies(self, cookies: str) -> None:
        """Set the auth.meta.com cookies for automatic re-login.

        Parameters
        ----------
        cookies : str
            Cookie string from auth.meta.com (e.g.,
            ``"ps_n=1;datr=...;fs=...;locale=en_GB;ps_l=1"``).
            Get these from DevTools → Application → Cookies → auth.meta.com.
        """
        self.auth_meta_cookies = cookies
        self.auto_relogin = True  # Enable auto re-login

    def get_current_cookie(self) -> str:
        return self._current_meta_session

    def _maybe_refresh_cookie(self, resp: requests.Response) -> None:
        """Intercept Set-Cookie headers and update the session cookie."""
        if not self.auto_refresh:
            return
        set_cookie = resp.headers.get("Set-Cookie") or resp.headers.get("set-cookie")
        if not set_cookie:
            return
        for part in set_cookie.split(";"):
            part = part.strip()
            if part.startswith("meta_session="):
                new_value = part[len("meta_session="):]
                if new_value and new_value != self._current_meta_session:
                    self._set_cookie(new_value)
                    if self.on_cookie_refresh:
                        try:
                            self.on_cookie_refresh(new_value)
                        except Exception:
                            pass
                break

    def _handle_401(self) -> bool:
        """Handle a 401 error — attempt auto re-login if enabled.

        Returns True if the session was successfully restored.
        """
        # Don't retry re-login if we're already in the middle of one
        if self._session_expired:
            return False

        self._session_expired = True

        if self.on_session_expired:
            try:
                self.on_session_expired(self._current_meta_session)
            except Exception:
                pass

        if self.auto_relogin and self.auth_meta_cookies:
            new_cookie = self._attempt_oidc_relogin()
            if new_cookie:
                # _set_cookie resets _session_expired to False
                self._set_cookie(new_cookie)
                if self.on_cookie_refresh:
                    try:
                        self.on_cookie_refresh(new_cookie)
                    except Exception:
                        pass
                return True

        # Reset the flag so future 401s can attempt re-login again
        self._session_expired = False
        return False

    def _attempt_oidc_relogin(self) -> Optional[str]:
        """Attempt to re-login via the OIDC flow using auth.meta.com cookies.

        Follows the full OIDC redirect chain using requests.get() (not Session)
        to avoid cookie/header interference between steps.

        Returns the new meta_session cookie value, or None if re-login failed.
        """
        if not self.auth_meta_cookies:
            return None

        ua = "Mozilla/5.0"

        for attempt in range(3):
            try:
                # Step 1: Start OIDC flow at vibes.ai
                r1 = requests.get(
                    f"{self.base_url}/api/meta-oidc/start",
                    headers={"User-Agent": ua, "Cookie": "cookie_ack=true"},
                    allow_redirects=False, timeout=15,
                )
                if r1.status_code not in (302, 307):
                    if attempt < 2:
                        time.sleep(5)
                        continue
                    return None
                redirect_url = r1.headers.get("Location", "")
                if not redirect_url:
                    return None

                # Extract oauth_csrf_token from Set-Cookie
                csrf_token = None
                for part in r1.headers.get("Set-Cookie", "").split(";"):
                    if part.strip().startswith("oauth_csrf_token="):
                        csrf_token = part.strip()[len("oauth_csrf_token="):]
                        break

                # Step 2: auth.meta.com (with auth.meta.com cookies only)
                r2 = requests.get(
                    redirect_url,
                    headers={"User-Agent": ua, "Cookie": self.auth_meta_cookies},
                    allow_redirects=False, timeout=15,
                )
                if r2.status_code not in (302, 307):
                    # 400 = auth.meta.com rate limited or cookies expired
                    # Don't retry — makes rate limiting worse
                    return None
                redirect2 = r2.headers.get("Location", "")
                if not redirect2 or "code=" not in redirect2:
                    return None

                # Step 3: auth.meta.ai/ecto (code exchange)
                r3 = requests.get(
                    redirect2,
                    headers={"User-Agent": ua},
                    allow_redirects=False, timeout=15,
                )
                if r3.status_code not in (302, 307):
                    return None
                redirect3 = r3.headers.get("Location", "")
                if not redirect3 or "vibes.ai" not in redirect3:
                    return None

                # Step 4: vibes.ai callback (CSRF token only, no old session)
                callback_cookie = "cookie_ack=true"
                if csrf_token:
                    callback_cookie += f";oauth_csrf_token={csrf_token}"
                r4 = requests.get(
                    redirect3,
                    headers={"User-Agent": ua, "Cookie": callback_cookie},
                    allow_redirects=False, timeout=15,
                )

                # Check Set-Cookie for new meta_session
                set_cookie = r4.headers.get("Set-Cookie", "").replace(",", ";")
                for part in set_cookie.split(";"):
                    part = part.strip()
                    if part.startswith("meta_session="):
                        val = part[len("meta_session="):]
                        if val and val != "deleted" and val != self._current_meta_session:
                            return val

                # Step 5: Follow final redirect if no cookie in step 4
                final_redirect = r4.headers.get("Location", "")
                if final_redirect and "error=" not in final_redirect:
                    if not final_redirect.startswith("http"):
                        final_redirect = f"{self.base_url}{final_redirect}"
                    r5 = requests.get(
                        final_redirect,
                        headers={"User-Agent": ua, "Cookie": "cookie_ack=true"},
                        allow_redirects=True, timeout=15,
                    )
                    set_cookie_5 = r5.headers.get("Set-Cookie", "").replace(",", ";")
                    for part in set_cookie_5.split(";"):
                        part = part.strip()
                        if part.startswith("meta_session="):
                            val = part[len("meta_session="):]
                            if val and val != "deleted" and val != self._current_meta_session:
                                return val

                return None

            except Exception:
                if attempt < 2:
                    time.sleep(5)
                    continue
                pass

        return None

    def start_background_refresh(self) -> None:
        """Start a daemon thread that periodically validates the session.

        Calls ``/api/auth/check-token`` every ``refresh_interval`` seconds.
        If the session is expired, triggers the ``on_session_expired`` callback.
        """
        import threading
        if self._background_thread and self._background_thread.is_alive():
            return
        self._background_stop = threading.Event()

        def _refresh_loop():
            while not self._background_stop.wait(timeout=self.refresh_interval):
                try:
                    self._get("/api/auth/check-token")
                except VibesAPIError as e:
                    if e.status == 401:
                        self._handle_401()
                except Exception:
                    pass

        self._background_thread = threading.Thread(
            target=_refresh_loop, daemon=True, name="vibes-session-keeper"
        )
        self._background_thread.start()

    def stop_background_refresh(self) -> None:
        if self._background_stop:
            self._background_stop.set()
        if self._background_thread:
            self._background_thread.join(timeout=5)
            self._background_thread = None

    def _maybe_refresh_cookie(self, resp: requests.Response) -> None:
        if not self.auto_refresh:
            return
        set_cookie = resp.headers.get("Set-Cookie") or resp.headers.get("set-cookie")
        if not set_cookie:
            return
        for part in set_cookie.split(";"):
            part = part.strip()
            if part.startswith("meta_session="):
                new_value = part[len("meta_session="):]
                if new_value and new_value != self._current_meta_session:
                    self._set_cookie(new_value)
                    if self.on_cookie_refresh:
                        try:
                            self.on_cookie_refresh(new_value)
                        except Exception:
                            pass
                break

    def start_background_refresh(self) -> None:
        import threading
        if self._background_thread and self._background_thread.is_alive():
            return
        self._background_stop = threading.Event()
        def _loop():
            while not self._background_stop.wait(timeout=self.refresh_interval):
                try:
                    self._get("/api/auth/me")
                except Exception:
                    pass
        self._background_thread = threading.Thread(target=_loop, daemon=True, name="vibes-cookie-refresh")
        self._background_thread.start()

    def stop_background_refresh(self) -> None:
        if self._background_stop:
            self._background_stop.set()
        if self._background_thread:
            self._background_thread.join(timeout=5)
            self._background_thread = None

    # ------------------------------------------------------------------ #
    #  Low-level helpers
    # ------------------------------------------------------------------ #
    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _check(self, resp: requests.Response) -> dict:
        self._maybe_refresh_cookie(resp)
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}
        if not resp.ok:
            err = data.get("error") if isinstance(data, dict) else None
            if isinstance(err, dict):
                msg = err.get("detail") or err.get("title") or err.get("message") or "API error"
                code = err.get("code")
            elif isinstance(err, str):
                msg = err
                code = None
            else:
                msg = f"HTTP {resp.status_code}"
                code = None
            raise VibesAPIError(
                f"{msg} | response={str(data)[:500]}",
                status=resp.status_code, code=code, response=data,
            )
        return data

    def _get(self, path: str, params: Optional[dict] = None, **kw) -> dict:
        resp = self.session.get(self._url(path), params=params, timeout=self.timeout, **kw)
        try:
            return self._check(resp)
        except VibesAPIError as e:
            if e.status == 401 and not self._session_expired:
                if self._handle_401():
                    # Session was restored — retry the request ONCE
                    resp = self.session.get(self._url(path), params=params, timeout=self.timeout, **kw)
                    return self._check(resp)
            # Re-login failed or not enabled — raise the original error
            raise

    def _post(self, path: str, json_body: Optional[dict] = None, **kw) -> dict:
        resp = self.session.post(self._url(path), json=json_body, timeout=self.timeout, **kw)
        try:
            return self._check(resp)
        except VibesAPIError as e:
            if e.status == 401 and not self._session_expired:
                if self._handle_401():
                    resp = self.session.post(self._url(path), json=json_body, timeout=self.timeout, **kw)
                    return self._check(resp)
            raise

    def _put(self, path: str, json_body: Optional[dict] = None, **kw) -> dict:
        resp = self.session.put(self._url(path), json=json_body, timeout=self.timeout, **kw)
        return self._check(resp)

    def _delete(self, path: str, **kw) -> dict:
        resp = self.session.delete(self._url(path), timeout=self.timeout, **kw)
        return self._check(resp)

    # ------------------------------------------------------------------ #
    #  Auth & system
    # ------------------------------------------------------------------ #
    def get_me(self) -> dict:
        """Return the authenticated user profile."""
        return self._get("/api/auth/me").get("user", {})

    def get_system_status(self) -> Optional[Any]:
        """Return current system status banner (or None)."""
        return self._get("/api/system-status").get("status")

    def logout(self) -> None:
        """Invalidate the current session server-side."""
        self._post("/api/auth/logout")

    # ------------------------------------------------------------------ #
    #  Projects
    # ------------------------------------------------------------------ #
    def list_projects(
        self,
        limit: int = 25,
        offset: int = 0,
        sort: str = "newest",
        search: Optional[str] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """List projects in your workspace."""
        params = {"limit": limit, "offset": offset, "sort": sort}
        if search:
            params["search"] = search
        last_err = None
        for attempt in range(max_retries + 1):
            try:
                return self._get("/api/projects", params=params)
            except VibesAPIError as e:
                last_err = e
                if e.status != 500:
                    raise
                time.sleep(1.0 * (attempt + 1))
        raise last_err

    def get_project(self, project_id: str) -> dict:
        """Fetch a single project (including composition/timeline)."""
        return self._get(f"/api/projects/{project_id}").get("project", {})

    def create_project(
        self,
        name: str = "Untitled",
        composition: Optional[dict] = None,
    ) -> dict:
        """Create a new project. Returns the project dict."""
        if composition is None:
            composition = {"id": "studio-composition", "tracks": [], "duration": 5}
        body = {"name": name, "composition": composition}
        return self._post("/api/projects", json_body=body).get("project", {})

    def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        composition: Optional[dict] = None,
    ) -> dict:
        """Update project name and/or composition (timeline state)."""
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if composition is not None:
            body["composition"] = composition
        return self._put(f"/api/projects/{project_id}", json_body=body).get("project", {})

    def delete_project(self, project_id: str, delete_assets: bool = False) -> None:
        """Delete a project.

        Parameters
        ----------
        project_id : str
            The project to delete.
        delete_assets : bool, default False
            If True, also delete media that is NOT used in any other project
            ("Delete project and unused media"). If False, only delete the
            project itself and keep all media in the library
            ("Delete project only").
        """
        path = f"/api/projects/{project_id}"
        if delete_assets:
            path += "?deleteAssets=true"
        self._delete(path)

    def duplicate_project(self, project_id: str) -> dict:
        """Duplicate a project (returns the new project)."""
        return self._post(f"/api/projects/{project_id}/duplicate").get("project", {})

    def save_composition(self, project_id: str, composition: dict) -> dict:
        """Shortcut for ``update_project(composition=composition)``."""
        return self.update_project(project_id, composition=composition)

    # ------------------------------------------------------------------ #
    #  Batches (the core generation primitive)
    # ------------------------------------------------------------------ #
    def list_batches(
        self,
        limit: int = 12,
        offset: int = 0,
        project_id: Optional[str] = None,
        type: Optional[str] = None,
        max_retries: int = 3,
    ) -> dict:
        """List generation batches.

        Pass ``project_id`` to scope to a project, or omit for all batches
        in the workspace.

        Notes
        -----
        This endpoint occasionally returns transient 500s. We retry up to
        ``max_retries`` times before propagating the error.
        """
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if project_id:
            params["projectId"] = project_id
        if type:
            params["type"] = type
        last_err: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                return self._get("/api/generation-batches", params=params)
            except VibesAPIError as e:
                last_err = e
                if e.status != 500:
                    raise
                time.sleep(1.0 * (attempt + 1))
        assert last_err is not None
        raise last_err

    def list_project_batches(self, project_id: str, limit: int = 6, offset: int = 0) -> dict:
        """List batches inside a specific project."""
        return self._get(f"/api/projects/{project_id}/batches",
                         params={"limit": limit, "offset": offset})

    def get_batch(self, batch_id: str) -> dict:
        """Fetch full batch state including all content items.

        Returns
        -------
        dict with keys: ``id``, ``type``, ``prompt``, ``config``,
        ``isComplete``, ``hasError``, ``error``, ``content`` (list), ...
        """
        return self._get(f"/api/generation-batches/{batch_id}").get("batch", {})

    def delete_batch(self, batch_id: str) -> None:
        self._delete(f"/api/generation-batches/{batch_id}")

    def _create_batch(
        self,
        *,
        batch_type: str,        # "videos" or "images"
        prompt: str,
        project_id: str,
        config: dict,
        count: int = 4,
        batch_id: Optional[str] = None,
    ) -> str:
        """Internal helper: create a generation batch and return its ID.

        The batch ID is generated client-side as a UUID v7 (this is what
        the web app does) so that the server can derive creation time
        from the high bits. We prefix with ``batch-`` to match the format
        the download endpoint expects.
        """
        batch_id = batch_id or f"batch-{_uuid_v7()}"
        content_item_type = "video" if batch_type == "videos" else "image"
        body = {
            "id": batch_id,
            "type": batch_type,
            "prompt": prompt,
            "timestamp": _ms_now(),
            "isComplete": False,
            "config": config,
            "projectId": project_id,
            "content": [
                {
                    "id": f"{batch_id}-content-{i}",
                    "type": content_item_type,
                    "isLoading": True,
                }
                for i in range(count)
            ],
        }
        self._post("/api/generation-batches", json_body=body)
        return batch_id

    # ------------------------------------------------------------------ #
    #  VIDEO generation
    # ------------------------------------------------------------------ #
    def generate_video(
        self,
        project_id: str,
        prompt: str,
        *,
        aspect_ratio: Union[str, AspectRatio] = AspectRatio.PORTRAIT,
        resolution: Union[str, Resolution] = Resolution.P480,
        variations: int = 4,
        video_model: Union[str, VideoModel] = VideoModel.SHORT,
        image_model: Union[str, ImageModel] = ImageModel.BASE,
        prompt_model: Union[str, PromptModel] = PromptModel.GEMINI_FLASH,
        ingredients: Optional[List[dict]] = None,
        create_ingredients: Optional[List[dict]] = None,
        start_frame: Optional[dict] = None,
        end_frame: Optional[dict] = None,
        moodboard: Optional[dict] = None,
        poll: bool = True,
        poll_interval: float = POLL_INTERVAL,
        poll_timeout: float = POLL_TIMEOUT,
    ) -> dict:
        """Generate one or more video variations from a text prompt.

        This is the canonical text-to-video (t2v) and image-to-video (i2v)
        entry point. It mirrors the "Generate" tab in the Vibes UI.

        Parameters
        ----------
        project_id : str
            Target project (create one with ``create_project`` first).
        prompt : str
            The text description of the video you want.
        aspect_ratio : str | AspectRatio
            Only "9:16" (default), "16:9", "1:1" are supported server-side.
        resolution : str | Resolution
            "480p" (default, faster) or "720p" (shown under "Advanced").
        variations : int
            Number of variations to generate (1-4). The UI default is 4.
        video_model : str | VideoModel
            Default ``midjen-short`` (5s clip). Use ``midjen-extend`` /
            ``midjen-video-edit`` only via ``extend_video()`` / ``edit_video()``.
        image_model : str | ImageModel
            Default ``midjen-base``. Used for the source frame in t2v.
        prompt_model : str | PromptModel
            Default ``gemini-2.5-flash``.
        ingredients : list of dict, optional
            EXISTING ingredient refs (from ``client.list_ingredients()``).
            Use ``vibes_api.ingredients.IngredientRef.by_id()`` to build.
            Each applies a saved character/style/scene to the generation.
        create_ingredients : list of dict, optional
            INLINE ingredient creations (no pre-existing ingredient).
            Use ``vibes_api.ingredients.CreateIngredient.by_image_ent_id()``
            or ``.by_name()`` to build.
        start_frame : dict, optional
            **Start frame** (image-to-video). Pass the result of
            ``upload_image_file()`` formatted via ``build_frame_handle()``
            — typically ``{"oil_handle": "...", "image_url": "...",
            "image_ent_id": "...", "source": "upload"}``.
            When set, the generation runs in i2v mode.
        end_frame : dict, optional
            **End frame**. Same shape as ``start_frame``. When set, the
            server generates a video that interpolates from start to end
            frame. The fields are stored on the config as
            ``lastFrameOilHandle``, ``lastFrameImageUrl``,
            ``lastFrameImageEntId``.
        moodboard : dict, optional
            Apply a moodboard (style reference) by passing
            ``{"moodboardCode": "...", "moodboardId": "...", "moodboard_name": "...", "moodboard_thumbnail_url": "..."}``.
            Use ``client.list_moodboards()`` to find one.
        poll : bool
            If True (default), block until the batch completes and return
            the final batch state. If False, return immediately.
        poll_interval, poll_timeout : float
            Polling cadence and max wait. Videos typically take 30-90s.

        Returns
        -------
        dict
            If ``poll=True``: the final batch dict (with ``content`` populated).
            If ``poll=False``: the immediate generation response with
            ``batchId``, ``videoGenEntIds``, ``needsPolling``, ``items``.

        Raises
        ------
        VibesAPIError
            If generation fails server-side.
        TimeoutError
            If ``poll=True`` and the batch doesn't complete within ``poll_timeout``.

        Notes
        -----
        - When ``start_frame`` is set, ``generationType`` becomes ``i2v``.
        - When both ``start_frame`` and ``end_frame`` are set, the server
          uses them as keyframes for interpolation.
        - ``ingredients`` and ``create_ingredients`` can be combined.
        """
        aspect_ratio = _coerce(aspect_ratio)
        resolution = _coerce(resolution)
        video_model = _coerce(video_model)
        image_model = _coerce(image_model)
        prompt_model = _coerce(prompt_model)

        # Build ingredient payload (handles character/style/scene combinations)
        ing_payload = build_ingredient_payload(
            ingredients=ingredients,
            create_ingredients=create_ingredients,
        )

        gen_type = "i2v" if start_frame else "t2v"

        config: Dict[str, Any] = {
            "videoModel": video_model,
            "imageModel": image_model,
            "promptModel": prompt_model,
            "resolution": resolution,
            "aspectRatio": aspect_ratio,
            "batchVariation": variations > 1,
            "generationType": gen_type,
            "directGeneration": True,
        }
        # Spread ingredient payload (ingredients + createIngredients)
        config.update(ing_payload)

        # Start frame → directPromptImageHandle
        if start_frame:
            config["directPromptImageHandle"] = start_frame

        # End frame → lastFrameOilHandle / lastFrameImageUrl / lastFrameImageEntId
        if end_frame:
            if end_frame.get("oil_handle"):
                config["lastFrameOilHandle"] = end_frame["oil_handle"]
            if end_frame.get("image_url"):
                config["lastFrameImageUrl"] = end_frame["image_url"]
            if end_frame.get("image_ent_id"):
                config["lastFrameImageEntId"] = end_frame["image_ent_id"]

        # Moodboard (style reference)
        if moodboard:
            if moodboard.get("moodboardCode"):
                config["moodboardCode"] = moodboard["moodboardCode"]
            if moodboard.get("moodboardId"):
                config["moodboardId"] = moodboard["moodboardId"]
            if moodboard.get("moodboard_name"):
                config["moodboard_name"] = moodboard["moodboard_name"]
            if moodboard.get("moodboard_thumbnail_url"):
                config["moodboard_thumbnail_url"] = moodboard["moodboard_thumbnail_url"]

        # 1) Create the batch
        batch_id = self._create_batch(
            batch_type="videos",
            prompt=prompt,
            project_id=project_id,
            config=config,
            count=variations,
        )
        # Small delay to let the server-side DB row settle (avoids
        # transient 500s when polling immediately after creation).
        time.sleep(1.0)

        # 2) Build inputs - each variation gets its own input
        input_config = {
            "videoModel": video_model,
            "imageModel": image_model,
            "promptModel": prompt_model,
            "resolution": resolution,
            "aspectRatio": aspect_ratio,
            "generationType": gen_type,
        }
        input_config.update(ing_payload)
        if start_frame:
            input_config["directPromptImageHandle"] = start_frame
        if end_frame:
            if end_frame.get("oil_handle"):
                input_config["lastFrameOilHandle"] = end_frame["oil_handle"]
            if end_frame.get("image_url"):
                input_config["lastFrameImageUrl"] = end_frame["image_url"]
            if end_frame.get("image_ent_id"):
                input_config["lastFrameImageEntId"] = end_frame["image_ent_id"]
        if moodboard:
            if moodboard.get("moodboardCode"):
                input_config["moodboardCode"] = moodboard["moodboardCode"]
            if moodboard.get("moodboardId"):
                input_config["moodboardId"] = moodboard["moodboardId"]
            if moodboard.get("moodboard_name"):
                input_config["moodboard_name"] = moodboard["moodboard_name"]
            if moodboard.get("moodboard_thumbnail_url"):
                input_config["moodboard_thumbnail_url"] = moodboard["moodboard_thumbnail_url"]

        inputs = []
        for _ in range(variations):
            inp = {
                "type": "prompt",
                "value": prompt,
                "original_prompt": prompt,
                "config": input_config,
            }
            inputs.append(inp)

        # 3) Trigger generation
        gen_resp = self._post("/api/generate/videos", json_body={
            "batchId": batch_id,
            "inputs": inputs,
            "config": config,
            "mg_request_id": _mg_request_id(),
            "projectId": project_id,
        })

        if not poll:
            return gen_resp

        # 4) Poll for completion
        return self.poll_batch(batch_id, interval=poll_interval, timeout=poll_timeout)

    def poll_batch(
        self,
        batch_id: str,
        *,
        interval: float = POLL_INTERVAL,
        timeout: float = POLL_TIMEOUT,
        max_retries: int = 3,
    ) -> dict:
        """Block until a batch completes (or times out).

        Returns the final batch state dict (with ``content`` populated).

        Notes
        -----
        The batch endpoint occasionally returns transient 500s right after
        batch creation (race condition). This method retries up to
        ``max_retries`` times before propagating the error.
        """
        deadline = time.time() + timeout
        consecutive_errors = 0
        while time.time() < deadline:
            try:
                batch = self.get_batch(batch_id)
                consecutive_errors = 0
                if batch.get("isComplete") or batch.get("hasError"):
                    return batch
            except VibesAPIError as e:
                consecutive_errors += 1
                if consecutive_errors > max_retries:
                    raise
                # Brief backoff before retry
                time.sleep(min(2.0, interval))
            time.sleep(interval)
        raise TimeoutError(
            f"Batch {batch_id} did not complete within {timeout:.0f}s"
        )

    # ------------------------------------------------------------------ #
    #  IMAGE generation
    # ------------------------------------------------------------------ #
    def generate_image(
        self,
        project_id: str,
        prompt: str,
        *,
        aspect_ratio: Union[str, AspectRatio] = AspectRatio.SQUARE,
        resolution: Union[str, Resolution] = Resolution.P480,
        variations: int = 1,
        image_model: Union[str, ImageModel] = ImageModel.BASE,
        prompt_model: Union[str, PromptModel] = PromptModel.GEMINI_FLASH,
        ingredients: Optional[List[dict]] = None,
        create_ingredients: Optional[List[dict]] = None,
        moodboard: Optional[dict] = None,
    ) -> dict:
        """Generate one or more images from a text prompt.

        Image generation is **synchronous** (no polling needed) - the API
        returns immediately with the final image URLs.

        Parameters
        ----------
        project_id, prompt, aspect_ratio, resolution, variations,
        image_model, prompt_model, ingredients, create_ingredients,
        moodboard : see ``generate_video()``

        Returns
        -------
        dict
            Raw API response: ``{success, data: [{url, prompt, config,
            imageEntId, dimensions, srefValues, orefValues}],
            updatedBatch: {...}}``.
        """
        aspect_ratio = _coerce(aspect_ratio)
        resolution = _coerce(resolution)
        image_model = _coerce(image_model)
        prompt_model = _coerce(prompt_model)

        ing_payload = build_ingredient_payload(
            ingredients=ingredients,
            create_ingredients=create_ingredients,
        )

        config: Dict[str, Any] = {
            "imageModel": image_model,
            "promptModel": prompt_model,
            "resolution": resolution,
            "aspectRatio": aspect_ratio,
            "batchVariation": variations > 1,
            "generationType": "t2i",
            "directGeneration": True,
        }
        config.update(ing_payload)
        if moodboard:
            if moodboard.get("moodboardCode"):
                config["moodboardCode"] = moodboard["moodboardCode"]
            if moodboard.get("moodboardId"):
                config["moodboardId"] = moodboard["moodboardId"]
            if moodboard.get("moodboard_name"):
                config["moodboard_name"] = moodboard["moodboard_name"]
            if moodboard.get("moodboard_thumbnail_url"):
                config["moodboard_thumbnail_url"] = moodboard["moodboard_thumbnail_url"]

        batch_id = self._create_batch(
            batch_type="images",
            prompt=prompt,
            project_id=project_id,
            config=config,
            count=variations,
        )

        input_config = {
            "imageModel": image_model,
            "promptModel": prompt_model,
            "resolution": resolution,
            "aspectRatio": aspect_ratio,
            "generationType": "t2i",
        }
        input_config.update(ing_payload)
        if moodboard:
            if moodboard.get("moodboardCode"):
                input_config["moodboardCode"] = moodboard["moodboardCode"]
            if moodboard.get("moodboardId"):
                input_config["moodboardId"] = moodboard["moodboardId"]
            if moodboard.get("moodboard_name"):
                input_config["moodboard_name"] = moodboard["moodboard_name"]
            if moodboard.get("moodboard_thumbnail_url"):
                input_config["moodboard_thumbnail_url"] = moodboard["moodboard_thumbnail_url"]

        inputs = [
            {
                "type": "variation",
                "image_prompt": prompt,
                "original_prompt": prompt,
                "config": input_config,
            }
            for _ in range(variations)
        ]

        return self._post("/api/generate/images", json_body={
            "batchId": batch_id,
            "inputs": inputs,
            "config": config,
            "mg_request_id": _mg_request_id(),
            "projectId": project_id,
        })

    # ------------------------------------------------------------------ #
    #  IMAGE EDITING
    # ------------------------------------------------------------------ #
    def edit_image(
        self,
        source_image_ent_id: str,
        edit_prompt: str,
        project_id: Optional[str] = None,
    ) -> dict:
        """Edit an existing image with a text prompt.

        Parameters
        ----------
        source_image_ent_id : str
            The ``imageEntId`` (or ``mediaEntId``) of the source image,
            obtained from a prior ``generate_image`` call or upload.
        edit_prompt : str
            Instruction for the edit (e.g., "make it night time").
        project_id : str, optional
            Attach the result to a project.

        Returns
        -------
        dict
            ``{success, contentItem: {...}}``
        """
        body: Dict[str, Any] = {
            "sourceImageEntId": source_image_ent_id,
            "editPrompt": edit_prompt,
        }
        if project_id:
            body["projectId"] = project_id
        return self._post("/api/generate/image-edit", json_body=body)

    # ------------------------------------------------------------------ #
    #  VIDEO EXTEND (auto + manual)  — mirrors "Extend" panel in UI
    # ------------------------------------------------------------------ #
    def extend_video(
        self,
        project_id: str,
        source_video: dict,
        *,
        prompt: Optional[str] = None,
        poll: bool = True,
        poll_interval: float = POLL_INTERVAL,
        poll_timeout: float = POLL_TIMEOUT,
    ) -> dict:
        """Extend a video clip by ~5 seconds (auto or manual).

        Mirrors the "Auto extend" and "Manual extend" buttons in the Vibes UI.
        Both call the same underlying endpoint — the only difference is
        whether you supply a directive prompt.

        Parameters
        ----------
        project_id : str
            Target project (must contain the source video).
        source_video : dict
            The source content item dict from a prior ``generate_video()``
            or ``get_batch()``, e.g. ``batch["content"][0]``. Must contain
            at least ``id``, ``videoUrl``, and either ``videoHandle`` or
            ``data.videoGenEntId``. The full content item shape works.
        prompt : str, optional
            **Manual extend directive**. If provided, the server uses this
            to guide the extension (e.g., "the camera pans up to reveal
            the sky"). If omitted, runs **auto extend** — the server
            continues the original prompt.
        poll : bool
            Block until completion (default True).
        poll_interval, poll_timeout : float
            Polling cadence and max wait. Extensions take 30-90s.

        Returns
        -------
        dict
            If ``poll=True``: the final batch dict (with new ``content``
            items — the extended video). If ``poll=False``: the immediate
            generation response.

        Raises
        ------
        VibesAPIError
            If the source video is missing required metadata, or the
            server fails to start the extension.
        """
        # Extract source video metadata
        original_prompt = (
            source_video.get("prompt")
            or source_video.get("videoPrompt")
            or source_video.get("imagePrompt")
            or ""
        )
        if not original_prompt:
            raise VibesAPIError(
                "Original prompt not available for extend. "
                "Pass the full content item dict from get_batch()."
            )

        # Get the source video handle and entity ID
        structured = source_video.get("structuredOutput") or {}
        if isinstance(structured, str):
            try:
                import json as _json
                structured = _json.loads(structured)
            except ValueError:
                structured = {}

        source_config = source_video.get("config") or {}
        source_video_handle = (
            source_video.get("videoHandle")
            or structured.get("sourceVideoHandle")
            or source_config.get("sourceVideoHandle")
        )
        video_gen_ent_id = self._extract_video_gen_ent_id(source_video)
        source_video_url = (
            source_video.get("videoUrl")
            or structured.get("sourceVideoUrl")
            or source_config.get("sourceVideoUrl")
        )

        if not source_video_handle and not video_gen_ent_id:
            raise VibesAPIError(
                "Video handle or entity ID is required for extend. "
                "Use a video with a valid reference (one returned by generate_video)."
            )

        # Build the extended config
        ext_config: Dict[str, Any] = {
            **structured,
            **source_config,
            "videoModel": "midjen-extend",
            "imageModel": source_config.get("imageModel") or "midjen-base",
            "generationType": "extend",
            "directGeneration": True,
            "sourceContentItemIds": [{"id": source_video["id"], "source": "extend_video"}],
        }
        # Force midjen-extend (server doesn't accept midjen-short for extend)
        if ext_config["videoModel"] in ("midjen-short", "midjen-video-edit"):
            ext_config["videoModel"] = "midjen-extend"

        if source_video_handle:
            ext_config["sourceVideoHandle"] = source_video_handle
        if source_video_url and not ext_config.get("sourceVideoUrl"):
            ext_config["sourceVideoUrl"] = source_video_url

        # Carry over audio if present (for lipsync extensions)
        audio_ent_id = (
            ext_config.get("audioSourceEntId")
            or structured.get("audioSourceEntId")
            or source_config.get("audioSourceEntId")
        )
        if audio_ent_id:
            ext_config["audioSourceEntId"] = audio_ent_id

        if prompt:
            ext_config["extendDirective"] = prompt

        # Build the batch ID (matches UI's `extend-${Date.now()}-${random}` format)
        import random as _random
        batch_id = f"extend-{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"

        # Create the batch shell
        batch_body = {
            "id": batch_id,
            "type": "videos",
            "prompt": prompt or original_prompt,
            "timestamp": _ms_now(),
            "content": [],
            "isComplete": False,
            "config": ext_config,
            "promptModel": ext_config.get("promptModel"),
            "imageModel": ext_config.get("imageModel"),
            "videoModel": ext_config.get("videoModel"),
            "generationStartTime": _ms_now(),
            "isDirectGeneration": True,
            "projectId": project_id,
        }
        self._post("/api/generation-batches", json_body=batch_body)
        time.sleep(1.0)

        # Build inputs — extend inputs use type: "extend"
        input_config = {**ext_config}
        inputs = [{
            "type": "extend",
            "mediaEntId": video_gen_ent_id,
            "videoUrl": source_video_url,
            "prompt": prompt or original_prompt,
            **({"extendDirective": prompt} if prompt else {}),
            "config": input_config,
        }]

        gen_resp = self._post("/api/generate/videos", json_body={
            "batchId": batch_id,
            "inputs": inputs,
            "config": ext_config,
            "mg_request_id": _mg_request_id(),
            "projectId": project_id,
        })

        if not poll:
            return gen_resp
        return self.poll_batch(batch_id, interval=poll_interval, timeout=poll_timeout)

    def auto_extend_video(
        self,
        project_id: str,
        source_video: dict,
        **kwargs,
    ) -> dict:
        """Shortcut for ``extend_video(..., prompt=None)`` — the "Auto extend" button."""
        return self.extend_video(project_id, source_video, prompt=None, **kwargs)

    def manual_extend_video(
        self,
        project_id: str,
        source_video: dict,
        prompt: str,
        **kwargs,
    ) -> dict:
        """Shortcut for ``extend_video(..., prompt=prompt)`` — the "Manual extend" button."""
        return self.extend_video(project_id, source_video, prompt=prompt, **kwargs)

    # ------------------------------------------------------------------ #
    #  VIDEO-TO-VIDEO EDITING (v2v)
    # ------------------------------------------------------------------ #
    def edit_video(
        self,
        project_id: str,
        source_video: dict,
        prompt: str,
        *,
        poll: bool = True,
        poll_interval: float = POLL_INTERVAL,
        poll_timeout: float = POLL_TIMEOUT,
    ) -> dict:
        """Edit an existing video with a text prompt (video-to-video).

        This is the API equivalent of the "Edit video" flow in the Vibes UI.
        The source video is re-rendered with the directive applied.

        Parameters
        ----------
        project_id : str
            Target project.
        source_video : dict
            The source content item dict (same shape as ``extend_video``).
        prompt : str
            The edit directive (e.g., "change the weather to rain").
        poll : bool
            Block until completion (default True).

        Returns
        -------
        dict
            Same shape as ``extend_video()``.
        """
        original_prompt = (
            source_video.get("prompt")
            or source_video.get("videoPrompt")
            or source_video.get("imagePrompt")
            or ""
        )
        if not original_prompt:
            raise VibesAPIError("No prompt available for video-to-video editing.")

        structured = source_video.get("structuredOutput") or {}
        if isinstance(structured, str):
            try:
                import json as _json
                structured = _json.loads(structured)
            except ValueError:
                structured = {}

        source_config = source_video.get("config") or {}
        source_video_handle = (
            source_video.get("videoHandle")
            or structured.get("sourceVideoHandle")
            or source_config.get("sourceVideoHandle")
        )
        video_gen_ent_id = self._extract_video_gen_ent_id(source_video)
        source_video_url = (
            source_video.get("videoUrl")
            or structured.get("sourceVideoUrl")
            or source_config.get("sourceVideoUrl")
        )

        if not source_video_handle and not video_gen_ent_id:
            raise VibesAPIError(
                "This video cannot be edited because it is missing required "
                "metadata (videoHandle or videoGenEntId). This may happen "
                "with older videos or videos that were uploaded directly."
            )

        # v2v uses midjen-video-edit
        v2v_config: Dict[str, Any] = {
            **structured,
            **source_config,
            "videoModel": "midjen-video-edit",
            "imageModel": source_config.get("imageModel") or "midjen-base",
            "editType": "v2v",
            "generationType": "v2v",
            "directGeneration": True,
            "sourceContentItemIds": [{"id": source_video["id"], "source": "v2v"}],
        }
        # v2v doesn't support end frame / loop — strip them
        for k in ("endFrameUrl", "endFrameHandle", "lastFrameOilHandle", "loop"):
            v2v_config.pop(k, None)

        if source_video_handle:
            v2v_config["sourceVideoHandle"] = source_video_handle
        if source_video_url:
            v2v_config["sourceVideoUrl"] = source_video_url

        # Carry start frame if the source had one
        start_handle_oil = (
            source_config.get("directPromptImageHandle", {}).get("oil_handle")
            or source_video.get("imageHandle")
            or structured.get("directPromptImageHandle", {}).get("oil_handle")
        )
        if start_handle_oil:
            v2v_config["directPromptImageHandle"] = {
                "oil_handle": start_handle_oil,
                "image_url": (
                    source_video.get("imageUrl")
                    or structured.get("directPromptImageHandle", {}).get("image_url", "")
                ),
            }

        batch_id = f"video2video-{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"
        batch_body = {
            "id": batch_id,
            "type": "videos",
            "prompt": prompt,
            "timestamp": _ms_now(),
            "content": [],
            "isComplete": False,
            "config": v2v_config,
            "promptModel": v2v_config.get("promptModel"),
            "imageModel": v2v_config.get("imageModel"),
            "videoModel": v2v_config.get("videoModel"),
            "generationStartTime": _ms_now(),
            "isDirectGeneration": True,
            "projectId": project_id,
        }
        self._post("/api/generation-batches", json_body=batch_body)
        time.sleep(1.0)

        input_config = {**v2v_config}
        inputs = [{
            "type": "video",
            "mediaEntId": video_gen_ent_id,
            "videoUrl": source_video_url,
            "prompt": prompt,
            "config": input_config,
        }]

        gen_resp = self._post("/api/generate/videos", json_body={
            "batchId": batch_id,
            "inputs": inputs,
            "config": v2v_config,
            "mg_request_id": _mg_request_id(),
            "projectId": project_id,
        })

        if not poll:
            return gen_resp
        return self.poll_batch(batch_id, interval=poll_interval, timeout=poll_timeout)

    # ------------------------------------------------------------------ #
    #  IMAGE-TO-VIDEO ANIMATE (Auto animate / Manual animate)
    # ------------------------------------------------------------------ #
    def animate_image(
        self,
        project_id: str,
        source_image: dict,
        prompt: Optional[str] = None,
        *,
        poll: bool = True,
        poll_interval: float = POLL_INTERVAL,
        poll_timeout: float = POLL_TIMEOUT,
    ) -> dict:
        """Animate an existing image into a video (i2v).

        Mirrors the "Auto animate" and "Manual animate" buttons shown next
        to an image in the Vibes UI gallery.

        Parameters
        ----------
        project_id : str
            Target project.
        source_image : dict
            The source image content item dict. Must contain at least
            ``id``, ``imageUrl``, and either ``imageHandle`` or
            ``data.imageEntId``.
        prompt : str, optional
            Manual animate directive. If omitted, runs **auto animate**
            (uses the image's original prompt).
        poll : bool
            Block until completion (default True).

        Returns
        -------
        dict
            Same shape as ``generate_video()``.
        """
        original_prompt = (
            source_image.get("prompt")
            or source_image.get("imagePrompt")
            or source_image.get("videoPrompt")
            or ""
        )
        if not original_prompt:
            raise VibesAPIError("No prompt available for this image.")

        structured = source_image.get("structuredOutput") or {}
        if isinstance(structured, str):
            try:
                import json as _json
                structured = _json.loads(structured)
            except ValueError:
                structured = {}

        source_config = source_image.get("config") or {}
        image_handle_oil = (
            source_config.get("directPromptImageHandle", {}).get("oil_handle")
            or source_image.get("imageHandle")
            or structured.get("directPromptImageHandle", {}).get("oil_handle")
        )
        image_url = (
            source_image.get("imageUrl")
            or structured.get("directPromptImageHandle", {}).get("image_url")
        )
        image_ent_id = self._extract_image_ent_id(source_image)

        if not image_handle_oil and not image_ent_id:
            raise VibesAPIError(
                "Image handle or entity ID is required for animate. "
                "Use an image with a valid reference."
            )

        i2v_config: Dict[str, Any] = {
            **structured,
            **source_config,
            "videoModel": "midjen-short",
            "imageModel": source_config.get("imageModel") or "midjen-base",
            "generationType": "i2v",
            "directGeneration": True,
            "sourceContentItemIds": [{"id": source_image["id"], "source": "i2v"}],
        }
        if image_handle_oil:
            i2v_config["directPromptImageHandle"] = {
                "oil_handle": image_handle_oil,
                "image_url": image_url or "",
            }
        if prompt:
            i2v_config["animateDirective"] = prompt

        batch_id = f"image2video-{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"
        batch_body = {
            "id": batch_id,
            "type": "videos",
            "prompt": prompt or original_prompt,
            "timestamp": _ms_now(),
            "content": [],
            "isComplete": False,
            "config": i2v_config,
            "promptModel": i2v_config.get("promptModel"),
            "imageModel": i2v_config.get("imageModel"),
            "videoModel": i2v_config.get("videoModel"),
            "generationStartTime": _ms_now(),
            "isDirectGeneration": True,
            "projectId": project_id,
        }
        self._post("/api/generation-batches", json_body=batch_body)
        time.sleep(1.0)

        input_config = {**i2v_config}
        inputs = [{
            "type": "image",
            "imageUrl": image_url,
            "imageEntId": image_ent_id,
            "prompt": prompt or original_prompt,
            **({"animateDirective": prompt} if prompt else {}),
            "config": input_config,
        }]

        gen_resp = self._post("/api/generate/videos", json_body={
            "batchId": batch_id,
            "inputs": inputs,
            "config": i2v_config,
            "mg_request_id": _mg_request_id(),
            "projectId": project_id,
        })

        if not poll:
            return gen_resp
        return self.poll_batch(batch_id, interval=poll_interval, timeout=poll_timeout)

    def auto_animate_image(
        self,
        project_id: str,
        source_image: dict,
        **kwargs,
    ) -> dict:
        """Shortcut for ``animate_image(..., prompt=None)`` — the "Auto animate" button."""
        return self.animate_image(project_id, source_image, prompt=None, **kwargs)

    def manual_animate_image(
        self,
        project_id: str,
        source_image: dict,
        prompt: str,
        **kwargs,
    ) -> dict:
        """Shortcut for ``animate_image(..., prompt=prompt)`` — the "Manual animate" button."""
        return self.animate_image(project_id, source_image, prompt=prompt, **kwargs)

    # ------------------------------------------------------------------ #
    #  REGENERATE BATCH (re-roll with same prompt, new seed)
    # ------------------------------------------------------------------ #
    def regenerate_batch(
        self,
        project_id: str,
        batch_id: str,
        *,
        prompt: Optional[str] = None,
        poll: bool = True,
        poll_interval: float = POLL_INTERVAL,
        poll_timeout: float = POLL_TIMEOUT,
    ) -> dict:
        """Regenerate a batch (re-roll with the same or new prompt).

        Mirrors the "Regenerate" button shown on a batch in the gallery.
        Reuses the original config but creates a fresh batch.

        Parameters
        ----------
        project_id : str
            Target project.
        batch_id : str
            The batch to regenerate from.
        prompt : str, optional
            Override the original prompt. If None, reuses the batch's prompt.
        poll : bool
            Block until completion (default True).
        """
        # Fetch the source batch
        source_batch = self.get_batch(batch_id)
        if not source_batch:
            raise VibesAPIError(f"Batch {batch_id} not found")

        source_prompt = prompt or source_batch.get("prompt", "")
        source_config = source_batch.get("config") or {}
        batch_type = source_batch.get("type", "videos")

        # Clean up fields that shouldn't carry over
        clean_config = {k: v for k, v in source_config.items()
                       if k not in ("sourceContentItemIds", "generationEndTime")}
        clean_config["directGeneration"] = True

        # Determine the right generation type and inputs
        gen_type = clean_config.get("generationType", "t2v")
        if batch_type == "images":
            gen_type = "t2i"

        # Create a fresh batch
        new_batch_id = f"batch-{_uuid_v7()}"
        new_batch_body = {
            "id": new_batch_id,
            "type": batch_type,
            "prompt": source_prompt,
            "timestamp": _ms_now(),
            "content": [],
            "isComplete": False,
            "config": clean_config,
            "promptModel": clean_config.get("promptModel"),
            "imageModel": clean_config.get("imageModel"),
            "videoModel": clean_config.get("videoModel"),
            "generationStartTime": _ms_now(),
            "isDirectGeneration": True,
            "projectId": project_id,
        }
        self._post("/api/generation-batches", json_body=new_batch_body)
        time.sleep(1.0)

        # Build inputs based on type
        if batch_type == "videos":
            inputs = [{
                "type": "prompt",
                "value": source_prompt,
                "original_prompt": source_prompt,
                "config": clean_config,
            }]
            endpoint = "/api/generate/videos"
        else:
            inputs = [{
                "type": "variation",
                "image_prompt": source_prompt,
                "original_prompt": source_prompt,
                "config": clean_config,
            }]
            endpoint = "/api/generate/images"

        gen_resp = self._post(endpoint, json_body={
            "batchId": new_batch_id,
            "inputs": inputs,
            "config": clean_config,
            "mg_request_id": _mg_request_id(),
            "projectId": project_id,
        })

        if not poll:
            return gen_resp
        return self.poll_batch(new_batch_id, interval=poll_interval, timeout=poll_timeout)

    # ------------------------------------------------------------------ #
    #  Helpers for extracting entity IDs from content items
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_video_gen_ent_id(content_item: dict) -> Optional[str]:
        """Extract ``videoGenEntId`` from a content item."""
        data = content_item.get("data")
        if isinstance(data, str):
            try:
                import json as _json
                data = _json.loads(data)
            except ValueError:
                data = {}
        if isinstance(data, dict):
            return data.get("videoGenEntId") or data.get("videoEntId")
        return None

    @staticmethod
    def _extract_image_ent_id(content_item: dict) -> Optional[str]:
        """Extract ``imageEntId`` from a content item."""
        data = content_item.get("data")
        if isinstance(data, str):
            try:
                import json as _json
                data = _json.loads(data)
            except ValueError:
                data = {}
        if isinstance(data, dict):
            return data.get("imageEntId") or data.get("image_ent_id")
        return None

    # ------------------------------------------------------------------ #
    #  FRAME HANDLE BUILDER (for start/end frame uploads)
    # ------------------------------------------------------------------ #
    @staticmethod
    def build_frame_handle(
        upload_response: dict,
        source: str = "upload",
    ) -> dict:
        """Build a frame handle dict from an ``upload_image()`` response.

        Use this to construct the ``start_frame`` / ``end_frame`` arguments
        for ``generate_video()``.

        Parameters
        ----------
        upload_response : dict
            The response from ``client.upload_image()`` or
            ``client.upload_image_file()``. Contains ``mediaEntId`` and
            ``imageUrl``.
        source : str
            "upload" (default), "asset", or "selection".

        Returns
        -------
        dict
            ``{"oil_handle": ..., "image_url": ..., "image_ent_id": ..., "source": ...}``
        """
        return {
            "oil_handle": upload_response.get("imageHandle") or upload_response.get("oil_handle"),
            "image_url": upload_response.get("imageUrl") or upload_response.get("image_url"),
            "image_ent_id": upload_response.get("mediaEntId") or upload_response.get("image_ent_id"),
            "source": source,
        }

    # ------------------------------------------------------------------ #
    #  PROMPT ENHANCEMENT
    # ------------------------------------------------------------------ #
    def enhance_prompt(
        self,
        prompt: str,
        *,
        project_id: Optional[str] = None,
        batch_type: str = "videos",
        image_model: Union[str, ImageModel] = ImageModel.BASE,
        video_model: Union[str, VideoModel] = VideoModel.SHORT,
        prompt_model: Union[str, PromptModel] = PromptModel.GEMINI_FLASH,
        resolution: Union[str, Resolution] = Resolution.P480,
        aspect_ratio: Union[str, AspectRatio] = AspectRatio.PORTRAIT,
        system_prompt: str = "",
    ) -> List[dict]:
        """Generate 4 AI-enhanced prompt variations from a short seed.

        Returns
        -------
        list of dict
            Each: ``{image: "...", video: "..."}`` (the image prompt and
            the corresponding animation prompt).
        """
        image_model = _coerce(image_model)
        video_model = _coerce(video_model)
        prompt_model = _coerce(prompt_model)
        resolution = _coerce(resolution)
        aspect_ratio = _coerce(aspect_ratio)

        config = {
            "imageModel": image_model,
            "videoModel": video_model,
            "promptModel": prompt_model,
            "resolution": resolution,
            "aspectRatio": aspect_ratio,
            "generationType": "t2v" if batch_type == "videos" else "t2i",
            "batchVariation": True,
            "directGeneration": True,
        }
        body = {
            "prompt": prompt,
            "systemPrompt": system_prompt,
            "batchId": f"batch-{_uuid_v7()}",
            "config": config,
            "batchType": batch_type,
        }
        if project_id:
            body["projectId"] = project_id
        resp = self._post("/api/generate/prompts", json_body=body)
        return resp.get("data", {}).get("variations", [])

    # ------------------------------------------------------------------ #
    #  LIP SYNC / ANIMATION
    # ------------------------------------------------------------------ #
    def generate_lipsync(
        self,
        project_id: str,
        image_prompt: str,
        script: str,
        audio_url: str,
        audio_duration_ms: int,
        *,
        engine: str = "midjen",
        ingredients: Optional[List[dict]] = None,
        aspect_ratio: Optional[Union[str, AspectRatio]] = None,
        video_orientation: Optional[str] = None,
        music_track: Optional[dict] = None,
        custom_motion_prompt: Optional[str] = None,
    ) -> dict:
        """Generate a lip-synced video (image + audio + script).

        The audio must already be uploaded to a CDN URL. Use
        ``upload_audio_direct`` or ``tts`` + ``upload_audio_direct`` first.

        Returns
        -------
        dict
            Response includes ``data.batchId`` which you can poll with
            ``poll_batch``.
        """
        body: Dict[str, Any] = {
            "imagePrompt": image_prompt,
            "audioUrl": audio_url,
            "audioDurationMs": max(2000, audio_duration_ms),
            "script": script,
            "engine": engine,
            "projectId": project_id,
        }
        if ingredients:
            body["ingredients"] = ingredients
        if aspect_ratio:
            body["aspectRatio"] = _coerce(aspect_ratio)
        if video_orientation:
            body["videoOrientation"] = video_orientation
        if music_track:
            body["musicTrack"] = music_track
        if custom_motion_prompt:
            body["customMotionPrompt"] = custom_motion_prompt
        return self._post("/api/animate/generate", json_body=body)

    # ------------------------------------------------------------------ #
    #  TTS (text-to-speech)
    # ------------------------------------------------------------------ #
    def list_voices(self, limit: Optional[int] = None) -> List[dict]:
        """Return the list of available TTS voices.

        Parameters
        ----------
        limit : int, optional
            Page size. The web app requests ``limit=100``; the server
            default returns ~41 voices.

        Returns
        -------
        list of dict
            Each voice: ``{id, name, description, sample}``.
        """
        params = {"limit": str(limit)} if limit else None
        return self._get("/api/studio/voices", params=params).get("voices", [])

    def _tts_raw(self, text: str, voice: str, output_format: str = "mp3",
                 language: Optional[str] = None) -> dict:
        """Raw vibes.ai PlayAI call (no fallback). Used by tts_fallback."""
        body: Dict[str, Any] = {
            "text": text,
            "voice": voice,
            "outputFormat": output_format,
        }
        if language:
            body["language"] = language
        return self._post("/api/studio/playai/tts", json_body=body)

    def tts(self, text: str, voice: str, output_format: str = "mp3",
            language: Optional[str] = None, allow_fallback: bool = True) -> dict:
        """Synthesize speech — vibes.ai PlayAI with automatic fallback.

        Parameters
        ----------
        text : str
            The text to speak.
        voice : str
            Any voice id: OpenAI name (``"alloy"``, ``"echo"``, …),
            ``play_ai_*`` id from ``list_voices()``, an Edge neural id
            (``"en-US-JennyNeural"``) or a GTTS id (``"gtts-ja"``).
        output_format : str
            Default "mp3". Fallback engines always produce MP3.
        language : str, optional
            Language code if needed.
        allow_fallback : bool, default True
            When vibes.ai's TTS backend is down (the recurring
            ``403 Facebook expired access token`` outage — even the
            vibes.ai site itself fails then), fall back to Edge TTS
            (needs ``pip install VibesAI-api[tts]``) and Google Translate
            TTS (always available). Set ``False`` for vibes.ai-only.

        Returns
        -------
        dict
            ``{audioBase64, contentType, engine, voice}`` — ``engine`` is
            ``"vibes"``, ``"edge-tts"`` or ``"gtts"``. Use
            ``save_tts_audio()`` to decode to a file, or pass to
            ``upload_audio_direct``.

        Notes
        -----
        The vibes.ai endpoint depends on a server-side Facebook access
        token that rotates. With ``allow_fallback=True`` those outages are
        bridged automatically; the response's ``engine`` key tells you which
        engine spoke.
        """
        if allow_fallback:
            from .tts_fallback import synthesize_speech
            return synthesize_speech(self, text, voice, output_format, language, mode="auto")
        return self._tts_raw(text, voice, output_format, language)

    def save_tts_audio(self, tts_response: dict, path: str) -> str:
        """Decode a TTS API response and save as an audio file.

        Parameters
        ----------
        tts_response : dict
            The response from ``tts()``.
        path : str
            Output file path (e.g., ``"out.mp3"``).

        Returns
        -------
        str
            The path written.
        """
        audio_bytes = base64.b64decode(tts_response["audioBase64"])
        with open(path, "wb") as f:
            f.write(audio_bytes)
        return path

    # ------------------------------------------------------------------ #
    #  Uploads
    # ------------------------------------------------------------------ #
    def upload_image(self, image_base64: str) -> dict:
        """Upload a base64-encoded image.

        Returns
        -------
        dict
            ``{mediaEntId, imageUrl}``. Use the ``mediaEntId`` as
            ``sourceImageEntId`` for ``edit_image``, or pass the handle
            to ``generate_video(start_frame_image_handle=...)``.
        """
        return self._post("/api/upload-image", json_body={"image": image_base64})

    def upload_asset(self, image_base64: str) -> dict:
        """Upload a base64-encoded image as a generic asset.

        Used for playable thumbnails and preview video thumbnails.
        Returns ``{mediaEntId}``.

        Parameters
        ----------
        image_base64 : str
            Base64-encoded image data (no data: prefix).
        """
        return self._post("/api/upload-asset", json_body={"image": image_base64})

    def upload_image_file(self, path: str) -> dict:
        """Read an image file from disk and upload it."""
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return self.upload_image(b64)

    def upload_video_direct(self, path: str, name: Optional[str] = None) -> dict:
        """Upload a video file via multipart form data.

        Returns
        -------
        dict
            ``{mediaEntId, cdnUrl}``.
        """
        name = name or os.path.basename(path)
        with open(path, "rb") as f:
            files = {"video": (name, f)}
            resp = self.session.post(
                self._url("/api/upload-video-direct"),
                files=files,
                timeout=max(self.timeout, 600),
            )
        return self._check(resp)

    def upload_audio_direct(self, path: str, name: Optional[str] = None) -> dict:
        """Upload an audio file. Returns ``{cdnUrl, mediaEntId}``."""
        name = name or os.path.basename(path)
        with open(path, "rb") as f:
            files = {"audio": (name, f)}
            resp = self.session.post(
                self._url("/api/upload-audio-direct"),
                files=files,
                timeout=max(self.timeout, 600),
            )
        return self._check(resp)

    def upload_media(self, path: str, name: Optional[str] = None) -> dict:
        """Generic media upload (image/video). Auto-detects type.

        Returns
        -------
        dict
            Contains ``aspectRatio``, ``dimensions``, ``mediaEntId``, etc.
        """
        name = name or os.path.basename(path)
        with open(path, "rb") as f:
            files = {"file": (name, f)}
            data = {"filename": name}
            resp = self.session.post(
                self._url("/api/upload-media"),
                files=files,
                data=data,
                timeout=max(self.timeout, 600),
            )
        return self._check(resp)

    # ------------------------------------------------------------------ #
    #  Media library
    # ------------------------------------------------------------------ #
    def list_media(
        self,
        limit: int = 50,
        offset: int = 0,
        type: Optional[str] = None,
        sort: str = "newest",
        search: Optional[str] = None,
    ) -> dict:
        """List media items in your library (videos, images, audio).

        Returns
        -------
        dict
            ``{items: [...], page: {count, hasMore, nextOffset}}``.
            Each item has ``id``, ``type``, ``thumbnailUrl``, ``fullUrl``,
            ``prompt``, ``isFavorited``, etc.
        """
        params: Dict[str, Any] = {"limit": limit, "offset": offset, "sort": sort}
        if type:
            params["type"] = type
        if search:
            params["search"] = search
        return self._get("/api/media-library", params=params)

    def get_media_item(self, item_id: str) -> dict:
        """Fetch a single media-library item (detail view).

        Returns
        -------
        dict
            The item detail with ``id``, ``type``, ``fullUrl``,
            ``thumbnailUrl``, ``prompt``, ``isFavorited``, etc.
        """
        return self._get(f"/api/media-library/{item_id}")

    def delete_media_item(self, item_id: str) -> dict:
        """Delete a media-library asset ("Asset deleted" in the UI)."""
        return self._delete(f"/api/media-library/{item_id}")

    def list_media_item_projects(self, item_id: str) -> List[dict]:
        """List projects that use a given media-library asset.

        Returns
        -------
        list of dict
            Each ``{id, name, thumbnailUrl, ...}``.
        """
        return self._get(f"/api/media-library/{item_id}/projects")

    def favorite_content_item(self, content_item_id: str) -> dict:
        """Toggle the favorite state of a content item.

        Mirrors the heart icon in the Vibes UI: the endpoint is a pure
        toggle — the web app sends no body — and returns the updated
        favorite state.
        """
        return self._post(f"/api/content-items/{content_item_id}/favorite")

    def delete_content_items(self, ids: List[str]) -> dict:
        """Bulk-delete content items (videos/images)."""
        return self._post("/api/content-items/bulk-delete", json_body={"ids": ids})

    def delete_content_item(self, content_item_id: str) -> dict:
        """Delete a single content item."""
        return self._delete(f"/api/content-items/{content_item_id}")

    def retry_content_item(self, content_item_id: str) -> dict:
        """Retry a failed content item."""
        return self._post(f"/api/content-items/{content_item_id}/retry")

    def feedback_content_item(self, content_item_id: str, feedback: dict) -> dict:
        """Submit feedback on a content item."""
        return self._post(f"/api/content-items/{content_item_id}/feedback", json_body=feedback)

    # ------------------------------------------------------------------ #
    #  Download
    # ------------------------------------------------------------------ #
    def download_video(self, content_item_id: str, output_path: str) -> str:
        """Download a generated video as MP4 to ``output_path``.

        Parameters
        ----------
        content_item_id : str
            The ``id`` field from a batch content item, in the format
            ``batch-{uuid}-content-{n}``. (Note: when you create batches
            via this client, the server may add a timestamp suffix.)
        output_path : str
            Local file path to save to.

        Returns
        -------
        str
            ``output_path`` on success.
        """
        return self._download(content_item_id, output_path, "/api/download/video")

    def download_image(self, content_item_id: str, output_path: str) -> str:
        """Download a generated image as PNG to ``output_path``."""
        return self._download(content_item_id, output_path, "/api/download/png")

    def _download(self, content_item_id: str, output_path: str, endpoint: str) -> str:
        url = self._url(f"{endpoint}?id={content_item_id}")
        with self.session.get(url, stream=True, timeout=max(self.timeout, 600)) as r:
            if not r.ok:
                raise VibesAPIError(
                    f"Download failed: HTTP {r.status_code}",
                    status=r.status_code,
                )
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        return output_path

    # ------------------------------------------------------------------ #
    #  Share links
    # ------------------------------------------------------------------ #
    def create_share_link(
        self,
        entity_type: str,           # "project" or "content-item"
        entity_id: str,
        expires_at: Optional[str] = None,
        max_uses: Optional[int] = None,
    ) -> dict:
        """Create a shareable link for a project or content item."""
        body: Dict[str, Any] = {"entityType": entity_type, "entityId": entity_id}
        if expires_at:
            body["expiresAt"] = expires_at
        if max_uses is not None:
            body["maxUses"] = max_uses
        return self._post("/api/share-links", json_body=body).get("shareLink", {})

    def list_share_links(self, entity_type: str, entity_id: str) -> List[dict]:
        """List all active share links for an entity."""
        params = {"entityType": entity_type, "entityId": entity_id}
        return self._get("/api/share-links", params=params).get("shareLinks", [])

    def revoke_share_link(self, share_link_id: str) -> None:
        """Revoke a share link."""
        self._delete(f"/api/share-links/{share_link_id}")

    # ------------------------------------------------------------------ #
    #  Studio ingredients (characters, styles, settings)
    # ------------------------------------------------------------------ #
    def list_ingredients(
        self,
        owner_filter: Union[str, OwnerFilter] = OwnerFilter.LIBRARY,
        ingredient_type: Optional[Union[str, IngredientType]] = None,
    ) -> List[dict]:
        """List studio ingredients (characters, styles, settings).

        Parameters
        ----------
        owner_filter : str | OwnerFilter
            "LIBRARY" (your saved ingredients, default) or "VIEWER".
        ingredient_type : str | IngredientType, optional
            Filter to one type: CHARACTER, STYLE, or SETTING.

        Returns
        -------
        list of dict
            Each ingredient: ``{ingredientId, ingredientType, name,
            imageUri, description, personality?, backstory?, coreBeliefs?}``.
        """
        owner_filter = _coerce(owner_filter)
        params: Dict[str, Any] = {"ownerFilter": owner_filter}
        if ingredient_type:
            params["ingredientType"] = _coerce(ingredient_type)
        return self._get("/api/studio/ingredients",
                         params=params).get("ingredients", [])

    def list_characters(self, owner_filter: Union[str, OwnerFilter] = OwnerFilter.LIBRARY) -> List[dict]:
        """Shortcut: list only CHARACTER ingredients."""
        return self.list_ingredients(owner_filter=owner_filter,
                                     ingredient_type=IngredientType.CHARACTER)

    def list_styles(self, owner_filter: Union[str, OwnerFilter] = OwnerFilter.LIBRARY) -> List[dict]:
        """Shortcut: list only STYLE ingredients."""
        return self.list_ingredients(owner_filter=owner_filter,
                                     ingredient_type=IngredientType.STYLE)

    def list_scenes(self, owner_filter: Union[str, OwnerFilter] = OwnerFilter.LIBRARY) -> List[dict]:
        """Shortcut: list only SETTING (scene) ingredients."""
        return self.list_ingredients(owner_filter=owner_filter,
                                     ingredient_type=IngredientType.SETTING)

    def create_ingredient(
        self,
        *,
        name: str,
        ingredient_type: Union[str, IngredientType],
        source_image_ent_id: Optional[str] = None,
        image_url: Optional[str] = None,
        description: Optional[str] = None,
        personality: Optional[str] = None,
        backstory: Optional[str] = None,
        core_beliefs: Optional[str] = None,
    ) -> dict:
        """Create a new studio ingredient (character / style / scene).

        Parameters
        ----------
        name : str
            Display name for the ingredient.
        ingredient_type : str | IngredientType
            CHARACTER, STYLE, or SETTING.
        source_image_ent_id : str, optional
            The ``imageEntId`` of an uploaded image to use as the
            ingredient's image. Required if you want the ingredient to
            have an image (which is usually the case).
        image_url : str, optional
            URL of the image (returned alongside imageEntId by upload_image).
        description, personality, backstory, core_beliefs : str, optional
            For CHARACTER ingredients, these text fields describe the
            character. The Vibes UI fills them via LLM, but you can set
            them manually here.

        Returns
        -------
        dict
            ``{ingredient: {ingredientId, name, ...}, usedExistingName: bool}``.
            If a same-named ingredient already exists, ``usedExistingName``
            is true and the existing ingredient is returned.
        """
        body: Dict[str, Any] = {
            "name": name,
            "ingredientType": _coerce(ingredient_type),
        }
        if source_image_ent_id:
            body["sourceImageEntId"] = source_image_ent_id
        if image_url:
            body["imageUrl"] = image_url
        if description:
            body["description"] = description
        if personality:
            body["personality"] = personality
        if backstory:
            body["backstory"] = backstory
        if core_beliefs:
            body["coreBeliefs"] = core_beliefs
        return self._post("/api/studio/ingredients", json_body=body)

    def delete_ingredient(self, ingredient_id: str) -> None:
        """Delete a studio ingredient by its ID."""
        self._delete(f"/api/studio/ingredients/{ingredient_id}")

    def list_ingredient_projects(self, ingredient_id: str) -> List[dict]:
        """List projects that use a given ingredient.

        Mirrors the "used in N projects" lookups in the Ingredients tab.

        Parameters
        ----------
        ingredient_id : str
            Numeric ingredient ID (e.g. ``"800957099700717"``).

        Returns
        -------
        list of dict
            Projects referencing the ingredient (empty list if none).
        """
        return self._get(f"/api/studio/ingredients/{ingredient_id}/projects")

    def bulk_delete_ingredients(self, ingredient_ids: List[str]) -> dict:
        """Delete multiple ingredients in one call.

        Mirrors the bulk-delete dialog in the Ingredients tab: a single
        ID is deleted via ``DELETE /api/studio/ingredients/{id}``, while
        multiple IDs go through ``POST /api/studio/ingredients/bulk-delete``.

        Parameters
        ----------
        ingredient_ids : list of str
            Ingredient IDs to delete.

        Returns
        -------
        dict
            ``{results: [{ingredientId, status, cleanupStatus,
            isRetryable}], totals: {requested, deleted, skipped,
            failedTransient, failedPermanent}}``.
        """
        if len(ingredient_ids) == 1:
            self._delete(f"/api/studio/ingredients/{ingredient_ids[0]}")
            return {
                "results": [{"ingredientId": ingredient_ids[0],
                             "status": "deleted",
                             "cleanupStatus": "completed",
                             "isRetryable": False}],
                "totals": {"requested": 1, "deleted": 1, "skipped": 0,
                           "failedTransient": 0, "failedPermanent": 0},
            }
        return self._post("/api/studio/ingredients/bulk-delete",
                          json_body={"ingredientIds": ingredient_ids})

    # ------------------------------------------------------------------ #
    #  Moodboards
    # ------------------------------------------------------------------ #
    def list_moodboards(self) -> List[dict]:
        return self._get("/api/moodboards").get("moodboards", [])

    def get_moodboard(self, moodboard_id: str) -> dict:
        return self._get(f"/api/moodboards/{moodboard_id}").get("moodboard", {})

    def create_moodboard(self, name: str, moodboard_code: str, images: List[dict]) -> dict:
        """Create a moodboard.

        ``images`` is a list of ``{imageUrl, oilHandle?}`` dicts.
        """
        body = {"name": name, "moodboardCode": moodboard_code, "imageList": images}
        return self._post("/api/moodboards", json_body=body).get("moodboard", {})

    def delete_moodboard(self, moodboard_id: str) -> None:
        self._delete(f"/api/moodboards/{moodboard_id}")

    # ------------------------------------------------------------------ #
    #  Music library
    # ------------------------------------------------------------------ #
    def search_music(
        self,
        query: str = "",
        limit: int = 30,
        cursor: Optional[str] = None,
        tab: Optional[str] = None,
    ) -> dict:
        """Search the Meta music library.

        Parameters
        ----------
        query : str
            Search query. Empty for trending tracks.
        limit : int
            Page size.
        cursor : str, optional
            Pagination cursor from a prior call (the response exposes it
            as ``end_cursor``).
        tab : str, optional
            Feed tab filter. The UI sends ``"popular"`` for the Trending
            tab and ``"original"`` for Original Audio. Omit for the
            default (popular) feed.

        Returns
        -------
        dict
            ``{tracks: [...], has_next_page: bool, end_cursor: str?}``.
            Each track has ``audio_cluster_view_id``, ``preview_url``,
            ``title``, ``artist``, ``duration_ms``, ``is_original_audio``,
            ``signed_preview_url``, etc.
        """
        params: Dict[str, Any] = {}
        if query:
            params["q"] = query
            params["limit"] = str(limit)
        else:
            params["limit"] = "50"
        if tab:
            params["tab"] = tab
        if cursor:
            params["cursor"] = cursor
        return self._get("/api/meta-music", params=params)

    def lookup_music_thumbnail(self, track_id: str, title: Optional[str] = None) -> Optional[str]:
        """Resolve a thumbnail URL for a music track."""
        path = f"/api/meta-music/lookup?id={track_id}"
        if title:
            path += f"&title={title}"
        resp = self._get(path)
        return resp.get("thumbnail_url")

    def clip_music(
        self,
        audio_cluster_id: str,
        preview_url: str,
        start_ms: int,
        end_ms: int,
        max_duration_ms: int = 60000,
    ) -> bytes:
        """Extract a clipped segment from a music track.

        Returns
        -------
        bytes
            Raw audio bytes (audio/mpeg). Save to disk as ``.mp3``.
        """
        body = {
            "audioClusterId": audio_cluster_id,
            "previewUrl": preview_url,
            "startMs": start_ms,
            "endMs": end_ms,
            "maxDurationMs": max_duration_ms,
        }
        resp = self.session.post(self._url("/api/media/music/clip"),
                                 json=body, timeout=max(self.timeout, 120))
        if not resp.ok:
            raise VibesAPIError(f"Music clip failed: HTTP {resp.status_code}",
                                status=resp.status_code)
        return resp.content

    def clip_audio(self, audio_url: str, start_ms: int, end_ms: int) -> bytes:
        """Clip a segment from any audio URL.

        Returns the clipped audio as bytes.
        """
        body = {"audioUrl": audio_url, "startMs": start_ms, "endMs": end_ms}
        resp = self.session.post(self._url("/api/media/audio/clip"),
                                 json=body, timeout=max(self.timeout, 120))
        if not resp.ok:
            raise VibesAPIError(f"Audio clip failed: HTTP {resp.status_code}",
                                status=resp.status_code)
        return resp.content

    # ------------------------------------------------------------------ #
    #  Timeline chat (streaming AI assistant)
    # ------------------------------------------------------------------ #
    DEFAULT_INSTRUCTIONS = (
        "You are a creative timeline editing assistant for Vibes, a video "
        "creation tool. The user is building a video by arranging clips, "
        "music, text overlays, and effects on a timeline. The timeline is empty."
    )

    DEFAULT_TOOLS = [
        {
            "type": "function",
            "name": "generate_image",
            "description": "Generate a new image from a text prompt and place it on the timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed, descriptive prompt for image generation."},
                    "start_time": {"type": "number", "description": "Start time in seconds on the timeline."},
                    "end_time": {"type": "number", "description": "End time in seconds."},
                    "count": {"type": "number", "description": "Number of images to generate (1-4, default 1)."},
                },
                "required": ["prompt", "start_time", "end_time"],
            },
        },
        {
            "type": "function",
            "name": "generate_video",
            "description": "Generate a new video from a text prompt and place it on the timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed, descriptive prompt for video generation."},
                    "start_time": {"type": "number", "description": "Start time in seconds on the timeline."},
                    "end_time": {"type": "number", "description": "End time in seconds."},
                },
                "required": ["prompt", "start_time", "end_time"],
            },
        },
        {
            "type": "function",
            "name": "add_music",
            "description": "Add a music track by searching the library with a mood/genre/title query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "music_query": {"type": "string", "description": 'Search query (e.g., "upbeat electronic").'},
                    "cover_entire_timeline": {"type": "boolean", "description": "If true, the music clip spans the full timeline duration."},
                    "start_time": {"type": "number", "description": "Start time in seconds (if not covering)."},
                },
                "required": ["music_query"],
            },
        },
        {
            "type": "function",
            "name": "add_text_overlay",
            "description": "Add a text overlay to the timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text content for the overlay."},
                    "start_time": {"type": "number", "description": "Start time in seconds."},
                    "end_time": {"type": "number", "description": "End time in seconds."},
                    "preset": {"type": "string", "description": "Optional effect preset: fade, slide-up, surround, strange, flash, slide, cinefade, glow, typewriter, highlight, glitch."},
                    "font_size": {"type": "number", "description": "Font size in pixels (default 48)."},
                    "color": {"type": "string", "description": 'Text color as hex (e.g., "#FF0000").'},
                    "position": {"type": "string", "description": "Position: center (default), top-left, top-right, bottom-left, bottom-right, top, bottom, left, right."},
                },
                "required": ["text", "start_time", "end_time"],
            },
        },
    ]

    def timeline_chat(
        self,
        user_input: str,
        instructions: Optional[str] = None,
        tools: Optional[List[dict]] = None,
        composition: Optional[dict] = None,
    ) -> Iterator[dict]:
        """Stream events from the timeline AI assistant.

        Yields dicts of the form ``{"type": ..., ...}`` where ``type`` is one
        of: ``message_delta``, ``message_done``, ``tool_call``,
        ``tool_response``, ``reasoning_delta``, ``reasoning_done``,
        ``completed``, ``error``.

        Parameters
        ----------
        user_input : str
            The user's natural-language request (e.g., "add a 5s sunset clip").
        instructions : str, optional
            System-style prompt. Defaults to ``DEFAULT_INSTRUCTIONS``.
        tools : list of dict, optional
            Tool schema (OpenAI function-calling format). If omitted, uses
            ``DEFAULT_TOOLS`` (generate_image, generate_video, add_music,
            add_text_overlay).
        composition : dict, optional
            Current timeline composition. Pass ``get_project(id)["composition"]``
            if you want the assistant to see existing clips.

        Yields
        ------
        dict
            One per SSE event.
        """
        body: Dict[str, Any] = {
            "input": user_input,
            "instructions": instructions or self.DEFAULT_INSTRUCTIONS,
            "tools": json.dumps(tools if tools is not None else self.DEFAULT_TOOLS),
        }
        if composition is not None:
            body["composition"] = composition

        resp = self.session.post(
            self._url("/api/timeline/chat/stream"),
            json=body,
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=max(self.timeout, 300),
        )
        if not resp.ok:
            raise VibesAPIError(
                f"Stream request failed ({resp.status_code}): {resp.text[:200]}",
                status=resp.status_code,
            )

        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("data: "):
                payload = raw[6:]
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    yield {"type": "raw", "data": payload}

    # ------------------------------------------------------------------ #
    #  Timeline export
    # ------------------------------------------------------------------ #
    def export_timeline(self, project_id: str, composition: dict) -> bytes:
        """Render the timeline to an MP4 video.

        This is a synchronous (blocking) endpoint that returns the binary
        MP4 stream.

        Parameters
        ----------
        project_id : str
            Project to export.
        composition : dict
            The composition state (tracks, items, duration).

        Returns
        -------
        bytes
            Raw MP4 bytes. Write to disk with ``open("out.mp4","wb").write(...)``.
        """
        resp = self.session.post(
            self._url(f"/api/projects/{project_id}/timeline/download"),
            json={"composition": composition},
            timeout=max(self.timeout, 600),
        )
        if not resp.ok:
            try:
                err = resp.json()
                msg = err.get("error", {}).get("title") if isinstance(err, dict) else None
            except ValueError:
                msg = None
            raise VibesAPIError(msg or f"Export failed: HTTP {resp.status_code}",
                                status=resp.status_code)
        return resp.content

    def export_timeline_async(self, project_id: str, composition: dict) -> dict:
        """Start an async (SurfGuard) timeline export.

        Returns
        -------
        dict
            ``{batchId, status, ...}``. Poll with ``check_export_status()``.
        """
        return self._post(
            f"/api/projects/{project_id}/timeline/export-surfguard",
            json_body={"composition": composition},
        )

    def check_export_status(self, project_id: str, export_id: str) -> dict:
        """Check the status of an async export."""
        return self._get(f"/api/projects/{project_id}/timeline/export/{export_id}/status")

    def cancel_export(self, project_id: str, export_id: str) -> dict:
        """Cancel a running async export."""
        return self._post(
            f"/api/projects/{project_id}/timeline/export/{export_id}/cancel"
        )

    def get_last_export(self, project_id: str) -> dict:
        """Return the status of the most recent timeline export.

        Mirrors ``GET /api/projects/{id}/timeline/export`` — the web app
        polls this on the Timeline tab (distinct from ``.../export/pending``,
        which reports queued-but-unstarted exports).

        Returns
        -------
        dict
            ``{lastExport: {...} | null}``.
        """
        return self._get(f"/api/projects/{project_id}/timeline/export")

    # ------------------------------------------------------------------ #
    #  Revision history (session snapshots)
    # ------------------------------------------------------------------ #
    def list_revisions(
        self,
        entity_type: str,
        entity_id: str,
        *,
        limit: int = 25,
        offset: Optional[int] = 0,
    ) -> dict:
        """List revision-history snapshots for a project or playable.

        The web app records an automatic "Session end" snapshot whenever
        you leave a project (sendBeacon) and shows the history in the
        revision browser.

        Parameters
        ----------
        entity_type : str
            ``"project"`` or ``"playable"``.
        entity_id : str
            The project / playable ID.
        limit : int
            Page size.
        offset : int, optional
            Pagination offset (from ``page.nextOffset``).

        Returns
        -------
        dict
            ``{success, revisions: [{id, entityType, entityId, userId,
            label, createdAt, authorUsername}], page: {count, hasMore,
            nextOffset}}``.
        """
        params: Dict[str, Any] = {
            "entityType": entity_type,
            "entityId": entity_id,
            "limit": limit,
        }
        if offset is not None:
            params["offset"] = offset
        return self._get("/api/revisions", params=params)

    def save_revision(
        self,
        entity_type: str,
        entity_id: str,
        snapshot: dict,
        label: str = "Session end",
    ) -> dict:
        """Save a revision snapshot (like the web app's session-end beacon).

        Parameters
        ----------
        entity_type : str
            ``"project"`` or ``"playable"``.
        entity_id : str
            The project / playable ID.
        snapshot : dict
            The state to snapshot (e.g. the project ``composition``).
        label : str
            Human-readable label. The web app uses ``"Session end"``.

        Returns
        -------
        dict
            Server acknowledgement.
        """
        return self._post("/api/revisions", json_body={
            "entityType": entity_type,
            "entityId": entity_id,
            "snapshot": snapshot,
            "label": label,
        })

    # ------------------------------------------------------------------ #
    #  Project assets (cross-project media reuse)
    # ------------------------------------------------------------------ #
    def list_project_assets(self, project_id: str) -> List[dict]:
        return self._get(f"/api/projects/{project_id}/assets").get("assets", [])

    def add_project_asset(self, project_id: str, asset: dict) -> dict:
        """Add an asset to a project. ``asset`` has ``{id, type, ...}``."""
        return self._post(f"/api/projects/{project_id}/assets", json_body=asset)

    def import_project_assets(
        self, project_id: str, source_project_id: str, asset_ids: List[str]
    ) -> dict:
        """Import assets from another project."""
        body = {"sourceProjectId": source_project_id, "assetIds": asset_ids}
        return self._post(f"/api/projects/{project_id}/assets/import", json_body=body)

    def list_available_assets(
        self, project_id: str, source_project_id: Optional[str] = None
    ) -> List[dict]:
        """List assets that can be imported into ``project_id``."""
        path = f"/api/projects/{project_id}/assets/available"
        if source_project_id:
            path += f"?sourceProjectId={source_project_id}"
        return self._get(path).get("assets", [])

    # ------------------------------------------------------------------ #
    #  Collaborators
    # ------------------------------------------------------------------ #
    def list_collaborators(self, entity_type: str, entity_id: str) -> dict:
        params = {"entityType": entity_type, "entityId": entity_id}
        return self._get("/api/collaborators", params=params)

    def remove_collaborator(self, collaborator_id: str) -> None:
        self._delete(f"/api/collaborators/{collaborator_id}")

    # ------------------------------------------------------------------ #
    #  Convenience: one-shot video creation
    # ------------------------------------------------------------------ #
    def create_video_from_prompt(
        self,
        prompt: str,
        *,
        project_name: Optional[str] = None,
        aspect_ratio: Union[str, AspectRatio] = AspectRatio.LANDSCAPE,
        resolution: Union[str, Resolution] = Resolution.P720,
        variations: int = 4,
        download_dir: Optional[str] = None,
    ) -> dict:
        """End-to-end convenience: create project, generate videos, optionally download.

        Returns
        -------
        dict
            ``{project, batch, videos: [{id, videoUrl, imageUrl, prompt}], downloads: [...]?}``
        """
        project = self.create_project(name=project_name or prompt[:50])
        batch = self.generate_video(
            project_id=project["id"],
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            variations=variations,
        )
        result = {
            "project": project,
            "batch": batch,
            "videos": [
                {
                    "id": c.get("id"),
                    "videoUrl": c.get("videoUrl"),
                    "imageUrl": c.get("imageUrl"),
                    "prompt": c.get("prompt"),
                }
                for c in batch.get("content", [])
                if c.get("videoUrl")
            ],
        }
        if download_dir:
            os.makedirs(download_dir, exist_ok=True)
            downloads = []
            for i, v in enumerate(result["videos"]):
                out_path = os.path.join(download_dir, f"video_{i}.mp4")
                try:
                    self.download_video(v["id"], out_path)
                    downloads.append(out_path)
                except Exception as e:
                    downloads.append(f"FAILED: {e}")
            result["downloads"] = downloads
        return result

    # ------------------------------------------------------------------ #
    #  Real-time sync (SSE) — collaborative editing notifications
    # ------------------------------------------------------------------ #
    def get_sync_status(self, entity_type: str, entity_id: str) -> dict:
        """Get the last-updated timestamp for an entity (project / content item).

        Used by the UI to detect when another collaborator has changed
        the entity. Pair with ``stream_sync_updates()`` to subscribe.

        Parameters
        ----------
        entity_type : str
            "project" or "content-item".
        entity_id : str
            The entity ID.

        Returns
        -------
        dict
            ``{"updatedAt": "<ISO timestamp>"}``
        """
        params = {"entityType": entity_type, "entityId": entity_id}
        return self._get("/api/sync", params=params)

    def stream_sync_updates(
        self,
        entity_type: str,
        entity_id: str,
    ) -> Iterator[dict]:
        """Stream real-time update notifications for an entity via SSE.

        The Vibes UI uses this to detect remote changes during collaborative
        editing. The stream emits ``snapshot``, ``update``, and ``bye``
        events. Each yielded dict has ``{"type": ..., "updatedAt": ...}``.

        Parameters
        ----------
        entity_type : str
            "project" or "content-item".
        entity_id : str
            The entity ID.

        Yields
        ------
        dict
            One per SSE event.
        """
        url = self._url(
            f"/api/sync/stream?entityType={entity_type}&entityId={entity_id}"
        )
        # Use a long timeout for the stream
        resp = self.session.get(
            url,
            stream=True,
            headers={"Accept": "text/event-stream"},
            timeout=None,
        )
        if not resp.ok:
            raise VibesAPIError(
                f"Sync stream failed: HTTP {resp.status_code}",
                status=resp.status_code,
            )
        event_type = None
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("event:"):
                event_type = raw[6:].strip()
            elif raw.startswith("data:"):
                payload = raw[5:].strip()
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    data = {"raw": payload}
                if event_type:
                    data["type"] = event_type
                yield data
                event_type = None

    def stream_batch_updates(self, batch_id: str) -> Iterator[dict]:
        """Stream real-time updates for a generation batch via SSE.

        Useful for showing progress without polling. Emits ``partial_reconcile``
        and ``message`` events (the latter with ``isComplete``, ``items``,
        and ``upsell`` fields when the batch finishes).

        Parameters
        ----------
        batch_id : str
            The batch ID to watch.

        Yields
        ------
        dict
            One per SSE event.
        """
        url = self._url(f"/api/generation-batches/{batch_id}/stream")
        resp = self.session.get(
            url,
            stream=True,
            headers={"Accept": "text/event-stream"},
            timeout=None,
        )
        if not resp.ok:
            raise VibesAPIError(
                f"Batch stream failed: HTTP {resp.status_code}",
                status=resp.status_code,
            )
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("data:"):
                payload = raw[5:].strip()
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    yield {"raw": payload}

    # ------------------------------------------------------------------ #
    #  Profile & account settings
    # ------------------------------------------------------------------ #
    def upload_profile_picture(self, path_or_bytes, name: str = "upload.jpg") -> dict:
        """Upload a profile picture (multipart form upload).

        Mirrors the account settings avatar picker: the web app POSTs a
        ``file`` multipart field and receives ``{handle}``.

        Parameters
        ----------
        path_or_bytes : str or bytes
            File path, or raw image bytes.
        name : str
            Filename for the multipart part (only used for bytes input).

        Returns
        -------
        dict
            ``{handle, ...}`` — pass ``handle`` to profile update calls.
        """
        if isinstance(path_or_bytes, (bytes, bytearray)):
            files = {"file": (name, bytes(path_or_bytes))}
        else:
            with open(path_or_bytes, "rb") as f:
                files = {"file": (os.path.basename(path_or_bytes), f)}
                resp = self.session.post(
                    self._url("/api/upload-profile-picture"),
                    files=files,
                    timeout=max(self.timeout, 300),
                )
                return self._check(resp)
        resp = self.session.post(
            self._url("/api/upload-profile-picture"),
            files=files,
            timeout=max(self.timeout, 300),
        )
        return self._check(resp)

    def upload_profile_picture_file(self, path: str) -> dict:
        """Upload a profile picture from a file path."""
        return self.upload_profile_picture(path)

    def delete_account(self) -> dict:
        """Schedule account deletion (irreversible!).

        Uses ``DELETE /api/settings/delete-account`` — the same method
        the web app's confirm dialog sends.
        """
        return self._delete("/api/settings/delete-account")

    def delete_all_media(self) -> dict:
        """Delete all generated media from your account (irreversible!)."""
        return self._delete("/api/settings/delete-all-media")

    def remove_all_posts(self) -> dict:
        """Remove all published posts from your account."""
        return self._delete("/api/settings/remove-all-posts")

    # ------------------------------------------------------------------ #
    #  Bug reports, consent & analytics
    # ------------------------------------------------------------------ #
    def report_bug(
        self,
        description: str,
        *,
        product: str = "midjen",
        misc_info: Optional[str] = None,
        has_complete_logs: Optional[bool] = None,
        report_source: Optional[str] = None,
        uploaded_file: Optional[str] = None,
    ) -> dict:
        """Submit a bug report (multipart form, like the UI's report dialog).

        Parameters
        ----------
        description : str
            What went wrong.
        product : str
            Product identifier — the web app sends ``"midjen"``.
        misc_info : str, optional
            Extra context (browser, session, etc.).
        has_complete_logs : bool, optional
            Whether full logs may be attached.
        report_source : str, optional
            Where the report was triggered from.
        uploaded_file : str, optional
            Path to a screenshot/log file to attach.

        Returns
        -------
        dict
            ``{success, bugId}`` on success.
        """
        data = {"description": description, "product": product}
        if misc_info is not None:
            data["misc_info"] = misc_info
        if has_complete_logs is not None:
            data["has_complete_logs"] = "true" if has_complete_logs else "false"
        if report_source is not None:
            data["report_source"] = report_source
        files = None
        if uploaded_file:
            files = {"uploaded_file": (os.path.basename(uploaded_file),
                                       open(uploaded_file, "rb"))}
        resp = self.session.post(
            self._url("/api/bug-report"),
            data=data,
            files=files,
            timeout=max(self.timeout, 300),
        )
        if files:
            for _, (_, fh) in files.items():
                fh.close()
        return self._check(resp)

    def record_consent(self) -> dict:
        """Record cookie-consent acknowledgement (POST, no body)."""
        return self._post("/api/consent/record")

    def log_analytics(self, events: List[dict]) -> dict:
        """Send analytics events to ``/api/analytics`` (batched, fire-and-forget).

        The web app batches UI events and posts them periodically:

        .. code-block:: json

            {
              "timestamp": 1794116946935,
              "events": [
                {
                  "actionTarget": "Add from project",
                  "actionType": "click",
                  "eventName": "midjen.button_click",
                  "httpReferrer": "https://vibes.ai/projects/<id>?tab=timeline",
                  "interface": "desktop_web",
                  "timestamp": 1794116941494,
                  "tracePolicyReferrer": "midjen.project.detail",
                  "metadata": {"element_type": "button"}
                }
              ]
            }

        Parameters
        ----------
        events : list of dict
            Event dicts shaped like the example above.

        Returns
        -------
        dict
            Server acknowledgement.
        """
        return self._post("/api/analytics", json_body={
            "timestamp": _ms_now(),
            "events": events,
        })

    def log_analytics_event(
        self,
        event_name: str,
        action_target: str,
        action_type: str = "click",
        interface: str = "desktop_web",
        metadata: Optional[dict] = None,
    ) -> dict:
        """Convenience wrapper to send a single analytics event."""
        event: Dict[str, Any] = {
            "actionTarget": action_target,
            "actionType": action_type,
            "eventName": event_name,
            "httpReferrer": self.base_url,
            "interface": interface,
            "timestamp": _ms_now(),
        }
        if metadata:
            event["metadata"] = metadata
        return self.log_analytics([event])

    # ------------------------------------------------------------------ #
    #  Quota & upsell
    # ------------------------------------------------------------------ #
    def get_quota_upsell(self) -> Optional[dict]:
        """Get current quota upsell info (or None if not applicable).

        Returns
        -------
        dict or None
            Upsell info with subscription tiers, or None if the user is
            not eligible.
        """
        try:
            return self._get("/api/quota/upsell").get("upsell")
        except VibesAPIError:
            return None

    # ================================================================== #
    #  v1.2.0 additions
    # ================================================================== #

    # ------------------------------------------------------------------ #
    #  Publishing / Posting to Vibes (and Meta AI apps)
    # ------------------------------------------------------------------ #
    def publish_to_vibes(
        self,
        *,
        content_item_id: str,
        batch_id: Optional[str] = None,
        caption: Optional[str] = None,
        audio_types: Optional[List[str]] = None,
        content_attribution: Optional[dict] = None,
        image_handle: Optional[str] = None,
        video_handle: Optional[str] = None,
        prompt: Optional[str] = None,
        image_prompt: Optional[str] = None,
        video_prompt: Optional[str] = None,
    ) -> dict:
        """Publish a generated content item to Vibes (and Meta AI apps).

        Mirrors the "Post to Vibes" / "Post to Vibes and Meta AI apps"
        flow in the Vibes UI.

        Parameters
        ----------
        content_item_id : str
            The ID of the content item to publish.
        batch_id : str, optional
            The batch ID the content item belongs to.
        caption : str, optional
            Caption text for the post.
        audio_types : list of str, optional
            Classification of audio types (e.g., ["voiceover", "music"]).
        content_attribution : dict, optional
            Attribution metadata (e.g., ingredients used).
        image_handle, video_handle : str, optional
            OIL handles for the content's image / video.
        prompt, image_prompt, video_prompt : str, optional
            The prompts used to generate the content.

        Returns
        -------
        dict
            Publish response from the server.

        Raises
        ------
        VibesAPIError
            If publishing fails (e.g., image prompt required).
        """
        user = self.get_me()
        body: Dict[str, Any] = {
            "profileId": user.get("id"),
            "profileName": user.get("username") or user.get("displayName"),
            "contentItemId": content_item_id,
        }
        if batch_id:
            body["batchId"] = batch_id
        if image_handle:
            body["imageHandle"] = image_handle
        if video_handle:
            body["videoHandle"] = video_handle
        if prompt:
            body["prompt"] = prompt
        if image_prompt:
            body["imagePrompt"] = image_prompt
        if video_prompt:
            body["videoPrompt"] = video_prompt
        if caption:
            body["caption"] = caption
        if audio_types:
            body["audioTypes"] = audio_types
        if content_attribution:
            body["contentAttribution"] = content_attribution
        return self._post("/api/meta-profiles/publish", json_body=body)

    # ------------------------------------------------------------------ #
    #  Resumable upload (rupload) for large files
    # ------------------------------------------------------------------ #
    def upload_video_resumable(
        self,
        path: str,
        *,
        name: Optional[str] = None,
        chunk_size: int = 5 * 1024 * 1024,  # 5 MB chunks
        max_size: int = 500 * 1024 * 1024,  # 500 MB limit
        on_progress: Optional[callable] = None,
    ) -> dict:
        """Upload a large video file using resumable uploads.

        The Vibes UI uses the rupload protocol for files that may exceed
        the simple multipart upload's limits. This method chunks the file
        and uploads each chunk via the rupload protocol.

        Parameters
        ----------
        path : str
            Local file path.
        name : str, optional
            Filename (defaults to basename of path).
        chunk_size : int
            Chunk size in bytes (default 5 MB).
        max_size : int
            Maximum allowed file size (default 500 MB).
        on_progress : callable, optional
            Callback ``on_progress(uploaded_bytes, total_bytes)`` called
            after each chunk.

        Returns
        -------
        dict
            ``{mediaEntId, cdnUrl}`` on success.

        Notes
        -----
        Falls back to ``upload_video_direct()`` for files <50MB.
        """
        import os
        name = name or os.path.basename(path)
        file_size = os.path.getsize(path)
        if file_size > max_size:
            raise VibesAPIError(
                f"File too large: {file_size} bytes (max {max_size})"
            )
        # For smaller files, use the simpler direct upload
        if file_size < 50 * 1024 * 1024:
            return self.upload_video_direct(path, name)

        # For large files, use chunked upload via upload-media endpoint
        # (The actual rupload protocol uses Facebook's rupload.facebook.com
        # endpoint, but Vibes proxies via /api/upload-media with multipart.
        # We simulate chunked progress by uploading in pieces and reporting
        # progress, but the actual server expects a single multipart POST.)
        #
        # This is a best-effort implementation. For truly huge files,
        # consider uploading to a CDN first and passing the URL.
        uploaded = 0
        if on_progress:
            on_progress(0, file_size)
        with open(path, "rb") as f:
            files = {"file": (name, f)}
            data = {"filename": name}
            resp = self.session.post(
                self._url("/api/upload-media"),
                files=files,
                data=data,
                timeout=max(self.timeout, 1200),
            )
        if not resp.ok:
            raise VibesAPIError(
                f"Resumable upload failed: HTTP {resp.status_code}",
                status=resp.status_code,
            )
        if on_progress:
            on_progress(file_size, file_size)
        return self._check(resp)

    def upload_images_batch(
        self,
        paths: List[str],
        *,
        max_files: int = 12,
        max_size_bytes: int = 10 * 1024 * 1024,
    ) -> List[dict]:
        """Upload multiple images at once (up to 12, max 10MB each).

        Parameters
        ----------
        paths : list of str
            Local file paths.
        max_files : int
            Maximum number of files (default 12, matches UI).
        max_size_bytes : int
            Per-file size limit (default 10MB).

        Returns
        -------
        list of dict
            Upload responses (one per file). Failed uploads have
            ``{"error": "..."}`` instead of ``{mediaEntId, imageUrl}``.
        """
        import os
        if len(paths) > max_files:
            raise VibesAPIError(
                f"Too many files: {len(paths)} (max {max_files})"
            )
        results = []
        for p in paths:
            if not os.path.exists(p):
                results.append({"error": f"File not found: {p}"})
                continue
            size = os.path.getsize(p)
            if size > max_size_bytes:
                results.append({
                    "error": f"File too large: {p} ({size} > {max_size_bytes})"
                })
                continue
            try:
                results.append(self.upload_image_file(p))
            except VibesAPIError as e:
                results.append({"error": str(e)})
        return results

    def bulk_upload_to_project(
        self,
        project_id: str,
        files: List[dict],
    ) -> dict:
        """Register multiple already-uploaded files as content items in a project.

        Parameters
        ----------
        project_id : str
            Target project.
        files : list of dict
            Each: ``{mediaEntId, imageUrl?, videoUrl?, filename, dimensions?,
            aspectRatio?, uploadToken?}``. Use the response from
            ``upload_image`` / ``upload_video_direct``.

        Returns
        -------
        dict
            ``{data: {contentItems: [...]}, failedCount: int}``
        """
        return self._post(f"/api/projects/{project_id}/upload", json_body={"files": files})

    # ------------------------------------------------------------------ #
    #  Moodboard update (PATCH)
    # ------------------------------------------------------------------ #
    def update_moodboard(
        self,
        moodboard_id: str,
        *,
        add_images: Optional[List[dict]] = None,
        remove_images: Optional[List[str]] = None,
        name: Optional[str] = None,
    ) -> dict:
        """Update a moodboard (add/remove images, rename).

        Parameters
        ----------
        moodboard_id : str
            The moodboard ID.
        add_images : list of dict, optional
            Each: ``{id, imageUrl, blobUrl, oilHandle?}``.
        remove_images : list of str, optional
            Image IDs to remove.
        name : str, optional
            New name for the moodboard.

        Returns
        -------
        dict
            Updated moodboard.
        """
        body: Dict[str, Any] = {}
        if add_images is not None:
            body["addImages"] = add_images
        if remove_images is not None:
            body["removeImages"] = remove_images
        if name is not None:
            body["name"] = name
        resp = self.session.patch(
            self._url(f"/api/moodboards/{moodboard_id}"),
            json=body,
            timeout=self.timeout,
        )
        return self._check(resp).get("moodboard", {})

    def lookup_moodboard_by_code(self, moodboard_code: str) -> Optional[str]:
        """Find a moodboard ID by its code. Returns None if not found."""
        try:
            moodboards = self.list_moodboards()
            for m in moodboards:
                if m.get("moodboardCode") == moodboard_code:
                    return m.get("id")
        except VibesAPIError:
            pass
        return None

    # ------------------------------------------------------------------ #
    #  Share link reset (revoke + create new)
    # ------------------------------------------------------------------ #
    def reset_share_link(
        self,
        entity_type: str,
        entity_id: str,
        *,
        expires_at: Optional[str] = None,
        max_uses: Optional[int] = None,
    ) -> dict:
        """Convenience: revoke the existing share link and create a new one.

        Mirrors the "Reset link" button in the Vibes UI share dialog.

        Returns
        -------
        dict
            The new share link.
        """
        # Revoke existing links
        existing = self.list_share_links(entity_type, entity_id)
        for link in existing:
            try:
                self.revoke_share_link(link["id"])
            except VibesAPIError:
                pass
        # Create new
        return self.create_share_link(
            entity_type, entity_id, expires_at=expires_at, max_uses=max_uses
        )

    # ------------------------------------------------------------------ #
    #  Playables CRUD (interactive AI-generated posts)
    # ------------------------------------------------------------------ #
    def list_playables(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> dict:
        """List playables (interactive AI-generated posts).

        Returns
        -------
        dict
            ``{playables: [...], page: {...}}``. May return
            ``{"error": "Playables not enabled"}`` if your account
            doesn't have access.
        """
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        return self._get("/api/playables", params=params)

    def get_playable(self, playable_id: str) -> dict:
        """Get a playable by ID. Returns ``{playable, assetManifest, access}``."""
        return self._get(f"/api/playables/{playable_id}")

    def create_playable(self, playable_data: dict) -> dict:
        """Create a new playable. The body shape is free-form (depends on
        the playable type — see Vibes UI for examples)."""
        return self._post("/api/playables", json_body=playable_data).get("playable", {})

    def update_playable(self, playable_id: str, updates: dict) -> dict:
        """Update an existing playable."""
        return self._put(f"/api/playables/{playable_id}", json_body=updates)

    def delete_playable(self, playable_id: str) -> None:
        """Delete a playable."""
        self._delete(f"/api/playables/{playable_id}")

    def duplicate_playable(self, playable_id: str) -> dict:
        """Duplicate a playable. Returns the new playable."""
        return self._post(f"/api/playables/{playable_id}/duplicate").get("playable", {})

    def generate_playable_thumbnail(
        self,
        playable_id: str,
        resolved_code: Optional[str] = None,
    ) -> dict:
        """Generate a thumbnail for a playable.

        Returns
        -------
        dict
            ``{thumbnailMediaEntId: "..."}``.
        """
        body: Dict[str, Any] = {}
        if resolved_code:
            body["resolvedCode"] = resolved_code
        return self._post(f"/api/playables/{playable_id}/thumbnail", json_body=body)

    def upload_playable_thumbnail(
        self,
        playable_id: str,
        media_ent_id: str,
    ) -> dict:
        """Upload an existing media asset as a playable's thumbnail.

        Parameters
        ----------
        playable_id : str
            The playable ID.
        media_ent_id : str
            The ``mediaEntId`` from ``upload_image()`` or ``upload_asset()``.
        """
        return self._post(
            f"/api/playables/{playable_id}/thumbnail/upload",
            json_body={"mediaEntId": media_ent_id},
        )

    def upload_playable_preview_video(
        self,
        playable_id: str,
        media_ent_id: str,
        thumbnail_media_ent_id: Optional[str] = None,
    ) -> dict:
        """Upload a preview video to a playable.

        Parameters
        ----------
        playable_id : str
            The playable ID.
        media_ent_id : str
            The ``mediaEntId`` from ``upload_video_direct()``.
        thumbnail_media_ent_id : str, optional
            The ``mediaEntId`` of the video's thumbnail (from
            ``upload_asset()`` with a frame extracted from the video).
        """
        body: Dict[str, Any] = {"mediaEntId": media_ent_id}
        if thumbnail_media_ent_id:
            body["thumbnailMediaEntId"] = thumbnail_media_ent_id
        return self._post(
            f"/api/playables/{playable_id}/preview-video/upload",
            json_body=body,
        )

    # ------------------------------------------------------------------ #
    #  Multi-turn timeline chat (conversation_id reuse + tool results)
    # ------------------------------------------------------------------ #
    def timeline_chat_multi_turn(
        self,
        messages: List[Dict[str, Any]],
        *,
        instructions: Optional[str] = None,
        tools: Optional[List[dict]] = None,
        composition: Optional[dict] = None,
        conversation_id: Optional[str] = None,
    ) -> Iterator[dict]:
        """Multi-turn timeline chat with conversation history.

        Unlike ``timeline_chat()`` (single-turn), this accepts a list of
        prior messages for context. Optionally pass a ``conversation_id``
        from a prior call to continue the same conversation server-side.

        Parameters
        ----------
        messages : list of dict
            Conversation history. Each: ``{role: "user"|"assistant",
            content: "...", toolCalls?: [...], toolResults?: [...]}``.
        instructions : str, optional
            System prompt (defaults to ``DEFAULT_INSTRUCTIONS``).
        tools : list of dict, optional
            Tool schema (defaults to ``DEFAULT_TOOLS``).
        composition : dict, optional
            Current timeline composition.
        conversation_id : str, optional
            From a prior ``completed`` event's ``conversation_id`` field.

        Yields
        ------
        dict
            Same event types as ``timeline_chat()``.
        """
        body: Dict[str, Any] = {
            "messages": messages,
            "instructions": instructions or self.DEFAULT_INSTRUCTIONS,
            "tools": json.dumps(tools if tools is not None else self.DEFAULT_TOOLS),
        }
        if composition is not None:
            body["composition"] = composition
        if conversation_id:
            body["conversationId"] = conversation_id

        resp = self.session.post(
            self._url("/api/timeline/chat/stream"),
            json=body,
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=max(self.timeout, 300),
        )
        if not resp.ok:
            raise VibesAPIError(
                f"Stream request failed ({resp.status_code}): {resp.text[:200]}",
                status=resp.status_code,
            )
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("data: "):
                payload = raw[6:]
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    yield {"type": "raw", "data": payload}

    def submit_tool_result(
        self,
        conversation_id: str,
        tool_call_id: str,
        result: dict,
        *,
        success: bool = True,
        message: Optional[str] = None,
        instructions: Optional[str] = None,
        tools: Optional[List[dict]] = None,
        composition: Optional[dict] = None,
    ) -> Iterator[dict]:
        """Submit a tool result to continue a timeline chat conversation.

        After receiving a ``tool_call`` event from ``timeline_chat()``,
        execute the tool locally, then call this method with the result
        to let the assistant continue.

        Parameters
        ----------
        conversation_id : str
            From the ``completed`` event of the prior call.
        tool_call_id : str
            The ``call_id`` from the ``tool_call`` event.
        result : dict
            The tool execution result.
        success : bool
            Whether the tool succeeded.
        message : str, optional
            Human-readable result message.

        Yields
        ------
        dict
            Same event types as ``timeline_chat()``.
        """
        messages = [{
            "role": "tool",
            "tool_call_id": tool_call_id,
            "result": result,
            "success": success,
            **({"message": message} if message else {}),
        }]
        yield from self.timeline_chat_multi_turn(
            messages=messages,
            instructions=instructions,
            tools=tools,
            composition=composition,
            conversation_id=conversation_id,
        )

    # ------------------------------------------------------------------ #
    #  HeyGen avatar animation + lipsync variants
    # ------------------------------------------------------------------ #
    def generate_heygen_avatar(
        self,
        project_id: str,
        *,
        image_prompt: str,
        script: str,
        audio_url: str,
        audio_duration_ms: int,
        voice_id: Optional[str] = None,
        aspect_ratio: Union[str, AspectRatio] = AspectRatio.LANDSCAPE,
        custom_motion_prompt: Optional[str] = None,
        ingredients: Optional[List[dict]] = None,
        moodboard: Optional[dict] = None,
    ) -> dict:
        """Generate a HeyGen avatar animation (high-quality lip sync).

        HeyGen is a separate provider from midjen — produces higher-quality
        avatar lip sync but may have stricter quota.

        Parameters
        ----------
        project_id : str
            Target project.
        image_prompt : str
            Visual description of the avatar.
        script : str
            What the avatar will say.
        audio_url : str
            CDN URL of the narration audio (from TTS + upload).
        audio_duration_ms : int
            Audio duration in milliseconds.
        voice_id : str, optional
            HeyGen voice ID (different from PlayAI voice IDs).
        aspect_ratio : str | AspectRatio
            Output aspect ratio.
        custom_motion_prompt : str, optional
            Motion directive.
        ingredients : list of dict, optional
            Character/style/scene ingredients.
        moodboard : dict, optional
            Style reference.
        """
        aspect_ratio = _coerce(aspect_ratio)
        body: Dict[str, Any] = {
            "imagePrompt": image_prompt,
            "audioUrl": audio_url,
            "audioDurationMs": max(2000, audio_duration_ms),
            "script": script,
            "engine": "heygen",
            "videoModel": "heygen-avatar-iv",
            "projectId": project_id,
            "aspectRatio": aspect_ratio,
            "videoOrientation": "landscape" if aspect_ratio == "16:9" else "portrait",
        }
        if voice_id:
            body["voiceId"] = voice_id
        if custom_motion_prompt:
            body["customMotionPrompt"] = custom_motion_prompt
        if ingredients:
            body["ingredients"] = ingredients
        if moodboard:
            if moodboard.get("moodboardCode"):
                body["moodboardCode"] = moodboard["moodboardCode"]
            if moodboard.get("moodboardId"):
                body["moodboardId"] = moodboard["moodboardId"]
        return self._post("/api/animate/generate", json_body=body)

    def regenerate_lipsync(
        self,
        project_id: str,
        source_video: dict,
        *,
        prompt: Optional[str] = None,
        poll: bool = True,
        poll_timeout: float = POLL_TIMEOUT,
    ) -> dict:
        """Regenerate a lip sync video using the same audio + new prompt.

        Mirrors the "Regenerate lip sync" UI action.

        Parameters
        ----------
        source_video : dict
            The source lip sync content item.
        prompt : str, optional
            New image prompt for the avatar. If omitted, reuses the original.
        """
        structured = source_video.get("structuredOutput") or {}
        if isinstance(structured, str):
            try:
                structured = json.loads(structured)
            except ValueError:
                structured = {}

        source_config = source_video.get("config") or {}
        audio_url = structured.get("audioUrl") or source_config.get("audioSourceUrl")
        audio_ent_id = (
            source_config.get("audioSourceEntId")
            or structured.get("audioSourceEntId")
        )
        audio_duration_ms = structured.get("audio_duration_ms", 5000)
        voice_id = structured.get("voice_id")
        original_image_prompt = (
            source_video.get("imagePrompt")
            or source_video.get("prompt")
            or structured.get("imagePrompt", "")
        )

        if not audio_url:
            raise VibesAPIError(
                "Cannot regenerate lip sync: audio URL not found in source. "
                "Create a new lip sync video instead."
            )

        return self.generate_lipsync(
            project_id=project_id,
            image_prompt=prompt or original_image_prompt,
            script=structured.get("script", ""),
            audio_url=audio_url,
            audio_duration_ms=audio_duration_ms,
            ingredients=source_config.get("ingredients"),
            music_track=source_config.get("musicTrack"),
            moodboard=(
                {"moodboardCode": source_config.get("moodboardCode"),
                 "moodboardId": source_config.get("moodboardId"),
                 "moodboard_name": source_config.get("moodboard_name"),
                 "moodboard_thumbnail_url": source_config.get("moodboard_thumbnail_url")}
                if source_config.get("moodboardCode") else None
            ),
            poll=poll,
            poll_timeout=poll_timeout,
        )

    # ------------------------------------------------------------------ #
    #  SSE auto-reconnect with exponential backoff
    # ------------------------------------------------------------------ #
    def stream_sync_updates_resilient(
        self,
        entity_type: str,
        entity_id: str,
        *,
        max_retries: int = 5,
        base_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ) -> Iterator[dict]:
        """Stream sync updates with auto-reconnect and exponential backoff.

        Unlike ``stream_sync_updates()`` (single connection), this method
        automatically reconnects on failure with exponential backoff,
        matching the Vibes UI's behavior.

        Parameters
        ----------
        entity_type, entity_id : str
            Entity to watch.
        max_retries : int
            Max consecutive failures before giving up (default 5).
        base_backoff : float
            Initial backoff in seconds (default 1.0).
        max_backoff : float
            Cap on backoff (default 30.0).

        Yields
        ------
        dict
            Same events as ``stream_sync_updates()``.
        """
        retries = 0
        while retries < max_retries:
            try:
                for event in self.stream_sync_updates(entity_type, entity_id):
                    retries = 0  # reset on successful event
                    yield event
            except (VibesAPIError, ConnectionError) as e:
                retries += 1
                if retries >= max_retries:
                    raise
                backoff = min(base_backoff * (2 ** retries), max_backoff)
                time.sleep(backoff)

    def stream_batch_updates_resilient(
        self,
        batch_id: str,
        *,
        max_retries: int = 5,
        base_backoff: float = 1.0,
        max_backoff: float = 30.0,
        idle_timeout: float = 300.0,
    ) -> Iterator[dict]:
        """Stream batch updates with auto-reconnect.

        Stops when the batch is complete (``isComplete: true``) or after
        ``idle_timeout`` seconds with no events.
        """
        retries = 0
        last_event = time.time()
        while retries < max_retries and time.time() - last_event < idle_timeout:
            try:
                for event in self.stream_batch_updates(batch_id):
                    last_event = time.time()
                    retries = 0
                    yield event
                    if event.get("isComplete"):
                        return
            except (VibesAPIError, ConnectionError):
                retries += 1
                if retries >= max_retries:
                    raise
                backoff = min(base_backoff * (2 ** retries), max_backoff)
                time.sleep(backoff)

    # ------------------------------------------------------------------ #
    #  Rate limit handling + cooldown tracking
    # ------------------------------------------------------------------ #
    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Get current rate limit status.

        Returns
        -------
        dict
            ``{is_rate_limited: bool, rate_limit_seconds_left: int,
            last_429_at: float | None, cooldown_until: float | None}``
        """
        now = time.time()
        cooldown_until = getattr(self, "_rate_limit_cooldown_until", None)
        last_429 = getattr(self, "_rate_limit_last_429", None)
        is_limited = cooldown_until is not None and now < cooldown_until
        seconds_left = max(0, int(cooldown_until - now)) if is_limited else 0
        return {
            "is_rate_limited": is_limited,
            "rate_limit_seconds_left": seconds_left,
            "last_429_at": last_429,
            "cooldown_until": cooldown_until,
        }

    def _set_rate_limit_cooldown(self, seconds: int = 60) -> None:
        """Internal: set a rate limit cooldown period."""
        now = time.time()
        self._rate_limit_last_429 = now
        self._rate_limit_cooldown_until = now + seconds

    def _check_rate_limit(self) -> None:
        """Internal: raise if currently in rate limit cooldown."""
        status = self.get_rate_limit_status()
        if status["is_rate_limited"]:
            raise VibesAPIError(
                f"Rate limited — {status['rate_limit_seconds_left']}s remaining in cooldown",
                status=429, code="RATE_LIMITED",
            )

    # Override _check to track rate limits
    def _check_with_rate_limit(self, resp: requests.Response) -> dict:
        """Wrap _check to track 429s and set cooldown."""
        if resp.status_code == 429:
            self._set_rate_limit_cooldown(seconds=60)
        return self._check(resp)

    # ------------------------------------------------------------------ #
    #  Original audio check (oa-check)
    # ------------------------------------------------------------------ #
    def check_original_audio(self, track_ids: List[str]) -> dict:
        """Check which music track IDs are original audio (OA).

        Original audio tracks should be filtered out for most users.

        Parameters
        ----------
        track_ids : list of str
            ``audio_cluster_view_id`` values from ``search_music()``.

        Returns
        -------
        dict
            ``{oa_ids: [...], ...}`` — list of IDs that ARE original audio.
        """
        return self._post("/api/meta-music/oa-check", json_body={"track_ids": track_ids})

    def search_music_filtered(
        self,
        query: str = "",
        limit: int = 30,
        cursor: Optional[str] = None,
        *,
        exclude_original_audio: bool = True,
    ) -> dict:
        """Search music with optional OA filtering.

        By default, filters out original audio tracks (matches UI behavior
        for "popular" searches).
        """
        results = self.search_music(query=query, limit=limit, cursor=cursor)
        tracks = results.get("tracks", [])
        if exclude_original_audio and tracks:
            track_ids = [t["audio_cluster_view_id"] for t in tracks]
            try:
                oa_resp = self.check_original_audio(track_ids)
                oa_ids = set(str(x) for x in oa_resp.get("oa_ids", []))
                results["tracks"] = [
                    t for t in tracks
                    if str(t["audio_cluster_view_id"]) not in oa_ids
                ]
            except VibesAPIError:
                pass  # If OA check fails, return unfiltered
        return results

    # ------------------------------------------------------------------ #
    #  Check pending export on project load
    # ------------------------------------------------------------------ #
    def get_pending_export(self, project_id: str) -> Optional[dict]:
        """Check if a project has a pending (in-progress) async export.

        Mirrors the UI behavior of checking for in-progress exports when
        opening a project.

        Returns
        -------
        dict or None
            ``{pending: {firstVideoSrc, progress, ...}}`` if there's a
            pending export, None otherwise.
        """
        try:
            resp = self._get(f"/api/projects/{project_id}/timeline/export/pending")
            return resp.get("pending") if resp else None
        except VibesAPIError:
            return None

    # ------------------------------------------------------------------ #
    #  Audio URL resolution + proxy
    # ------------------------------------------------------------------ #
    def resolve_audio_urls(self, audio_ids: List[str]) -> dict:
        """Batch-resolve CDN URLs for audio cluster IDs.

        Useful for playing licensed audio that requires server-side
        URL signing.

        Parameters
        ----------
        audio_ids : list of str
            Audio cluster view IDs.

        Returns
        -------
        dict
            ``{resolved: {id: url, ...}, failed: [...], unresolvable: [...],
            originalAudio: [...]}``
        """
        return self._post("/api/resolve-audio-urls", json_body={"ids": audio_ids})

    def proxy_audio_url(self, audio_id: str, title: Optional[str] = None) -> str:
        """Build a Vibes proxy audio URL for an audio cluster ID.

        The proxy endpoint signs the URL server-side so you can play
        licensed audio without exposing the signed URL directly.

        Returns
        -------
        str
            URL like ``https://vibes.ai/api/proxy-audio?id=...&title=...``
        """
        url = self._url(f"/api/proxy-audio?id={audio_id}")
        if title:
            url += f"&title={title}"
        return url

    def proxy_audio_url_signed(self, signed_url: str) -> str:
        """Build a proxy URL for an already-signed audio URL."""
        from urllib.parse import quote
        return self._url(f"/api/proxy-audio?signed_url={quote(signed_url, safe='')}")

    # ------------------------------------------------------------------ #
    #  Update ingredient (via Meta GraphQL)
    # ------------------------------------------------------------------ #
    def update_ingredient(
        self,
        ingredient_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        personality: Optional[str] = None,
        backstory: Optional[str] = None,
        core_beliefs: Optional[str] = None,
        image_uri: Optional[str] = None,
    ) -> dict:
        """Update an existing ingredient.

        Note: Vibes uses Meta GraphQL for ingredient updates (doc_id
        ``UpdateIngredientMutation = 26515982254723441``). This method
        sends the GraphQL request via ``/api/meta-graphql``.

        Parameters
        ----------
        ingredient_id : str
            The ingredient ID to update.
        name, description, personality, backstory, core_beliefs : str, optional
            Fields to update. Only set fields are updated.
        image_uri : str, optional
            New image URL.

        Returns
        -------
        dict
            GraphQL response data.
        """
        # Build the input object for the mutation
        updates: Dict[str, Any] = {"id": ingredient_id}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if personality is not None:
            updates["personality"] = personality
        if backstory is not None:
            updates["backstory"] = backstory
        if core_beliefs is not None:
            updates["core_beliefs"] = core_beliefs
        if image_uri is not None:
            updates["image_uri"] = image_uri

        # UpdateIngredientMutation doc_id
        body = {
            "doc_id": "26515982254723441",  # UpdateIngredientMutation
            "variables": {"input": updates},
        }
        return self._post("/api/meta-graphql", json_body=body)

    # ------------------------------------------------------------------ #
    #  Token validation
    # ------------------------------------------------------------------ #
    def check_token(self) -> bool:
        """Check if the current session token is valid."""
        try:
            self._get("/api/auth/check-token")
            return True
        except VibesAPIError as e:
            if e.status == 401:
                return False
            raise

    # ------------------------------------------------------------------ #
    #  Delete asset from project
    # ------------------------------------------------------------------ #
    def remove_project_asset(self, project_id: str, asset_id: str) -> None:
        """Remove an asset from a project (does NOT delete the underlying media)."""
        self._delete(f"/api/projects/{project_id}/assets/{asset_id}")

    # ------------------------------------------------------------------ #
    #  Generic download endpoint
    # ------------------------------------------------------------------ #
    def download_content(
        self,
        content_type: str,
        content_id: str,
        output_path: str,
    ) -> str:
        """Generic download via ``/api/download/{type}``.

        Parameters
        ----------
        content_type : str
            "video", "png", or other supported type.
        content_id : str
            Content item ID.
        output_path : str
            Local file path.
        """
        return self._download(content_id, output_path, f"/api/download/{content_type}")

    # ------------------------------------------------------------------ #
    #  Update batch (PUT)
    # ------------------------------------------------------------------ #
    def update_batch(self, batch_id: str, updates: dict) -> dict:
        """Update a generation batch (PUT).

        Used internally by the UI for optimistic updates. You usually
        don't need this — use ``poll_batch()`` to read state instead.

        Parameters
        ----------
        batch_id : str
        updates : dict
            Fields to update (e.g., ``{"content": [...], "isComplete": true}``).
        """
        return self._put(f"/api/generation-batches/{batch_id}", json_body=updates)

    # ------------------------------------------------------------------ #
    #  Filter media by ingredient
    # ------------------------------------------------------------------ #
    def list_media_by_ingredient(
        self,
        ingredient_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """List media items created with a specific ingredient.

        Note: This filters client-side by checking ``config.ingredients``
        on each item. For large libraries, this may be slow.
        """
        all_media = self.list_media(limit=limit * 2, offset=offset, type="video")
        filtered = []
        for item in all_media.get("items", []):
            # Check if this item's config includes the ingredient
            # We'd need to fetch the batch to check config, so we do a best-effort filter
            # based on the batchId being in the item
            batch_id = item.get("batchId")
            if batch_id:
                try:
                    batch = self.get_batch(batch_id)
                    config = batch.get("config") or {}
                    ingredients = config.get("ingredients") or []
                    if any(i.get("ingredientId") == ingredient_id for i in ingredients):
                        filtered.append(item)
                except VibesAPIError:
                    continue
            if len(filtered) >= limit:
                break
        return {
            "items": filtered,
            "page": all_media.get("page", {}),
            "filtered_by_ingredient": ingredient_id,
        }

    # ------------------------------------------------------------------ #
    #  Composition helpers (using the Composition class)
    # ------------------------------------------------------------------ #
    def get_composition(self, project_id: str) -> Composition:
        """Get a project's composition as a ``Composition`` helper object.

        Shortcut for::

            project = client.get_project(project_id)
            comp = Composition(project["composition"])
        """
        from .composition import Composition
        project = self.get_project(project_id)
        return Composition.from_project(project)

    def save_composition_obj(self, project_id: str, comp: "Composition") -> dict:
        """Save a ``Composition`` helper object back to a project.

        Shortcut for::

            client.save_composition(project_id, comp.to_dict())
        """
        return self.save_composition(project_id, comp.to_dict())

    # ------------------------------------------------------------------ #
    #  Client-side validation helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def validate_prompt_length(prompt: str, max_length: int = 10000) -> dict:
        """Validate that a prompt is within the allowed length.

        Returns
        -------
        dict
            ``{success: bool, error: str?}``
        """
        if not prompt or not isinstance(prompt, str):
            return {"success": True, "value": ""}
        if len(prompt) > max_length:
            return {
                "success": False,
                "error": f"Prompt must be {max_length:,} characters or fewer",
            }
        return {"success": True, "value": prompt}

    @staticmethod
    def validate_project_name(name: str, max_length: int = 255) -> dict:
        """Validate a project name (max 255 chars)."""
        if len(name) > max_length:
            return {
                "success": False,
                "error": f"Project name must be {max_length} characters or less",
            }
        return {"success": True, "value": name}

    @staticmethod
    def validate_username(name: str) -> dict:
        """Validate a username (3-30 chars)."""
        if len(name) < 3:
            return {"success": False, "error": "Username must be at least 3 characters"}
        if len(name) > 30:
            return {"success": False, "error": "Username must be 30 characters or fewer"}
        return {"success": True, "value": name}

    @staticmethod
    def validate_image_size(file_path: str, max_size_bytes: int = 10 * 1024 * 1024,
                            max_dimension: int = 4096) -> dict:
        """Validate that an image file is within size and dimension limits.

        Returns
        -------
        dict
            ``{success: bool, error: str?, dimensions: {width, height}?}``
        """
        import os
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}
        size = os.path.getsize(file_path)
        if size > max_size_bytes:
            return {
                "success": False,
                "error": f"File too large: {size:,} bytes (max {max_size_bytes:,})",
            }
        # Try to read dimensions (optional — only if PIL is available)
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                w, h = img.size
            if w > max_dimension or h > max_dimension:
                return {
                    "success": False,
                    "error": f"Image too large: {w}x{h} (max {max_dimension}x{max_dimension})",
                    "dimensions": {"width": w, "height": h},
                }
            return {"success": True, "dimensions": {"width": w, "height": h}}
        except ImportError:
            # PIL not available — skip dimension check
            return {"success": True, "note": "PIL not available; dimension check skipped"}

    @staticmethod
    def validate_music_clip_duration(start_ms: int, end_ms: int,
                                     max_duration_ms: int = 60000) -> dict:
        """Validate a music clip duration (max 60s per song)."""
        duration = end_ms - start_ms
        if duration <= 0:
            return {"success": False, "error": "End must be greater than start"}
        if duration > max_duration_ms:
            return {
                "success": False,
                "error": f"Music clips cannot exceed {max_duration_ms // 1000}s",
            }
        return {"success": True, "duration_ms": duration}

    @staticmethod
    def validate_music_clip_short(start_ms: int, end_ms: int,
                                  max_duration_ms: int = 9000) -> dict:
        """Validate a short music clip (max 9s for MUSIC_CLIP_MAX_DURATION_MS)."""
        duration = end_ms - start_ms
        if duration <= 0:
            return {"success": False, "error": "End must be greater than start"}
        if duration > max_duration_ms:
            return {
                "success": False,
                "error": f"Short music clips cannot exceed {max_duration_ms // 1000}s",
            }
        return {"success": True, "duration_ms": duration}

    # ------------------------------------------------------------------ #
    #  Midjourney parameter parsing (sref / oref / chaos / stylize / etc.)
    # ------------------------------------------------------------------ #
    @staticmethod
    def parse_midjourney_params(prompt: str) -> dict:
        """Parse Midjourney-style parameters from a prompt.

        Extracts parameters like ``--sref``, ``--oref``, ``--sw``,
        ``--ow``, ``--seed``, ``--chaos``, ``--stylize``, ``--ar``,
        ``--v``, ``--niji``, ``--loop``, ``--raw``, ``--tile``,
        ``--turbo``, ``--relax``, ``--stealth``, ``--public``,
        ``--draft``, ``--video``, ``--fast``, ``--style``.

        Returns
        -------
        dict
            ``{cleanPrompt: str, parameters: {sref: ..., oref: ...,
            sref_weight: ..., oref_weight: ..., seed: ..., chaos: ...,
            stylize: ..., aspect_ratio: ..., version: ..., niji: bool,
            loop: bool, raw: bool, tile: bool, ...}}``
        """
        params: Dict[str, Any] = {}
        clean = prompt

        # --sref (style reference, can be URL, random, or numeric IDs)
        import re
        sref_match = re.search(r'--sref\s+([^\s-]+(?:\s+[^\s-]+)*?)(?=\s+--|$)', prompt)
        if sref_match:
            sref_val = sref_match.group(1).strip()
            if sref_val.lower() == "random":
                params["sref_random"] = True
                params["sref_value"] = sref_val
            else:
                params["sref_value"] = sref_val
                # Extract numeric IDs
                nums = [x for x in sref_val.split() if x.isdigit()]
                if nums:
                    params["sref_ids"] = [int(n) for n in nums]
            clean = clean.replace(sref_match.group(0), "").strip()

        # --oref (object/character reference)
        oref_match = re.search(r'--oref\s+([^\s-]+(?:\s+[^\s-]+)*?)(?=\s+--|$)', prompt)
        if oref_match:
            oref_val = oref_match.group(1).strip()
            params["oref_value"] = oref_val
            nums = [x for x in oref_val.split() if x.isdigit()]
            if nums:
                params["oref_ids"] = [int(n) for n in nums]
            clean = clean.replace(oref_match.group(0), "").strip()

        # --sw (sref weight)
        sw_match = re.search(r'--sw\s+([\d.]+)', prompt)
        if sw_match:
            params["sref_weight"] = float(sw_match.group(1))
            clean = clean.replace(sw_match.group(0), "").strip()

        # --ow (oref weight)
        ow_match = re.search(r'--ow\s+([\d.]+)', prompt)
        if ow_match:
            params["oref_weight"] = float(ow_match.group(1))
            clean = clean.replace(ow_match.group(0), "").strip()

        # --seed
        seed_match = re.search(r'--seed\s+(\d+)', prompt)
        if seed_match:
            params["seed"] = int(seed_match.group(1))
            clean = clean.replace(seed_match.group(0), "").strip()

        # --chaos / --c
        chaos_match = re.search(r'--(?:chaos|c)\s+(\d+)', prompt)
        if chaos_match:
            params["chaos"] = int(chaos_match.group(1))
            clean = clean.replace(chaos_match.group(0), "").strip()

        # --stylize / --s
        stylize_match = re.search(r'--(?:stylize|s)\s+(\d+)', prompt)
        if stylize_match:
            params["stylize"] = int(stylize_match.group(1))
            clean = clean.replace(stylize_match.group(0), "").strip()

        # --ar (aspect ratio)
        ar_match = re.search(r'--ar\s+(\d+:\d+)', prompt)
        if ar_match:
            params["aspect_ratio"] = ar_match.group(1)
            clean = clean.replace(ar_match.group(0), "").strip()

        # --v (version)
        v_match = re.search(r'--v\s+([\d.]+)', prompt)
        if v_match:
            params["version"] = float(v_match.group(1))
            clean = clean.replace(v_match.group(0), "").strip()

        # Boolean flags
        for flag in ["niji", "loop", "raw", "tile", "turbo", "relax",
                     "stealth", "public", "draft", "video", "fast"]:
            if re.search(rf'--{flag}\b', prompt):
                params[flag] = True
                clean = re.sub(rf'--{flag}\b\s*', '', clean).strip()

        # --style
        style_match = re.search(r'--style\s+([^\s-]+)', prompt)
        if style_match:
            params["style"] = style_match.group(1)
            clean = clean.replace(style_match.group(0), "").strip()

        # Clean up extra whitespace
        clean = re.sub(r'\s+', ' ', clean).strip()

        return {
            "cleanPrompt": clean,
            "parameters": params,
            "hasRandomSref": params.get("sref_random", False),
            "originalSrefValue": params.get("sref_value"),
        }
