"""Parse data the Threads web application sends with rendered pages.

Only normalized post/profile fields leave this module. Browser credentials and
bootstrap values are not extracted.
"""

import json
import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from .errors import ThreadsError
from .models import Page, Post


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def integer(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def parse_post(raw: dict, root_code: str | None = None) -> Post | None:
    user = raw.get("user") or {}
    code = raw.get("code")
    username = user.get("username")
    if not code or not username:
        return None
    info = raw.get("text_post_app_info") or {}
    if info.get("is_post_unavailable"):
        return None
    caption = raw.get("caption") or {}
    text = caption.get("text") if isinstance(caption, dict) else str(caption)
    if text is None:
        fragments = (info.get("text_fragments") or {}).get("fragments") or []
        text = "".join(f.get("plaintext") or "" for f in fragments)
    created_at = None
    timestamp = raw.get("taken_at")
    if isinstance(timestamp, (float, int)):
        try:
            created_at = datetime.fromtimestamp(timestamp, UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    alt = [raw["accessibility_caption"]] if raw.get("accessibility_caption") else []
    alt += [
        m["accessibility_caption"]
        for m in (raw.get("carousel_media") or [])
        if m.get("accessibility_caption")
    ]
    quoted = (info.get("share_info") or {}).get("quoted_post") or {}
    return Post(
        code=str(code),
        id=str(raw.get("pk") or raw.get("id") or code),
        username=str(username),
        name=user.get("full_name") or "",
        text=text or "",
        url=f"https://www.threads.com/@{username}/post/{code}",
        created_at=created_at,
        is_reply=bool(info.get("is_reply")),
        root_code=root_code if str(code) != root_code else None,
        likes=integer(raw.get("like_count")),
        replies=integer(info.get("direct_reply_count")),
        reposts=integer(info.get("repost_count")),
        has_viewer_replied=info.get("has_viewer_replied"),
        language=raw.get("detected_language"),
        media_alt=alt,
        quoted_code=quoted.get("code"),
    )


def posts_in(value, root_code=None) -> list[Post]:
    posts = {}

    def walk(item):
        if isinstance(item, dict):
            if item.get("code") and item.get("user"):
                post = parse_post(item, root_code)
                if post:
                    posts[post.code] = post
                # A quoted attachment is context, not another search candidate.
                return
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return list(posts.values())


def _page_info(connection: dict) -> tuple[bool, str | None]:
    info = connection.get("page_info")
    if not isinstance(info, dict) or "has_next_page" not in info:
        raise ThreadsError("schema_changed", "Threads pagination metadata is missing.", 6)
    more = bool(info["has_next_page"])
    cursor = info.get("end_cursor")
    if more and not cursor:
        raise ThreadsError(
            "schema_changed", "Threads says more results exist but gave no cursor.", 6
        )
    return more, cursor


def page_from_data(roots: list[dict], kind: str, root_code: str | None = None) -> Page:
    viewer = None
    for data in roots:
        v = data.get("viewer") or {}
        if isinstance(v, dict):
            u = v.get("user") or v
            if isinstance(u, dict) and u.get("username"):
                viewer = u["username"]

    if kind == "status":
        return Page([], viewer=viewer)

    if kind == "search":
        connection = next((d["searchResults"] for d in roots if "searchResults" in d), None)
        if not isinstance(connection, dict) or not isinstance(connection.get("edges"), list):
            raise ThreadsError("schema_changed", "No recognized Threads search result payload.", 6)
        more, cursor = _page_info(connection)
        return Page(posts_in(connection["edges"]), more, cursor, viewer)

    if kind == "profile":
        users = [d.get("user") for d in roots if isinstance(d.get("user"), dict)]
        user = next((u for u in users if u.get("username")), None)
        if user is None:
            raise ThreadsError("profile_unavailable", "Profile data is absent or unavailable.", 3)
        profile = {
            k: user.get(k)
            for k in ("username", "full_name", "biography", "is_verified", "follower_count")
        }
        return Page([], viewer=viewer, profile=profile)

    media = [d["media"] for d in roots if isinstance(d.get("media"), dict)]
    connections = [
        d["data"]
        for d in roots
        if isinstance(d.get("data"), dict) and isinstance(d["data"].get("edges"), list)
    ]
    # Pagination responses may expose edges directly under `data`.
    connections += [d for d in roots if isinstance(d.get("edges"), list)]
    found = {}
    for post in posts_in(media + connections, root_code):
        found[post.code] = post
    if not found:
        raise ThreadsError(
            "post_unavailable", "No recognized post data; post may be unavailable.", 3
        )
    if root_code and root_code not in found and kind == "post":
        raise ThreadsError("schema_changed", "Response did not contain the requested post.", 6)
    more, cursor = _page_info(connections[0]) if connections else (False, None)
    page = Page(list(found.values()), more, cursor, viewer)
    root = found.get(root_code)
    if kind == "post" and root and root.replies and not connections:
        page.warnings.append(
            {
                "code": "reply_payload_missing",
                "message": "The post reports replies but this page supplied no reply connection.",
            }
        )
    return page


def parse_html(html: str, kind: str, root_code: str | None = None) -> Page:
    soup = BeautifulSoup(html, "html.parser")
    roots = []
    for script in soup.select('script[type="application/json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in objects(payload):
            result = obj.get("result")
            if isinstance(result, dict) and isinstance(result.get("data"), dict):
                key = {"search": "searchResults", "profile": "user", "post": "media"}.get(kind)
                if key in result["data"] and result.get("errors"):
                    raise ThreadsError(
                        "upstream_error", "Threads returned an error for this page's data.", 5
                    )
                roots.append(result["data"])
    if not roots:
        text = soup.get_text(" ", strip=True).lower()
        if any(t in text for t in ("log in to threads", "log into threads", "登录 threads")):
            raise ThreadsError("auth_required", "Threads requires login. Sign in using Dia.", 4)
        if any(t in text for t in ("confirm you're human", "captcha", "unusual activity")):
            raise ThreadsError("verification_required", "Complete Threads verification in Dia.", 4)
    page = page_from_data(roots, kind, root_code)
    page.authenticated = any(
        isinstance(d.get("viewer"), dict)
        and isinstance(d["viewer"].get("user"), dict)
        and bool(d["viewer"]["user"].get("pk") or d["viewer"]["user"].get("id"))
        for d in roots
    )
    for icon in soup.select("svg[aria-label]"):
        if icon.get("aria-label") in {"Profile", "个人主页", "個人檔案", "個人主頁"}:
            anchor = icon.find_parent("a")
            href = anchor.get("href", "") if anchor else ""
            if re.fullmatch(r"/@[A-Za-z0-9_.]+/?", href):
                page.viewer = href.removeprefix("/@").rstrip("/")
                break
    return page
