"""Private, local request/response pipe to the already-connected browser.

Only normalized public content crosses this boundary. No browser credentials.
"""

import json
import os
import sys
import uuid

from .errors import ThreadsError
from .parser import page_from_data


class BrowserBridge:
    def __init__(self):
        if os.environ.get("THREADS_BROWSER_BRIDGE") != "1":
            raise ThreadsError(
                "browser_connection_required",
                "Run this command through runBrowserCli in the connected Dia browser. "
                "Use --auth public only for the limited anonymous window.",
                4,
            )

    def exchange(self, action: str, **params):
        request_id = uuid.uuid4().hex[:12]
        sys.stdout.write(
            json.dumps({"bridge_request": {"id": request_id, "action": action, **params}}) + "\n"
        )
        sys.stdout.flush()
        line = sys.stdin.readline(20_000_001)
        try:
            if not line or len(line) > 20_000_000:
                raise ValueError()
            reply = json.loads(line)
            if reply.get("id") != request_id:
                raise ValueError()
            if reply.get("error"):
                code = reply["error"].get("code", "browser_error")
                if code not in {
                    "auth_required",
                    "verification_required",
                    "schema_changed",
                    "pagination_unavailable",
                    "browser_error",
                    "rate_limited",
                    "send_unconfirmed",
                    "not_submitted",
                    "account_mismatch",
                    "already_contacted",
                }:
                    code = "browser_error"
                raise ThreadsError(
                    code,
                    reply["error"].get("message", "Browser collection failed."),
                    4 if code in {"auth_required", "verification_required"} else 5,
                )
            return reply
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ThreadsError(
                "browser_error", "Invalid response from the browser bridge.", 5
            ) from None

    def request(self, action: str, **params):
        reply = self.exchange(action, **params)
        try:
            data = reply["page"]
            page = page_from_data(
                data["data_roots"], params.get("kind", "search"), params.get("root_code")
            )
            page.authenticated = bool(data.get("authenticated"))
            page.viewer = data.get("viewer")
            return page
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ThreadsError("browser_error", "Invalid browser page response.", 5) from None
