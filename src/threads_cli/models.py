from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Post:
    code: str
    id: str
    username: str
    text: str
    url: str
    created_at: str | None = None
    collected_at: str = field(default_factory=now_iso)
    name: str = ""
    is_reply: bool = False
    root_code: str | None = None
    likes: int | None = None
    replies: int | None = None
    reposts: int | None = None
    has_viewer_replied: bool | None = None
    language: str | None = None
    media_alt: list[str] = field(default_factory=list)
    quoted_code: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Page:
    posts: list[Post]
    has_next: bool = False
    cursor: str | None = None
    viewer: str | None = None
    profile: dict | None = None
    authenticated: bool = False
    warnings: list[dict] = field(default_factory=list)


@dataclass
class Collection:
    posts: list[Post] = field(default_factory=list)
    pages: int = 0
    has_more: bool = False
    completion: str = "complete"
    errors: list[dict] = field(default_factory=list)
    viewer: str | None = None

    def to_dict(self) -> dict:
        return {
            "posts": [post.to_dict() for post in self.posts],
            "pages": self.pages,
            "has_more": self.has_more,
            "completion": self.completion,
            "errors": self.errors,
            "viewer": self.viewer,
        }
