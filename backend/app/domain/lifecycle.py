"""Module."""

from __future__ import annotations

SCHEDULED = "scheduled"
OPEN = "open"
CLOSED = "closed"
PUBLISHED = "published"

ALL_STATES: tuple[str, ...] = (SCHEDULED, OPEN, CLOSED, PUBLISHED)

TRANSITIONS: dict[str, tuple[str, ...]] = {
    SCHEDULED: (OPEN,),
    OPEN: (CLOSED,),
    CLOSED: (PUBLISHED,),
    PUBLISHED: (),
}

LABELS: dict[str, str] = {
    SCHEDULED: "Scheduled",
    OPEN: "Voting open",
    CLOSED: "Closed",
    PUBLISHED: "Published",
}


class InvalidTransition(Exception):
    """InvalidTransition."""


class ElectionNotOpen(Exception):
    """ElectionNotOpen."""


def can_transition(old: str, new: str) -> bool:
    return new in TRANSITIONS.get(old, ())


def assert_transition(old: str, new: str) -> None:
    if old not in ALL_STATES:
        raise InvalidTransition(f"Unknown state: {old!r}")
    if new not in ALL_STATES:
        raise InvalidTransition(f"Unknown state: {new!r}")
    if not can_transition(old, new):
        allowed = TRANSITIONS[old] or ("(terminal state)",)
        raise InvalidTransition(f"Illegal transition from {old} to {new}; allowed: {list(allowed)}")


def assert_accepts_ballots(state: str) -> None:
    if state != OPEN:
        raise ElectionNotOpen(f"Election is {LABELS.get(state, state)}; it is not accepting votes")
