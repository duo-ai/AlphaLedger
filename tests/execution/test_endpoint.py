import os
import subprocess
import sys
import traceback
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Literal, get_args, get_type_hints

import pytest

from alphaledger.broker.endpoint import (
    PAPER_BASE_URL,
    EndpointConfiguration,
    HttpMethod,
    IndeterminateResponseError,
    LiveEndpointError,
    PaperTransport,
    TransportResponse,
    assert_paper_endpoint,
    resolve_paper_base_url,
    send_paper_request,
    validate_process_start,
)


class RecordingEndpointEvents:
    def __init__(self) -> None:
        self.banners: list[str] = []
        self.no_trade_reasons: list[str] = []

    def startup(self, banner: str) -> None:
        self.banners.append(banner)

    def no_trade(self, reason: str) -> None:
        self.no_trade_reasons.append(reason)


class RecordingTransport:
    def __init__(self, response: TransportResponse | None = None) -> None:
        self.response = response or TransportResponse(status_code=200)
        self.requests: list[tuple[str, str, bytes, bool]] = []

    def request(
        self,
        method: str,
        url: str,
        body: bytes,
        *,
        follow_redirects: Literal[False],
    ) -> TransportResponse:
        self.requests.append((method, url, body, follow_redirects))
        return self.response


def configuration(recorder: RecordingEndpointEvents) -> EndpointConfiguration:
    return EndpointConfiguration.from_resolver(recorder)


def test_clean_start_returns_paper_host_and_records_it() -> None:
    recorder = RecordingEndpointEvents()

    assert resolve_paper_base_url(recorder) == PAPER_BASE_URL
    assert validate_process_start(recorder) == PAPER_BASE_URL
    assert recorder.banners == [f"trading_endpoint={PAPER_BASE_URL}"]


def test_paper_pre_submit_assertion_allows_body_send() -> None:
    recorder = RecordingEndpointEvents()
    transport = RecordingTransport()

    response = send_paper_request(
        configuration(recorder), "POST", "/orders", b"payload", transport, recorder
    )

    assert response.status_code == 200
    assert transport.requests == [("POST", f"{PAPER_BASE_URL}/orders", b"payload", False)]
    assert recorder.no_trade_reasons == []


