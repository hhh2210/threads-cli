from datetime import UTC, datetime

from threads_cli.filters import classify_cs2, local_match
from threads_cli.models import Post

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


def post(text, username="alice", code="ROOT123", **updates):
    p = Post(
        code,
        code,
        username,
        text,
        f"https://www.threads.com/@{username}/post/{code}",
        created_at="2026-09-06T12:00:00+00:00",
        replies=2,
    ).to_dict()
    p.update(updates)
    return p


def test_simplified_is_not_proof_of_mainland():
    p = classify_cs2(post("CS2 完美C+ 找队友"), now=NOW)["assessment"]
    assert p["status"] == "review"
    assert p["region"] == "unknown"
    assert p["writing_system"] == "simplified"


def test_gold_c_plus_accepts_b_but_excludes_b_plus_and_above():
    for rank in ("B-", "B", "黄金C+", "金色C+"):
        result = classify_cs2(post(f"本人大陆 CS2 完美{rank} 找队友"), now=NOW)["assessment"]
        assert result["status"] == "match"
        assert result["my_rank"] == "金C+"
    for rank in ("B+", "金B+", "A-", "A+", "金A", "S", "金S"):
        result = classify_cs2(post(f"CS2 完美{rank} 找队友"), now=NOW)["assessment"]
        assert "rank_too_high" in result["reasons"]


def test_short_reply_keeps_topic_without_inheriting_personal_attributes():
    parent = post("本人大陆 CS2 完美A+ 5e都有号 找队友")
    reply = post("B来", username="bob", code="REPLY12", root_code="ROOT123", is_reply=True)
    result = classify_cs2(reply, [parent], now=NOW)["assessment"]
    assert result["status"] == "review"
    assert result["game_matches"] and result["recruitment_intent"]
    assert result["rank"] is None
    assert result["region"] == "unknown"
    assert result["platform"] == "unknown"
    unrelated = post("旅游找队友")
    assert classify_cs2(reply, [unrelated], now=NOW)["assessment"]["status"] == "exclude"


def test_explicit_platform_rank_region_and_intent_can_match():
    p = classify_cs2(post("本人大陆玩家，CS2 完美C+ 找搭子，只玩完美"), now=NOW)["assessment"]
    assert p["status"] == "match"
    assert p["rank"] == "C+"


def test_cs2_adjacent_to_chinese_characters_is_recognized():
    original = post("有人一起玩cs2吗 完美5e都有号 官匹也可以 玩的不是很好")
    update = post("我也只玩官匹", code="REPLY12", root_code="ROOT123")
    result = classify_cs2(original, [update], now=NOW)["assessment"]
    assert result["game_matches"]
    assert result["platform"] == "perfect"
    assert "author_later_changed_platform" in result["reasons"]


def test_ambiguous_perfect_travel_and_programming_are_excluded():
    for text in ("完美的旅游搭子", "C++ 完美解决编程问题", "CS2 退游去打瓦了"):
        assert classify_cs2(post(text), now=NOW)["assessment"]["status"] == "exclude"


def test_later_author_reply_can_revoke_platform_but_other_person_cannot():
    original = post("CS2 完美 5E都有号，找搭子")
    other = post("我只玩官匹", username="bob", code="REPLY12", root_code="ROOT123")
    own = {**other, "username": "alice"}
    a = classify_cs2(original, [other], now=NOW)["assessment"]
    b = classify_cs2(original, [own], now=NOW)["assessment"]
    assert "author_later_changed_platform" not in a["reasons"]
    assert "author_later_changed_platform" in b["reasons"]


def test_rank_in_author_reply_changes_assessment():
    original = post("有没有一起打cs的朋友，完美都有玩")
    own = post("5E S，完美A+", code="REPLY12", root_code="ROOT123")
    a = classify_cs2(original, [own], now=NOW)["assessment"]
    assert a["rank"] == "A+"
    assert "rank_too_high" in a["reasons"]


def test_old_unknown_and_contacted_are_never_silently_promoted():
    original = post("本人大陆 CS2 完美B找搭子", created_at="2026-01-29T00:00:00+00:00")
    a = classify_cs2(original, annotation={"contacted_at": "2026-08-30"}, now=NOW)["assessment"]
    assert a["status"] == "review"
    assert {"old_post", "already_contacted"} <= set(a["reasons"])


def test_strict_local_and_with_script_normalization():
    p = post("CS2 找隊友 完美平台")
    assert local_match(p, ["CS2", "队友", "完美"])
    assert not local_match(p, ["CS2", "大陆"])
    assert not local_match(p, excluded=["完美"])
    assert not local_match({**p, "created_at": None}, since=NOW)
    assert not local_match({**p, "replies": None}, max_replies=10)


def test_region_self_report_conflict_and_commercial_posts():
    for text in ("我在台北",):
        # An unsupported phrase stays unknown rather than inferring residency.
        assert (
            classify_cs2(post(text + "，CS2完美C+找搭子"), now=NOW)["assessment"]["region"]
            == "unknown"
        )
    p = classify_cs2(post("本人台湾，CS2完美C+找搭子"), now=NOW)["assessment"]
    assert "outside_mainland" in p["reasons"]
    p = classify_cs2(post("CS2完美C+找搭子，陪玩接单"), now=NOW)["assessment"]
    assert "commercial_or_group_recruitment" in p["reasons"]


def test_female_filter_requires_sourced_identity_not_avatar_or_word_brother():
    original = post("本人大陆 CS2 完美C+ 找队友，兄弟来")
    a = classify_cs2(original, desired_gender="female", now=NOW)["assessment"]
    assert a["gender"] == "unknown" and "gender_unverified" in a["reasons"]
    a = classify_cs2(original, annotation={"gender": "female"}, desired_gender="female", now=NOW)[
        "assessment"
    ]
    assert a["status"] == "review"
    for gender, status in (("female", "match"), ("male", "exclude")):
        a = classify_cs2(
            original,
            annotation={"gender": gender, "gender_evidence_url": original["url"]},
            desired_gender="female",
            now=NOW,
        )["assessment"]
        assert a["status"] == status
