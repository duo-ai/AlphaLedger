import os
import subprocess
import sys
import traceback
from dataclasses import FrozenInstanceError
from typing import Literal, get_type_hints

import pytest

from alphaledger.broker.endpoint import (
    PAPER_BASE_URL,
    EndpointConfiguration,
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
        self.requests: list[tuple[str, bytes, bool]] = []

    def request(
        self,
        url: str,
        body: bytes,
        *,
        follow_redirects: Literal[False],
    ) -> TransportResponse:
        self.requests.append((url, body, follow_redirects))
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
        configuration(recorder), "/orders", b"payload", transport, recorder
    )

    assert response.status_code == 200
    assert transport.requests == [(f"{PAPER_BASE_URL}/orders", b"payload", False)]
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
        send_paper_request(configuration(recorder), "/orders", b"payload", transport, recorder)

    request_hints = get_type_hints(PaperTransport.request)
    assert request_hints["follow_redirects"] == Literal[False]
    assert transport.requests == [(f"{PAPER_BASE_URL}/orders", b"payload", False)]
    assert all(not request[0].startswith(redirect_target) for request in transport.requests)


def test_corruption_after_start_is_rejected_by_pre_submit_assertion() -> None:
    recorder = RecordingEndpointEvents()
    endpoint_configuration = configuration(recorder)
    validate_process_start(recorder)
    object.__setattr__(endpoint_configuration, "base_url", "https://example.invalid")
    transport = RecordingTransport()

    with pytest.raises(LiveEndpointError):
        send_paper_request(endpoint_configuration, "/orders", b"payload", transport, recorder)

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
        send_paper_request(configuration(recorder), "/orders", b"payload", transport, recorder)

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
        send_paper_request(configuration, "/v2/orders", b"payload", transport, events)
    assert events.no_trade_reasons, "an indeterminate outcome must reach the ledger"
    assert len(transport.requests) == 1, "no replay is permitted"


def test_a_same_origin_redirect_records_its_own_reason() -> None:
    events = RecordingEndpointEvents()
    transport = RecordingTransport(
        TransportResponse(status_code=307, location=f"{PAPER_BASE_URL}/v2/orders/")
    )
    configuration = EndpointConfiguration.from_resolver(events)
    with pytest.raises(IndeterminateResponseError):
        send_paper_request(configuration, "/v2/orders", b"payload", transport, events)
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
