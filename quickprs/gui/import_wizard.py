"""Unified import wizard for adding channels/systems from any source.

Provides a tabbed dialog that handles:
  - From File: drag-and-drop CSV/text, auto-detect format, preview, import
  - From Template: checkbox list of built-in templates, multi-select, one-click add
  - From Database: searchable P25 system database, select system, add to personality
  - From Clipboard: paste talkgroups/frequencies/channel data, auto-detect, preview, import
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ..templates import get_template_names, get_template_channels
from ..system_database import search_systems, list_all_systems
from ..scanner_import import (
    detect_scanner_format, import_scanner_csv,
    import_dsd_freqs, import_sdrtrunk_tgs,
)
from ..radioreference import (
    parse_pasted_talkgroups, parse_pasted_frequencies,
    parse_pasted_conv_channels,
)


class ImportWizard(tk.Toplevel):
    """Unified import wizard for adding channels/systems from any source."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Import Wizard")
        self.geometry("850x600")
        self.minsize(700, 500)
        self.transient(parent)

        # Preview data (set by each tab's preview action)
        self._preview_data = None
        self._preview_type = None  # 'channels', 'talkgroups', 'templates'

        self._build_ui()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _build_ui(self):
        """Build the tabbed wizard interface."""
        # Notebook with tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))

        # Build each tab
        self._build_file_tab()
        self._build_template_tab()
        self._build_database_tab()
        self._build_clipboard_tab()

        # Bottom bar with status + close button
        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill=tk.X, side=tk.BOTTOM)

        self._status_label = ttk.Label(bottom, text="Select a source and preview before importing.")
        self._status_label.pack(side=tk.LEFT)

        ttk.Button(bottom, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    # ─── From File tab ────────────────────────────────────────────────

    def _build_file_tab(self):
        """Build the From File import tab."""
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="From File")

        # File selection
        top = ttk.Frame(frame)
        top.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(top, text="CSV/Text file:").pack(side=tk.LEFT)
        self._file_path_var = tk.StringVar()
        self._file_entry = ttk.Entry(top, textvariable=self._file_path_var, width=50)
        self._file_entry.pack(side=tk.LEFT, padx=(8, 4), fill=tk.X, expand=True)
        ttk.Button(top, text="Browse...", command=self._browse_file).pack(side=tk.LEFT, padx=2)

        # Format detection row
        fmt_row = ttk.Frame(frame)
        fmt_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(fmt_row, text="Format:").pack(side=tk.LEFT)
        self._file_format_var = tk.StringVar(value="auto")
        for fmt in ("auto", "chirp", "uniden", "sdrtrunk", "dsd+", "quickprs", "freq_list"):
            ttk.Radiobutton(fmt_row, text=fmt.upper(), variable=self._file_format_var,
                            value=fmt).pack(side=tk.LEFT, padx=3)

        # Action buttons
        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(btn_row, text="Preview", command=self._preview_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Import", command=self._import_file).pack(side=tk.LEFT, padx=2)
        self._file_status = ttk.Label(btn_row, text="")
        self._file_status.pack(side=tk.LEFT, padx=8)

        # Preview area
        preview_frame = ttk.LabelFrame(frame, text="Preview", padding=4)
        preview_frame.pack(fill=tk.BOTH, expand=True)

        self._file_preview = tk.Text(preview_frame, wrap=tk.NONE, state=tk.DISABLED,
                                     font=("Consolas", 9), height=15)
        vsb = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL,
                            command=self._file_preview.yview)
        hsb = ttk.Scrollbar(preview_frame, orient=tk.HORIZONTAL,
                            command=self._file_preview.xview)
        self._file_preview.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._file_preview.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        preview_frame.grid_rowconfigure(0, weight=1)
        preview_frame.grid_columnconfigure(0, weight=1)

    def _browse_file(self):
        """Open file browser for CSV/text import."""
        path = filedialog.askopenfilename(
            title="Select Import File",
            filetypes=[
                ("Supported Files", "*.csv *.txt *.tsv"),
                ("CSV Files", "*.csv"),
                ("Text Files", "*.txt"),
                ("All Files", "*.*"),
            ],
            parent=self,
        )
        if path:
            self._file_path_var.set(path)
            # Auto-detect format
            fmt = detect_scanner_format(path)
            if fmt != 'unknown':
                self._file_format_var.set(fmt)
                self._file_status.config(text=f"Detected: {fmt.upper()}")
            else:
                self._file_status.config(text="Format: unknown (select manually)")

    def _preview_file(self):
        """Preview the contents of the selected file."""
        path = self._file_path_var.get().strip()
        if not path:
            messagebox.showwarning("No File", "Please select a file first.", parent=self)
            return

        fmt = self._file_format_var.get()
        try:
            channels, talkgroups = self._load_file(path, fmt)
        except Exception as e:
            self._file_status.config(text=f"Error: {e}")
            return

        # Format preview
        lines = []
        if channels:
            lines.append(f"Channels: {len(channels)}")
            lines.append("")
            lines.append(f"{'#':<4} {'Name':<10} {'TX Freq':<12} {'RX Freq':<12} "
                         f"{'TX Tone':<10} {'RX Tone':<10} {'Long Name':<18}")
            lines.append("-" * 80)
            for i, ch in enumerate(channels[:50]):
                lines.append(
                    f"{i+1:<4} {ch.get('short_name',''):<10} "
                    f"{ch.get('tx_freq',0):<12.4f} "
                    f"{ch.get('rx_freq',0):<12.4f} "
                    f"{ch.get('tx_tone',''):<10} "
                    f"{ch.get('rx_tone',''):<10} "
                    f"{ch.get('long_name',''):<18}")
            if len(channels) > 50:
                lines.append(f"... and {len(channels) - 50} more")
            self._preview_data = channels
            self._preview_type = 'channels'

        elif talkgroups:
            lines.append(f"Talkgroups: {len(talkgroups)}")
            lines.append("")
            lines.append(f"{'#':<4} {'ID':<8} {'Name':<10} {'Long Name':<18}")
            lines.append("-" * 44)
            for i, tg in enumerate(talkgroups[:50]):
                lines.append(
                    f"{i+1:<4} {tg.get('group_id',0):<8} "
                    f"{tg.get('short_name',''):<10} "
                    f"{tg.get('long_name',''):<18}")
            if len(talkgroups) > 50:
                lines.append(f"... and {len(talkgroups) - 50} more")
            self._preview_data = talkgroups
            self._preview_type = 'talkgroups'

        else:
            lines.append("No data found in file.")
            self._preview_data = None
            self._preview_type = None

        self._file_preview.config(state=tk.NORMAL)
        self._file_preview.delete("1.0", tk.END)
        self._file_preview.insert(tk.END, "\n".join(lines))
        self._file_preview.config(state=tk.DISABLED)

        count = len(channels or talkgroups or [])
        data_type = "channels" if channels else "talkgroups" if talkgroups else "items"
        self._file_status.config(text=f"Preview: {count} {data_type}")

    def _load_file(self, path, fmt):
        """Load a file and return (channels, talkgroups).

        Returns:
            tuple of (channels_list, talkgroups_list) — one will be empty
        """
        from pathlib import Path as P
        from ..csv_import import import_csv as import_qprs_csv

        channels = []
        talkgroups = []

        if fmt == 'auto':
            fmt = detect_scanner_format(path)

        if fmt in ('chirp', 'uniden', 'sdrtrunk'):
            channels = import_scanner_csv(path, fmt=fmt)
        elif fmt == 'dsd+':
            channels = import_dsd_freqs(path)
        elif fmt == 'quickprs':
            data_type, objects = import_qprs_csv(path)
            if data_type == 'groups':
                for gs in objects:
                    for g in gs.groups:
                        talkgroups.append({
                            'group_id': g.group_id,
                            'short_name': g.group_name,
                            'long_name': g.long_name,
                        })
            elif data_type == 'conv':
                for cs in objects:
                    for ch in cs.channels:
                        channels.append({
                            'short_name': ch.short_name,
                            'tx_freq': ch.tx_freq,
                            'rx_freq': ch.rx_freq,
                            'tx_tone': ch.tx_tone,
                            'rx_tone': ch.rx_tone,
                            'long_name': ch.long_name,
                            'system_name': '',
                        })
        elif fmt == 'freq_list':
            channels = import_dsd_freqs(path)
        else:
            # Try SDRTrunk talkgroup format
            try:
                talkgroups = import_sdrtrunk_tgs(path)
                if talkgroups:
                    return channels, talkgroups
            except Exception:
                pass
            # Fall back to scanner import with auto-detect
            try:
                channels = import_scanner_csv(path, fmt='auto')
            except ValueError:
                # Try as a frequency list
                try:
                    channels = import_dsd_freqs(path)
                except Exception:
                    raise ValueError(
                        "Cannot detect file format. "
                        "Select a format manually.")

        return channels, talkgroups

    def _import_file(self):
        """Import the previewed file data into the current personality."""
        if not self.app.prs:
            messagebox.showwarning("No File", "Load a PRS file first.", parent=self)
            return

        path = self._file_path_var.get().strip()
        if not path:
            messagebox.showwarning("No File", "Please select a file first.", parent=self)
            return

        fmt = self._file_format_var.get()
        try:
            channels, talkgroups = self._load_file(path, fmt)
        except Exception as e:
            messagebox.showerror("Import Error", str(e), parent=self)
            return

        if not channels and not talkgroups:
            messagebox.showinfo("No Data", "No importable data found in file.", parent=self)
            return

        # Ask for set name
        from pathlib import Path as P
        default_name = P(path).stem[:8].upper()
        set_name = _ask_set_name(self, default_name)
        if not set_name:
            return

        self.app.save_undo_snapshot(f"Import from {P(path).name}")
        try:
            if channels:
                self._inject_channels(set_name, channels)
            elif talkgroups:
                self._inject_talkgroups(set_name, talkgroups)

            self.app.personality_view.refresh()
            self.app.mark_modified()
            self._file_status.config(text="Imported successfully!")
            self._status_label.config(text=f"Imported into set '{set_name}'")
        except Exception as e:
            messagebox.showerror("Import Error", str(e), parent=self)

    # ─── From Template tab ────────────────────────────────────────────

    def _build_template_tab(self):
        """Build the From Template tab with checkboxes."""
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="From Template")

        ttk.Label(frame, text="Select templates to add as conventional channel sets:").pack(
            anchor=tk.W, pady=(0, 8))

        # Template checkboxes with descriptions
        check_frame = ttk.Frame(frame)
        check_frame.pack(fill=tk.BOTH, expand=True)

        # Scrollable canvas for checkboxes
        canvas = tk.Canvas(check_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(check_frame, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._template_vars = {}
        template_info = {
            'murs': ("MURS", "5 channels, license-free VHF (Part 95J)"),
            'gmrs': ("GMRS", "22 channels, licensed UHF family/business (Part 95E)"),
            'frs': ("FRS", "22 channels, license-free UHF (Part 95B)"),
            'marine': ("Marine VHF", "15 channels, maritime communications"),
            'noaa': ("NOAA Weather", "7 channels, NWS weather broadcasts (RX only)"),
            'weather': None,  # alias for noaa, skip
            'interop': ("Interoperability", "20 channels, national public safety interop"),
            'public_safety': ("Public Safety", "10 channels, fire/EMS/LE simplex"),
        }

        for name in get_template_names():
            info = template_info.get(name)
            if info is None:
                continue  # skip aliases

            label, desc = info
            var = tk.BooleanVar(value=False)
            self._template_vars[name] = var

            row = ttk.Frame(inner)
            row.pack(fill=tk.X, pady=2, padx=4)
            cb = ttk.Checkbutton(row, text=label, variable=var)
            cb.pack(side=tk.LEFT)

            # Channel count
            try:
                count = len(get_template_channels(name))
                detail = f"  ({count} channels) {desc}"
            except Exception:
                detail = f"  {desc}"
            ttk.Label(row, text=detail, foreground="gray").pack(side=tk.LEFT, padx=8)

        # Preview + import buttons
        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(btn_row, text="Select All", command=self._select_all_templates).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Clear All", command=self._clear_all_templates).pack(
            side=tk.LEFT, padx=2)

        ttk.Separator(btn_row, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(btn_row, text="Preview", command=self._preview_templates).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Import Selected", command=self._import_templates).pack(
            side=tk.LEFT, padx=2)

        self._template_status = ttk.Label(btn_row, text="")
        self._template_status.pack(side=tk.LEFT, padx=8)

        # Preview area
        preview_frame = ttk.LabelFrame(frame, text="Preview", padding=4)
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        self._template_preview = tk.Text(preview_frame, wrap=tk.NONE, state=tk.DISABLED,
                                         font=("Consolas", 9), height=8)
        vsb = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL,
                            command=self._template_preview.yview)
        self._template_preview.configure(yscrollcommand=vsb.set)
        self._template_preview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _select_all_templates(self):
        for var in self._template_vars.values():
            var.set(True)

    def _clear_all_templates(self):
        for var in self._template_vars.values():
            var.set(False)

    def _get_selected_templates(self):
        """Return list of selected template names."""
        return [name for name, var in self._template_vars.items() if var.get()]

    def _preview_templates(self):
        """Preview selected templates."""
        selected = self._get_selected_templates()
        if not selected:
            messagebox.showinfo("No Selection", "Select at least one template.", parent=self)
            return

        lines = []
        total = 0
        for name in selected:
            channels = get_template_channels(name)
            total += len(channels)
            lines.append(f"=== {name.upper()} ({len(channels)} channels) ===")
            for ch in channels:
                freq = ch.get('tx_freq', 0)
                sname = ch.get('short_name', '')
                lname = ch.get('long_name', '')
                lines.append(f"  {sname:<10} {freq:<12.4f} {lname}")
            lines.append("")

        lines.append(f"Total: {total} channels across {len(selected)} template(s)")

        self._template_preview.config(state=tk.NORMAL)
        self._template_preview.delete("1.0", tk.END)
        self._template_preview.insert(tk.END, "\n".join(lines))
        self._template_preview.config(state=tk.DISABLED)

        self._template_status.config(text=f"{len(selected)} templates, {total} channels")

    def _import_templates(self):
        """Import selected templates as conv sets."""
        if not self.app.prs:
            messagebox.showwarning("No File", "Load a PRS file first.", parent=self)
            return

        selected = self._get_selected_templates()
        if not selected:
            messagebox.showinfo("No Selection", "Select at least one template.", parent=self)
            return

        self.app.save_undo_snapshot(f"Import {len(selected)} templates")

        total_channels = 0
        imported = []
        for name in selected:
            channels = get_template_channels(name)
            set_name = name[:8].upper()

            channels_data = []
            for ch in channels:
                channels_data.append({
                    'short_name': ch.get('short_name', '')[:8],
                    'tx_freq': ch.get('tx_freq', 0),
                    'rx_freq': ch.get('rx_freq', ch.get('tx_freq', 0)),
                    'tx_tone': ch.get('tx_tone', ''),
                    'rx_tone': ch.get('rx_tone', ''),
                    'long_name': ch.get('long_name', '')[:16],
                })

            try:
                self._inject_channels(set_name, channels_data)
                total_channels += len(channels_data)
                imported.append(name)
            except Exception as e:
                messagebox.showwarning("Import Warning",
                                       f"Failed to import {name}: {e}", parent=self)

        self.app.personality_view.refresh()
        self.app.mark_modified()
        self._template_status.config(
            text=f"Imported {total_channels} channels from {len(imported)} templates")
        self._status_label.config(
            text=f"Templates imported: {', '.join(imported)}")

    # ─── From Database tab ────────────────────────────────────────────

    def _build_database_tab(self):
        """Build the From Database tab with searchable system list."""
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="From Database")

        # Search bar
        search_row = ttk.Frame(frame)
        search_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(search_row, text="Search:").pack(side=tk.LEFT)
        self._db_search_var = tk.StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self._db_search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=(8, 4))
        search_entry.bind('<Return>', lambda e: self._search_database())
        ttk.Button(search_row, text="Search", command=self._search_database).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(search_row, text="Show All", command=self._show_all_systems).pack(
            side=tk.LEFT, padx=2)

        # Results tree
        cols = ("name", "long_name", "location", "band", "type", "sysid")
        self._db_tree = ttk.Treeview(frame, columns=cols, show="headings", height=12)
        self._db_tree.heading("name", text="Name")
        self._db_tree.heading("long_name", text="Full Name")
        self._db_tree.heading("location", text="Location")
        self._db_tree.heading("band", text="Band")
        self._db_tree.heading("type", text="Type")
        self._db_tree.heading("sysid", text="SysID")

        self._db_tree.column("name", width=80, minwidth=60)
        self._db_tree.column("long_name", width=250, minwidth=150)
        self._db_tree.column("location", width=180, minwidth=100)
        self._db_tree.column("band", width=80, minwidth=60)
        self._db_tree.column("type", width=80, minwidth=60)
        self._db_tree.column("sysid", width=60, minwidth=50)

        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._db_tree.yview)
        self._db_tree.configure(yscrollcommand=vsb.set)
        self._db_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._db_tree.bind('<<TreeviewSelect>>', self._on_db_select)

        # Bottom area with details and import
        bottom = ttk.Frame(frame)
        bottom.pack(fill=tk.X, pady=(8, 0))

        self._db_detail = ttk.Label(bottom, text="Select a system from the list above.")
        self._db_detail.pack(side=tk.LEFT)

        ttk.Button(bottom, text="Add to Personality",
                   command=self._import_from_database).pack(side=tk.RIGHT, padx=2)

        # Show all on open
        self._show_all_systems()

    def _show_all_systems(self):
        """Populate the tree with all known systems."""
        self._populate_db_tree(list_all_systems())

    def _search_database(self):
        """Search systems and update the tree."""
        query = self._db_search_var.get().strip()
        if not query:
            self._show_all_systems()
            return
        results = search_systems(query)
        self._populate_db_tree(results)

    def _populate_db_tree(self, systems):
        """Fill the treeview with system entries."""
        self._db_tree.delete(*self._db_tree.get_children())
        for sys in systems:
            self._db_tree.insert("", tk.END, iid=sys.name, values=(
                sys.name,
                sys.long_name,
                sys.location,
                sys.band,
                sys.system_type,
                sys.system_id,
            ))

    def _on_db_select(self, event):
        """Show details for the selected system."""
        selection = self._db_tree.selection()
        if not selection:
            return
        name = selection[0]
        from ..system_database import get_system_by_name
        sys = get_system_by_name(name)
        if sys:
            self._db_detail.config(
                text=f"{sys.long_name} | {sys.location} | "
                     f"SysID: {sys.system_id} | WACN: {sys.wacn} | "
                     f"{sys.band} MHz {sys.system_type} | {sys.description}")

    def _import_from_database(self):
        """Add the selected system to the current personality."""
        if not self.app.prs:
            messagebox.showwarning("No File", "Load a PRS file first.", parent=self)
            return

        selection = self._db_tree.selection()
        if not selection:
            messagebox.showinfo("No Selection", "Select a system first.", parent=self)
            return

        name = selection[0]
        from ..system_database import get_system_by_name, get_iden_template_key
        sys = get_system_by_name(name)
        if not sys:
            return

        self.app.save_undo_snapshot(f"Add system {sys.name}")

        try:
            from ..injector import (
                add_p25_trunked_system, make_group_set, make_trunk_set,
                make_iden_set, add_group_set, add_trunk_set, add_iden_set,
            )
            from ..record_types import P25TrkSystemConfig, build_sys_flags
            from ..iden_library import (
                get_template, get_default_name, find_matching_iden_set,
            )

            # Create an empty P25 system with the database info
            config = P25TrkSystemConfig(
                short_name=sys.name[:8],
                long_name=sys.long_name[:16],
                sys_id=sys.system_id,
                wacn=sys.wacn,
                flags=build_sys_flags(),
            )

            # Add empty group and trunk sets
            group_set = make_group_set(sys.name[:8], [])
            trunk_set = make_trunk_set(sys.name[:8], [])

            # Auto-select IDEN template
            iden_key = get_iden_template_key(sys)
            existing_iden = find_matching_iden_set(self.app.prs, iden_key)
            iden_set = None
            if not existing_iden:
                template = get_template(iden_key)
                if template:
                    iden_name = get_default_name(iden_key)
                    iden_set = make_iden_set(iden_name, template)

            add_p25_trunked_system(
                self.app.prs, config,
                trunk_set=trunk_set,
                group_set=group_set,
                iden_set=iden_set,
            )

            self.app.personality_view.refresh()
            self.app.mark_modified()
            self._db_detail.config(text=f"Added {sys.name} to personality!")
            self._status_label.config(text=f"System '{sys.name}' added successfully.")
        except Exception as e:
            messagebox.showerror("Import Error", str(e), parent=self)

    # ─── From Clipboard tab ──────────────────────────────────────────

    def _build_clipboard_tab(self):
        """Build the From Clipboard tab."""
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="From Clipboard")

        # Instructions
        ttk.Label(frame,
                  text="Paste talkgroups, frequencies, or channel data below.\n"
                       "Supports RadioReference page copy, tab-separated tables, "
                       "and plain frequency lists.",
                  wraplength=750, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 8))

        # Text area for pasting
        paste_frame = ttk.Frame(frame)
        paste_frame.pack(fill=tk.BOTH, expand=True)

        self._clip_text = tk.Text(paste_frame, wrap=tk.NONE,
                                  font=("Consolas", 9), height=10)
        vsb = ttk.Scrollbar(paste_frame, orient=tk.VERTICAL,
                            command=self._clip_text.yview)
        hsb = ttk.Scrollbar(paste_frame, orient=tk.HORIZONTAL,
                            command=self._clip_text.xview)
        self._clip_text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._clip_text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        paste_frame.grid_rowconfigure(0, weight=1)
        paste_frame.grid_columnconfigure(0, weight=1)

        # Actions
        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=(8, 4))

        ttk.Button(btn_row, text="Paste from Clipboard",
                   command=self._paste_clipboard).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Detect & Preview",
                   command=self._preview_clipboard).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Import",
                   command=self._import_clipboard).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Clear",
                   command=lambda: self._clip_text.delete("1.0", tk.END)).pack(
            side=tk.LEFT, padx=2)

        self._clip_status = ttk.Label(btn_row, text="")
        self._clip_status.pack(side=tk.LEFT, padx=8)

        # Preview area
        preview_frame = ttk.LabelFrame(frame, text="Detected Data", padding=4)
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        self._clip_preview = tk.Text(preview_frame, wrap=tk.NONE, state=tk.DISABLED,
                                     font=("Consolas", 9), height=8)
        vsb2 = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL,
                             command=self._clip_preview.yview)
        self._clip_preview.configure(yscrollcommand=vsb2.set)
        self._clip_preview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb2.pack(side=tk.RIGHT, fill=tk.Y)

        # State for detected clipboard data
        self._clip_data = None
        self._clip_data_type = None

    def _paste_clipboard(self):
        """Paste text from the system clipboard."""
        try:
            text = self.clipboard_get()
            self._clip_text.delete("1.0", tk.END)
            self._clip_text.insert("1.0", text)
            self._clip_status.config(text=f"Pasted {len(text)} characters")
        except tk.TclError:
            self._clip_status.config(text="Clipboard is empty or unavailable")

    def _preview_clipboard(self):
        """Auto-detect and preview clipboard content."""
        text = self._clip_text.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Empty", "No text to parse.", parent=self)
            return

        lines = []
        tgs = []
        freqs = []
        channels = []

        # Try parsing as talkgroups
        try:
            tgs = parse_pasted_talkgroups(text)
        except Exception:
            pass

        # Try parsing as frequencies
        try:
            freqs = parse_pasted_frequencies(text)
        except Exception:
            pass

        # Try parsing as conv channels
        try:
            channels = parse_pasted_conv_channels(text)
        except Exception:
            pass

        # Pick the best result (most data)
        if tgs and len(tgs) >= len(freqs) and len(tgs) >= len(channels):
            self._clip_data = tgs
            self._clip_data_type = 'talkgroups'
            lines.append(f"Detected: {len(tgs)} talkgroups")
            lines.append("")
            lines.append(f"{'#':<4} {'ID':<8} {'Name':<10} {'Long Name':<20}")
            lines.append("-" * 46)
            for i, tg in enumerate(tgs[:30]):
                lines.append(
                    f"{i+1:<4} {tg.dec_id:<8} "
                    f"{tg.alpha_tag[:10]:<10} "
                    f"{tg.description[:20]:<20}")
            if len(tgs) > 30:
                lines.append(f"... and {len(tgs) - 30} more")

        elif freqs and len(freqs) >= len(channels):
            self._clip_data = freqs
            self._clip_data_type = 'frequencies'
            lines.append(f"Detected: {len(freqs)} frequencies")
            lines.append("")
            lines.append(f"{'#':<4} {'Frequency':<14}")
            lines.append("-" * 20)
            for i, f in enumerate(freqs[:30]):
                # freqs are tuples of (freq, freq) or similar
                freq_val = f[0] if isinstance(f, (list, tuple)) else f
                lines.append(f"{i+1:<4} {freq_val:<14.4f}")
            if len(freqs) > 30:
                lines.append(f"... and {len(freqs) - 30} more")

        elif channels:
            self._clip_data = channels
            self._clip_data_type = 'channels'
            lines.append(f"Detected: {len(channels)} conventional channels")
            lines.append("")
            for i, ch in enumerate(channels[:30]):
                name = ch.get('short_name', ch.get('name', ''))
                freq = ch.get('tx_freq', ch.get('freq', 0))
                lines.append(f"  {i+1}. {name} - {freq:.4f} MHz")
            if len(channels) > 30:
                lines.append(f"... and {len(channels) - 30} more")

        else:
            self._clip_data = None
            self._clip_data_type = None
            lines.append("Could not detect any importable data.")
            lines.append("")
            lines.append("Supported formats:")
            lines.append("  - RadioReference talkgroup tables (copy from website)")
            lines.append("  - Frequency lists (one per line, in MHz or Hz)")
            lines.append("  - Tab-separated channel data")

        self._clip_preview.config(state=tk.NORMAL)
        self._clip_preview.delete("1.0", tk.END)
        self._clip_preview.insert(tk.END, "\n".join(lines))
        self._clip_preview.config(state=tk.DISABLED)

        data_type = self._clip_data_type or "unknown"
        count = len(self._clip_data) if self._clip_data else 0
        self._clip_status.config(text=f"Detected: {count} {data_type}")

    def _import_clipboard(self):
        """Import detected clipboard data."""
        if not self.app.prs:
            messagebox.showwarning("No File", "Load a PRS file first.", parent=self)
            return

        if not self._clip_data:
            self._preview_clipboard()
            if not self._clip_data:
                messagebox.showinfo("No Data",
                                    "Click 'Detect & Preview' first.", parent=self)
                return

        set_name = _ask_set_name(self, "IMPORT")
        if not set_name:
            return

        self.app.save_undo_snapshot(f"Import from clipboard")

        try:
            if self._clip_data_type == 'talkgroups':
                tgs_data = []
                for tg in self._clip_data:
                    tgs_data.append({
                        'group_id': tg.dec_id,
                        'short_name': tg.alpha_tag[:8],
                        'long_name': (tg.description or tg.alpha_tag)[:16],
                    })
                self._inject_talkgroups(set_name, tgs_data)

            elif self._clip_data_type == 'frequencies':
                channels_data = []
                for i, f in enumerate(self._clip_data):
                    freq_val = f[0] if isinstance(f, (list, tuple)) else f
                    channels_data.append({
                        'short_name': f"F{i+1}",
                        'tx_freq': freq_val,
                        'rx_freq': freq_val,
                        'tx_tone': '',
                        'rx_tone': '',
                        'long_name': f"{freq_val:.4f}",
                    })
                self._inject_channels(set_name, channels_data)

            elif self._clip_data_type == 'channels':
                channels_data = []
                for ch in self._clip_data:
                    channels_data.append({
                        'short_name': ch.get('short_name', ch.get('name', ''))[:8],
                        'tx_freq': ch.get('tx_freq', ch.get('freq', 0)),
                        'rx_freq': ch.get('rx_freq', ch.get('freq', 0)),
                        'tx_tone': ch.get('tx_tone', ''),
                        'rx_tone': ch.get('rx_tone', ''),
                        'long_name': ch.get('long_name', '')[:16],
                    })
                self._inject_channels(set_name, channels_data)

            self.app.personality_view.refresh()
            self.app.mark_modified()
            self._clip_status.config(text="Imported successfully!")
            self._status_label.config(text=f"Clipboard data imported into '{set_name}'")

        except Exception as e:
            messagebox.showerror("Import Error", str(e), parent=self)

    # ─── Shared injection helpers ────────────────────────────────────

    def _inject_channels(self, set_name, channels_data):
        """Inject a list of channel dicts as a new conv set."""
        from ..injector import make_conv_set, add_conv_system
        from ..record_types import ConvSystemConfig

        conv_set = make_conv_set(set_name, channels_data)
        config = ConvSystemConfig(short_name=set_name[:8])
        add_conv_system(self.app.prs, config, conv_set=conv_set)

    def _inject_talkgroups(self, set_name, tgs_data):
        """Inject a list of talkgroup dicts as a new group set."""
        from ..injector import make_group_set, add_group_set

        tg_tuples = []
        for tg in tgs_data:
            tg_tuples.append((
                tg.get('group_id', 0),
                tg.get('short_name', '')[:8],
                tg.get('long_name', '')[:16],
            ))

        group_set = make_group_set(set_name, tg_tuples)
        add_group_set(self.app.prs, group_set)


