"""Session and arm state machine tests.

The machine is a closed table, so the valuable tests are the ones that pin its
shape rather than walk a happy path. Two do most of the work: the illegal-pair
test enumerates every one of the forty-nine (state, event) combinations and
asserts that exactly the declared ones are accepted, so an edge added by
accident fails here rather than being discovered by an orchestrator; and the
membership test lists all seven states by name, so an eighth cannot appear
without a test failing.

The remaining tests exist because the two additions to design section 11's
diagram, `Exiting -> Halted` and the disarm edges, are deviations from a cited
source. Each is tested by name so a later reader can see they were deliberate.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from itertools import product
from pathlib import Path

import pytest

from alphaledger.execution.session import (
    LEGAL_TRANSITIONS,
    SessionEvent,
    SessionState,
    permits_new_entry,
    transition,
)

NON_TERMINAL = (
    SessionState.READY,
    SessionState.WORKING,
    SessionState.OPEN,
    SessionState.EXITING,
    SessionState.CLOSED,
    SessionState.HALTED,
)


# --- the shape of the machine ---------------------------------------------


def test_the_session_has_exactly_seven_states_named_by_the_design() -> None:
    """AC-1. An eighth state is a design change, not an implementation detail."""
    assert [state.value for state in SessionState] == [
        "disarmed",
        "ready",
        "working",
        "open",
        "exiting",
        "closed",
        "halted",
    ]
    assert len(SessionState) == 7


def test_every_event_names_the_state_it_attempts_to_enter() -> None:
    """The property that lets a refusal name both states.

    `transition` derives the target of a refused move from the event alone, the
    same way UNIT-012's per-order machine does. That only works while the two
    enumerations agree, so the agreement is pinned rather than assumed.
    """
    assert {event.value for event in SessionEvent} == {state.value for state in SessionState}


def test_the_table_holds_exactly_the_seventeen_declared_transitions() -> None:
    """Ten from the design diagram, plus the two additions the spec records."""
    assert len(LEGAL_TRANSITIONS) == 17
    from_diagram = {
        (SessionState.DISARMED, SessionEvent.READY): SessionState.READY,
        (SessionState.READY, SessionEvent.WORKING): SessionState.WORKING,
        (SessionState.WORKING, SessionEvent.OPEN): SessionState.OPEN,
        (SessionState.WORKING, SessionEvent.READY): SessionState.READY,
        (SessionState.OPEN, SessionEvent.EXITING): SessionState.EXITING,
        (SessionState.EXITING, SessionEvent.CLOSED): SessionState.CLOSED,
        (SessionState.CLOSED, SessionEvent.READY): SessionState.READY,
        (SessionState.READY, SessionEvent.HALTED): SessionState.HALTED,
        (SessionState.WORKING, SessionEvent.HALTED): SessionState.HALTED,
        (SessionState.OPEN, SessionEvent.HALTED): SessionState.HALTED,
    }
    assert from_diagram.items() <= LEGAL_TRANSITIONS.items()


def test_the_transition_table_cannot_be_mutated_by_a_caller() -> None:
    """A shared table a caller could edit would not be a frozen machine."""
    with pytest.raises(TypeError):
        LEGAL_TRANSITIONS[(SessionState.HALTED, SessionEvent.WORKING)] = (  # type: ignore[index]
            SessionState.WORKING
        )


# --- success paths ---------------------------------------------------------


def test_a_full_session_runs_from_disarmed_to_closed_and_back_to_ready() -> None:
    """The path design section 11 draws, walked end to end."""
    state = SessionState.DISARMED
    for event, expected in (
        (SessionEvent.READY, SessionState.READY),
        (SessionEvent.WORKING, SessionState.WORKING),
        (SessionEvent.OPEN, SessionState.OPEN),
        (SessionEvent.EXITING, SessionState.EXITING),
        (SessionEvent.CLOSED, SessionState.CLOSED),
        (SessionEvent.READY, SessionState.READY),
    ):
        state = transition(state, event)
        assert state is expected


def test_a_cancelled_or_rejected_entry_returns_the_session_to_ready() -> None:
    """The diagram's `Working -> Ready` edge: an entry that never opened."""
    assert transition(SessionState.WORKING, SessionEvent.READY) is SessionState.READY


def test_a_flatten_that_did_not_complete_halts_the_session() -> None:
    """AC-3, and the first of the two additions to the diagram.

    `Exiting` has exactly one outgoing edge in design section 11, to `Closed`
    on success. UNIT-017 is merged and already reports a flatten that did not
    complete, so the code can produce a fact the diagram gives the session
    nowhere to put. `.claude/rules/01-safety.md` bullet 4 requires a fail
    closed halt on uncertainty with no exception for exiting, and
    `.claude/rules/30-execution.md` bullet 8 requires flatten failure to
    escalate while keeping entry disabled. Without this edge the machine would
    raise on a condition the system is required to handle.
    """
    assert transition(SessionState.EXITING, SessionEvent.HALTED) is SessionState.HALTED


@pytest.mark.parametrize("state", NON_TERMINAL, ids=lambda state: state.value)
def test_a_human_can_disarm_from_every_non_terminal_state(state: SessionState) -> None:
    """AC-4, and the second addition.

    `Disarmed` appears in the diagram only as the initial state, which read
    literally makes disarm unreachable once running and contradicts section
    11's own sentence that disarm remains available. Six edges, one from each
    state that is not `Disarmed` itself.
    """
    assert transition(state, SessionEvent.DISARMED) is SessionState.DISARMED


