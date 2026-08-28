"""Typed mapping between structure plans and Alpaca order payloads.

The adapter owns the wire vocabulary and canonical byte representation. It
does not choose a price, submit an order, or interpret an unknown broker status
as a terminal result.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from alphaledger.domain import StructurePlan

__all__ = [
    "DEBIT_CREDIT_SIGN_CONVENTION",
    "BrokerOrder",
    "BrokerOrderStatus",
    "OrderAdapterError",
    "build_mleg_order",
    "canonical_bytes",
    "order_payload_hash",
    "parse_order",
]

# Alpaca's MLeg wire convention. Positive means cash paid and negative means
# cash received. The adapter preserves the approved Decimal without rounding.
DEBIT_CREDIT_SIGN_CONVENTION: Final[Mapping[str, Decimal]] = MappingProxyType(
    {"debit": Decimal("1"), "credit": Decimal("-1")}
)

_LEG_KEYS = frozenset({"symbol", "ratio_qty", "side", "position_intent"})
_LEG_SIDES = frozenset({"buy", "sell"})
_POSITION_INTENTS = frozenset({"buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close"})
_SIDE_BY_POSITION_INTENT = MappingProxyType(
    {
        "buy_to_open": "buy",
        "buy_to_close": "buy",
        "sell_to_open": "sell",
        "sell_to_close": "sell",
    }
)


class OrderAdapterError(ValueError):
    """An order payload cannot cross the typed adapter boundary."""


class BrokerOrderStatus(StrEnum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    DONE_FOR_DAY = "done_for_day"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REPLACED = "replaced"
    PENDING_CANCEL = "pending_cancel"
    PENDING_REPLACE = "pending_replace"
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    PENDING_NEW = "pending_new"
    ACCEPTED_FOR_BIDDING = "accepted_for_bidding"
    STOPPED = "stopped"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    CALCULATED = "calculated"
    HELD = "held"
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
    """Map an approved structure to Alpaca's documented MLeg wire shape."""
    _require_positive_integer(quantity, "quantity")
    if not isinstance(client_order_id, str) or not client_order_id:
        raise OrderAdapterError("client_order_id must be a non-empty string")
    _require_decimal(limit_price, "limit_price")

    return {
        "order_class": "mleg",
        "qty": str(quantity),
        "type": "limit",
        "limit_price": limit_price,
        "time_in_force": "day",
        "client_order_id": client_order_id,
        "legs": [_map_leg(leg, index) for index, leg in enumerate(plan.legs)],
    }


def canonical_bytes(payload: Mapping[str, object]) -> bytes:
    """Return deterministic UTF-8 JSON bytes without accepting binary floats."""
    normalized = _normalize_json_value(payload, "")
    return json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def order_payload_hash(payload: Mapping[str, object]) -> str:
    """Bind a risk approval to the exact canonical order payload."""
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def parse_order(raw: Mapping[str, object]) -> BrokerOrder:
    """Parse a broker order without retaining or echoing the raw payload."""
    broker_status = _required_string(raw, "status")
    try:
        status = BrokerOrderStatus(broker_status)
    except ValueError:
        status = BrokerOrderStatus.UNKNOWN

    return BrokerOrder(
        broker_id=_required_string(raw, "id"),
        client_order_id=_required_string(raw, "client_order_id"),
        status=status,
        filled_quantity=_required_quantity(raw, "filled_qty"),
        created_at=_required_timestamp(raw, "created_at"),
        updated_at=_optional_timestamp(raw, "updated_at"),
        submitted_at=_optional_timestamp(raw, "submitted_at"),
        filled_at=_optional_timestamp(raw, "filled_at"),
    )


