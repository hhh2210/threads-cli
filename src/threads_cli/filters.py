"""Conservative local filtering. Unknown identity/location stays unknown."""

import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from opencc import OpenCC

GAME = re.compile(r"(?<![A-Za-z0-9])cs(?:\s*:?\s*go|2)?(?![A-Za-z0-9+])|反恐精英", re.I)
RANK = re.compile(r"完美(?:平台)?\s*(黄金|金色|金)?\s*([SABCDEF][+-]?)(?![a-z+])", re.I)
TEAM = re.compile(
    r"搭子|队友|固[排玩]|[找缺来].{0,8}[人友]|一起.{0,8}[打玩]|[打玩].{0,8}一起|有[无没有人].{0,8}[打玩]|[234][=＝缺]"
)
SELL = re.compile(
    r"接单|陪玩.{0,8}(?:[收价元块单]|[0-9])|[0-9]+\s*[元块]/?[时把局]|有偿|进群|加群|群招募"
)
OUTSIDE = re.compile(
    r"(?<!不)(?:只玩|只打|主玩|主打|找.{0,5}队友.{0,5})(?:\s*)(?:faceit|外服|台服|港服|欧服|美服)",
    re.I,
)
NO_PERFECT = re.compile(
    r"(?:不玩|不打|退了|退坑).{0,3}完美|(?:只玩|只打|只)\s*(?:官匹|faceit|5e|外服|台服)", re.I
)
MAINLAND_SELF = re.compile(
    r"(?:本人|我是|人在|坐标|常驻|base\s*(?:in)?\s*)\s*(?:中国大陆|大陆|内地|北京|上海|广州|深圳|杭州|成都|武汉|南京|重庆|天津|西安|苏州|长沙|郑州|合肥|济南|福州|厦门|青岛|沈阳|哈尔滨|昆明|南宁|南昌|贵阳|太原|石家庄)",
    re.I,
)
OUTSIDE_SELF = re.compile(
    r"(?:本人|我是|人在|坐标|常驻|base\s*(?:in)?\s*)\s*(?:台湾|台北|台中|高雄|香港|澳门|日本|韩国|新加坡|马来西亚|美国|加拿大|澳洲|澳大利亚|英国|德国)",
    re.I,
)


@lru_cache
def converter(mode="t2s"):
    return OpenCC(mode)


def writing_system(text: str) -> str:
    if not re.search(r"[\u3400-\u9fff]", text):
        return "non_chinese"
    has_trad = converter().convert(text) != text
    has_simp = converter("s2t").convert(text) != text
    if has_trad:
        return "traditional_or_mixed"
    return "simplified" if has_simp else "undetermined_chinese"


def local_match(
    post: dict,
    all_terms=(),
    excluded=(),
    since: datetime | None = None,
    max_replies: int | None = None,
) -> bool:
    text = converter().convert(post.get("text", "")).casefold()
    if any(converter().convert(term).casefold() not in text for term in all_terms):
        return False
    if any(converter().convert(term).casefold() in text for term in excluded):
        return False
    if since:
        if not post.get("created_at") or datetime.fromisoformat(post["created_at"]) < since:
            return False
    if max_replies is not None:
        if post.get("replies") is None or post["replies"] > max_replies:
            return False
    return True


