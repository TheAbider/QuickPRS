"""Multi-level undo/redo stack for PRS modifications.

Stores snapshots of the full PRS file bytes. Each snapshot also
has a description of what was changed.
"""


class UndoStack:
    """Multi-level undo/redo stack for PRS modifications.

    Stores snapshots of the full PRS file bytes. Each snapshot also
    has a description of what was changed.
    """

    def __init__(self, max_levels=20):
        self._undo_stack = []  # list of (bytes, description)
        self._redo_stack = []  # list of (bytes, description)
        self.max_levels = max_levels

    def push(self, prs_bytes, description=""):
        """Save current state before a modification."""
        self._undo_stack.append((prs_bytes, description))
        if len(self._undo_stack) > self.max_levels:
            self._undo_stack.pop(0)
        self._redo_stack.clear()  # new action clears redo

    def undo(self, current_bytes):
        """Undo: pop from undo stack, push current to redo, return previous bytes."""
        if not self._undo_stack:
            return None, ""
        prev_bytes, desc = self._undo_stack.pop()
        self._redo_stack.append((current_bytes, desc))
        return prev_bytes, desc

    def redo(self, current_bytes):
        """Redo: pop from redo stack, push current to undo, return next bytes."""
        if not self._redo_stack:
            return None, ""
        next_bytes, desc = self._redo_stack.pop()
        self._undo_stack.append((current_bytes, desc))
        return next_bytes, desc

    def can_undo(self):
        return bool(self._undo_stack)

    def can_redo(self):
        return bool(self._redo_stack)

    def undo_description(self):
        """Get description of what would be undone."""
        if self._undo_stack:
            return self._undo_stack[-1][1]
        return ""

    def redo_description(self):
        """Get description of what would be redone."""
        if self._redo_stack:
            return self._redo_stack[-1][1]
        return ""

    def clear(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
