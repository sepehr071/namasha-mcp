import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_live_search_video_related(client):
    r = (await client.call_tool("nm_search", {"query": "آموزش"})).structured_content
    assert len(r["videos"]) > 10
    vid = r["videos"][0]["id"]
    v = (await client.call_tool("nm_video", {"video": vid})).structured_content
    assert v["title"] and v["views"] >= 0 and v["duration_s"] > 0 and v["uploaded"] and v["channel"]["username"]
    assert (await client.call_tool("nm_related", {"video": vid})).structured_content["videos"]


async def test_live_channel(client):
    c = (await client.call_tool("nm_channel", {"channel": "PooyaCom"})).structured_content
    assert c["name"] and c["created"]
    r = (await client.call_tool("nm_channel_videos", {"channel": "PooyaCom"})).structured_content
    assert len(r["videos"]) == 60
    p2 = (await client.call_tool("nm_channel_videos", {"channel": "PooyaCom", "page": 2})).structured_content
    assert p2["videos"][0]["id"] != r["videos"][0]["id"]


async def test_live_home_and_categories(client):
    cats = (await client.call_tool("nm_categories", {})).structured_content["categories"]
    assert len(cats) >= 10
    assert (await client.call_tool("nm_category_videos", {"category": cats[0]["slug"]})).structured_content["videos"]
    assert len((await client.call_tool("nm_featured", {})).structured_content["videos"]) >= 6


async def test_live_comments_and_related_pages(client):
    c = (await client.call_tool("nm_comments", {"video": "IeReebyg"})).structured_content["comments"]
    assert c and c[0]["text"]
    p2 = (await client.call_tool("nm_related", {"video": "IeReebyg", "page": 2})).structured_content["videos"]
    assert len(p2) > 5
