import json

import pytest

from threads_cli.errors import ThreadsError
from threads_cli.parser import parse_html


def raw_post(code="ROOT123", username="alice", text="CS2 完美C+找搭子", **updates):
    return {
        "code": code,
        "pk": code,
        "user": {"username": username, "full_name": username},
        "caption": {"text": text},
        "taken_at": 1788739200,
        "like_count": 0,
        "text_post_app_info": {"direct_reply_count": 2, "is_reply": False},
        **updates,
    }


def html_for(data):
    payload = {
        "require": [
            [
                "ScheduledServerJS",
                "handle",
                None,
                [
                    {
                        "__bbox": {
                            "require": [
                                [
                                    "RelayPrefetchedStreamCache",
                                    "next",
                                    [],
                                    [
                                        "preloader",
                                        {"__bbox": {"result": {"data": data}, "complete": True}},
                                    ],
                                ]
                            ]
                        }
                    }
                ],
            ]
        ]
    }
    return '<script type="application/json">' + json.dumps(payload) + "</script>"


def search_data(posts, more=False, cursor=None):
    return {
        "searchResults": {
            "edges": [{"node": {"thread": {"thread_items": [{"post": p}]}}} for p in posts],
            "page_info": {"has_next_page": more, "end_cursor": cursor},
        }
    }


def test_normalizes_real_relay_shape_and_preserves_zero():
    page = parse_html(html_for(search_data([raw_post()])), "search")
    post = page.posts[0]
    assert post.text == "CS2 完美C+找搭子"
    assert post.likes == 0
    assert post.replies == 2
    assert post.created_at.endswith("+00:00")
    assert "session" not in post.to_dict()


def test_empty_search_is_valid_only_with_recognized_metadata():
    assert parse_html(html_for(search_data([])), "search").posts == []
    with pytest.raises(ThreadsError, match="No recognized"):
        parse_html(html_for({"unexpected": []}), "search")
    with pytest.raises(ThreadsError, match="pagination"):
        parse_html(html_for({"searchResults": {"edges": []}}), "search")


def test_missing_next_cursor_fails_not_silently_truncates():
    with pytest.raises(ThreadsError, match="no cursor"):
        parse_html(html_for(search_data([raw_post()], True)), "search")


def test_quoted_author_not_promoted_to_candidate():
    post = raw_post()
    post["text_post_app_info"]["share_info"] = {
        "quoted_post": raw_post("QUOTE12", "other", "我是大陆玩家 完美B找搭子")
    }
    page = parse_html(html_for(search_data([post])), "search")
    assert [p.username for p in page.posts] == ["alice"]
    assert page.posts[0].quoted_code == "QUOTE12"


def test_reply_author_and_root_are_not_conflated():
    root = raw_post()
    reply = raw_post("REPLY12", "bob", "只玩官匹")
    reply["text_post_app_info"]["is_reply"] = True
    data = {
        "media": root,
        "data": {
            "edges": [{"node": {"thread_items": [{"post": root}, {"post": reply}]}}],
            "page_info": {"has_next_page": False, "end_cursor": None},
        },
    }
    page = parse_html(html_for(data), "post", "ROOT123")
    assert len(page.posts) == 2
    assert page.posts[1].root_code == "ROOT123"
    assert page.posts[1].username == "bob"
    assert page.posts[0].root_code is None


def test_login_and_challenge_are_not_empty_searches():
    for text in ("Log in to Threads", "Confirm you're human"):
        with pytest.raises(ThreadsError) as e:
            parse_html(f"<html><body>{text}</body></html>", "search")
        assert e.value.exit_code == 4


def test_bootstrap_secrets_never_in_normalized_post():
    bootstrap = {
        "define": [
            ["DTSGInitialData", [], {"token": "fake-test-token"}, 0],
            ["CurrentUserInitialData", [], {"USER_ID": "123"}, 0],
        ]
    }
    page = parse_html(
        html_for(search_data([raw_post()]))
        + '<script type="application/json">'
        + json.dumps(bootstrap)
        + "</script>",
        "search",
    )
    assert not page.authenticated
    assert "fake-test-token" not in json.dumps(page.posts[0].to_dict())
