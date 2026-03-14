"""Tests for the multi-level undo/redo stack."""

import pytest

from quickprs.undo import UndoStack


class TestUndoStack:
    """Core undo/redo stack behavior."""

    def test_empty_stack(self):
        """New stack has nothing to undo or redo."""
        stack = UndoStack()
        assert not stack.can_undo()
        assert not stack.can_redo()
        assert stack.undo_description() == ""
        assert stack.redo_description() == ""

    def test_undo_empty_returns_none(self):
        """Undo on empty stack returns (None, '')."""
        stack = UndoStack()
        result, desc = stack.undo(b"current")
        assert result is None
        assert desc == ""

    def test_redo_empty_returns_none(self):
        """Redo on empty stack returns (None, '')."""
        stack = UndoStack()
        result, desc = stack.redo(b"current")
        assert result is None
        assert desc == ""

    def test_push_and_undo(self):
        """Push one state, undo to it."""
        stack = UndoStack()
        stack.push(b"state_0", "initial")
        assert stack.can_undo()
        assert not stack.can_redo()

        prev, desc = stack.undo(b"state_1")
        assert prev == b"state_0"
        assert desc == "initial"
        assert not stack.can_undo()
        assert stack.can_redo()

    def test_push_five_undo_three(self):
        """Push 5 states, undo 3, verify correct state each time."""
        stack = UndoStack()
        for i in range(5):
            stack.push(f"state_{i}".encode(), f"action_{i}")

        # Undo 3 times
        current = b"state_5"
        for i in range(4, 1, -1):  # 4, 3, 2
            prev, desc = stack.undo(current)
            assert prev == f"state_{i}".encode()
            assert desc == f"action_{i}"
            current = prev

        # Should have 2 left in undo stack
        assert stack.can_undo()
        assert stack.can_redo()

    def test_undo_then_redo(self):
        """Undo then redo restores the state."""
        stack = UndoStack()
        stack.push(b"state_A", "first")
        stack.push(b"state_B", "second")

        # Undo (current is C)
        prev, desc = stack.undo(b"state_C")
        assert prev == b"state_B"
        assert desc == "second"

        # Redo (current is now B)
        next_bytes, desc = stack.redo(b"state_B")
        assert next_bytes == b"state_C"
        assert desc == "second"

    def test_redo_cleared_after_new_push(self):
        """New action after undo clears the redo stack."""
        stack = UndoStack()
        stack.push(b"state_0", "first")
        stack.push(b"state_1", "second")

        # Undo
        stack.undo(b"state_2")
        assert stack.can_redo()

        # Push new action — redo should be cleared
        stack.push(b"state_NEW", "new action")
        assert not stack.can_redo()

    def test_max_levels(self):
        """Push 25 states with max_levels=20, only 20 remain."""
        stack = UndoStack(max_levels=20)
        for i in range(25):
            stack.push(f"state_{i}".encode(), f"action_{i}")

        # Should have exactly 20
        count = 0
        current = b"state_25"
        while stack.can_undo():
            prev, desc = stack.undo(current)
            current = prev
            count += 1

        assert count == 20

    def test_max_levels_oldest_removed(self):
        """Oldest states are evicted when max_levels exceeded."""
        stack = UndoStack(max_levels=3)
        stack.push(b"A", "alpha")
        stack.push(b"B", "beta")
        stack.push(b"C", "charlie")
        stack.push(b"D", "delta")  # A should be evicted

        current = b"E"
        states = []
        while stack.can_undo():
            prev, desc = stack.undo(current)
            states.append(desc)
            current = prev

        assert states == ["delta", "charlie", "beta"]
        assert b"A" not in [s for s, _ in []]  # A is gone

    def test_description_tracking(self):
        """undo_description and redo_description report correctly."""
        stack = UndoStack()
        stack.push(b"state_0", "add system")
        stack.push(b"state_1", "add channel")

        assert stack.undo_description() == "add channel"
        assert stack.redo_description() == ""

        stack.undo(b"state_2")
        assert stack.undo_description() == "add system"
        assert stack.redo_description() == "add channel"

    def test_clear(self):
        """Clear empties both stacks."""
        stack = UndoStack()
        stack.push(b"A", "first")
        stack.push(b"B", "second")
        stack.undo(b"C")  # B is now on redo

        stack.clear()
        assert not stack.can_undo()
        assert not stack.can_redo()

    def test_multiple_undo_redo_cycles(self):
        """Multiple undo/redo cycles maintain consistency."""
        stack = UndoStack()
        stack.push(b"s0", "a0")
        stack.push(b"s1", "a1")
        stack.push(b"s2", "a2")

        # Undo all 3
        c = b"s3"
        c, _ = stack.undo(c)  # c = s2
        assert c == b"s2"
        c, _ = stack.undo(c)  # c = s1
        assert c == b"s1"
        c, _ = stack.undo(c)  # c = s0
        assert c == b"s0"

        # Redo all 3
        c, _ = stack.redo(c)  # c = s1
        assert c == b"s1"
        c, _ = stack.redo(c)  # c = s2
        assert c == b"s2"
        c, _ = stack.redo(c)  # c = s3
        assert c == b"s3"

        # No more redo
        assert not stack.can_redo()

    def test_push_without_description(self):
        """Push without description defaults to empty string."""
        stack = UndoStack()
        stack.push(b"data")
        assert stack.undo_description() == ""

        prev, desc = stack.undo(b"current")
        assert prev == b"data"
        assert desc == ""

    def test_interleaved_undo_push(self):
        """Undo partway then push new state branches correctly."""
        stack = UndoStack()
        stack.push(b"s0", "a0")
        stack.push(b"s1", "a1")
        stack.push(b"s2", "a2")

        # Undo 2 steps: pops s2, then s1
        stack.undo(b"s3")  # pops (s2, a2), returns s2
        stack.undo(b"s2")  # pops (s1, a1), returns s1

        # Push new branch — clears redo, undo_stack is now [s0, s1_alt]
        stack.push(b"s1_alt", "branch")

        # Redo should be empty (new branch)
        assert not stack.can_redo()

        # Undo should give s1_alt, then s0 (s1 was consumed by earlier undo)
        c = b"s1_alt_next"
        c, d = stack.undo(c)
        assert c == b"s1_alt"
        assert d == "branch"
        c, d = stack.undo(c)
        assert c == b"s0"
        assert d == "a0"
        assert not stack.can_undo()
