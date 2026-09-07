import json

import pytest

from threads_cli.errors import ThreadsError
from threads_cli.models import Post
from threads_cli.rate import RateGate
from threads_cli.store import Store
from threads_cli.urls import post_url


def test_observations_dedupe_without_losing_query_provenance(tmp_path):
    store = Store(tmp_path)
    one = store.start_run("search", "cs2")
    two = store.start_run("search", "完美")
    post = Post(
        "ROOT123",
        "123",
        "alice",
        "cs2完美",
        "https://www.threads.com/@alice/post/ROOT123",
        replies=3,
    )
    store.save([post, post], one)
    post.replies = None
    store.save([post], two)
    assert len(store.all_posts()) == 1
    assert len(store.all_posts(one)) == 1
    assert len(store.all_posts(two)) == 1
    assert store.get("ROOT123")["replies"] == 3
    assert store.runs()[0]["finished_at"] is None
    store.close()


def test_cookie_requests_cannot_be_redirected_by_input_urls():
    for url in (
        "https://evil.example/@alice/post/ROOT123",
        "https://www.threads.com.evil.example/@alice/post/ROOT123",
        "http://threads.com/@alice/post/ROOT123",
        "https://token@threads.com/@alice/post/ROOT123",
        "https://threads.com:444/@alice/post/ROOT123",
        "https://threads.com/messages/",
    ):
        with pytest.raises(ThreadsError):
            post_url(url)
    assert post_url("https://threads.net/@alice/post/ROOT123?x=tracking")[0] == (
        "https://www.threads.com/@alice/post/ROOT123"
    )


def test_collectors_do_not_run_in_parallel(tmp_path):
    with RateGate(tmp_path):
        with pytest.raises(ThreadsError) as e, RateGate(tmp_path):
            pass
        assert e.value.code == "collector_busy"


def test_rate_limit_survives_new_process_lifetime(tmp_path):
    with RateGate(tmp_path) as gate:
        gate.block(120)
    with RateGate(tmp_path) as gate:
        with pytest.raises(ThreadsError) as e:
            gate.wait()
        assert e.value.code == "rate_limited"
    assert "blocked_until" in json.loads((tmp_path / "rate.json").read_text())
