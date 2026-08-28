import traceback

import pytest

from alphaledger.broker.endpoint import (
    PAPER_BASE_URL,
    EndpointConfiguration,
    LiveEndpointError,
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
        follow_redirects: bool,
    ) -> TransportResponse:
        self.requests.append((url, body, follow_redirects))
        return self.response


def test_clean_start_returns_paper_host_and_records_it() -> None:
    recorder = RecordingEndpointEvents()

    assert resolve_paper_base_url() == PAPER_BASE_URL
    assert validate_process_start(recorder) == PAPER_BASE_URL
    assert recorder.banners == [f"trading_endpoint={PAPER_BASE_URL}"]


def test_paper_pre_submit_assertion_allows_body_send() -> None:
    recorder = RecordingEndpointEvents()
    transport = RecordingTransport()

    response = send_paper_request(
        EndpointConfiguration(PAPER_BASE_URL), "/orders", b"payload", transport, recorder
    )

    assert response.status_code == 200
    assert transport.requests == [(f"{PAPER_BASE_URL}/orders", b"payload", False)]
    assert recorder.no_trade_reasons == []


def test_environment_override_is_rejected_without_exposing_its_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = "sensitive-marker"
    rejected_url = "https://" + "api.alpaca.markets" + f"/?token={credential}"
    monkeypatch.setenv("APCA_API_BASE_URL", rejected_url)

    with pytest.raises(LiveEndpointError) as error:
        resolve_paper_base_url()

    assert credential not in str(error.value)
    assert rejected_url not in str(error.value)


def test_cross_host_redirect_is_rejected_before_body_send() -> None:
    recorder = RecordingEndpointEvents()
    transport = RecordingTransport(
        TransportResponse(status_code=302, location="https://example.invalid/orders")
    )

    with pytest.raises(LiveEndpointError):
        send_paper_request(
            EndpointConfiguration(PAPER_BASE_URL),
            "/orders",
            b"payload",
            transport,
            recorder,
        )

    assert transport.requests == [(f"{PAPER_BASE_URL}/orders", b"payload", False)]
    assert all(
        not request[0].startswith("https://example.invalid") for request in transport.requests
    )


def test_mutation_after_start_is_rejected_by_pre_submit_assertion() -> None:
    recorder = RecordingEndpointEvents()
    configuration = EndpointConfiguration(PAPER_BASE_URL)
    validate_process_start(recorder)
    configuration.base_url = "https://example.invalid"
    transport = RecordingTransport()

    with pytest.raises(LiveEndpointError):
        send_paper_request(configuration, "/orders", b"payload", transport, recorder)

    assert transport.requests == []


def test_each_restart_revalidates_instead_of_using_previous_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RecordingEndpointEvents()
    assert validate_process_start(recorder) == PAPER_BASE_URL
    monkeypatch.setenv("APCA_API_BASE_URL", "https://example.invalid")

    with pytest.raises(LiveEndpointError):
        validate_process_start(recorder)

    assert recorder.banners == [f"trading_endpoint={PAPER_BASE_URL}"]


def test_failed_assertion_records_no_trade_and_never_falls_back() -> None:
    recorder = RecordingEndpointEvents()

    with pytest.raises(LiveEndpointError):
        assert_paper_endpoint("https://example.invalid", recorder)

    assert recorder.no_trade_reasons == ["endpoint_not_paper"]
    assert resolve_paper_base_url() == PAPER_BASE_URL


@pytest.mark.parametrize(
    "location",
    ["https://paper-api.alpaca.markets:sensitive-marker/orders", "https://[invalid"],
)
def test_malformed_redirect_records_no_trade_and_sends_no_replay(location: str) -> None:
    recorder = RecordingEndpointEvents()
    transport = RecordingTransport(TransportResponse(status_code=307, location=location))

    with pytest.raises(LiveEndpointError, match="redirect target rejected") as error:
        send_paper_request(
            EndpointConfiguration(PAPER_BASE_URL), "/orders", b"payload", transport, recorder
        )

    formatted_error = "".join(traceback.format_exception(error.value))
    assert location not in formatted_error
    assert "sensitive-marker" not in formatted_error
    assert recorder.no_trade_reasons == ["redirect_not_paper"]
    assert len(transport.requests) == 1
