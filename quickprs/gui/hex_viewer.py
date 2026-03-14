"""Hex viewer for raw PRS section data.

Displays binary data in a traditional hex dump format with:
- Offset column (hex)
- Hex bytes (16 per line, grouped by 8)
- ASCII column
- Search for hex patterns or ASCII strings
- Click on a byte to show offset/value in status bar
- Color-coded display (printable chars, zeros, FF markers)
- Copy selection as hex or ASCII
"""

import tkinter as tk
from tkinter import ttk


class HexViewer(tk.Toplevel):
    """Hex viewer for raw PRS section data."""

    def __init__(self, parent, data, title="Hex Viewer", offset_in_file=0):
        super().__init__(parent)
        self.title(title)
        self.geometry("820x560")
        self.transient(parent)

        self._data = data
        self._file_offset = offset_in_file
        self._search_matches = []
        self._current_match = -1

        self._build_ui()
        self._render_hex()
        self._update_status(0)

    def _build_ui(self):
        # Search bar
        search_frame = ttk.Frame(self, padding=4)
        search_frame.pack(fill=tk.X)

        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self._search_var,
                                 width=24)
        search_entry.pack(side=tk.LEFT, padx=4)
        search_entry.bind("<Return>", lambda e: self._search())

        self._search_mode = tk.StringVar(value="hex")
        ttk.Radiobutton(search_frame, text="Hex", value="hex",
                        variable=self._search_mode).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(search_frame, text="ASCII", value="ascii",
                        variable=self._search_mode).pack(side=tk.LEFT, padx=2)

        ttk.Button(search_frame, text="Find", width=6,
                   command=self._search).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_frame, text="Next", width=6,
                   command=self._next_match).pack(side=tk.LEFT, padx=2)

        self._search_status = ttk.Label(search_frame, text="",
                                        foreground="gray")
        self._search_status.pack(side=tk.LEFT, padx=8)

        # Hex display
        frame = ttk.Frame(self, padding=4)
        frame.pack(fill=tk.BOTH, expand=True)

        self._text = tk.Text(frame, wrap=tk.NONE,
                             font=("Consolas", 10), state=tk.DISABLED,
                             cursor="arrow", spacing1=1, spacing3=1)
        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                            command=self._text.yview)
        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL,
                            command=self._text.xview)
        self._text.configure(yscrollcommand=vsb.set,
                             xscrollcommand=hsb.set)

        self._text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        # Configure tags for color coding
        self._text.tag_configure("offset", foreground="#666666")
        self._text.tag_configure("hex_zero", foreground="#999999")
        self._text.tag_configure("hex_ff", foreground="#cc3333")
        self._text.tag_configure("hex_normal", foreground="#333333")
        self._text.tag_configure("hex_printable", foreground="#003399")
        self._text.tag_configure("ascii_dot", foreground="#999999")
        self._text.tag_configure("ascii_char", foreground="#003399")
        self._text.tag_configure("separator", foreground="#cccccc")
        self._text.tag_configure("header", foreground="#666666",
                                 font=("Consolas", 10, "bold"))
        self._text.tag_configure("search_hit",
                                 background="#ffff99",
                                 foreground="#000000")
        self._text.tag_configure("search_current",
                                 background="#ff9933",
                                 foreground="#000000")

        # Click binding for byte selection
        self._text.bind("<Button-1>", self._on_click)

        # Status bar
        status_frame = ttk.Frame(self, padding=4)
        status_frame.pack(fill=tk.X)

        self._status_label = ttk.Label(status_frame, text="",
                                       font=("Consolas", 9))
        self._status_label.pack(side=tk.LEFT)

        # Buttons
        btn_frame = ttk.Frame(self, padding=4)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="Close", command=self.destroy,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Copy Hex",
                   command=self._copy_hex,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Copy ASCII",
                   command=self._copy_ascii,
                   width=10).pack(side=tk.RIGHT, padx=2)

        size_label = ttk.Label(
            btn_frame,
            text=f"{len(self._data)} bytes ({len(self._data):,})",
            foreground="gray")
        size_label.pack(side=tk.LEFT, padx=4)

    def _render_hex(self):
        """Render the hex dump into the text widget."""
        self._text.config(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)

        data = self._data

        # Header line
        header = "Offset    " + " ".join(f"{i:02X}" for i in range(16))
        header += "  " + "0123456789ABCDEF"
        self._text.insert(tk.END, header + "\n", "header")
        self._text.insert(tk.END, "-" * 76 + "\n", "header")

        # Store byte-to-position mapping for click detection
        self._byte_positions = {}

        for offset in range(0, len(data), 16):
            chunk = data[offset:offset + 16]
            line_start = self._text.index(tk.END + "-1c")

            # Offset column
            self._text.insert(tk.END, f"{offset:08X}  ", "offset")

            # Hex bytes
            for i, b in enumerate(chunk):
                byte_offset = offset + i
                pos_start = self._text.index(tk.END + "-1c")

                if b == 0x00:
                    tag = "hex_zero"
                elif b == 0xFF:
                    tag = "hex_ff"
                elif 32 <= b <= 126:
                    tag = "hex_printable"
                else:
                    tag = "hex_normal"

                self._text.insert(tk.END, f"{b:02X}", tag)
                pos_end = self._text.index(tk.END + "-1c")
                self._byte_positions[byte_offset] = (pos_start, pos_end)

                # Space after each byte, extra space after 8th byte
                if i == 7:
                    self._text.insert(tk.END, "  ", "separator")
                elif i < 15:
                    self._text.insert(tk.END, " ")

            # Pad if less than 16 bytes
            if len(chunk) < 16:
                remaining = 16 - len(chunk)
                pad = remaining * 3
                if len(chunk) <= 8:
                    pad += 1  # account for missing mid-space
                self._text.insert(tk.END, " " * pad)

            # ASCII column
            self._text.insert(tk.END, "  ")
            for b in chunk:
                if 32 <= b <= 126:
                    self._text.insert(tk.END, chr(b), "ascii_char")
                else:
                    self._text.insert(tk.END, ".", "ascii_dot")

            self._text.insert(tk.END, "\n")

        self._text.config(state=tk.DISABLED)

    def _on_click(self, event):
        """Handle click on hex display to show byte info."""
        index = self._text.index(f"@{event.x},{event.y}")
        line, col = map(int, index.split("."))

        if line < 3:
            return  # clicked on header

        # Each data line starts at line 3
        data_line = line - 3
        data_offset = data_line * 16

        # Determine which byte was clicked based on column
        # Offset takes 10 chars ("XXXXXXXX  ")
        # Then hex bytes: each is "XX " (3 chars), extra space at col 8
        hex_start = 10
        if col < hex_start:
            return

        hex_col = col - hex_start
        # Account for grouping: bytes 0-7 take 24 chars (8*3),
        # then 1 extra space, bytes 8-15 take 24 chars
        if hex_col < 24:
            byte_in_line = hex_col // 3
        elif hex_col == 24:
            return  # clicked on separator
        elif hex_col < 49:
            byte_in_line = 8 + (hex_col - 25) // 3
        else:
            # Clicked in ASCII area
            ascii_start = 51  # approximate
            byte_in_line = hex_col - ascii_start
            if byte_in_line < 0 or byte_in_line >= 16:
                return

        byte_offset = data_offset + byte_in_line
        if byte_offset < len(self._data):
            self._update_status(byte_offset)

    def _update_status(self, offset):
        """Update status bar with info about the byte at offset."""
        if offset >= len(self._data):
            return

        b = self._data[offset]
        char = chr(b) if 32 <= b <= 126 else "."
        file_off = offset + self._file_offset

        parts = [
            f"Offset: 0x{offset:04X} ({offset})",
            f"File: 0x{file_off:04X}",
            f"Value: 0x{b:02X} ({b}) '{char}'",
        ]

        # Show uint16 LE if possible
        if offset + 1 < len(self._data):
            u16 = self._data[offset] | (self._data[offset + 1] << 8)
            parts.append(f"uint16LE: {u16}")

        self._status_label.config(text="  |  ".join(parts))

    def _search(self):
        """Search for hex pattern or ASCII string."""
        query = self._search_var.get().strip()
        if not query:
            return

        self._search_matches = []
        self._current_match = -1

        # Remove old highlights
        self._text.tag_remove("search_hit", "1.0", tk.END)
        self._text.tag_remove("search_current", "1.0", tk.END)

        mode = self._search_mode.get()

        if mode == "hex":
            # Parse hex string: "FF 00 AB" or "FF00AB"
            hex_str = query.replace(" ", "").replace("0x", "")
            try:
                search_bytes = bytes.fromhex(hex_str)
            except ValueError:
                self._search_status.config(text="Invalid hex pattern")
                return
        else:
            # ASCII search
            search_bytes = query.encode("ascii", errors="ignore")

        if not search_bytes:
            return

        # Find all occurrences in data
        data = self._data
        search_len = len(search_bytes)
        pos = 0
        while pos <= len(data) - search_len:
            idx = data.find(search_bytes, pos)
            if idx < 0:
                break
            self._search_matches.append(idx)
            pos = idx + 1

        if not self._search_matches:
            self._search_status.config(text="No matches")
            return

        # Highlight all matches
        for match_offset in self._search_matches:
            for i in range(search_len):
                byte_off = match_offset + i
                if byte_off in self._byte_positions:
                    start, end = self._byte_positions[byte_off]
                    self._text.tag_add("search_hit", start, end)

        self._current_match = 0
        self._highlight_current_match(search_len)
        total = len(self._search_matches)
        self._search_status.config(text=f"1 of {total} matches")

    def _next_match(self):
        """Jump to next search match."""
        if not self._search_matches:
            return

        search_len = len(self._search_var.get().strip().replace(" ", ""))
        if self._search_mode.get() == "hex":
            search_len = search_len // 2
        else:
            search_len = len(self._search_var.get().strip())

        # Remove current highlight
        self._text.tag_remove("search_current", "1.0", tk.END)

        self._current_match = (
            (self._current_match + 1) % len(self._search_matches))
        self._highlight_current_match(search_len)

        total = len(self._search_matches)
        cur = self._current_match + 1
        self._search_status.config(text=f"{cur} of {total} matches")

    def _highlight_current_match(self, search_len):
        """Highlight the current match and scroll to it."""
        if self._current_match < 0:
            return

        match_offset = self._search_matches[self._current_match]
        for i in range(search_len):
            byte_off = match_offset + i
            if byte_off in self._byte_positions:
                start, end = self._byte_positions[byte_off]
                self._text.tag_add("search_current", start, end)
                if i == 0:
                    self._text.see(start)

        self._update_status(match_offset)

    def _copy_hex(self):
        """Copy all data as hex string to clipboard."""
        self.clipboard_clear()
        self.clipboard_append(self._data.hex())

    def _copy_ascii(self):
        """Copy all data as ASCII (non-printable as dots) to clipboard."""
        ascii_str = "".join(
            chr(b) if 32 <= b <= 126 else "." for b in self._data)
        self.clipboard_clear()
        self.clipboard_append(ascii_str)
