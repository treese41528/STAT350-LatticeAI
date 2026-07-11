"""Identity: anonymous device IDs now, Purdue CAS later.

The SPA generates a UUID (localStorage) and sends it as `X-Device-Id` on every
request. On first contact we bind it into a signed HttpOnly cookie; thereafter
BOTH must be present and agree. Requiring the custom header also acts as CSRF
protection (cross-site forms cannot set headers), so no separate CSRF token.

CAS integration later = implement another `IdentityProvider` and swap it in
`app.main`; user ids are namespaced ("device:<uuid>" / "cas:<login>") so the
DB and API never care which scheme minted them.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeSerializer

DEVICE_HEADER = "X-Device-Id"
DEVICE_COOKIE = "stat350_device"
_DEVICE_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


@dataclass(frozen=True)
class Identity:
    user_id: str            # "device:<uuid>" | "cas:<login>"
    kind: str               # "device" | "cas"
    display_name: str | None = None


class IdentityProvider(Protocol):
    def resolve(self, request: Request, response: Response) -> Identity | None:
        """Return the request's identity, minting credentials if needed.

        Returns None when the request carries no usable identity (the route
        should 401/400).
        """
        ...


class DeviceCookieIdentity:
    def __init__(self, secret_key: str):
        self._signer = URLSafeSerializer(secret_key, salt="stat350-device")

    def resolve(self, request: Request, response: Response) -> Identity | None:
        header_id = (request.headers.get(DEVICE_HEADER) or "").strip()
        if not _DEVICE_RE.match(header_id):
            return None
        header_id = header_id.lower()

        cookie_raw = request.cookies.get(DEVICE_COOKIE)
        if cookie_raw:
            try:
                cookie_id = self._signer.loads(cookie_raw)
            except BadSignature:
                cookie_id = None
            if cookie_id == header_id:
                return Identity(user_id=f"device:{header_id}", kind="device")
            if cookie_id is not None:
                # Header/cookie mismatch: the cookie is authoritative. Reject so
                # a copied header can't ride someone else's browser session.
                return None

        # First contact (or lost cookie): bind the header id.
        response.set_cookie(
            DEVICE_COOKIE,
            self._signer.dumps(header_id),
            max_age=400 * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return Identity(user_id=f"device:{header_id}", kind="device")


def new_device_id() -> str:
    return str(uuid.uuid4())
