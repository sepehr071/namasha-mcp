"""Namasha tools: search, video detail, related, channels, featured, categories. Namasha has no JSON API: pages are parsed."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any
from urllib.parse import quote

from bs4 import BeautifulSoup
from bs4.element import Tag
from pydantic import Field

from .http import SITE, ApiError, fetch
from .registry import tool

UID = re.compile(r"^[A-Za-z0-9]{3,12}$")
USERNAME = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
SLUG = re.compile(r"^[a-z0-9_\-]{1,32}$")
DESC_MAX = 1500
RESERVED = {"v", "search", "playlist", "login", "embed"}

Video = Annotated[
    str, Field(description="Video id (the part after /v/ in the URL, e.g. yt6ef2FC) or the full namasha.com video URL.")
]
Channel = Annotated[str, Field(description="Channel username (the part after namasha.com/, e.g. PooyaCom or 360).")]
Page = Annotated[int, Field(ge=1, le=50, description="Page number, 1-based (60 videos per page).")]

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _uid(video: str) -> str:
    uid = (m.group(1) if (m := re.search(r"/v/([A-Za-z0-9]+)", video)) else video).strip()
    if not UID.match(uid):
        raise ApiError(f"'{video}' is not a video id or namasha.com video URL.")
    return uid


def _user(channel: str) -> str:
    name = re.sub(r"^https?://(www\.)?namasha\.com/", "", channel.strip()).strip("/")
    if not USERNAME.match(name) or name.lower() in RESERVED:
        raise ApiError(f"'{channel}' is not a channel username.")
    return name


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _int(text: str | None) -> int | None:
    digits = re.sub(r"\D", "", (text or "").translate(_DIGITS))
    return int(digits) if digits else None


def _clock(text: str | None) -> int | None:
    """'۰۴:۳۰' or '1:02:03' to seconds."""
    parts = (text or "").translate(_DIGITS).strip().split(":")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    secs = 0
    for p in parts:
        secs = secs * 60 + int(p)
    return secs


def _text(el: Tag | None) -> str | None:
    return el.get_text(" ", strip=True) if el else None


def _card(el: Tag) -> dict | None:
    """One video card (grid or suggestion list). Home cards carry no channel or age."""
    a = el.select_one("a.thumbnail-url")
    m = re.search(r"/v/([A-Za-z0-9]+)", (a or {}).get("href", ""))
    if not m:
        return None
    ch = el.select_one("a:has(.thumbnail-channel-title)")
    age = el.select_one(".thumbnail-text > span, .thumbnail-text > div > span")
    return {
        "id": m.group(1),
        "title": a.get("title") or _text(a),
        "duration_s": _clock(_text(el.select_one(".time-stamp"))),
        "channel": ch["href"].rstrip("/").rsplit("/", 1)[-1] if ch else None,
        "channel_name": _text(el.select_one(".thumbnail-channel-title")),
        "age": _text(age).translate(_DIGITS) if age and not age.select_one(".thumbnail-channel-title") else None,
        "url": f"{SITE}/v/{m.group(1)}",
    }


def _cards(root: Tag | BeautifulSoup) -> list[dict]:
    seen: set[str] = set()
    out = []
    for el in root.select(".thumbnail[data-id]"):
        c = _card(el)
        if c and c["id"] not in seen:
            seen.add(c["id"])
            out.append(c)
    return out


def _nonempty(html: str, what: str) -> BeautifulSoup:
    soup = _soup(html)
    if not soup.select_one("main"):
        raise ApiError(f"Namasha returned an unexpected page for {what}.")
    return soup


@tool("Search Namasha")
async def nm_search(
    query: Annotated[str, Field(description="Persian or English search text.")],
    page: Page = 1,
) -> dict:
    """Search Namasha videos by text.

    Returns up to 60 videos per page (title, duration, channel, age) in the site's order. Use nm_video with an id
    for views, likes and the date.
    """
    if len(query.strip()) < 2:
        raise ApiError("Search text must be at least 2 characters.")
    soup = _nonempty(
        await fetch(f"{SITE}/search", {"q": query.strip(), "page": page} if page > 1 else {"q": query.strip()}),
        "search",
    )
    return {"videos": _cards(soup.select_one(".list-row") or soup), "page": page}


@tool("Namasha video details")
async def nm_video(video: Video) -> dict:
    """Get one Namasha video: title, description, views, likes, comment count, duration, upload date, tags, channel.

    Use nm_related for similar videos and nm_channel for the channel.
    """
    uid = _uid(video)
    soup = _nonempty(await fetch(f"{SITE}/v/{uid}"), f"video {uid}")
    ld: dict[str, Any] = {}
    for s in soup.select('script[type="application/ld+json"]'):
        try:
            d = json.loads(s.string or "")
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "VideoObject":
            ld = d
    if not ld:
        raise ApiError(f"No Namasha video '{video}'.", 404)
    author = ld.get("author") or {}
    comments = soup.select_one("span.action-comment-count")  # server-rendered, also when comments load by AJAX
    dur = soup.select_one('meta[property="video:duration"]')
    ch_link = soup.select_one(".video-description-wrapper, #video-desc")  # channel row sits just above the description
    ch_a = ch_link.find_previous("a", href=re.compile(r"^https://www\.namasha\.com/[^/]+$")) if ch_link else None
    return {
        "id": uid,
        "title": ld.get("name"),
        "description": (_text(soup.select_one("#video-desc")) or "")[:DESC_MAX],
        "views": (ld.get("interactionStatistic") or {}).get("userInteractionCount"),
        "likes": _int(_text(soup.select_one(".video-like-count"))),
        "comments": _int(_text(comments)),
        "duration_s": int(dur["content"]) if dur and dur.get("content", "").isdigit() else None,
        "uploaded": ld.get("uploadDate"),
        "tags": [_text(a) for a in soup.select(".video-tags a")],
        "channel": {
            "username": (ch_a or {}).get("href", "").rstrip("/").rsplit("/", 1)[-1] or None,
            "name": author.get("name"),
            "verified": bool(ch_a and ch_a.select_one("svg")) or None,
        },
        "url": f"{SITE}/v/{uid}",
    }


@tool("Namasha related videos")
async def nm_related(video: Video, page: Annotated[int, Field(ge=1, le=10, description="Page, 1-based.")] = 1) -> dict:
    """List the videos Namasha suggests next to a video (page 1 about 12, later pages 20 each).

    Each has title, duration, channel and age. An empty list means no more pages. Use nm_video for details.
    """
    uid = _uid(video)
    soup = _nonempty(await fetch(f"{SITE}/v/{uid}"), f"video {uid}")
    if page == 1:
        side = soup.select_one(".video-side-bar")
        return {"videos": _cards(side) if side else [], "page": 1}
    m = re.search(r"data-params=\"id:(\d+),page:2\"", str(soup))
    if not m:
        return {"videos": [], "page": page}
    return {
        "videos": _cards(_soup(await fetch(f"{SITE}/suggestedVideos", {"id": m.group(1), "page": page}))),
        "page": page,
    }


@tool("Namasha comments")
async def nm_comments(video: Video) -> dict:
    """List the public comments of a video (text, author, age, likes; replies follow their parent).

    Most videos have none. nm_video gives the comment count.
    """
    uid = _uid(video)
    soup = _nonempty(await fetch(f"{SITE}/v/{uid}"), f"video {uid}")
    m = re.search(r"/videoComments'\s*,\s*\{\s*id:\s*(\d+)", str(soup))
    if not m:
        return {"comments": []}
    frag = _soup(await fetch(f"{SITE}/videoComments", {"id": m.group(1)}))
    emoji = {
        re.search(r"/(\d+)\.png", i["src"]).group(1): i.get("alt") or ""
        for i in frag.select("img.emoji-img[src]")
        if re.search(r"/(\d+)\.png", i["src"])
    }
    out = []
    for c in frag.select(".comment[data-id]"):
        body = c.select_one(".comment-text")
        if not body:
            continue
        for i in body.select("img[src]"):
            n = re.search(r"/(\d+)\.png", i["src"])
            i.replace_with(f" :{emoji.get(n.group(1), '')}: " if n and emoji.get(n.group(1)) else "")
        a = c.select_one("a.comment-author")
        rates = [_int(_text(r)) for r in c.select(".comment-rate-count")]
        out.append(
            {
                "id": c["data-id"],
                "author": a["href"].rstrip("/").rsplit("/", 1)[-1] if a else None,
                "author_name": _text(c.select_one(".comment-channel-title")),
                "text": re.sub(r"\s+", " ", _text(body) or ""),
                "age": (_text(c.select_one("time")) or "").translate(_DIGITS) or None,
                "likes": rates[0] if rates else None,
                "dislikes": rates[1] if len(rates) > 1 else None,
                "reply": "reply" in c.get("class", []) or None,
            }
        )
    return {"comments": out}


@tool("Namasha channel")
async def nm_channel(channel: Channel) -> dict:
    """Get a Namasha channel: name, verified flag, description, creation date, links.

    Namasha shows no follower or video counts. Use nm_channel_videos for its videos.
    """
    user = _user(channel)
    soup = _nonempty(await fetch(f"{SITE}/{quote(user)}/about"), f"channel {user}")
    title = soup.select_one("h1.channel-title")
    if not title:
        raise ApiError(f"No Namasha channel '{channel}'.", 404)
    stats = {_text(r.find("span")): _text(r.find_all("span")[-1]) for r in soup.select(".channel-stats .stat-row")}
    desc = soup.find("h2", string=re.compile("توضیحات"))
    p = desc.find_next("p") if desc else None
    desc_text = re.sub(r"\s+", " ", _text(p) or "") or None
    return {
        "username": user,
        "name": _text(title.find("span")),
        "verified": bool(title.select_one("svg")) or None,
        "description": None if desc_text and "توضیحی ثبت نشده" in desc_text else (desc_text or "")[:DESC_MAX],
        "created": (stats.get("تاریخ ایجاد کانال") or "").translate(_DIGITS) or None,
        "links": [
            {"title": _text(a.select_one(".link-text")), "url": a["href"]}
            for a in soup.select(".channel-links a[href]")
        ],
        "url": f"{SITE}/{user}",
    }


@tool("Namasha channel videos")
async def nm_channel_videos(channel: Channel, page: Page = 1) -> dict:
    """List a channel's videos, newest first (60 per page).

    Each has title, duration and age. An empty list means no more pages.
    """
    user = _user(channel)
    soup = _nonempty(await fetch(f"{SITE}/{quote(user)}", {"page": page} if page > 1 else None), f"channel {user}")
    if not soup.select_one("h1.channel-title"):
        raise ApiError(f"No Namasha channel '{channel}'.", 404)
    videos = _cards(soup.select_one(".list-row") or soup)
    for v in videos:
        v["channel"], v["channel_name"] = user, _text(soup.select_one("h1.channel-title span"))
    return {"videos": videos, "page": page}


@tool("Namasha featured videos")
async def nm_featured(
    section: Annotated[
        str, Field(description="'featured' (the editors' picks, منتخب) or 'special' (ویژه).")
    ] = "featured",
) -> dict:
    """List the videos on Namasha's home page: editors' picks or the special row.

    Namasha has no view-based trending list; this is the closest. Home cards carry only title and duration.
    """
    if section not in ("featured", "special"):
        raise ApiError("section must be 'featured' or 'special'.")
    soup = _nonempty(await fetch(f"{SITE}/"), "the home page")
    want = "منتخب" if section == "featured" else "ویژه"
    h2 = next((h for h in soup.select(".list-row h2") if _text(h) == want), None)
    if not h2:
        raise ApiError(f"The '{want}' row is not on the home page right now.")
    return {"section": section, "videos": _cards(h2.find_parent(class_="list-row"))}


@tool("Namasha categories")
async def nm_categories() -> dict:
    """List Namasha's video categories with the slug nm_category_videos takes."""
    soup = _nonempty(await fetch(f"{SITE}/"), "the home page")
    seen: dict[str, str] = {}
    for a in soup.select('[data-popup="category-menu"] a[href*="/playlist/"]'):
        seen.setdefault(a["href"].rstrip("/").rsplit("/", 1)[-1], _text(a))
    return {"categories": [{"slug": k, "name": v} for k, v in seen.items()]}


@tool("Namasha category videos")
async def nm_category_videos(
    category: Annotated[str, Field(description="Category slug from nm_categories, e.g. music or sport.")],
    page: Page = 1,
) -> dict:
    """List the newest videos of a category (60 per page).

    Each has title, duration, channel and age.
    """
    slug = category.strip().lower()
    if not SLUG.match(slug):
        raise ApiError(f"'{category}' is not a category slug; call nm_categories.")
    soup = _nonempty(await fetch(f"{SITE}/playlist/{slug}", {"page": page} if page > 1 else None), f"category {slug}")
    return {
        "category": _text(soup.select_one("main h1")),
        "videos": _cards(soup.select_one(".list-row") or soup),
        "page": page,
    }