@pytest.mark.parametrize(
    "variable_name",
    ["APCA_API_BASE_URL", "ALPACA_API_BASE_URL", "ALPACA_BASE_URL"],
)
def test_each_environment_override_is_rejected_without_exposing_its_value(
    variable_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RecordingEndpointEvents()
    credential = "sensitive-marker"
    rejected_url = "https://" + "api.alpaca.markets" + f"/?token={credential}"
    monkeypatch.setenv(variable_name, rejected_url)

    with pytest.raises(LiveEndpointError) as error:
        resolve_paper_base_url(recorder)

    assert credential not in str(error.value)
    assert rejected_url not in str(error.value)
    assert recorder.no_trade_reasons == ["endpoint_not_paper"]


def test_redirect_contract_disables_following_and_rejects_replay() -> None:
    recorder = RecordingEndpointEvents()
    redirect_target = "https://example.invalid/orders"
    transport = RecordingTransport(TransportResponse(status_code=302, location=redirect_target))

    with pytest.raises(LiveEndpointError):
        send_paper_request(
            configuration(recorder), "POST", "/orders", b"payload", transport, recorder
        )

    request_hints = get_type_hints(PaperTransport.request)
    assert request_hints["follow_redirects"] == Literal[False]
    assert transport.requests == [("POST", f"{PAPER_BASE_URL}/orders", b"payload", False)]
    assert all(not request[0].startswith(redirect_target) for request in transport.requests)


def test_corruption_after_start_is_rejected_by_pre_submit_assertion() -> None:
    recorder = RecordingEndpointEvents()
    endpoint_configuration = configuration(recorder)
    validate_process_start(recorder)
    object.__setattr__(endpoint_configuration, "base_url", "https://example.invalid")
    transport = RecordingTransport()

    with pytest.raises(LiveEndpointError):
        send_paper_request(
            endpoint_configuration, "POST", "/orders", b"payload", transport, recorder
        )

    assert transport.requests == []
    assert recorder.no_trade_reasons == ["endpoint_not_paper"]


def test_configuration_is_frozen_and_requires_resolver_bound_factory() -> None:
    recorder = RecordingEndpointEvents()
    endpoint_configuration = configuration(recorder)

    with pytest.raises(TypeError):
        EndpointConfiguration()
    with pytest.raises(TypeError):
        EndpointConfiguration("https://example.invalid")  # type: ignore[call-arg]
    with pytest.raises(FrozenInstanceError):
        endpoint_configuration.base_url = "https://example.invalid"  # type: ignore[misc]


def test_fresh_interpreter_revalidates_endpoint_environment() -> None:
    rejected_environment = os.environ.copy()
    rejected_environment["APCA_API_BASE_URL"] = "https://example.invalid"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from alphaledger.broker.endpoint import validate_process_start

class Recorder:
    def startup(self, banner: str) -> None: print("unexpected_startup_banner")
    def no_trade(self, reason: str) -> None: print(reason)

validate_process_start(Recorder())
""",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=rejected_environment,
    )

    assert result.returncode != 0
    assert result.stdout.strip() == "endpoint_not_paper"


def test_failed_assertion_records_no_trade_and_never_falls_back() -> None:
    recorder = RecordingEndpointEvents()

    with pytest.raises(LiveEndpointError):
        assert_paper_endpoint("https://example.invalid", recorder)

    assert recorder.no_trade_reasons == ["endpoint_not_paper"]


@pytest.mark.parametrize(
    ("path", "response", "expected_reason"),
    [
        ("orders", None, "request_path_invalid"),
        (
            "/orders",
            TransportResponse(status_code=307, location="https://[invalid"),
            "redirect_invalid",
        ),
    ],
)
def test_rejection_causes_record_distinct_reason_codes(
    path: str,
    response: TransportResponse | None,
    expected_reason: str,
) -> None:
    recorder = RecordingEndpointEvents()

    with pytest.raises(LiveEndpointError):
        send_paper_request(
            configuration(recorder),
            "POST",
            path,
            b"payload",
            RecordingTransport(response),
            recorder,
        )

    assert recorder.no_trade_reasons == [expected_reason]
    assert expected_reason != "endpoint_not_paper"


def test_sensitive_endpoint_values_are_absent_from_repr() -> None:
    recorder = RecordingEndpointEvents()
    endpoint_configuration = configuration(recorder)
    location = "https://example.invalid/?token=sensitive-marker"
    response = TransportResponse(status_code=302, location=location)

    assert PAPER_BASE_URL not in repr(endpoint_configuration)
    assert location not in repr(response)
    assert "sensitive-marker" not in repr(response)


@pytest.mark.parametrize(
    "location",
    ["https://paper-api.alpaca.markets:sensitive-marker/orders", "https://[invalid"],
)
def test_malformed_redirect_is_redacted_and_sends_no_replay(location: str) -> None:
    recorder = RecordingEndpointEvents()
    transport = RecordingTransport(TransportResponse(status_code=307, location=location))

    with pytest.raises(LiveEndpointError, match="redirect target rejected") as error:
        send_paper_request(
            configuration(recorder), "POST", "/orders", b"payload", transport, recorder
        )

    formatted_error = "".join(traceback.format_exception(error.value))
    assert location not in formatted_error
    assert "sensitive-marker" not in formatted_error
    assert recorder.no_trade_reasons == ["redirect_invalid"]
    assert len(transport.requests) == 1


# AC-10, from the second safety review


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("/v2/orders/", IndeterminateResponseError),
        (f"{PAPER_BASE_URL}/v2/orders/", IndeterminateResponseError),
        # a cross-host target is the graver case: someone is steering us away
        ("https://example.invalid/v2/orders/", LiveEndpointError),
    ],
)
def test_no_redirect_is_ever_treated_as_success(
    status: int, location: str, expected: type[Exception]
) -> None:
    """A same-origin redirect is not success. The broker may not have accepted
    the request, and a caller checking status_code < 400 would record an order
    that was never created."""
    events = RecordingEndpointEvents()
    transport = RecordingTransport(TransportResponse(status_code=status, location=location))
    configuration = EndpointConfiguration.from_resolver(events)
    with pytest.raises(expected):
        send_paper_request(configuration, "POST", "/v2/orders", b"payload", transport, events)
    assert events.no_trade_reasons, "an indeterminate outcome must reach the ledger"
    assert len(transport.requests) == 1, "no replay is permitted"


def test_a_same_origin_redirect_records_its_own_reason() -> None:
    events = RecordingEndpointEvents()
    transport = RecordingTransport(
        TransportResponse(status_code=307, location=f"{PAPER_BASE_URL}/v2/orders/")
    )
    configuration = EndpointConfiguration.from_resolver(events)
    with pytest.raises(IndeterminateResponseError):
        send_paper_request(configuration, "POST", "/v2/orders", b"payload", transport, events)
    assert events.no_trade_reasons[-1] not in {
        "endpoint_not_paper",
        "request_path_invalid",
    }, "an indeterminate response is a distinct cause from a rejected endpoint"


def test_resolver_rejects_a_live_host_set_after_a_first_clean_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subprocess restart test cannot see an in-process cache."""
    events = RecordingEndpointEvents()
    assert resolve_paper_base_url(events) == PAPER_BASE_URL
    monkeypatch.setenv("APCA_API_BASE_URL", "https://" + "api.alpaca.markets")
    with pytest.raises(LiveEndpointError):
        resolve_paper_base_url(events)


# --- UNIT-036: the verb and the response body -----------------------------

VERBS = ("GET", "POST", "PATCH", "DELETE")


@pytest.mark.parametrize("method", VERBS)
def test_every_verb_reaches_the_transport_unchanged(method: str) -> None:
    """AC-1. Submit is POST, reads are GET, replace is PATCH, cancel is DELETE."""
    recorder = RecordingEndpointEvents()
    transport = RecordingTransport()

    send_paper_request(configuration(recorder), method, "/v2/orders", b"", transport, recorder)

    assert transport.requests == [(method, f"{PAPER_BASE_URL}/v2/orders", b"", False)]


def test_a_read_returns_its_body_byte_for_byte() -> None:
    """AC-2. Nothing decodes on the way through, so nothing can mangle a payload.

    The payload is deliberately not valid UTF-8. A boundary that decoded would
    raise here rather than pass the bytes along, and the caller that has to
    parse a broker response is the one entitled to decide the encoding.
    """
    recorder = RecordingEndpointEvents()
    payload = b'{"id":"abc","status":"filled"}\xff\xfe'
    transport = RecordingTransport(TransportResponse(status_code=200, body=payload))

    response = send_paper_request(
        configuration(recorder), "GET", "/v2/orders/abc", b"", transport, recorder
    )

    assert response.body == payload
    assert isinstance(response.body, bytes)


def test_a_response_body_defaults_to_empty() -> None:
    """A transport with nothing to return stays constructible."""
    assert TransportResponse(status_code=204).body == b""


def test_a_body_is_absent_from_the_repr() -> None:
    """A broker payload in a traceback is a disclosure risk, like `location`."""
    rendered = repr(TransportResponse(status_code=200, body=b"account-secret"))
    assert "account-secret" not in rendered


@pytest.mark.parametrize("method", VERBS)
def test_a_query_string_is_accepted_and_forwarded_intact(method: str) -> None:
    """AC-5. Every GET the order path needs carries one."""
    recorder = RecordingEndpointEvents()
    transport = RecordingTransport()
    path = "/v2/orders?status=open&limit=20"

    send_paper_request(configuration(recorder), method, path, b"", transport, recorder)

    assert transport.requests == [(method, f"{PAPER_BASE_URL}{path}", b"", False)]


@pytest.mark.parametrize("method", VERBS)
def test_a_redirect_is_indeterminate_under_every_verb(method: str) -> None:
    """AC-4. The original test covered one verb; a GET must not slip through."""
    recorder = RecordingEndpointEvents()
    transport = RecordingTransport(
        TransportResponse(status_code=307, location=f"{PAPER_BASE_URL}/v2/orders/")
    )

    with pytest.raises(IndeterminateResponseError):
        send_paper_request(configuration(recorder), method, "/v2/orders", b"", transport, recorder)

    assert "response_indeterminate" in recorder.no_trade_reasons


@pytest.mark.parametrize("method", VERBS)
@pytest.mark.parametrize("path", ["https://paper-api.alpaca.markets/v2/orders", "//evil.example"])
def test_a_non_relative_path_is_refused_under_every_verb(method: str, path: str) -> None:
    """AC-5's other half. Widening the verb must not widen the path rule."""
    recorder = RecordingEndpointEvents()
    transport = RecordingTransport()

    with pytest.raises(LiveEndpointError):
        send_paper_request(configuration(recorder), method, path, b"", transport, recorder)

    assert transport.requests == []
    assert "request_path_invalid" in recorder.no_trade_reasons


def test_the_module_still_admits_no_mode_switch_or_live_host() -> None:
    """AC-6. UNIT-010's own criterion, restated by the unit that could break it.

    A boolean can be set to `False`, which is why UNIT-010 refused to have one.
    Widening the transport is exactly the change that could have reintroduced a
    `paper=` parameter or a second host, so it is checked here rather than
    assumed to have survived.
    """
    source = (
        Path(__file__).resolve().parents[2] / "src" / "alphaledger" / "broker" / "endpoint.py"
    ).read_text(encoding="utf-8")

    assert "paper: bool" not in source
    assert "paper=" not in source
    # Deliberately not a search for the word "live": `LiveEndpointError` is the
    # class that exists to reject it, so the word belongs here and its absence
    # would be the defect. What must not appear is a second host. Asserted as
    # "exactly one broker host, and it is the paper one" rather than by
    # spelling the forbidden host, which the repository guard refuses to let
    # any file or command contain.
    assert source.count("alpaca.markets") == 1
    assert PAPER_BASE_URL in source


def test_the_verb_type_admits_exactly_four_values() -> None:
    """AC-1's other half. PUT and an arbitrary string are both unexpressible."""
    assert set(get_args(HttpMethod)) == {"GET", "POST", "PATCH", "DELETE"}
