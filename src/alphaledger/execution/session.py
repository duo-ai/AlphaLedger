"""The session and arm state machine from design section 11.

This is the vocabulary an orchestrator uses to say what a session is doing, and
the thing that refuses a move nobody should be able to make. It is deliberately
the smallest possible module: a closed table, a pure function over it, and one
predicate derived from the same table.

It is not the per-order machine. UNIT-012 owns that, in `lifecycle.py`, and the
two share member names while meaning different things by them: an order is
`working` when the broker holds it, a session is `working` when it has an entry
in flight. An order reaching a terminal state is an event this machine may
observe; it is never a state this machine enters. Nothing here imports from
that module, and a test asserts that, because the failure this prevents is a
session state read as an order state and acted on.

Nothing here reads a clock or performs I/O. That is what lets UNIT-034 rebuild
a session's state by replaying recorded transitions and get the same answer it
got live: a machine that consulted a clock would give a different answer on
replay, and the ledger would stop being evidence of what happened.

Two edges are in the table that design section 11's diagram does not draw, and
both are deviations from a cited source, recorded in
`specs/features/001-autonomous-session/spec.md` rather than taken silently.

`Exiting -> Halted`. The diagram gives `Exiting` exactly one outgoing edge, to
`Closed` on a successful flatten. UNIT-017 is merged and already reports a
flatten that did not complete, so the system can produce a fact the diagram
gives the session nowhere to put, and the machine would have raised on it.
`.claude/rules/01-safety.md` bullet 4 requires a fail closed halt on
uncertainty and states no exception for exiting, and
`.claude/rules/30-execution.md` bullet 8 requires flatten failure to escalate
while entry stays disabled.

A disarm edge from every state but `Disarmed` itself. `Disarmed` appears in the
diagram only as the initial state, which read literally makes disarm
unreachable once a session is running, and contradicts section 11's own
sentence that disarm, emergency halt, and manual flatten remain available. Six
edges rather than one, because a human has to be able to stop this from
wherever it currently is.

`Halted` is the one state with a single way out, and that way out is a person.
It accepts disarm and nothing else, so no arriving event can resume a halted
session by itself.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "LEGAL_TRANSITIONS",
    "SessionEvent",
    "SessionState",
    "permits_new_entry",
    "transition",
]


class SessionState(StrEnum):
    """The seven states design section 11 names, and no others."""

    DISARMED = "disarmed"
    READY = "ready"
    WORKING = "working"
    OPEN = "open"
    EXITING = "exiting"
    CLOSED = "closed"
    HALTED = "halted"


class SessionEvent(StrEnum):
    """Events, named for the state each one attempts to enter.

    Naming an event for its target rather than its cause is what lets a refusal
    name both sides of a move it would not make, and it is the shape UNIT-012
    already uses. The cost is that several distinct causes share one event:
    `HALTED` is emitted by a health breach, a risk breach, a kill switch, and a
    flatten that did not complete alike. That is the right trade here, because
    the machine's job is to decide whether a move is legal, and every one of
    those causes makes exactly the same move. Which cause fired is a fact for
    the ledger, and UNIT-034 records it there.
    """

    DISARMED = "disarmed"
    READY = "ready"
    WORKING = "working"
    OPEN = "open"
    EXITING = "exiting"
    CLOSED = "closed"
    HALTED = "halted"


# Seventeen edges: the ten design section 11 draws, `Exiting -> Halted`, and
# six disarm edges. A frozen mapping rather than a state-machine package for
# the reason UNIT-012 records for the same choice: this is a closed table with
# no guards, callbacks, or engine state, so the mapping is smaller to read and
# easier to audit than a dependency would be, and neither `transitions` nor
# `python-statemachine` is in the locked dependency set.
LEGAL_TRANSITIONS: Final[MappingProxyType[tuple[SessionState, SessionEvent], SessionState]] = (
    MappingProxyType(
        {
            # Arm. The one edge that starts a session, and it takes a human.
            (SessionState.DISARMED, SessionEvent.READY): SessionState.READY,
            # The entry path, and the way back when an entry never opened.
            (SessionState.READY, SessionEvent.WORKING): SessionState.WORKING,
            (SessionState.WORKING, SessionEvent.OPEN): SessionState.OPEN,
            (SessionState.WORKING, SessionEvent.READY): SessionState.READY,
            # The exit path, back to ready for the next candidate.
            (SessionState.OPEN, SessionEvent.EXITING): SessionState.EXITING,
            (SessionState.EXITING, SessionEvent.CLOSED): SessionState.CLOSED,
            (SessionState.CLOSED, SessionEvent.READY): SessionState.READY,
            # Halt, from every state that can still be holding or placing risk.
            # The fourth is the addition the diagram omits.
            (SessionState.READY, SessionEvent.HALTED): SessionState.HALTED,
            (SessionState.WORKING, SessionEvent.HALTED): SessionState.HALTED,
            (SessionState.OPEN, SessionEvent.HALTED): SessionState.HALTED,
            (SessionState.EXITING, SessionEvent.HALTED): SessionState.HALTED,
            # Disarm, from everywhere but disarmed. Including from halted,
            # which is the only way out of it.
            (SessionState.READY, SessionEvent.DISARMED): SessionState.DISARMED,
            (SessionState.WORKING, SessionEvent.DISARMED): SessionState.DISARMED,
            (SessionState.OPEN, SessionEvent.DISARMED): SessionState.DISARMED,
            (SessionState.EXITING, SessionEvent.DISARMED): SessionState.DISARMED,
            (SessionState.CLOSED, SessionEvent.DISARMED): SessionState.DISARMED,
            (SessionState.HALTED, SessionEvent.DISARMED): SessionState.DISARMED,
        }
    )
)


def transition(current: SessionState, event: SessionEvent) -> SessionState:
    """Apply one declared transition, or refuse without changing anything.

    The refusal names the state the session was in, the state the event would
    have entered, and the event itself. All three, because an operator reading
    a halted session's log needs to know what it was doing when it refused, not
    only what it refused to do.
    """
    try:
        return LEGAL_TRANSITIONS[(current, event)]
    except KeyError:
        target = SessionState(event.value)
        raise ValueError(
            f"illegal session transition from '{current.value}' to '{target.value}' "
            f"on event '{event.value}'"
        ) from None


def permits_new_entry(state: SessionState) -> bool:
    """Whether a session in `state` may place a new entry.

    Derived from the table rather than written down a second time. A separate
    list of permitted states could drift from the transitions and the drift
    would be invisible, and the direction it would drift in is the dangerous
    one: a stale list saying a halted session may trade. Asking the table
    whether the session can reach `working` from here cannot disagree with the
    table, because it is the table.

    Today that is `ready` alone. `halted` and `disarmed` are excluded by
    construction, which is what the rules require of them.
    """
    return (state, SessionEvent.WORKING) in LEGAL_TRANSITIONS
