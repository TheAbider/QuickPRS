"""System Import Wizard - multi-step dialog for adding P25 systems.

Walks users through adding a P25 system step by step:
  Step 1: Choose source (database / RadioReference / manual)
  Step 2: Configure (name, System ID, WACN, band)
  Step 3: Frequencies (optional — paste, CSV, or skip)
  Step 4: Talkgroups (optional — paste, CSV, or skip)
  Step 5: Review & Add
"""

import csv
import io
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ..system_database import (
    list_all_systems, search_systems, get_system_by_name,
    get_iden_template_key, get_default_iden_name,
)
from ..iden_library import get_template, get_template_keys, get_default_name
from ..injector import (
    add_p25_trunked_system, make_trunk_set, make_group_set,
    make_iden_set, make_p25_group,
)
from ..record_types import P25TrkSystemConfig
from ..validation import validate_prs, ERROR
from ..logger import log_action, log_error


STEP_TITLES = [
    "Choose Source",
    "Configure System",
    "Frequencies (Optional)",
    "Talkgroups (Optional)",
    "Review & Add",
]


class SystemWizard(tk.Toplevel):
    """Multi-step wizard dialog for adding a P25 system."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Add P25 System - Wizard")
        self.geometry("700x550")
        self.minsize(600, 450)
        self.transient(parent)
        self.grab_set()

        self.current_step = 0

        # Wizard state
        self.source = tk.StringVar(value="database")  # database/rr/manual
        self.selected_system = None  # P25System from database

        # System config fields
        self.sys_name = tk.StringVar()
        self.sys_long_name = tk.StringVar()
        self.sys_id = tk.StringVar()
        self.sys_wacn = tk.StringVar(value="0")
        self.sys_band = tk.StringVar(value="800")
        self.sys_type = tk.StringVar(value="Phase II")

        # Frequency/talkgroup data
        self.freq_text = ""
        self.tg_text = ""

        # Build UI
        self._build_ui()
        self._show_step(0)

        self.bind("<Escape>", lambda e: self.destroy())

    def _build_ui(self):
        """Build the wizard layout: header, content area, nav buttons."""
        # Header with step indicator
        header = ttk.Frame(self, padding=(16, 8))
        header.pack(fill=tk.X)

        self.step_label = ttk.Label(
            header, text="Step 1 of 5: Choose Source",
            font=("", 12, "bold"))
        self.step_label.pack(anchor=tk.W)

        # Step progress bar
        self.progress = ttk.Progressbar(
            header, maximum=5, value=1, mode='determinate')
        self.progress.pack(fill=tk.X, pady=(4, 0))

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X)

        # Content area (swapped per step)
        self.content_frame = ttk.Frame(self, padding=16)
        self.content_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X)

        # Navigation buttons
        nav = ttk.Frame(self, padding=(16, 8))
        nav.pack(fill=tk.X)

        self.btn_cancel = ttk.Button(nav, text="Cancel",
                                     command=self.destroy, width=10)
        self.btn_cancel.pack(side=tk.LEFT)

        self.btn_finish = ttk.Button(nav, text="Add to Personality",
                                     command=self._finish, width=18)
        self.btn_finish.pack(side=tk.RIGHT, padx=(4, 0))
        self.btn_finish.pack_forget()  # hidden until step 5

        self.btn_next = ttk.Button(nav, text="Next >",
                                   command=self._next_step, width=10)
        self.btn_next.pack(side=tk.RIGHT, padx=(4, 0))

        self.btn_prev = ttk.Button(nav, text="< Back",
                                   command=self._prev_step, width=10)
        self.btn_prev.pack(side=tk.RIGHT)

    def _show_step(self, step):
        """Display the content for the given step index."""
        self.current_step = step
        self.step_label.config(
            text=f"Step {step + 1} of 5: {STEP_TITLES[step]}")
        self.progress['value'] = step + 1

        # Clear content area
        for child in self.content_frame.winfo_children():
            child.destroy()

        # Build step content
        builders = [
            self._build_step_source,
            self._build_step_configure,
            self._build_step_frequencies,
            self._build_step_talkgroups,
            self._build_step_review,
        ]
        builders[step](self.content_frame)

        # Update navigation buttons
        self.btn_prev.config(state=tk.NORMAL if step > 0 else tk.DISABLED)
        if step < 4:
            self.btn_next.pack(side=tk.RIGHT, padx=(4, 0))
            self.btn_finish.pack_forget()
        else:
            self.btn_next.pack_forget()
            self.btn_finish.pack(side=tk.RIGHT, padx=(4, 0))

    def _next_step(self):
        """Validate current step and advance."""
        if self.current_step == 0:
            # Source selection - populate fields if database
            if self.source.get() == "database" and self.selected_system:
                sys = self.selected_system
                self.sys_name.set(sys.name[:8])
                self.sys_long_name.set(sys.long_name[:16])
                self.sys_id.set(str(sys.system_id))
                self.sys_wacn.set(str(sys.wacn))
                self.sys_band.set(sys.band.replace("/", "/"))
                self.sys_type.set(sys.system_type)
            elif self.source.get() == "database" and not self.selected_system:
                messagebox.showwarning(
                    "No System Selected",
                    "Select a system from the database or choose "
                    "a different source.",
                    parent=self)
                return

        elif self.current_step == 1:
            # Validate system config
            name = self.sys_name.get().strip()
            if not name:
                messagebox.showwarning(
                    "Missing Name",
                    "System name is required.",
                    parent=self)
                return
            try:
                sid = int(self.sys_id.get().strip())
                if sid < 0 or sid > 65535:
                    raise ValueError("out of range")
            except ValueError:
                messagebox.showwarning(
                    "Invalid System ID",
                    "System ID must be a number 0-65535.",
                    parent=self)
                return
            try:
                wacn = int(self.sys_wacn.get().strip())
                if wacn < 0:
                    raise ValueError("negative")
            except ValueError:
                messagebox.showwarning(
                    "Invalid WACN",
                    "WACN must be a non-negative number.",
                    parent=self)
                return

        elif self.current_step == 2:
            # Save frequency text
            if hasattr(self, '_freq_text_widget'):
                self.freq_text = self._freq_text_widget.get("1.0", tk.END).strip()

        elif self.current_step == 3:
            # Save talkgroup text
            if hasattr(self, '_tg_text_widget'):
                self.tg_text = self._tg_text_widget.get("1.0", tk.END).strip()

        self._show_step(self.current_step + 1)

    def _prev_step(self):
        """Go back one step."""
        if self.current_step > 0:
            self._show_step(self.current_step - 1)

    # ─── Step builders ───────────────────────────────────────────────

    def _build_step_source(self, parent):
        """Step 1: Choose source — database, RadioReference, or manual."""
        ttk.Label(parent, text="How would you like to add the system?",
                  font=("", 10)).pack(anchor=tk.W, pady=(0, 12))

        # Radio buttons for source selection
        sources = [
            ("database", "From built-in database",
             "Select from a list of well-known US P25 systems"),
            ("manual", "Manual entry",
             "Enter all system parameters by hand"),
        ]

        for val, label, desc in sources:
            frame = ttk.Frame(parent)
            frame.pack(fill=tk.X, pady=2)
            rb = ttk.Radiobutton(frame, text=label, value=val,
                                 variable=self.source,
                                 command=self._on_source_changed)
            rb.pack(anchor=tk.W)
            ttk.Label(frame, text=desc, foreground="gray").pack(
                anchor=tk.W, padx=(24, 0))

        # Database search panel (shown when database is selected)
        self._db_frame = ttk.LabelFrame(parent, text="System Database",
                                        padding=8)
        self._db_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        # Search bar
        search_row = ttk.Frame(self._db_frame)
        search_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(search_row, text="Search:").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search_changed)
        search_entry = ttk.Entry(search_row, textvariable=self._search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # System list
        cols = ("name", "location", "band", "type", "sysid")
        self._sys_tree = ttk.Treeview(
            self._db_frame, columns=cols, show="headings",
            height=8, selectmode="browse")
        self._sys_tree.heading("name", text="Name")
        self._sys_tree.heading("location", text="Location")
        self._sys_tree.heading("band", text="Band")
        self._sys_tree.heading("type", text="Type")
        self._sys_tree.heading("sysid", text="SysID")
        self._sys_tree.column("name", width=80, minwidth=60)
        self._sys_tree.column("location", width=200, minwidth=100)
        self._sys_tree.column("band", width=70, minwidth=50)
        self._sys_tree.column("type", width=80, minwidth=60)
        self._sys_tree.column("sysid", width=60, minwidth=40)

        scrollbar = ttk.Scrollbar(self._db_frame, orient=tk.VERTICAL,
                                  command=self._sys_tree.yview)
        self._sys_tree.config(yscrollcommand=scrollbar.set)

        self._sys_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._sys_tree.bind("<<TreeviewSelect>>", self._on_system_selected)
        self._sys_tree.bind("<Double-1>", lambda e: self._next_step())

        # Populate list
        self._populate_system_list()
        self._on_source_changed()

    def _on_source_changed(self):
        """Show/hide database panel based on source selection."""
        if self.source.get() == "database":
            self._db_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        else:
            self._db_frame.pack_forget()
            self.selected_system = None

    def _populate_system_list(self, query=""):
        """Fill the system treeview with matching systems."""
        self._sys_tree.delete(*self._sys_tree.get_children())
        systems = search_systems(query) if query else list_all_systems()
        for sys in systems:
            self._sys_tree.insert("", tk.END, iid=sys.name,
                                  values=(sys.name, sys.location,
                                          sys.band, sys.system_type,
                                          sys.system_id))

    def _on_search_changed(self, *args):
        """Filter system list on search text change."""
        query = self._search_var.get().strip()
        self._populate_system_list(query)

    def _on_system_selected(self, event):
        """Handle system selection in the treeview."""
        sel = self._sys_tree.selection()
        if sel:
            name = sel[0]
            self.selected_system = get_system_by_name(name)

    def _build_step_configure(self, parent):
        """Step 2: Configure system parameters."""
        ttk.Label(parent, text="System Configuration",
                  font=("", 10)).pack(anchor=tk.W, pady=(0, 12))

        grid = ttk.Frame(parent)
        grid.pack(fill=tk.X)

        fields = [
            ("System Name (8 chars):", self.sys_name),
            ("Long Name (16 chars):", self.sys_long_name),
            ("System ID:", self.sys_id),
            ("WACN:", self.sys_wacn),
        ]

        for i, (label, var) in enumerate(fields):
            ttk.Label(grid, text=label).grid(
                row=i, column=0, sticky=tk.W, pady=4, padx=(0, 8))
            entry = ttk.Entry(grid, textvariable=var, width=30)
            entry.grid(row=i, column=1, sticky=tk.W, pady=4)

        # Band selection
        row = len(fields)
        ttk.Label(grid, text="Band:").grid(
            row=row, column=0, sticky=tk.W, pady=4, padx=(0, 8))
        band_combo = ttk.Combobox(
            grid, textvariable=self.sys_band, state="readonly",
            values=["700", "800", "900", "700/800"], width=27)
        band_combo.grid(row=row, column=1, sticky=tk.W, pady=4)

        # System type
        row += 1
        ttk.Label(grid, text="Type:").grid(
            row=row, column=0, sticky=tk.W, pady=4, padx=(0, 8))
        type_combo = ttk.Combobox(
            grid, textvariable=self.sys_type, state="readonly",
            values=["Phase I", "Phase II"], width=27)
        type_combo.grid(row=row, column=1, sticky=tk.W, pady=4)

        # Info about the selected database system
        if self.selected_system:
            info_frame = ttk.LabelFrame(parent, text="Database Info",
                                        padding=8)
            info_frame.pack(fill=tk.X, pady=(16, 0))
            sys = self.selected_system
            ttk.Label(info_frame,
                      text=f"{sys.long_name}\n"
                           f"{sys.location}\n"
                           f"{sys.description}",
                      wraplength=600).pack(anchor=tk.W)

    def _build_step_frequencies(self, parent):
        """Step 3: Frequencies (optional)."""
        ttk.Label(parent,
                  text="Paste trunk frequencies below, or skip this step.\n"
                       "Format: one frequency per line (RX MHz), or "
                       "TX,RX pairs.",
                  font=("", 10), wraplength=600).pack(
                      anchor=tk.W, pady=(0, 8))

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill=tk.X, pady=(0, 4))

        ttk.Button(btn_row, text="Import CSV...",
                   command=self._import_freq_csv, width=14).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Clear",
                   command=lambda: self._freq_text_widget.delete(
                       "1.0", tk.END),
                   width=8).pack(side=tk.LEFT, padx=4)

        count_label = ttk.Label(btn_row, text="")
        count_label.pack(side=tk.RIGHT)

        self._freq_text_widget = tk.Text(parent, height=15, wrap=tk.NONE)
        self._freq_text_widget.pack(fill=tk.BOTH, expand=True)

        if self.freq_text:
            self._freq_text_widget.insert("1.0", self.freq_text)

        def update_count(*args):
            text = self._freq_text_widget.get("1.0", tk.END).strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            count_label.config(text=f"{len(lines)} lines")

        self._freq_text_widget.bind("<KeyRelease>", update_count)
        update_count()

    def _import_freq_csv(self):
        """Load frequencies from a CSV file."""
        path = filedialog.askopenfilename(
            title="Open Frequency CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self)
        if not path:
            return
        try:
            with open(path, newline='', encoding='utf-8-sig') as f:
                content = f.read()
            self._freq_text_widget.delete("1.0", tk.END)
            self._freq_text_widget.insert("1.0", content)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read file: {e}",
                                 parent=self)

    def _build_step_talkgroups(self, parent):
        """Step 4: Talkgroups (optional)."""
        ttk.Label(parent,
                  text="Paste talkgroups below, or skip this step.\n"
                       "Format: ID,ShortName,LongName (one per line)",
                  font=("", 10), wraplength=600).pack(
                      anchor=tk.W, pady=(0, 8))

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill=tk.X, pady=(0, 4))

        ttk.Button(btn_row, text="Import CSV...",
                   command=self._import_tg_csv, width=14).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Clear",
                   command=lambda: self._tg_text_widget.delete(
                       "1.0", tk.END),
                   width=8).pack(side=tk.LEFT, padx=4)

        count_label = ttk.Label(btn_row, text="")
        count_label.pack(side=tk.RIGHT)

        self._tg_text_widget = tk.Text(parent, height=15, wrap=tk.NONE)
        self._tg_text_widget.pack(fill=tk.BOTH, expand=True)

        if self.tg_text:
            self._tg_text_widget.insert("1.0", self.tg_text)

        def update_count(*args):
            text = self._tg_text_widget.get("1.0", tk.END).strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            count_label.config(text=f"{len(lines)} lines")

        self._tg_text_widget.bind("<KeyRelease>", update_count)
        update_count()

    def _import_tg_csv(self):
        """Load talkgroups from a CSV file."""
        path = filedialog.askopenfilename(
            title="Open Talkgroup CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self)
        if not path:
            return
        try:
            with open(path, newline='', encoding='utf-8-sig') as f:
                content = f.read()
            self._tg_text_widget.delete("1.0", tk.END)
            self._tg_text_widget.insert("1.0", content)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read file: {e}",
                                 parent=self)

    def _build_step_review(self, parent):
        """Step 5: Review & Add."""
        ttk.Label(parent, text="Review System Configuration",
                  font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 12))

        name = self.sys_name.get().strip()[:8]
        long_name = self.sys_long_name.get().strip()[:16] or name
        sys_id = self.sys_id.get().strip()
        wacn = self.sys_wacn.get().strip()
        band = self.sys_band.get()
        sys_type = self.sys_type.get()

        # Parse frequencies
        freqs = self._parse_freqs()
        tgs = self._parse_talkgroups()

        # IDEN template
        iden_key = f"{band.split('/')[0] if '/' in band else band}-" \
                   f"{'TDMA' if 'II' in sys_type else 'FDMA'}"

        info_lines = [
            f"System Name:    {name}",
            f"Long Name:      {long_name}",
            f"System ID:      {sys_id}",
            f"WACN:           {wacn}",
            f"Band:           {band}",
            f"Type:           {sys_type}",
            f"IDEN Template:  {iden_key}",
            "",
            f"Frequencies:    {len(freqs) if freqs else 'None (empty trunk set)'}",
            f"Talkgroups:     {len(tgs) if tgs else 'None (empty group set)'}",
        ]

        # What will be created
        info_lines.extend([
            "",
            "The following will be created:",
            f"  - P25 Trunked System: {name} / {long_name}",
            f"  - Trunk Set: {name} "
            f"({len(freqs)} frequencies)" if freqs else
            f"  - Trunk Set: {name} (empty)",
            f"  - Group Set: {name} "
            f"({len(tgs)} talkgroups)" if tgs else
            f"  - Group Set: {name} (empty)",
            f"  - IDEN Set: {iden_key[:5]} (standard {band} template)",
            f"  - WAN entry: {name}",
        ])

        text = tk.Text(parent, height=18, wrap=tk.WORD, state=tk.NORMAL)
        text.insert("1.0", "\n".join(info_lines))
        text.config(state=tk.DISABLED)
        text.pack(fill=tk.BOTH, expand=True)

    def _parse_freqs(self):
        """Parse pasted frequency text into (tx, rx) tuples."""
        if not self.freq_text:
            return []
        from ..iden_library import calculate_tx_freq
        freqs = []
        for line in self.freq_text.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.replace(";", ",").split(",")
            try:
                if len(parts) >= 2:
                    tx = float(parts[0].strip())
                    rx = float(parts[1].strip())
                    freqs.append((tx, rx))
                else:
                    rx = float(parts[0].strip())
                    tx = calculate_tx_freq(rx)
                    freqs.append((tx, rx))
            except (ValueError, IndexError):
                continue
        return freqs

    def _parse_talkgroups(self):
        """Parse pasted talkgroup text into (id, short, long) tuples."""
        if not self.tg_text:
            return []
        tgs = []
        for line in self.tg_text.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            try:
                gid = int(parts[0].strip())
                sn = parts[1].strip()[:8] if len(parts) > 1 else str(gid)
                ln = parts[2].strip()[:16] if len(parts) > 2 else sn
                tgs.append((gid, sn, ln))
            except (ValueError, IndexError):
                continue
        return tgs

    def _finish(self):
        """Add the system to the personality and close."""
        if not self.app.prs:
            messagebox.showwarning("Warning", "No file loaded.", parent=self)
            return

        name = self.sys_name.get().strip()[:8]
        long_name = self.sys_long_name.get().strip()[:16] or name
        sys_id = int(self.sys_id.get().strip())
        wacn = int(self.sys_wacn.get().strip())
        band = self.sys_band.get()
        sys_type = self.sys_type.get()

        # Save undo state
        self.app.save_undo_snapshot("Add P25 System via Wizard")

        try:
            prs = self.app.prs

            # Parse data
            freqs = self._parse_freqs()
            tgs = self._parse_talkgroups()

            # Build sets
            trunk_set = make_trunk_set(name, freqs) if freqs else None
            group_set = None
            if tgs:
                groups = [make_p25_group(gid, sn, ln)
                          for gid, sn, ln in tgs]
                from ..record_types import P25GroupSet
                group_set = P25GroupSet(name=name[:8], groups=groups)

            # Build IDEN set from standard template
            iden_key = f"{band.split('/')[0] if '/' in band else band}-" \
                       f"{'TDMA' if 'II' in sys_type else 'FDMA'}"
            template = get_template(iden_key)
            iden_set = None
            iden_name = iden_key[:5]
            if template:
                iden_set = make_iden_set(
                    get_default_name(iden_key), template.entries)
                iden_name = get_default_name(iden_key)

            # Determine WAN config from IDEN template
            wan_base = 851_006_250
            wan_spacing = 12500
            if template and template.entries:
                first = template.entries[0]
                wan_base = first.get('base_freq_hz', wan_base)
                wan_spacing = first.get('chan_spacing_hz', wan_spacing)

            # Build system config
            config = P25TrkSystemConfig(
                system_name=name,
                long_name=long_name,
                trunk_set_name=name if trunk_set else "",
                group_set_name=name if group_set else "",
                wan_name=name,
                system_id=sys_id,
                wacn=wacn,
                iden_set_name=iden_name if iden_set else "",
                wan_base_freq_hz=wan_base,
                wan_chan_spacing_hz=wan_spacing,
            )

            add_p25_trunked_system(prs, config,
                                   trunk_set=trunk_set,
                                   group_set=group_set,
                                   iden_set=iden_set)

            # Validate
            issues = validate_prs(prs)
            errors = [(s, m) for s, m in issues if s == ERROR]

            self.app.modified = True
            self.app._update_title()
            self.app.personality_view.refresh()

            freq_str = f"{len(freqs)} freqs" if freqs else "no freqs"
            tg_str = f"{len(tgs)} TGs" if tgs else "no TGs"
            log_action("wizard_add",
                       f"Added P25 system '{name}' "
                       f"(SysID {sys_id}, {freq_str}, {tg_str})")

            if errors:
                messagebox.showwarning(
                    "System Added (with warnings)",
                    f"P25 system '{name}' added successfully.\n\n"
                    f"Validation found {len(errors)} error(s):\n" +
                    "\n".join(m for _, m in errors[:5]),
                    parent=self)
            else:
                messagebox.showinfo(
                    "System Added",
                    f"P25 system '{name}' added successfully.\n"
                    f"  System ID: {sys_id}\n"
                    f"  {freq_str}, {tg_str}",
                    parent=self)

            self.destroy()

        except Exception as e:
            log_error("wizard_add", str(e))
            messagebox.showerror(
                "Error",
                f"Failed to add system: {e}",
                parent=self)


class SystemDatabaseDialog(tk.Toplevel):
    """Standalone dialog showing the P25 system database.

    Accessed from Tools > P25 System Database. Shows a searchable
    table of all known systems with an "Add to Personality" button.
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("P25 System Database")
        self.geometry("800x500")
        self.minsize(650, 400)
        self.transient(parent)

        self._build_ui()
        self._populate()

        self.bind("<Escape>", lambda e: self.destroy())

    def _build_ui(self):
        """Build the database browser UI."""
        # Search bar
        top = ttk.Frame(self, padding=(8, 8, 8, 4))
        top.pack(fill=tk.X)

        ttk.Label(top, text="Search:").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        search_entry = ttk.Entry(top, textvariable=self._search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=(4, 8))
        search_entry.focus_set()

        self._count_label = ttk.Label(top, text="")
        self._count_label.pack(side=tk.LEFT)

        # Treeview
        tree_frame = ttk.Frame(self, padding=(8, 0, 8, 4))
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("name", "long_name", "location", "band", "type",
                "sysid", "wacn")
        self._tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings",
            selectmode="browse")
        self._tree.heading("name", text="Name")
        self._tree.heading("long_name", text="Full Name")
        self._tree.heading("location", text="Location")
        self._tree.heading("band", text="Band")
        self._tree.heading("type", text="Type")
        self._tree.heading("sysid", text="SysID")
        self._tree.heading("wacn", text="WACN")
        self._tree.column("name", width=70, minwidth=50)
        self._tree.column("long_name", width=200, minwidth=100)
        self._tree.column("location", width=150, minwidth=80)
        self._tree.column("band", width=70, minwidth=50)
        self._tree.column("type", width=80, minwidth=60)
        self._tree.column("sysid", width=60, minwidth=40)
        self._tree.column("wacn", width=80, minwidth=50)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                                  command=self._tree.yview)
        self._tree.config(yscrollcommand=scrollbar.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._tree.bind("<Double-1>", lambda e: self._add_system())

        # Detail panel
        detail = ttk.LabelFrame(self, text="System Details", padding=8)
        detail.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._detail_label = ttk.Label(detail, text="Select a system above",
                                       wraplength=750)
        self._detail_label.pack(anchor=tk.W)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Buttons
        btn_frame = ttk.Frame(self, padding=8)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="Add to Personality",
                   command=self._add_system, width=20).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Open Wizard...",
                   command=self._open_wizard, width=14).pack(
                       side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Close",
                   command=self.destroy, width=10).pack(side=tk.LEFT)

    def _populate(self, query=""):
        """Fill treeview with systems."""
        self._tree.delete(*self._tree.get_children())
        systems = search_systems(query) if query else list_all_systems()
        for sys in systems:
            self._tree.insert("", tk.END, iid=sys.name,
                              values=(sys.name, sys.long_name,
                                      sys.location, sys.band,
                                      sys.system_type, sys.system_id,
                                      sys.wacn))
        self._count_label.config(text=f"{len(systems)} systems")

    def _on_search(self, *args):
        query = self._search_var.get().strip()
        self._populate(query)

    def _on_select(self, event):
        sel = self._tree.selection()
        if sel:
            sys = get_system_by_name(sel[0])
            if sys:
                self._detail_label.config(
                    text=f"{sys.long_name} ({sys.name})\n"
                         f"Location: {sys.location}\n"
                         f"Band: {sys.band} | Type: {sys.system_type}\n"
                         f"System ID: {sys.system_id} | WACN: {sys.wacn}\n"
                         f"{sys.description}")

    def _add_system(self):
        """Add the selected system to the current personality."""
        if not self.app.prs:
            messagebox.showwarning("Warning", "No file loaded.", parent=self)
            return

        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a system first.",
                                   parent=self)
            return

        sys = get_system_by_name(sel[0])
        if not sys:
            return

        if not messagebox.askyesno(
                "Confirm",
                f"Add '{sys.long_name}' ({sys.name}) to the personality?\n\n"
                f"This will create:\n"
                f"  - System header + config\n"
                f"  - Empty trunk set\n"
                f"  - Empty group set\n"
                f"  - Standard IDEN set ({sys.band})\n"
                f"  - WAN entry",
                parent=self):
            return

        self.app.save_undo_snapshot("Add System from Database")

        try:
            _add_system_from_database(self.app.prs, sys)
            self.app.modified = True
            self.app._update_title()
            self.app.personality_view.refresh()
            log_action("db_add",
                       f"Added '{sys.name}' from system database")
            messagebox.showinfo(
                "System Added",
                f"P25 system '{sys.name}' added.\n"
                f"Add frequencies and talkgroups to complete setup.",
                parent=self)
        except Exception as e:
            log_error("db_add", str(e))
            messagebox.showerror("Error", f"Failed: {e}", parent=self)

    def _open_wizard(self):
        """Open the full wizard dialog."""
        sel = self._tree.selection()
        wizard = SystemWizard(self, self.app)
        if sel:
            sys = get_system_by_name(sel[0])
            if sys:
                wizard.selected_system = sys
                wizard.source.set("database")
                wizard.sys_name.set(sys.name[:8])
                wizard.sys_long_name.set(sys.long_name[:16])
                wizard.sys_id.set(str(sys.system_id))
                wizard.sys_wacn.set(str(sys.wacn))
                wizard.sys_band.set(sys.band)
                wizard.sys_type.set(sys.system_type)
        wizard.wait_window()


