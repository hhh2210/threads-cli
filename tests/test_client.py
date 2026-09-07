import pytest

from threads_cli.client import Client
from threads_cli.errors import ThreadsError
from threads_cli.models import Page, Post


def p(code):
    return Post(code, code, "alice", "CS2", f"https://www.threads.com/@alice/post/{code}")


def fake_client(tmp_path, monkeypatch, initial, subsequent=None):
    client = Client(directory=tmp_path)
    initial.authenticated = True
    client._read_page = lambda *a, **kw: initial
    if subsequent:
        client._next_search = subsequent
    return client


def test_pagination_dedupe_and_checkpoint(tmp_path, monkeypatch):
    client = fake_client(
        tmp_path,
        monkeypatch,
        Page([p("ONE1234")], True, "cursor1"),
        lambda *a: Page([p("ONE1234"), p("TWO1234")], False),
    )
    checkpoints = []
    result = client.search("cs2", pages=2, on_page=lambda posts: checkpoints.append(posts))
    assert [x.code for x in result.posts] == ["ONE1234", "TWO1234"]
    assert result.pages == 2
    assert len(checkpoints) == 2
    assert result.completion == "complete"


def test_partial_failure_preserves_successful_page(tmp_path, monkeypatch):
    def fail(*args):
        raise ThreadsError("schema_changed", "changed", 6)

    client = fake_client(tmp_path, monkeypatch, Page([p("ONE1234")], True, "cursor1"), fail)
    result = client.search("cs2", pages=2)
    assert len(result.posts) == 1
    assert result.completion == "partial"
    assert result.errors[0]["code"] == "schema_changed"


def test_page_limit_and_repeated_cursor_are_distinct(tmp_path, monkeypatch):
    client = fake_client(
        tmp_path,
        monkeypatch,
        Page([p("ONE1234")], True, "cursor1"),
        lambda *a: Page([p("TWO1234")], True, "cursor1"),
    )
    assert client.search("cs2", pages=1).completion == "page_limit_reached"
    result = client.search("cs2", pages=3)
    assert result.completion == "partial"
    assert result.errors[0]["code"] == "pagination_stalled"


def test_mutation_operation_rejected_before_network(tmp_path):
    client = Client(directory=tmp_path)
    with pytest.raises(ThreadsError) as e:
        client._request(
            "POST",
            "https://www.threads.com/graphql/query",
            data={"fb_api_req_friendly_name": "CreatePostMutation"},
        )
    assert e.value.code == "read_only"
