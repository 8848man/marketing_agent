"""Shared outbound-HTTP helpers: redirect blocking and bounded body reads."""

from __future__ import annotations

from collections.abc import Callable
from urllib.request import HTTPRedirectHandler, OpenerDirector, build_opener


class ResponseTooLarge(ValueError):
    pass


class NoRedirectHandler(HTTPRedirectHandler):
    """Refuse every redirect; urllib then surfaces the 3xx as HTTPError.

    With ``on_redirect`` the returned exception is raised instead.
    """

    def __init__(self, on_redirect: Callable[[], Exception] | None = None):
        self._on_redirect = on_redirect

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if self._on_redirect is not None:
            raise self._on_redirect()
        return None


def opener(on_redirect: Callable[[], Exception] | None = None) -> OpenerDirector:
    return build_opener(NoRedirectHandler(on_redirect))


def read_limited(response, max_bytes: int) -> bytes:
    data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ResponseTooLarge("RESPONSE_TOO_LARGE")
    return data