# ─── Helper dialogs ──────────────────────────────────────────────────

def _ask_set_name(parent, default=""):
    """Ask the user for a set name (max 8 chars).

    Returns the name string, or None if cancelled.
    """
    dialog = tk.Toplevel(parent)
    dialog.title("Set Name")
    dialog.geometry("350x120")
    dialog.transient(parent)
    dialog.grab_set()

    ttk.Label(dialog, text="Enter a name for the data set (max 8 characters):").pack(
        padx=12, pady=(12, 4), anchor=tk.W)

    name_var = tk.StringVar(value=default)
    entry = ttk.Entry(dialog, textvariable=name_var, width=20)
    entry.pack(padx=12, anchor=tk.W)
    entry.select_range(0, tk.END)
    entry.focus_set()

    result = [None]

    def on_ok():
        val = name_var.get().strip()
        if val:
            result[0] = val[:8].upper()
        dialog.destroy()

    def on_cancel():
        dialog.destroy()

    entry.bind('<Return>', lambda e: on_ok())
    entry.bind('<Escape>', lambda e: on_cancel())

    btn_frame = ttk.Frame(dialog)
    btn_frame.pack(fill=tk.X, padx=12, pady=8)
    ttk.Button(btn_frame, text="OK", command=on_ok).pack(side=tk.RIGHT, padx=2)
    ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side=tk.RIGHT, padx=2)

    dialog.wait_window()
    return result[0]
