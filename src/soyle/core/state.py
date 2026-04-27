"""Application state machine — enforces valid state transitions."""
from __future__ import annotations

from enum import StrEnum


class State(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    POLISHING = "polishing"
    INJECTING = "injecting"


VALID_TRANSITIONS: dict[State, set[State]] = {
    State.IDLE: {State.RECORDING},
    State.RECORDING: {State.TRANSCRIBING, State.IDLE},
    State.TRANSCRIBING: {State.POLISHING, State.IDLE},
    State.POLISHING: {State.INJECTING, State.IDLE},
    State.INJECTING: {State.IDLE},
}


class StateMachine:
    """Simple deterministic state machine with explicit transitions."""

    def __init__(self) -> None:
        self._current: State = State.IDLE

    @property
    def current(self) -> State:
        return self._current

    def can_start_recording(self) -> bool:
        return self._current == State.IDLE

    def transition(self, to: State) -> None:
        allowed = VALID_TRANSITIONS[self._current]
        if to not in allowed:
            raise ValueError(
                f"invalid transition: {self._current} -> {to} (allowed: {allowed})"
            )
        self._current = to

    def reset_to_idle(self) -> None:
        """Forced reset; used after errors from any state."""
        self._current = State.IDLE
