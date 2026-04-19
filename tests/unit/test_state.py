"""Tests for StateMachine."""
from __future__ import annotations

import pytest

from whisperflow.core.state import State, StateMachine


def test_initial_state_is_idle() -> None:
    sm = StateMachine()
    assert sm.current == State.IDLE


def test_can_start_recording_from_idle() -> None:
    sm = StateMachine()
    assert sm.can_start_recording() is True


def test_cannot_start_recording_from_recording() -> None:
    sm = StateMachine()
    sm.transition(State.RECORDING)
    assert sm.can_start_recording() is False


def test_valid_transition_idle_to_recording() -> None:
    sm = StateMachine()
    sm.transition(State.RECORDING)
    assert sm.current == State.RECORDING


def test_full_happy_path_cycle() -> None:
    sm = StateMachine()
    sm.transition(State.RECORDING)
    sm.transition(State.TRANSCRIBING)
    sm.transition(State.POLISHING)
    sm.transition(State.INJECTING)
    sm.transition(State.IDLE)
    assert sm.current == State.IDLE


def test_invalid_transition_raises() -> None:
    sm = StateMachine()
    # IDLE -> TRANSCRIBING (skipping RECORDING) is invalid
    with pytest.raises(ValueError, match="invalid transition"):
        sm.transition(State.TRANSCRIBING)


def test_any_state_can_return_to_idle_on_error() -> None:
    sm = StateMachine()
    sm.transition(State.RECORDING)
    sm.reset_to_idle()
    assert sm.current == State.IDLE
