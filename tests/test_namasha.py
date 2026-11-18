import pytest
from conftest import page

pytestmark = pytest.mark.anyio

TOOLS = {
    "nm_search",
    "nm_video",
    "nm_related",
    "nm_comments",
    "nm_channel",
    "nm_channel_videos",
    "nm_featured",
    "nm_categories",
    "nm_category_videos",
}


async def test_all_tools_are_read_only_and_described(client):
    tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True, t.name
        assert t.title and t.description.splitlines()[0].endswith("."), t.name


async def test_search_parses_cards_and_pages(client, api):
    api["/search"] = page("search.html")
    r = (await client.call_tool("nm_search", {"query": "شیر", "page": 2})).structured_content
    v = r["videos"][0]
    assert v["id"] == "BBRSnbYt" and v["duration_s"] == 106 and v["age"] == "9 سال پیش"
    assert v["channel"] == "channel6653942652" and v["url"] == "https://www.namasha.com/v/BBRSnbYt"
    assert len(r["videos"]) == 3 and api.calls[0].url.params["page"] == "2"


async def test_search_rejects_short_text(client, api):
    r = await client.call_tool("nm_search", {"query": " a "})
    assert r.is_error and not api.calls


async def test_video_details(client, api):
    api["/v/yt6ef2FC"] = page("video.html")
    r = (await client.call_tool("nm_video", {"video": "https://www.namasha.com/v/yt6ef2FC?x=1"})).structured_content
    assert r["title"] == "زندگی در طبیعت/ شیرها" and r["views"] == 286309 and r["likes"] == 44
    assert r["duration_s"] == 270 and r["uploaded"].startswith("2025-05-14") and r["comments"] == 0
    assert r["channel"] == {"username": "360", "name": "ویدیوهای 360 درجه", "verified": True}
    assert r["tags"] == ["سرگرمی و طنز"]


async def test_related(client, api):
    api["/v/yt6ef2FC"] = page("video.html")
    r = (await client.call_tool("nm_related", {"video": "yt6ef2FC"})).structured_content
    assert len(r["videos"]) == 3 and r["videos"][0]["id"] == "Gptdserk"
    assert r["videos"][0]["channel"] == "PooyaCom" and r["videos"][0]["duration_s"] == 2664


async def test_video_rejects_bad_id(client, api):
    r = await client.call_tool("nm_video", {"video": "../etc"})
    assert r.is_error and not api.calls


async def test_video_page_without_data_is_not_found(client, api):
    api["/v/zzzzzzzz"] = page("home.html")
    r = await client.call_tool("nm_video", {"video": "zzzzzzzz"})
    assert r.is_error and "No Namasha video" in r.content[0].text


async def test_channel_about(client, api):
    api["/PooyaCom/about"] = page("about.html")
    r = (await client.call_tool("nm_channel", {"channel": "PooyaCom"})).structured_content
    assert r["name"] == "پویاکام" and r["verified"] is True and r["created"] == "15 اسفند 1398"
    assert "\n" not in r["description"] and len(r["links"]) == 2


async def test_channel_videos_fill_in_channel(client, api):
    api["/360"] = page("channel.html")
    r = (await client.call_tool("nm_channel_videos", {"channel": "360"})).structured_content
    assert len(r["videos"]) == 3 and {v["channel"] for v in r["videos"]} == {"360"}


async def test_featured_rows(client, api):
    api["/"] = page("home.html")
    f = (await client.call_tool("nm_featured", {})).structured_content
    s = (await client.call_tool("nm_featured", {"section": "special"})).structured_content
    assert f["videos"] and s["videos"] and f["videos"][0]["id"] != s["videos"][0]["id"]
    assert (await client.call_tool("nm_featured", {"section": "x"})).is_error


async def test_categories(client, api):
    api["/"] = page("home.html")
    r = (await client.call_tool("nm_categories", {})).structured_content
    assert r["categories"][0] == {"slug": "funny", "name": "سرگرمی و طنز"}


async def test_category_videos(client, api):
    api["/playlist/music"] = page("category.html")
    r = (await client.call_tool("nm_category_videos", {"category": "music"})).structured_content
    assert r["category"] == "موسیقی و هنر" and r["videos"][0]["id"] == "CtTmEZHE"
    assert (await client.call_tool("nm_category_videos", {"category": "../x"})).is_error


async def test_video_comment_count_when_comments_load_by_ajax(client, api):
    api["/v/IeReebyg"] = page("video_comments.html")
    r = (await client.call_tool("nm_video", {"video": "IeReebyg"})).structured_content
    assert r["comments"] == 5 and r["views"] == 743


async def test_comments(client, api):
    api["/v/IeReebyg"] = page("video_comments.html")
    api["/videoComments"] = page("comments.html")
    r = (await client.call_tool("nm_comments", {"video": "IeReebyg"})).structured_content["comments"]
    assert len(r) == 5 and api.calls[1].url.params["id"] == "7218543759"
    assert r[0]["text"] and r[0]["author"] and r[0]["age"] and "reply" not in r[0]
    assert sum(1 for c in r if c.get("reply")) == 1
    assert any(":" in c["text"] for c in r)  # emoji image turned into :name:


async def test_comments_none(client, api):
    api["/v/yt6ef2FC"] = page("video.html")
    assert (await client.call_tool("nm_comments", {"video": "yt6ef2FC"})).structured_content == {"comments": []}


async def test_related_page_two(client, api):
    api["/v/IeReebyg"] = page("video_comments.html")
    api["/suggestedVideos"] = page("suggested.html")
    r = (await client.call_tool("nm_related", {"video": "IeReebyg", "page": 2})).structured_content
    assert r["videos"][0]["id"] == "AbCdEf12" and api.calls[1].url.params["page"] == "2"