def test_a_session_that_reaches_ready_and_stops_is_a_legal_path() -> None:
    """The no-trade path. Arming is not a promise to trade."""
    assert transition(SessionState.DISARMED, SessionEvent.READY) is SessionState.READY
    assert permits_new_entry(SessionState.READY)
    # Nothing forces the next move, and disarming from there is legal.
    assert transition(SessionState.READY, SessionEvent.DISARMED) is SessionState.DISARMED


# --- refusals --------------------------------------------------------------


ILLEGAL_PAIRS = [
    (state, event)
    for state, event in product(SessionState, SessionEvent)
    if (state, event) not in LEGAL_TRANSITIONS
]


def test_the_illegal_pairs_are_the_complement_of_the_table() -> None:
    """Guards the parameterisation below against silently testing nothing."""
    assert len(ILLEGAL_PAIRS) == 49 - 17


@pytest.mark.parametrize(
    ("state", "event"), ILLEGAL_PAIRS, ids=lambda value: str(getattr(value, "value", value))
)
def test_every_transition_outside_the_table_is_refused(
    state: SessionState, event: SessionEvent
) -> None:
    """AC-2, over every illegal pair rather than one example.

    The message must name both states and the event, because a refusal that
    named only the event would leave an operator reading a log unable to say
    what the session was actually doing when it refused.
    """
    with pytest.raises(ValueError) as caught:
        transition(state, event)

    message = str(caught.value)
    assert state.value in message
    assert SessionState(event.value).value in message
    assert event.value in message


@pytest.mark.parametrize(
    "event",
    [event for event in SessionEvent if event is not SessionEvent.DISARMED],
    ids=lambda event: event.value,
)
def test_a_halted_session_cannot_resume_by_any_route_but_disarm(
    event: SessionEvent,
) -> None:
    """AC-5. A halt is cleared by a human, not by the next event to arrive."""
    with pytest.raises(ValueError):
        transition(SessionState.HALTED, event)
    assert transition(SessionState.HALTED, SessionEvent.DISARMED) is SessionState.DISARMED


def test_a_refused_transition_reports_the_state_it_was_given() -> None:
    """One message read in full, since the sweep above only checks membership."""
    with pytest.raises(ValueError) as caught:
        transition(SessionState.CLOSED, SessionEvent.OPEN)
    assert str(caught.value) == (
        "illegal session transition from 'closed' to 'open' on event 'open'"
    )


# --- the entry predicate ---------------------------------------------------


def test_only_ready_permits_a_new_entry() -> None:
    """Halted and disarmed must not, and the rest fall out of the table."""
    assert permits_new_entry(SessionState.READY)
    for state in SessionState:
        if state is not SessionState.READY:
            assert not permits_new_entry(state), state


def test_the_entry_predicate_is_derived_from_the_table_not_a_second_list() -> None:
    """Two hand-written lists could disagree; one derived from the other cannot.

    This is the property, not the current answer: a state permits a new entry
    exactly when the table lets it move to `working`. If a later unit adds such
    an edge, the predicate follows it automatically rather than being a stale
    copy that says a halted session may trade.
    """
    for state in SessionState:
        expected = (state, SessionEvent.WORKING) in LEGAL_TRANSITIONS
        assert permits_new_entry(state) is expected


# --- purity, and the boundary against the per-order machine ----------------


MODULE = Path(__file__).resolve().parents[2] / "src" / "alphaledger" / "execution" / "session.py"


def imported_modules() -> set[str]:
    """Every module `session.py` imports, read from its syntax tree.

    Parsed rather than grepped. A substring search over the file would also
    match the prose, so it would fail on a docstring that merely explains why
    the per-order machine is a different scope, and it would pass on an import
    smuggled in under an alias. The tree sees imports and only imports.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_the_module_holds_no_per_order_state() -> None:
    """AC-6. The confusion UNIT-012's intake exists to prevent.

    The two machines share member names, `working` most obviously, and mean
    different things by them. Importing the per-order machine here would be the
    first step toward a session state being read as an order state.
    """
    assert not any("lifecycle" in module for module in imported_modules())

    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    referenced |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not referenced & {"OrderState", "OrderEvent"}


def test_the_module_reads_no_clock_and_performs_no_io() -> None:
    """AC-7. A machine that read a clock could not be replayed from a ledger."""
    imported = imported_modules()
    for forbidden in ("datetime", "time", "os", "pathlib", "random"):
        assert forbidden not in imported, forbidden
    assert not any(module.startswith("alphaledger.broker") for module in imported)

    # `open` and friends are builtins, so no import would reveal them.
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called & {"open", "print", "input", "eval", "exec"}


def test_the_same_state_and_event_give_the_same_answer_in_a_fresh_process() -> None:
    """The purity UNIT-034 needs to rebuild a session from the ledger.

    Run in a subprocess rather than asserted in this one, because a machine
    that retained anything between calls would still look pure to a test that
    shared its interpreter.
    """
    program = (
        "from alphaledger.execution.session import SessionEvent, SessionState, transition\n"
        "state = SessionState.DISARMED\n"
        "for event in (SessionEvent.READY, SessionEvent.WORKING, SessionEvent.OPEN):\n"
        "    state = transition(state, event)\n"
        "print(state.value)\n"
        "print(transition(SessionState.EXITING, SessionEvent.HALTED).value)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
        cwd=MODULE.parents[3],
    )
    assert result.stdout.split() == ["open", "halted"]
