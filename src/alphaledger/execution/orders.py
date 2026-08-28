"""Typed mapping between structure plans and broker order payloads."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from alphaledger.domain import StructurePlan

DEBIT_CREDIT_SIGN_CONVENTION: Mapping[str, Decimal] = {}


class OrderAdapterError(ValueError):
    """An order payload cannot cross the typed adapter boundary."""


class BrokerOrderStatus(StrEnum):
    FILLED = "filled"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    broker_id: str
    client_order_id: str
    status: BrokerOrderStatus
    filled_quantity: Decimal
    created_at: datetime
    updated_at: datetime | None
    submitted_at: datetime | None
    filled_at: datetime | None


def build_mleg_order(
    plan: StructurePlan,
    quantity: int,
    limit_price: Decimal,
    client_order_id: str,
) -> Mapping[str, object]:
    return {}


def canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return b""


def order_payload_hash(payload: Mapping[str, object]) -> str:
    return ""


def parse_order(raw: Mapping[str, object]) -> BrokerOrder:
    return BrokerOrder(
        broker_id="",
        client_order_id="",
        status=BrokerOrderStatus.REJECTED,
        filled_quantity=Decimal(0),
        created_at=datetime(1970, 1, 1, tzinfo=UTC),
        updated_at=None,
        submitted_at=None,
        filled_at=None,
    )
