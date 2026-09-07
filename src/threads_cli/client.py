from pathlib import Path
from urllib.parse import urlencode, urlsplit

from curl_cffi import requests

from .bridge import BrowserBridge
from .errors import ThreadsError
from .models import Collection
from .parser import parse_html
from .rate import RateGate
from .store import data_dir
from .urls import post_url, profile_url

BASE = "https://www.threads.com"
CRAWLER_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


class Client:
    def __init__(self, directory: Path | None = None, timeout=25, mode="public", viewer=None):
        self.mode = mode
        self.viewer = viewer
        self.timeout = timeout
        self.gate = RateGate(directory or data_dir())
        self.session = None
        self.bridge = None
        self.request_count = 0

    def __enter__(self):
        self.gate.__enter__()
        try:
            if self.mode == "browser":
                self.bridge = BrowserBridge()
            else:
                self.session = requests.Session(impersonate="chrome")
                self.session.headers.update(
                    {"User-Agent": CRAWLER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"}
                )
        except BaseException:
            self.gate.__exit__()
            raise
        return self

    def __exit__(self, *args):
        if self.session:
            self.session.close()
        self.gate.__exit__(*args)

    def _request(self, method, url, **kwargs):
        target = urlsplit(url)
        if target.scheme != "https" or target.netloc != "www.threads.com":
            raise ThreadsError("invalid_destination", "Requests stay on Threads.", 2)
        if method != "GET" or self.mode != "public":
            raise ThreadsError("read_only", "Only public GET requests are supported here.", 2)
        self.gate.wait()
        self.request_count += 1
        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=False)
        except requests.RequestsError:
            raise ThreadsError("network_error", "Threads request failed or timed out.", 5) from None
        if response.status_code == 429:
            self.gate.block()
            raise ThreadsError(
                "rate_limited", "Threads requested a cooldown; collection stopped.", 7
            )
        if response.status_code in {401, 403, 461, 471}:
            raise ThreadsError("verification_required", "Check the Threads page in Dia.", 4)
        if 300 <= response.status_code < 400:
            raise ThreadsError(
                "unexpected_redirect", "Threads redirected this read; use a full canonical URL.", 5
            )
        if response.status_code == 404:
            raise ThreadsError("not_found", "Threads did not find this page.", 3)
        if response.status_code != 200:
            raise ThreadsError("http_error", f"Threads returned HTTP {response.status_code}.", 5)
        return response.text

    def _browser_request(self, action, **params):
        self.gate.wait()
        self.request_count += 1
        try:
            return self.bridge.request(action, **params)
        except ThreadsError as error:
            if error.code == "rate_limited":
                self.gate.block()
            raise

    def _read_page(self, url, kind, root_code=None):
        if self.mode == "browser":
            page = self._browser_request("page", url=url, kind=kind, root_code=root_code)
            if not page.authenticated:
                raise ThreadsError("auth_required", "Complete Threads login in Dia.", 4)
            if self.viewer and page.viewer and self.viewer.casefold() != page.viewer.casefold():
                raise ThreadsError(
                    "account_mismatch",
                    "The browser is signed in as a different profile than the configured viewer.",
                    4,
                )
            return page
        return parse_html(self._request("GET", url), kind, root_code)

    def _next_search(self, query, cursor, recent):
        if self.mode != "browser":
            raise ThreadsError(
                "browser_connection_required", "Deeper search requires the browser connection.", 4
            )
        return self._browser_request(
            "next_search", query=query, cursor=cursor, recent=recent, kind="search"
        )

    def search(self, query: str, recent=False, pages=1, limit=30, on_page=None) -> Collection:
        params = {"q": query, "serp_type": "default"}
        if recent:
            params["filter"] = "recent"
        url = BASE + "/search?" + urlencode(params)
        result = Collection()
        seen = set()
        seen_cursors = set()
        page = None
        for index in range(pages):
            try:
                page = (
                    self._read_page(url, "search")
                    if index == 0
                    else self._next_search(query, page.cursor, recent)
                )
                result.pages += 1
                result.viewer = page.viewer or result.viewer or self.viewer
                if on_page:
                    on_page(page.posts)
                for post in page.posts:
                    if post.code not in seen:
                        seen.add(post.code)
                        result.posts.append(post)
                result.has_more = page.has_next
                if len(result.posts) >= limit:
                    if len(result.posts) > limit or page.has_next:
                        result.completion = "limit_reached"
                        result.has_more = True
                    break
                if not page.has_next:
                    break
                if page.cursor in seen_cursors:
                    raise ThreadsError(
                        "pagination_stalled", "Threads repeated a pagination cursor.", 6
                    )
                seen_cursors.add(page.cursor)
            except ThreadsError as error:
                result.errors.append(error.as_dict())
                result.completion = "partial" if result.posts else "failed"
                break
        else:
            if result.has_more:
                result.completion = "page_limit_reached"
        return result

    def read(self, value: str) -> Collection:
        url, code = post_url(value)
        page = self._read_page(url, "post", code)
        return Collection(
            page.posts,
            1,
            page.has_next,
            "partial"
            if page.warnings
            else ("reply_page_limit_reached" if page.has_next else "complete"),
            errors=page.warnings,
            viewer=page.viewer or self.viewer,
        )

    def user(self, handle: str) -> dict:
        return self._read_page(profile_url(handle), "profile").profile

    def status(self) -> dict:
        if self.mode == "public":
            page = self._read_page(BASE + "/search?q=cs2", "search")
            return {
                "mode": "public",
                "authenticated": False,
                "sample_count": len(page.posts),
                "coverage": "limited_public_window",
                "tracking_viewer": self.viewer,
            }
        page = self._read_page(BASE + "/", "status")
        return {
            "authenticated": True,
            "username": page.viewer,
            "browser": "Dia",
            "transport": "browser_page; no cookies exported",
        }
