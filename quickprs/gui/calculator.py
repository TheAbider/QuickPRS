"""Radio Calculator dialog — repeater offsets, CTCSS/DCS lookup,
channel spacing analysis, and P25 channel frequency computation.

Accessible from Tools > Radio Calculator in the main GUI.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from ..freq_tools import (
    CTCSS_TONES, DCS_CODES,
    calculate_repeater_offset, calculate_all_offsets,
    identify_service, calculate_p25_channel, calculate_channel_spacing,
)


class RadioCalculator(tk.Toplevel):
    """Standalone calculator tool for common radio math."""

    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        self.title("Radio Calculator")
        self.geometry("680x520")
        self.transient(parent)
        self.resizable(True, True)
        self.minsize(550, 400)

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self._build_repeater_tab(nb)
        self._build_ctcss_dcs_tab(nb)
        self._build_spacing_tab(nb)
        self._build_p25_tab(nb)

        # Close on Escape
        self.bind("<Escape>", lambda e: self.destroy())

    # ─── Tab 1: Repeater Offset Calculator ────────────────────────

    def _build_repeater_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="Repeater Offset")

        # Input row
        input_row = ttk.Frame(frame)
        input_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(input_row, text="Output frequency (MHz):").pack(
            side=tk.LEFT)
        self._rpt_freq_var = tk.StringVar()
        entry = ttk.Entry(input_row, textvariable=self._rpt_freq_var,
                          width=14)
        entry.pack(side=tk.LEFT, padx=6)
        ttk.Button(input_row, text="Calculate",
                   command=self._calc_repeater).pack(side=tk.LEFT, padx=4)
        if self.app:
            self._rpt_add_btn = ttk.Button(
                input_row, text="Add to Personality",
                command=self._add_repeater_pair, state=tk.DISABLED)
            self._rpt_add_btn.pack(side=tk.RIGHT, padx=4)

        # Results area
        self._rpt_result = tk.Text(frame, wrap=tk.WORD,
                                   font=("Consolas", 10), height=16,
                                   state=tk.DISABLED)
        rpt_vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                                command=self._rpt_result.yview)
        self._rpt_result.configure(yscrollcommand=rpt_vsb.set)
        self._rpt_result.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        rpt_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Calculate on Enter
        entry.bind("<Return>", lambda e: self._calc_repeater())

        # Store last calculated result for "Add to Personality"
        self._last_rpt_result = None

    def _calc_repeater(self):
        """Calculate repeater offset and service identification."""
        try:
            freq = float(self._rpt_freq_var.get().strip())
        except ValueError:
            self._rpt_result.config(state=tk.NORMAL)
            self._rpt_result.delete("1.0", tk.END)
            self._rpt_result.insert("1.0", "Enter a valid frequency in MHz.")
            self._rpt_result.config(state=tk.DISABLED)
            return

        lines = []

        # Service identification
        svc = identify_service(freq)
        lines.append(f"Frequency:   {freq:.5f} MHz")
        lines.append(f"Service:     {svc['service']}")
        lines.append(f"Band:        {svc['band']}")
        if svc['notes']:
            lines.append(f"Notes:       {svc['notes']}")
        lines.append("")

        # Standard offset
        result = calculate_repeater_offset(freq)
        if result:
            offset, direction = result
            if direction == "+":
                input_freq = freq + offset
            else:
                input_freq = freq - offset

            # Determine band name
            if 144.0 <= freq <= 148.0:
                band = "2m (144-148 MHz)"
            elif 222.0 <= freq <= 225.0:
                band = "1.25m (222-225 MHz)"
            elif 420.0 <= freq <= 450.0:
                band = "70cm (420-450 MHz)"
            elif 902.0 <= freq <= 928.0:
                band = "33cm (902-928 MHz)"
            else:
                band = "unknown"

            lines.append("Standard Repeater Pair:")
            lines.append(f"  Output (RX):  {freq:.5f} MHz")
            lines.append(f"  Input  (TX):  {input_freq:.5f} MHz")
            lines.append(f"  Offset:       {direction}{offset:.1f} MHz")
            lines.append(f"  Band:         {band}")
            lines.append("")

            self._last_rpt_result = {
                'output_freq': freq,
                'input_freq': input_freq,
                'offset': offset,
                'direction': direction,
            }
            if self.app and hasattr(self, '_rpt_add_btn'):
                self._rpt_add_btn.config(state=tk.NORMAL)
        else:
            lines.append("Not in a standard repeater band.")
            lines.append("Supported bands: 2m, 1.25m, 70cm, 33cm")
            self._last_rpt_result = None
            if self.app and hasattr(self, '_rpt_add_btn'):
                self._rpt_add_btn.config(state=tk.DISABLED)

        # All possible offsets
        all_offsets = calculate_all_offsets(freq)
        if all_offsets:
            lines.append("")
            lines.append("All Possible Repeater Pairs:")
            lines.append("-" * 50)
            for input_f, off, band_name, desc in all_offsets:
                lines.append(f"  Input: {input_f:.5f} MHz  ({desc})")

        self._rpt_result.config(state=tk.NORMAL)
        self._rpt_result.delete("1.0", tk.END)
        self._rpt_result.insert("1.0", "\n".join(lines))
        self._rpt_result.config(state=tk.DISABLED)

    def _add_repeater_pair(self):
        """Add the calculated repeater pair as a conv channel.

        Opens the standard add-channel dialog with the repeater pair
        frequencies pre-filled. The user selects which conv set to add
        to via the normal _quick_add_channels flow.
        """
        if not self.app or not self.app.prs or not self._last_rpt_result:
            messagebox.showwarning(
                "Warning",
                "No personality loaded or no repeater pair calculated.",
                parent=self)
            return

        rpt = self._last_rpt_result
        out_freq = rpt['output_freq']
        in_freq = rpt['input_freq']

        # Find conv sets
        parsed = self.app._parse_sets()
        conv = parsed.get('conv') or []

        if not conv:
            messagebox.showinfo(
                "No Conv Sets",
                "No conventional channel sets exist yet.\n"
                "Create one first using + Channels in the toolbar.",
                parent=self)
            return

        # Pick set, then show add-channel form with pre-filled freqs
        if len(conv) == 1:
            set_name = conv[0].name
        else:
            # Ask which set
            dlg = tk.Toplevel(self)
            dlg.title("Select Conv Set")
            dlg.geometry("300x130")
            dlg.transient(self)
            dlg.resizable(False, False)
            dlg.grab_set()

            ttk.Label(dlg, text="Add repeater pair to which set?",
                      padding=8).pack(anchor=tk.W)
            set_var = tk.StringVar(value=conv[0].name)
            combo = ttk.Combobox(dlg, textvariable=set_var,
                                 state="readonly",
                                 values=[c.name for c in conv])
            combo.pack(padx=12, fill=tk.X)

            chosen = [None]

            def pick():
                chosen[0] = set_var.get()
                dlg.destroy()

            btn_row = ttk.Frame(dlg, padding=8)
            btn_row.pack(fill=tk.X)
            ttk.Button(btn_row, text="OK", command=pick,
                       width=8).pack(side=tk.LEFT, padx=4)
            ttk.Button(btn_row, text="Cancel", command=dlg.destroy,
                       width=8).pack(side=tk.RIGHT, padx=4)
            dlg.bind("<Return>", lambda e: pick())
            dlg.bind("<Escape>", lambda e: dlg.destroy())
            dlg.wait_window()
            if chosen[0] is None:
                return
            set_name = chosen[0]

        # Now open the add-channel form pre-filled
        pv = self.app.personality_view
        vals = pv._simple_form_dialog(
            f"Add Repeater to '{set_name}'", [
                ("Short Name:", "RPT", "str8"),
                ("Long Name:", "REPEATER", "str16"),
                ("TX Freq (MHz):", f"{in_freq:.5f}", "float"),
                ("RX Freq (MHz):", f"{out_freq:.5f}", "float"),
                ("TX Tone:", "", "str"),
                ("RX Tone:", "", "str"),
            ])
        if vals is None:
            return

        short_name = vals[0].strip()
        long_name = vals[1].strip()
        try:
            tx_freq = float(vals[2])
            rx_freq = float(vals[3])
        except ValueError:
            messagebox.showerror("Error", "Invalid frequency value.",
                                 parent=self)
            return
        tx_tone = vals[4].strip()
        rx_tone = vals[5].strip()

        if not short_name:
            return
        if len(short_name) > 8:
            short_name = short_name[:8]
        if len(long_name) > 16:
            long_name = long_name[:16]

        try:
            from ..injector import (
                _parse_section_data, _replace_conv_sections,
                _get_header_bytes, _get_first_count, make_conv_channel,
            )
            from ..record_types import parse_conv_channel_section

            prs = self.app.prs
            conv_sec = prs.get_section_by_class("CConvChannel")
            set_sec = prs.get_section_by_class("CConvSet")
            if not conv_sec or not set_sec:
                messagebox.showerror("Error",
                                     "No conv sections found.",
                                     parent=self)
                return

            byte1, byte2 = _get_header_bytes(conv_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CConvSet")
            existing_sets = _parse_section_data(
                conv_sec, parse_conv_channel_section, first_count)

            target = None
            for cs in existing_sets:
                if cs.name == set_name:
                    target = cs
                    break
            if not target:
                messagebox.showerror("Error",
                                     f"Conv set '{set_name}' not found.",
                                     parent=self)
                return

            channel = make_conv_channel(
                short_name, tx_freq, rx_freq,
                tx_tone, rx_tone, long_name)
            target.channels.append(channel)

            self.app.save_undo_snapshot("Add repeater pair")
            _replace_conv_sections(
                prs, existing_sets, byte1, byte2,
                set_byte1, set_byte2)
            self.app.mark_modified()
            pv.refresh()
            self.app.status_set(
                f"Added repeater: {short_name} "
                f"TX:{tx_freq:.5f} RX:{rx_freq:.5f}")
        except Exception as e:
            messagebox.showerror("Error",
                                 f"Failed to add channel:\n{e}",
                                 parent=self)

    # ─── Tab 2: CTCSS/DCS Lookup ─────────────────────────────────

    def _build_ctcss_dcs_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="CTCSS/DCS Lookup")

        # Search bar
        search_row = ttk.Frame(frame)
        search_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(search_row, text="Search:").pack(side=tk.LEFT)
        self._tone_search_var = tk.StringVar()
        self._tone_search_var.trace_add("write", self._filter_tones)
        search_entry = ttk.Entry(search_row,
                                 textvariable=self._tone_search_var,
                                 width=16)
        search_entry.pack(side=tk.LEFT, padx=6)
        ttk.Button(search_row, text="Copy Selected",
                   command=self._copy_tone).pack(side=tk.RIGHT, padx=4)

        # Treeview with CTCSS and DCS
        columns = ("type", "value", "display")
        self._tone_tree = ttk.Treeview(frame, columns=columns,
                                        show="headings", height=18)
        self._tone_tree.heading("type", text="Type")
        self._tone_tree.heading("value", text="Code/Tone")
        self._tone_tree.heading("display", text="Display")
        self._tone_tree.column("type", width=80, minwidth=60)
        self._tone_tree.column("value", width=100, minwidth=80)
        self._tone_tree.column("display", width=160, minwidth=100)

        tone_vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                                  command=self._tone_tree.yview)
        self._tone_tree.configure(yscrollcommand=tone_vsb.set)
        self._tone_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tone_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Double-click to copy
        self._tone_tree.bind("<Double-1>", lambda e: self._copy_tone())

        # Populate
        self._all_tone_items = []
        for tone in CTCSS_TONES:
            display = f"{tone:.1f} Hz"
            item = self._tone_tree.insert("", tk.END,
                                           values=("CTCSS", f"{tone:.1f}",
                                                   display))
            self._all_tone_items.append((item, "CTCSS", f"{tone:.1f}",
                                         display))

        for code in DCS_CODES:
            normal = f"D{code:03d}N"
            inverted = f"D{code:03d}I"
            display = f"{normal} / {inverted}"
            item = self._tone_tree.insert("", tk.END,
                                           values=("DCS", normal, display))
            self._all_tone_items.append((item, "DCS", normal, display))

    def _filter_tones(self, *_args):
        """Filter CTCSS/DCS list based on search text."""
        query = self._tone_search_var.get().strip().lower()

        for item, tone_type, value, display in self._all_tone_items:
            matches = (not query
                       or query in tone_type.lower()
                       or query in value.lower()
                       or query in display.lower())
            if matches:
                # Re-attach if detached
                try:
                    self._tone_tree.reattach(item, "", tk.END)
                except tk.TclError:
                    pass
            else:
                try:
                    self._tone_tree.detach(item)
                except tk.TclError:
                    pass

    def _copy_tone(self):
        """Copy selected tone/code value to clipboard."""
        sel = self._tone_tree.selection()
        if not sel:
            return
        values = self._tone_tree.item(sel[0], "values")
        if values:
            # Copy the code/tone value (column 1)
            self.clipboard_clear()
            self.clipboard_append(values[1])
            if self.app:
                self.app.status_set(f"Copied: {values[1]}")

    # ─── Tab 3: Channel Spacing ──────────────────────────────────

    def _build_spacing_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="Channel Spacing")

        # Input rows
        row1 = ttk.Frame(frame)
        row1.pack(fill=tk.X, pady=4)
        ttk.Label(row1, text="Frequency 1 (MHz):").pack(side=tk.LEFT)
        self._sp_freq1_var = tk.StringVar()
        e1 = ttk.Entry(row1, textvariable=self._sp_freq1_var, width=14)
        e1.pack(side=tk.LEFT, padx=6)

        row2 = ttk.Frame(frame)
        row2.pack(fill=tk.X, pady=4)
        ttk.Label(row2, text="Frequency 2 (MHz):").pack(side=tk.LEFT)
        self._sp_freq2_var = tk.StringVar()
        e2 = ttk.Entry(row2, textvariable=self._sp_freq2_var, width=14)
        e2.pack(side=tk.LEFT, padx=6)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=6)
        ttk.Button(btn_row, text="Calculate",
                   command=self._calc_spacing).pack(side=tk.LEFT, padx=4)

        # Results
        self._sp_result = tk.Text(frame, wrap=tk.WORD,
                                  font=("Consolas", 10), height=14,
                                  state=tk.DISABLED)
        sp_vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                                command=self._sp_result.yview)
        self._sp_result.configure(yscrollcommand=sp_vsb.set)
        self._sp_result.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sp_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        e1.bind("<Return>", lambda e: e2.focus_set())
        e2.bind("<Return>", lambda e: self._calc_spacing())

    def _calc_spacing(self):
        """Calculate spacing between two frequencies."""
        try:
            f1 = float(self._sp_freq1_var.get().strip())
            f2 = float(self._sp_freq2_var.get().strip())
        except ValueError:
            self._sp_result.config(state=tk.NORMAL)
            self._sp_result.delete("1.0", tk.END)
            self._sp_result.insert("1.0",
                                   "Enter two valid frequencies in MHz.")
            self._sp_result.config(state=tk.DISABLED)
            return

        info = calculate_channel_spacing(f1, f2)
        low = min(f1, f2)
        high = max(f1, f2)

        lines = [
            f"Frequency 1:   {f1:.5f} MHz",
            f"Frequency 2:   {f2:.5f} MHz",
            "",
            f"Spacing:       {info['spacing_khz']:.3f} kHz"
            f"  ({info['spacing_khz'] / 1000:.6f} MHz)",
            "",
        ]

        # Interference assessment
        if info['would_interfere_nb']:
            lines.append("INTERFERENCE:  Would interfere at 12.5 kHz "
                         "narrowband spacing")
        elif info['would_interfere_wb']:
            lines.append("WARNING:       Would interfere at 25 kHz "
                         "wideband spacing")
            lines.append("               OK for 12.5 kHz narrowband")
        else:
            lines.append("Interference:  No conflict at narrowband "
                         "or wideband spacing")

        lines.append("")
        lines.append(f"Channels between ({low:.5f} - {high:.5f}):")
        lines.append(f"  At 12.5 kHz spacing:  {info['channels_12_5']} "
                     f"channels")
        lines.append(f"  At 25.0 kHz spacing:  {info['channels_25']} "
                     f"channels")

        # Show example channel plan at 12.5 kHz
        if 1 <= info['channels_12_5'] <= 20:
            lines.append("")
            lines.append("12.5 kHz channel plan:")
            for i in range(info['channels_12_5'] + 2):
                ch_freq = low + i * 0.0125
                if ch_freq > high + 0.001:
                    break
                marker = " <-- " if (abs(ch_freq - f1) < 0.001
                                     or abs(ch_freq - f2) < 0.001) else ""
                lines.append(f"  CH {i+1:2d}: {ch_freq:.5f} MHz{marker}")

        self._sp_result.config(state=tk.NORMAL)
        self._sp_result.delete("1.0", tk.END)
        self._sp_result.insert("1.0", "\n".join(lines))
        self._sp_result.config(state=tk.DISABLED)

    # ─── Tab 4: P25 Channel Calculator ───────────────────────────

    def _build_p25_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="P25 Channel")

        # Input fields
        r1 = ttk.Frame(frame)
        r1.pack(fill=tk.X, pady=4)
        ttk.Label(r1, text="Base frequency (MHz):").pack(side=tk.LEFT)
        self._p25_base_var = tk.StringVar()
        e_base = ttk.Entry(r1, textvariable=self._p25_base_var, width=14)
        e_base.pack(side=tk.LEFT, padx=6)

        r2 = ttk.Frame(frame)
        r2.pack(fill=tk.X, pady=4)
        ttk.Label(r2, text="Channel spacing (kHz):").pack(side=tk.LEFT)
        self._p25_spacing_var = tk.StringVar(value="12.5")
        spacing_combo = ttk.Combobox(
            r2, textvariable=self._p25_spacing_var, width=10,
            values=["6.25", "12.5", "25.0"])
        spacing_combo.pack(side=tk.LEFT, padx=6)

        r3 = ttk.Frame(frame)
        r3.pack(fill=tk.X, pady=4)
        ttk.Label(r3, text="Logical Channel Number:").pack(side=tk.LEFT)
        self._p25_lcn_var = tk.StringVar()
        e_lcn = ttk.Entry(r3, textvariable=self._p25_lcn_var, width=10)
        e_lcn.pack(side=tk.LEFT, padx=6)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=6)
        ttk.Button(btn_row, text="Calculate",
                   command=self._calc_p25).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Calculate Range",
                   command=self._calc_p25_range).pack(side=tk.LEFT, padx=4)

        # Range inputs (optional)
        range_row = ttk.Frame(frame)
        range_row.pack(fill=tk.X, pady=2)
        ttk.Label(range_row, text="LCN range (for bulk):").pack(
            side=tk.LEFT)
        self._p25_lcn_start_var = tk.StringVar()
        ttk.Entry(range_row, textvariable=self._p25_lcn_start_var,
                  width=8).pack(side=tk.LEFT, padx=4)
        ttk.Label(range_row, text="to").pack(side=tk.LEFT)
        self._p25_lcn_end_var = tk.StringVar()
        ttk.Entry(range_row, textvariable=self._p25_lcn_end_var,
                  width=8).pack(side=tk.LEFT, padx=4)

        # Results
        self._p25_result = tk.Text(frame, wrap=tk.WORD,
                                   font=("Consolas", 10), height=12,
                                   state=tk.DISABLED)
        p25_vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                                 command=self._p25_result.yview)
        self._p25_result.configure(yscrollcommand=p25_vsb.set)
        self._p25_result.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        p25_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        e_base.bind("<Return>", lambda e: e_lcn.focus_set())
        e_lcn.bind("<Return>", lambda e: self._calc_p25())

    def _calc_p25(self):
        """Calculate single P25 channel frequency."""
        try:
            base = float(self._p25_base_var.get().strip())
            spacing = float(self._p25_spacing_var.get().strip())
            lcn = int(self._p25_lcn_var.get().strip())
        except ValueError:
            self._p25_result.config(state=tk.NORMAL)
            self._p25_result.delete("1.0", tk.END)
            self._p25_result.insert("1.0",
                                    "Enter base freq (MHz), spacing (kHz),"
                                    " and LCN (integer).")
            self._p25_result.config(state=tk.DISABLED)
            return

        freq = calculate_p25_channel(base, spacing, lcn)

        # Service identification
        svc = identify_service(freq)

        lines = [
            "P25 Channel Calculation",
            "=" * 40,
            f"Base frequency:   {base:.5f} MHz",
            f"Channel spacing:  {spacing} kHz",
            f"Logical Channel:  {lcn}",
            "",
            f"Formula:  {base:.5f} + ({lcn} x {spacing}/1000)",
            f"Result:   {freq:.5f} MHz",
            "",
            f"Service:  {svc['service']}",
            f"Band:     {svc['band']}",
        ]
        if svc['notes']:
            lines.append(f"Notes:    {svc['notes']}")

        self._p25_result.config(state=tk.NORMAL)
        self._p25_result.delete("1.0", tk.END)
        self._p25_result.insert("1.0", "\n".join(lines))
        self._p25_result.config(state=tk.DISABLED)

    def _calc_p25_range(self):
        """Calculate P25 frequencies for a range of LCNs."""
        try:
            base = float(self._p25_base_var.get().strip())
            spacing = float(self._p25_spacing_var.get().strip())
            lcn_start = int(self._p25_lcn_start_var.get().strip())
            lcn_end = int(self._p25_lcn_end_var.get().strip())
        except ValueError:
            self._p25_result.config(state=tk.NORMAL)
            self._p25_result.delete("1.0", tk.END)
            self._p25_result.insert("1.0",
                                    "Fill in base freq, spacing, and LCN "
                                    "range start/end.")
            self._p25_result.config(state=tk.DISABLED)
            return

        if lcn_end < lcn_start:
            lcn_start, lcn_end = lcn_end, lcn_start
        if lcn_end - lcn_start > 500:
            lcn_end = lcn_start + 500

        lines = [
            f"P25 Channel Range: LCN {lcn_start} - {lcn_end}",
            f"Base: {base:.5f} MHz  Spacing: {spacing} kHz",
            "=" * 40,
        ]

        for lcn in range(lcn_start, lcn_end + 1):
            freq = calculate_p25_channel(base, spacing, lcn)
            lines.append(f"  LCN {lcn:5d}:  {freq:.5f} MHz")

        self._p25_result.config(state=tk.NORMAL)
        self._p25_result.delete("1.0", tk.END)
        self._p25_result.insert("1.0", "\n".join(lines))
        self._p25_result.config(state=tk.DISABLED)
