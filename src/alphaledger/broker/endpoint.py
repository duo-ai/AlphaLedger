"""Paper endpoint safety boundary."""

import os
from dataclasses import dataclass, field
from typing import Literal, Protocol
from urllib.parse import urlsplit

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
_BASE_URL_ENVIRONMENT_VARIABLES = (
    "APCA_API_BASE_URL",
    "ALPACA_API_BASE_URL",
    "ALPACA_BASE_URL",
)
_ENDPOINT_REJECTION_REASON = "endpoint_not_paper"
_PATH_REJECTION_REASON = "request_path_invalid"
_REDIRECT_REJECTION_REASON = "redirect_invalid"
_INDETERMINATE_RESPONSE_REASON = "response_indeterminate"
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class IndeterminateResponseError(RuntimeError):
    """The broker's answer does not say whether the request was accepted.

    Every 3xx is one of these, whatever its target. A same-origin redirect is
    not success: the request may or may not have been taken. Design section 11
    step 5 forbids blindly retrying an unknown result, so this is raised rather
    than returned, and the caller must resolve by broker lookup.
    """


class LiveEndpointError(RuntimeError):
    """Raised when an operation could reach a non-paper endpoint."""


class EndpointRecorder(Protocol):
    """Record endpoint decisions without receiving configuration values."""

    def startup(self, banner: str) -> None: ...

    def no_trade(self, reason: str) -> None: ...


@dataclass(frozen=True, init=False)
class EndpointConfiguration:
    """Factory-created paper configuration rechecked for every broker request."""

    base_url: str = field(repr=False)

    def __init__(self) -> None:
        raise TypeError("use EndpointConfiguration.from_resolver")

    @classmethod
    def from_resolver(cls, recorder: EndpointRecorder) -> EndpointConfiguration:
        """Create configuration only from the fail-closed endpoint resolver."""
        configuration = object.__new__(cls)
        object.__setattr__(configuration, "base_url", resolve_paper_base_url(recorder))
        return configuration


@dataclass(frozen=True)
class TransportResponse:
    """Response metadata required to reject redirect replay."""

    status_code: int
    location: str | None = field(default=None, repr=False)


class PaperTransport(Protocol):
    """Transport that exposes redirect control and the actual request target."""

    def request(
        self,
        url: str,
        body: bytes,
        *,
        follow_redirects: Literal[False],
    ) -> TransportResponse: ...


def resolve_paper_base_url(recorder: EndpointRecorder) -> str:
    for variable_name in _BASE_URL_ENVIRONMENT_VARIABLES:
        configured_url = os.environ.get(variable_name)
        if configured_url is not None and configured_url != PAPER_BASE_URL:
            recorder.no_trade(_ENDPOINT_REJECTION_REASON)
            raise LiveEndpointError(f"paper endpoint required; reject {variable_name}")
    return PAPER_BASE_URL


def assert_paper_endpoint(base_url: str, recorder: EndpointRecorder) -> None:
    if base_url != PAPER_BASE_URL:
        recorder.no_trade(_ENDPOINT_REJECTION_REASON)
        raise LiveEndpointError("paper endpoint required")


def validate_process_start(recorder: EndpointRecorder) -> str:
    base_url = resolve_paper_base_url(recorder)
    assert_paper_endpoint(base_url, recorder)
    recorder.startup(f"trading_endpoint={base_url}")
    return base_url


def send_paper_request(
    configuration: EndpointConfiguration,
    path: str,
    body: bytes,
    transport: PaperTransport,
    recorder: EndpointRecorder,
) -> TransportResponse:
    base_url = configuration.base_url
    assert_paper_endpoint(base_url, recorder)
    if not path.startswith("/") or path.startswith("//"):
        recorder.no_trade(_PATH_REJECTION_REASON)
        raise LiveEndpointError("broker request path must be relative")

    response = transport.request(
        f"{base_url}{path}",
        body,
        follow_redirects=False,
    )
    if response.status_code in _REDIRECT_STATUS_CODES:
        # A cross-host target is the more alarming case and gets its own reason,
        # but no redirect is a determinate answer. Returning a same-origin 3xx
        # would let a caller checking status_code < 400 record an order the
        # broker may never have created.
        _assert_safe_redirect(response.location, recorder)
        recorder.no_trade(_INDETERMINATE_RESPONSE_REASON)
        raise IndeterminateResponseError(
            f"broker returned {response.status_code}; the outcome is unknown "
            "and must be resolved by broker lookup, never by resending"
        )
    return response


def _assert_safe_redirect(location: str | None, recorder: EndpointRecorder) -> None:
    try:
        if location is None:
            raise ValueError
        paper_url = urlsplit(PAPER_BASE_URL)
        redirect_url = urlsplit(location)
        is_relative = not redirect_url.scheme and not redirect_url.netloc
        is_paper_origin = (
            redirect_url.scheme == paper_url.scheme
            and redirect_url.hostname == paper_url.hostname
            and redirect_url.port is None
        )
    except ValueError:
        recorder.no_trade(_REDIRECT_REJECTION_REASON)
        raise LiveEndpointError("redirect target rejected") from None
    if not is_relative and not is_paper_origin:
        recorder.no_trade(_REDIRECT_REJECTION_REASON)
        raise LiveEndpointError("redirect target rejected")
