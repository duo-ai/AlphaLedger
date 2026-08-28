"""Paper endpoint safety boundary."""

import os
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
_BASE_URL_ENVIRONMENT_VARIABLES = (
    "APCA_API_BASE_URL",
    "ALPACA_API_BASE_URL",
    "ALPACA_BASE_URL",
)
_ENDPOINT_REJECTION_REASON = "endpoint_not_paper"


class LiveEndpointError(RuntimeError):
    """Raised when an operation could reach a non-paper endpoint."""


class EndpointRecorder(Protocol):
    """Record endpoint decisions without receiving configuration values."""

    def startup(self, banner: str) -> None: ...

    def no_trade(self, reason: str) -> None: ...


@dataclass
class EndpointConfiguration:
    """Mutable runtime configuration rechecked for every broker request."""

    base_url: str


@dataclass(frozen=True)
class TransportResponse:
    """Response metadata required to reject redirect replay."""

    status_code: int
    location: str | None = None


class PaperTransport(Protocol):
    """Transport that exposes redirect control and the actual request target."""

    def request(
        self,
        url: str,
        body: bytes,
        *,
        follow_redirects: bool,
    ) -> TransportResponse: ...


def resolve_paper_base_url() -> str:
    for variable_name in _BASE_URL_ENVIRONMENT_VARIABLES:
        configured_url = os.environ.get(variable_name)
        if configured_url is not None and configured_url != PAPER_BASE_URL:
            raise LiveEndpointError(f"paper endpoint required; reject {variable_name}")
    return PAPER_BASE_URL


def assert_paper_endpoint(base_url: str, recorder: EndpointRecorder) -> None:
    if base_url != PAPER_BASE_URL:
        recorder.no_trade(_ENDPOINT_REJECTION_REASON)
        raise LiveEndpointError("paper endpoint required")


def validate_process_start(recorder: EndpointRecorder) -> str:
    try:
        base_url = resolve_paper_base_url()
    except LiveEndpointError:
        recorder.no_trade(_ENDPOINT_REJECTION_REASON)
        raise
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
        recorder.no_trade(_ENDPOINT_REJECTION_REASON)
        raise LiveEndpointError("broker request path must be relative")

    response = transport.request(
        f"{base_url}{path}",
        body,
        follow_redirects=False,
    )
    if response.status_code in {301, 302, 303, 307, 308}:
        _assert_safe_redirect(response.location, recorder)
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
        recorder.no_trade("redirect_not_paper")
        raise LiveEndpointError("redirect target rejected") from None
    if not is_relative and not is_paper_origin:
        recorder.no_trade("redirect_not_paper")
        raise LiveEndpointError("redirect target rejected")
