import re
from urllib.parse import urlsplit

from .errors import ThreadsError

HOSTS = {"threads.com", "www.threads.com", "threads.net", "www.threads.net"}
HANDLE = re.compile(r"[A-Za-z0-9_.]{1,64}\Z")
CODE = re.compile(r"[A-Za-z0-9_-]{5,32}\Z")


def profile_url(handle: str) -> str:
    handle = handle.removeprefix("@")
    if not HANDLE.fullmatch(handle):
        raise ThreadsError("invalid_handle", "Expected a Threads username.", 2)
    return f"https://www.threads.com/@{handle}"


def post_url(value: str) -> tuple[str, str]:
    if "://" not in value:
        if not CODE.fullmatch(value):
            raise ThreadsError("invalid_post", "Expected a Threads post URL or shortcode.", 2)
        return f"https://www.threads.com/t/{value}", value
    u = urlsplit(value)
    if u.scheme != "https" or u.hostname not in HOSTS or u.port not in (None, 443):
        raise ThreadsError("invalid_url", "Only HTTPS Threads post URLs are accepted.", 2)
    if u.username or u.password:
        raise ThreadsError("invalid_url", "Credentials are not allowed in post URLs.", 2)
    m = re.fullmatch(r"/(?:@([A-Za-z0-9_.]+)/post|t)/([A-Za-z0-9_-]{5,32})/?", u.path)
    if not m:
        raise ThreadsError("invalid_post", "Expected /@username/post/shortcode.", 2)
    handle, code = m.groups()
    path = f"/@{handle}/post/{code}" if handle else f"/t/{code}"
    return f"https://www.threads.com{path}", code