def _map_leg(leg: Mapping[str, object], index: int) -> Mapping[str, object]:
    field = f"legs[{index}]"
    keys = frozenset(leg)
    unexpected = sorted(keys - _LEG_KEYS)
    if unexpected:
        raise OrderAdapterError(f"{field} contains undeclared key '{unexpected[0]}'")
    missing = sorted(_LEG_KEYS - keys)
    if missing:
        raise OrderAdapterError(f"{field} is missing required key '{missing[0]}'")

    symbol = leg["symbol"]
    if not isinstance(symbol, str) or not symbol:
        raise OrderAdapterError(f"{field}.symbol must be a non-empty string")
    ratio_qty = _ratio_quantity(leg["ratio_qty"], f"{field}.ratio_qty")
    side = leg["side"]
    if not isinstance(side, str) or side not in _LEG_SIDES:
        raise OrderAdapterError(f"{field}.side must be buy or sell")
    position_intent = leg["position_intent"]
    if not isinstance(position_intent, str) or position_intent not in _POSITION_INTENTS:
        raise OrderAdapterError(f"{field}.position_intent is not recognized")
    if _SIDE_BY_POSITION_INTENT[position_intent] != side:
        raise OrderAdapterError(f"{field}.side conflicts with {field}.position_intent")

    return {
        "symbol": symbol,
        "ratio_qty": ratio_qty,
        "side": side,
        "position_intent": position_intent,
    }


def _ratio_quantity(value: object, field: str) -> str:
    if isinstance(value, bool):
        raise OrderAdapterError(f"{field} must be a positive integer, not bool")
    if isinstance(value, float):
        raise OrderAdapterError(f"{field} must never be float")
    if not isinstance(value, str | int | Decimal):
        raise OrderAdapterError(f"{field} must be a positive integer")
    try:
        quantity = Decimal(value)
    except InvalidOperation as exc:
        raise OrderAdapterError(f"{field} must be a positive integer") from exc
    if not quantity.is_finite() or quantity <= 0 or quantity != quantity.to_integral_value():
        raise OrderAdapterError(f"{field} must be a positive integer")
    return str(int(quantity))


def _require_positive_integer(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OrderAdapterError(f"{field} must be a positive integer")


def _require_decimal(value: object, field: str) -> None:
    if isinstance(value, float):
        raise OrderAdapterError(f"{field} must be Decimal, never float")
    if not isinstance(value, Decimal):
        raise OrderAdapterError(f"{field} must be Decimal")
    if not value.is_finite():
        raise OrderAdapterError(f"{field} must be finite")


def _normalize_json_value(value: object, field: str) -> object:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        raise OrderAdapterError(f"{field or 'payload'} must never contain float")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise OrderAdapterError(f"{field or 'payload'} must contain a finite Decimal")
        return str(value)
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise OrderAdapterError(f"{field or 'payload'} contains a non-string key")
            child_field = f"{field}.{key}" if field else key
            normalized[key] = _normalize_json_value(item, child_field)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [
            _normalize_json_value(item, f"{field}[{index}]") for index, item in enumerate(value)
        ]
    raise OrderAdapterError(
        f"{field or 'payload'} contains unsupported type {type(value).__name__}"
    )


def _required(raw: Mapping[str, object], field: str) -> object:
    if field not in raw:
        raise OrderAdapterError(f"broker order is missing required field '{field}'")
    return raw[field]


def _required_string(raw: Mapping[str, object], field: str) -> str:
    value = _required(raw, field)
    if not isinstance(value, str) or not value:
        raise OrderAdapterError(f"broker order field '{field}' must be a non-empty string")
    return value


def _required_quantity(raw: Mapping[str, object], field: str) -> Decimal:
    value = _required(raw, field)
    if isinstance(value, bool | float) or not isinstance(value, str | int | Decimal):
        raise OrderAdapterError(f"broker order field '{field}' must be an exact quantity")
    try:
        quantity = Decimal(value)
    except InvalidOperation as exc:
        raise OrderAdapterError(f"broker order field '{field}' must be an exact quantity") from exc
    if not quantity.is_finite() or quantity < 0:
        raise OrderAdapterError(f"broker order field '{field}' must be a nonnegative quantity")
    return quantity


def _required_timestamp(raw: Mapping[str, object], field: str) -> datetime:
    value = _required(raw, field)
    return _parse_timestamp(value, field)


def _optional_timestamp(raw: Mapping[str, object], field: str) -> datetime | None:
    value = raw.get(field)
    if value is None:
        return None
    return _parse_timestamp(value, field)


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise OrderAdapterError(f"broker order field '{field}' must be an RFC3339 timestamp")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise OrderAdapterError(
            f"broker order field '{field}' must be an RFC3339 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OrderAdapterError(f"broker order field '{field}' must include a UTC offset")
    return parsed.astimezone(UTC)