def _add_system_from_database(prs, sys):
    """Add a P25 system from the database to a PRS file.

    Creates system header, config, empty trunk set, empty group set,
    and standard IDEN set based on the system's band/type.

    Args:
        prs: PRSFile object
        sys: P25System from the database
    """
    name = sys.name[:8]
    long_name = sys.long_name[:16]

    # Build IDEN set from standard template
    iden_key = get_iden_template_key(sys)
    template = get_template(iden_key)
    iden_set = None
    iden_name = get_default_iden_name(sys)
    wan_base = 851_006_250
    wan_spacing = 12500

    if template:
        iden_set = make_iden_set(iden_name, template.entries)
        if template.entries:
            wan_base = template.entries[0].get('base_freq_hz', wan_base)
            wan_spacing = template.entries[0].get(
                'chan_spacing_hz', wan_spacing)

    config = P25TrkSystemConfig(
        system_name=name,
        long_name=long_name,
        trunk_set_name="",
        group_set_name="",
        wan_name=name,
        system_id=sys.system_id,
        wacn=sys.wacn,
        iden_set_name=iden_name if iden_set else "",
        wan_base_freq_hz=wan_base,
        wan_chan_spacing_hz=wan_spacing,
    )

    add_p25_trunked_system(prs, config, iden_set=iden_set)