def classify_cs2(
    post: dict,
    context: list[dict] = (),
    annotation: dict | None = None,
    days: int = 14,
    my_rank: str = "金C+",
    now: datetime | None = None,
    desired_gender: str | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    annotation = annotation or {}
    text = converter().convert(post.get("text", ""))
    rank_match = RANK.search(text)
    is_game = bool(GAME.search(text) or rank_match)
    platform = "perfect" if "完美" in text and is_game else "unknown"
    rank = (("金" if rank_match[1] else "") + rank_match[2].upper()) if rank_match else None
    intent = bool(TEAM.search(text))
    # Short replies inherit only the recruitment topic, never the parent's
    # personal rank or region. Mixed-platform threads leave platform unknown.
    parent = next((p for p in context if p.get("code") == post.get("root_code")), None)
    if post.get("is_reply") and parent:
        parent_text = converter().convert(parent.get("text", ""))
        parent_game = bool(GAME.search(parent_text) or RANK.search(parent_text))
        if parent_game and TEAM.search(parent_text):
            is_game = True
            if re.fullmatch(
                r"\s*(?:[+＋]{1,3}|\+1|1{2,3}|来|有[！!]?|我打|[BC][+-]?\s*来)\s*", text, re.I
            ):
                intent = True
            if "完美" in text:
                platform = "perfect"
    # Replies such as '完美B能一起打吗' carry direct recruitment intent too.
    if rank_match and re.search(r"一起|[+＋]{2}|来|有人", text):
        intent = True
    reasons = []
    exclude = []
    score = (40 if is_game else 0) + (20 if intent else 0)
    if not is_game:
        exclude.append("not_cs2")
    if not intent:
        exclude.append("no_recruitment_intent")
    if SELL.search(text):
        exclude.append("commercial_or_group_recruitment")
    if OUTSIDE.search(text):
        exclude.append("overseas_platform")
    if NO_PERFECT.search(text):
        exclude.append("not_currently_playing_perfect")

    own_updates = sorted(
        [
            p
            for p in context
            if p.get("username") == post.get("username")
            and p.get("root_code") == post.get("code")
            and p.get("created_at")
            and p["created_at"] >= (post.get("created_at") or "")
        ],
        key=lambda p: p["created_at"],
    )
    update_evidence = []
    for update in own_updates:
        update_text = converter().convert(update.get("text", ""))
        if NO_PERFECT.search(update_text):
            exclude.append("author_later_changed_platform")
            update_evidence.append({"url": update["url"], "text": update["text"]})
        m = RANK.search(update_text)
        if m:
            rank = ("金" if m[1] else "") + m[2].upper()
            update_evidence.append({"url": update["url"], "text": update["text"]})

    region = annotation.get("region") or "unknown"
    region_evidence = annotation.get("evidence_url")
    if region == "unknown":
        if OUTSIDE_SELF.search(text):
            region = "outside_mainland_self_reported"
            region_evidence = post["url"]
        elif MAINLAND_SELF.search(text):
            region = "mainland_self_reported"
            region_evidence = post["url"]
    if region.startswith("outside"):
        exclude.append("outside_mainland")
    if region == "unknown":
        reasons.append("region_unverified")
    if platform == "unknown":
        reasons.append("perfect_unverified")
    else:
        score += 30

    if rank is None:
        reasons.append("rank_unverified")
    elif rank.removeprefix("金") in {"C", "C+", "C-", "B", "B-"}:
        score += 20
    elif rank.removeprefix("金") == "B+" or rank.startswith(("A", "S", "金A", "金S")):
        exclude.append("rank_too_high")
    else:
        reasons.append("rank_needs_review")

    gender = annotation.get("gender") or "unknown"
    gender_evidence = annotation.get("gender_evidence_url")
    if desired_gender:
        if gender == "unknown" or not gender_evidence:
            reasons.append("gender_unverified")
        elif gender != desired_gender:
            exclude.append("gender_mismatch")

    age_days = None
    if post.get("created_at"):
        age_days = (now - datetime.fromisoformat(post["created_at"])).total_seconds() / 86400
        if age_days > days:
            reasons.append("old_post")
        else:
            score += 20
    else:
        reasons.append("date_unverified")
    if post.get("replies") is None:
        reasons.append("reply_count_unknown")
    elif post["replies"] <= 10:
        score += 10
    if annotation.get("contacted_at") or post.get("has_viewer_replied"):
        reasons.append("already_contacted")
    if region.startswith("mainland"):
        score += 20
    writing = writing_system(post.get("text", ""))
    if writing == "simplified":
        score += 3
    # Script is a preference; it is never used to assert geographic identity.
    return {
        **post,
        "assessment": {
            "status": "exclude" if exclude else ("review" if reasons else "match"),
            "score": score,
            "my_rank": my_rank,
            "game_matches": is_game,
            "recruitment_intent": intent,
            "rank": rank,
            "platform": platform,
            "region": region,
            "gender": gender,
            "gender_evidence_url": gender_evidence,
            "desired_gender": desired_gender,
            "region_evidence": region_evidence,
            "writing_system": writing,
            "age_days": round(age_days, 1) if age_days is not None else None,
            "reasons": list(dict.fromkeys(exclude + reasons)),
            "author_updates": update_evidence,
        },
    }


def since_value(value: str | None) -> datetime | None:
    if not value:
        return None
    if re.fullmatch(r"\d+d", value):
        return datetime.now(UTC) - timedelta(days=int(value[:-1]))
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
