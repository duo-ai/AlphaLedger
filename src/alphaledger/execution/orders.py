"""Typed mapping between structure plans and Alpaca order payloads.

The adapter owns the wire vocabulary and canonical byte representation. It
does not choose a price, submit an order, or interpret an unknown broker status
as a terminal result.
"""

import hashlib
import json
import re
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
    "BrokerActivity",
    "BrokerActivityType",
    "BrokerOrder",
    "BrokerOrderStatus",
    "BrokerPosition",
    "BrokerPositionSide",
    "OrderAdapterError",
    "build_mleg_order",
    "canonical_bytes",
    "order_payload_hash",
    "parse_activity",
    "parse_order",
    "parse_position",
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
_POSITIVE_INTEGER_PATTERN = re.compile(r"[1-9][0-9]*")
_INTEGER_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)")
_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_NONNEGATIVE_DECIMAL_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_RFC3339_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})"
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


class BrokerActivityType(StrEnum):
    FILL = "fill"
    PARTIAL_FILL = "partial_fill"
    UNKNOWN = "unknown"


class BrokerPositionSide(StrEnum):
    LONG = "long"
    SHORT = "short"
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


@dataclass(frozen=True, slots=True)
class BrokerActivity:
    broker_id: str
    activity_type: BrokerActivityType
    symbol: str
    signed_quantity: int
    price: Decimal
    transaction_time: datetime


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    symbol: str
    signed_quantity: int
    average_entry_price: Decimal
    side: BrokerPositionSide


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
    if not 2 <= len(plan.legs) <= 4:
        raise OrderAdapterError("mleg orders must contain between 2 and 4 legs")

    legs = [_map_leg(leg, index) for index, leg in enumerate(plan.legs)]
    symbols = [leg["symbol"] for leg in legs]
    if len(set(symbols)) != len(symbols):
        raise OrderAdapterError("mleg order symbols must be unique")

    return {
        "order_class": "mleg",
        "qty": str(quantity),
        "type": "limit",
        "limit_price": limit_price,
        "time_in_force": "day",
        "client_order_id": client_order_id,
        "legs": legs,
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


def parse_activity(raw: Mapping[str, object]) -> BrokerActivity:
    """Parse a trade activity needed to reconstruct fills after a restart."""
    raw_activity_type = _required_string(raw, "type", record_kind="activity")
    try:
        activity_type = BrokerActivityType(raw_activity_type)
    except ValueError:
        activity_type = BrokerActivityType.UNKNOWN

    side = _required_string(raw, "side", record_kind="activity")
    if side == "buy":
        quantity_sign = 1
    elif side == "sell":
        quantity_sign = -1
    else:
        raise OrderAdapterError("broker activity field 'side' is not recognized")
    quantity = _required_integer(raw, "qty", record_kind="activity")
    if quantity < 0:
        raise OrderAdapterError("broker activity field 'qty' must be nonnegative")

    return BrokerActivity(
        broker_id=_required_string(raw, "id", record_kind="activity"),
        activity_type=activity_type,
        symbol=_required_string(raw, "symbol", record_kind="activity"),
        signed_quantity=quantity_sign * quantity,
        price=_required_exact_decimal(raw, "price", record_kind="activity"),
        transaction_time=_required_timestamp(
            raw,
            "transaction_time",
            record_kind="activity",
        ),
    )


def parse_position(raw: Mapping[str, object]) -> BrokerPosition:
    """Parse the broker's signed position truth after a restart."""
    raw_side = _required_string(raw, "side", record_kind="position")
    try:
        side = BrokerPositionSide(raw_side)
    except ValueError:
        side = BrokerPositionSide.UNKNOWN

    return BrokerPosition(
        symbol=_required_string(raw, "symbol", record_kind="position"),
        signed_quantity=_required_integer(raw, "qty", record_kind="position"),
        average_entry_price=_required_exact_decimal(
            raw,
            "avg_entry_price",
            record_kind="position",
        ),
        side=side,
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
    if isinstance(value, str) and _POSITIVE_INTEGER_PATTERN.fullmatch(value) is None:
        raise OrderAdapterError(f"{field} must be a positive integer")
    try:
        quantity = Decimal(value)
    except InvalidOperation:
        raise OrderAdapterError(f"{field} must be a positive integer") from None
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


def _required(
    raw: Mapping[str, object],
    field: str,
    *,
    record_kind: str = "order",
) -> object:
    if field not in raw:
        raise OrderAdapterError(f"broker {record_kind} is missing required field '{field}'")
    return raw[field]


def _required_string(
    raw: Mapping[str, object],
    field: str,
    *,
    record_kind: str = "order",
) -> str:
    value = _required(raw, field, record_kind=record_kind)
    if not isinstance(value, str) or not value:
        raise OrderAdapterError(f"broker {record_kind} field '{field}' must be a non-empty string")
    return value


def _required_quantity(raw: Mapping[str, object], field: str) -> Decimal:
    value = _required(raw, field)
    if isinstance(value, bool | float) or not isinstance(value, str | int | Decimal):
        raise OrderAdapterError(f"broker order field '{field}' must be an exact quantity")
    if isinstance(value, str) and _NONNEGATIVE_DECIMAL_PATTERN.fullmatch(value) is None:
        raise OrderAdapterError(f"broker order field '{field}' must be an exact quantity")
    try:
        quantity = Decimal(value)
    except InvalidOperation:
        raise OrderAdapterError(f"broker order field '{field}' must be an exact quantity") from None
    if not quantity.is_finite() or quantity < 0:
        raise OrderAdapterError(f"broker order field '{field}' must be a nonnegative quantity")
    return quantity


def _required_integer(
    raw: Mapping[str, object],
    field: str,
    *,
    record_kind: str,
) -> int:
    value = _required(raw, field, record_kind=record_kind)
    if isinstance(value, bool | float) or not isinstance(value, str | int | Decimal):
        raise OrderAdapterError(f"broker {record_kind} field '{field}' must be an integer")
    if isinstance(value, str) and _INTEGER_PATTERN.fullmatch(value) is None:
        raise OrderAdapterError(f"broker {record_kind} field '{field}' must be an integer")
    try:
        quantity = Decimal(value)
    except InvalidOperation:
        raise OrderAdapterError(
            f"broker {record_kind} field '{field}' must be an integer"
        ) from None
    if not quantity.is_finite() or quantity != quantity.to_integral_value():
        raise OrderAdapterError(f"broker {record_kind} field '{field}' must be an integer")
    return int(quantity)


def _required_exact_decimal(
    raw: Mapping[str, object],
    field: str,
    *,
    record_kind: str,
) -> Decimal:
    value = _required(raw, field, record_kind=record_kind)
    if isinstance(value, bool | float) or not isinstance(value, str | int | Decimal):
        raise OrderAdapterError(f"broker {record_kind} field '{field}' must be an exact decimal")
    if isinstance(value, str) and _DECIMAL_PATTERN.fullmatch(value) is None:
        raise OrderAdapterError(f"broker {record_kind} field '{field}' must be an exact decimal")
    try:
        exact = Decimal(value)
    except InvalidOperation:
        raise OrderAdapterError(
            f"broker {record_kind} field '{field}' must be an exact decimal"
        ) from None
    if not exact.is_finite():
        raise OrderAdapterError(f"broker {record_kind} field '{field}' must be an exact decimal")
    return exact


def _required_timestamp(
    raw: Mapping[str, object],
    field: str,
    *,
    record_kind: str = "order",
) -> datetime:
    value = _required(raw, field, record_kind=record_kind)
    return _parse_timestamp(value, field, record_kind=record_kind)


def _optional_timestamp(raw: Mapping[str, object], field: str) -> datetime | None:
    value = _required(raw, field)
    if value is None:
        return None
    return _parse_timestamp(value, field, record_kind="order")


def _parse_timestamp(value: object, field: str, *, record_kind: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise OrderAdapterError(
            f"broker {record_kind} field '{field}' must be an RFC3339 timestamp"
        )
    if _RFC3339_PATTERN.fullmatch(value) is None:
        raise OrderAdapterError(
            f"broker {record_kind} field '{field}' must be an RFC3339 timestamp"
        )
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise OrderAdapterError(
            f"broker {record_kind} field '{field}' must be an RFC3339 timestamp"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OrderAdapterError(f"broker {record_kind} field '{field}' must include a UTC offset")
    return parsed.astimezone(UTC)
