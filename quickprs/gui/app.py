"""QuickPRS main application window.

Tkinter + ttk GUI for loading, viewing, and modifying Harris RPM
personality (.PRS) files. Supports RadioReference import for bulk
injection of P25 trunked systems.

Layout:
  +----------------------------------------------+
  | Menu Bar: File | Tools | Help                 |
  +-------------------+--------------------------+
  |                   |                          |
  | Personality Tree  |  Right Panel (Notebook)  |
  | (systems, groups, |  - Import tab            |
  |  channels, sets)  |  - Details tab           |
  |                   |  - Validation tab        |
  |                   |                          |
  +-------------------+--------------------------+
  | Status Bar                                    |
  +----------------------------------------------+
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

try:
    import sv_ttk
    HAS_SV_TTK = True
except ImportError:
    HAS_SV_TTK = False

try:
    import darkdetect
    HAS_DARKDETECT = True
except ImportError:
    HAS_DARKDETECT = False

try:
    import windnd
    HAS_WINDND = True
except ImportError:
    HAS_WINDND = False

from .. import __version__
from ..prs_parser import parse_prs
from ..prs_writer import write_prs
from ..validation import validate_prs, validate_prs_detailed, ERROR, WARNING
from ..logger import log_action, log_error
from ..undo import UndoStack

from .personality_view import PersonalityView
from .import_panel import ImportPanel
from .settings import (
    SettingsDialog, load_settings, save_settings,
    add_recent_file, get_recent_files,
)


class QuickPRSApp:
    """Main application class."""

    def __init__(self, root):
        self.root = root
        self.root.title(f"QuickPRS v{__version__} - Harris RPM Personality Tool")
        self.root.geometry("1400x850")
        self.root.minsize(1000, 600)

        # Apply theme
        self.dark_mode = False
        self._apply_theme()

        # State
        self.prs = None
        self.prs_path = None
        self.modified = False
        self._last_saved_bytes = None  # bytes snapshot at last save/load
        self.settings = load_settings()
        self._undo_stack = UndoStack(max_levels=20)

        # Build UI
        self._build_menu()
        self._build_toolbar()
        self._build_main_area()
        self._build_status_bar()

        # Keybindings
        self.root.bind('<Control-n>', lambda e: self.new_blank())
        self.root.bind('<Control-o>', lambda e: self.open_file())
        self.root.bind('<Control-s>', lambda e: self.save_file())
        self.root.bind('<Control-S>', lambda e: self.save_as())
        self.root.bind('<Control-z>', lambda e: self.undo_injection())
        self.root.bind('<Control-y>', lambda e: self.redo())
        self.root.bind('<Control-Z>', lambda e: self.redo())
        self.root.bind('<Control-d>', lambda e: self.compare_files())
        self.root.bind('<Control-e>', lambda e: self.export_json())
        self.root.bind('<Control-i>', lambda e: self._show_import_wizard())
        self.root.bind('<Control-m>', lambda e: self.merge_prs())
        self.root.bind('<Control-t>', lambda e: self.add_template_channels())
        self.root.bind('<Control-g>', lambda e: self.generate_report())
        self.root.bind('<Delete>', lambda e: self._delete_selected())
        self.root.bind('<F2>', lambda e: self._rename_selected())
        self.root.bind('<F5>', lambda e: self.validate())
        self.root.bind('<F8>', lambda e: self._capacity_report())
        self.root.bind('<Insert>', lambda e: self._insert_context_aware())
        self.root.bind('<F1>', lambda e: self.show_shortcuts())

        # Drag-and-drop file opening (Windows)
        if HAS_WINDND:
            windnd.hook_dropfiles(self.root, func=self._on_file_drop)

        self._update_title()
        self._restore_geometry()

    # ─── Menu bar ────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open...", command=self.open_file,
                              accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.save_file,
                              accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.save_as,
                              accelerator="Ctrl+Shift+S")
        file_menu.add_separator()

        file_menu.add_command(label="New Blank Personality...",
                              command=self.new_blank,
                              accelerator="Ctrl+N")
        file_menu.add_command(label="Build from Config...",
                              command=self.build_from_config)
        file_menu.add_separator()

        file_menu.add_command(label="Import Wizard...",
                              command=self._show_import_wizard,
                              accelerator="Ctrl+I")
        file_menu.add_command(label="Import CSV...",
                              command=self.import_csv)
        file_menu.add_command(label="Export JSON...",
                              command=self.export_json,
                              accelerator="Ctrl+E")
        file_menu.add_command(label="Export as Config...",
                              command=self.export_config)
        file_menu.add_command(label="Import JSON...",
                              command=self.import_json)
        file_menu.add_command(label="Merge PRS...",
                              command=self.merge_prs,
                              accelerator="Ctrl+M")
        file_menu.add_command(label="Import Scanner CSV...",
                              command=self.import_scanner_csv)

        # Export submenu
        export_menu = tk.Menu(file_menu, tearoff=0)
        export_menu.add_command(label="CHIRP CSV...",
                                command=self._export_chirp)
        export_menu.add_command(label="Uniden CSV...",
                                command=self._export_uniden)
        export_menu.add_command(label="SDRTrunk Talkgroups...",
                                command=self._export_sdrtrunk)
        export_menu.add_command(label="DSD+ Frequencies...",
                                command=self._export_dsd)
        export_menu.add_separator()
        export_menu.add_command(label="Markdown...",
                                command=self._export_markdown)
        file_menu.add_cascade(label="Export", menu=export_menu)

        # Recent files submenu
        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Recent Files", menu=self.recent_menu)
        self._refresh_recent_menu()

        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        # Edit menu
        edit_menu = tk.Menu(menubar, tearoff=0)
        self._edit_menu = edit_menu
        edit_menu.add_command(label="Undo",
                               command=self.undo_injection,
                               accelerator="Ctrl+Z",
                               state=tk.DISABLED)
        edit_menu.add_command(label="Redo",
                               command=self.redo,
                               accelerator="Ctrl+Y",
                               state=tk.DISABLED)
        edit_menu.add_separator()
        edit_menu.add_command(label="Delete Selected",
                               command=self._delete_selected,
                               accelerator="Delete")
        edit_menu.add_command(label="Rename Selected",
                               command=self._rename_selected,
                               accelerator="F2")
        menubar.add_cascade(label="Edit", menu=edit_menu)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Toggle Dark/Light",
                               command=self._toggle_theme)
        menubar.add_cascade(label="View", menu=view_menu)

        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Validate", command=self.validate,
                                accelerator="F5")
        tools_menu.add_command(label="Health Check...",
                                command=self._show_health_check)
        tools_menu.add_command(label="Frequency Map...",
                                command=self._show_freq_map)
        tools_menu.add_command(label="Summary", command=self.show_summary)
        tools_menu.add_separator()
        tools_menu.add_command(label="Compare PRS...",
                                command=self.compare_files,
                                accelerator="Ctrl+D")
        tools_menu.add_command(label="Change Report...",
                                command=self._show_change_report)
        tools_menu.add_command(label="Export CSV...", command=self.export_csv)
        tools_menu.add_separator()
        tools_menu.add_command(label="Add Template Channels...",
                                command=self.add_template_channels,
                                accelerator="Ctrl+T")
        tools_menu.add_command(label="Radio Options...",
                                command=self.edit_radio_options)
        tools_menu.add_command(label="Button Configurator...",
                                command=self._show_button_configurator)
        tools_menu.add_separator()
        tools_menu.add_command(label="IDEN Template Library...",
                                command=self._add_standard_iden_set)
        tools_menu.add_separator()
        tools_menu.add_command(label="Generate Report...",
                                command=self.generate_report,
                                accelerator="Ctrl+G")
        tools_menu.add_command(label="Capacity Report...",
                                command=self._capacity_report,
                                accelerator="F8")
        tools_menu.add_command(label="Summary Card...",
                                command=self._generate_summary_card)
        tools_menu.add_separator()
        tools_menu.add_command(label="Zone Planner...",
                                command=self._show_zone_planner)
        tools_menu.add_separator()
        tools_menu.add_command(label="P25 System Database...",
                                command=self._show_system_database)
        tools_menu.add_command(label="System Import Wizard...",
                                command=self._show_system_wizard)
        tools_menu.add_separator()
        tools_menu.add_command(label="Scan Priority...",
                                command=self._show_scan_priority)
        tools_menu.add_separator()
        tools_menu.add_command(label="Frequency Reference...",
                                command=self._show_freq_reference)
        tools_menu.add_separator()
        tools_menu.add_command(label="Cleanup...",
                                command=self._show_cleanup_dialog)
        tools_menu.add_separator()
        tools_menu.add_command(label="View Log...",
                                command=self.show_log)
        tools_menu.add_command(label="Settings...",
                                command=self.show_settings)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Keyboard Shortcuts",
                               command=self.show_shortcuts,
                               accelerator="F1")
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

    # ─── Toolbar ─────────────────────────────────────────────────────

    def _build_toolbar(self):
        toolbar = ttk.Frame(self.root, padding=2)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="Open", command=self.open_file,
                    width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Save", command=self.save_file,
                    width=8).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4)

        ttk.Button(toolbar, text="Validate", command=self.validate,
                    width=10).pack(side=tk.LEFT, padx=2)

        # Quick-add section
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4)

        ttk.Button(toolbar, text="+ System", command=self._quick_add_system,
                    width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="+ TGs", command=self._quick_add_talkgroups,
                    width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="+ Channels", command=self._quick_add_channels,
                    width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Templates", command=self.add_template_channels,
                    width=10).pack(side=tk.LEFT, padx=2)

        # Import section
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4)

        ttk.Button(toolbar, text="Import Wizard", command=self._show_import_wizard,
                    width=14).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Import RR", command=self._quick_import_rr,
                    width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Import CSV", command=self.import_csv,
                    width=10).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4)

        # File path label
        self.file_label = ttk.Label(toolbar, text="No file loaded",
                                     foreground="gray")
        self.file_label.pack(side=tk.LEFT, padx=8)

        # Right side - capacity indicator
        self._capacity_label = ttk.Label(toolbar, text="")
        self._capacity_label.pack(side=tk.RIGHT, padx=8)

    # ─── Main area (paned) ───────────────────────────────────────────

    def _build_main_area(self):
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Left: personality tree
        left_frame = ttk.LabelFrame(paned, text="Personality", padding=4)
        self.personality_view = PersonalityView(left_frame, self)
        self.personality_view.pack(fill=tk.BOTH, expand=True)
        paned.add(left_frame, weight=1)

        # Right: notebook with tabs
        right_frame = ttk.Frame(paned)
        self.notebook = ttk.Notebook(right_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Import tab
        import_frame = ttk.Frame(self.notebook, padding=8)
        self.import_panel = ImportPanel(import_frame, self)
        self.import_panel.pack(fill=tk.BOTH, expand=True)
        self.notebook.add(import_frame, text="Import")

        # Validation tab
        validation_frame = ttk.Frame(self.notebook, padding=8)
        self._build_validation_tab(validation_frame)
        self.notebook.add(validation_frame, text="Validation")

        # Details tab
        details_frame = ttk.Frame(self.notebook, padding=8)
        self._build_details_tab(details_frame)
        self.notebook.add(details_frame, text="Details")

        # Statistics tab
        stats_frame = ttk.Frame(self.notebook, padding=8)
        self._build_statistics_tab(stats_frame)
        self.notebook.add(stats_frame, text="Statistics")

        paned.add(right_frame, weight=2)

    def _build_validation_tab(self, parent):
        """Build the validation results display with grouped tree."""
        header = ttk.Frame(parent)
        header.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(header, text="Run Validation",
                    command=self.validate).pack(side=tk.LEFT)
        self.val_summary = ttk.Label(header, text="")
        self.val_summary.pack(side=tk.LEFT, padx=8)

        # Grouped results tree (hierarchical)
        cols = ("severity", "message")
        self.val_tree = ttk.Treeview(parent, columns=cols,
                                      show="tree headings", height=20)
        self.val_tree.heading("#0", text="Category", anchor=tk.W)
        self.val_tree.heading("severity", text="Severity")
        self.val_tree.heading("message", text="Message")
        self.val_tree.column("#0", width=200, minwidth=120)
        self.val_tree.column("severity", width=80, minwidth=60)
        self.val_tree.column("message", width=500, minwidth=200)

        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL,
                             command=self.val_tree.yview)
        self.val_tree.configure(yscrollcommand=vsb.set)
        self.val_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_details_tab(self, parent):
        """Build the details text display."""
        self.details_text = tk.Text(parent, wrap=tk.WORD, state=tk.DISABLED,
                                     font=("Consolas", 10))
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL,
                             command=self.details_text.yview)
        self.details_text.configure(yscrollcommand=vsb.set)
        self.details_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_statistics_tab(self, parent):
        """Build the statistics display tab."""
        header = ttk.Frame(parent)
        header.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(header, text="Refresh Statistics",
                    command=self._refresh_statistics).pack(side=tk.LEFT)

        self.stats_text = tk.Text(parent, wrap=tk.WORD, state=tk.DISABLED,
                                   font=("Consolas", 10))
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL,
                             command=self.stats_text.yview)
        self.stats_text.configure(yscrollcommand=vsb.set)
        self.stats_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _refresh_statistics(self):
        """Compute and display personality statistics."""
        if not self.prs:
            messagebox.showinfo("Statistics", "No file loaded.")
            return

        from ..validation import compute_statistics, format_statistics

        stats = compute_statistics(self.prs)
        filename = Path(self.prs_path).name if self.prs_path else ""
        lines = format_statistics(stats, filename=filename)

        self.stats_text.configure(state=tk.NORMAL)
        self.stats_text.delete("1.0", tk.END)
        self.stats_text.insert(tk.END, "\n".join(lines))
        self.stats_text.configure(state=tk.DISABLED)

        # Switch to statistics tab
        self.notebook.select(3)
        self.status_set("Statistics computed")

    def _show_zone_planner(self):
        """Show the zone planner dialog."""
        if not self.prs:
            messagebox.showinfo("Zone Planner", "No file loaded.")
            return

        from ..zones import (
            plan_zones, format_zone_plan, validate_zone_plan,
            export_zone_plan_csv,
        )

        win = tk.Toplevel(self.root)
        win.title("Zone Planner")
        win.geometry("700x500")
        win.transient(self.root)

        # Strategy selector
        top_frame = ttk.Frame(win, padding=8)
        top_frame.pack(fill=tk.X)
        ttk.Label(top_frame, text="Strategy:").pack(side=tk.LEFT)
        strategy_var = tk.StringVar(value="auto")
        for strat in ("auto", "by_set", "combined"):
            ttk.Radiobutton(top_frame, text=strat, variable=strategy_var,
                             value=strat).pack(side=tk.LEFT, padx=4)

        # Text display
        text_frame = ttk.Frame(win, padding=(8, 0, 8, 8))
        text_frame.pack(fill=tk.BOTH, expand=True)
        zone_text = tk.Text(text_frame, wrap=tk.WORD,
                             font=("Consolas", 10), state=tk.DISABLED)
        vsb = ttk.Scrollbar(text_frame, orient=tk.VERTICAL,
                             command=zone_text.yview)
        zone_text.configure(yscrollcommand=vsb.set)
        zone_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        def refresh():
            strategy = strategy_var.get()
            zones = plan_zones(self.prs, strategy=strategy)
            lines = format_zone_plan(zones)
            issues = validate_zone_plan(zones)
            if issues:
                lines.append("")
                for sev, msg in issues:
                    lines.append(f"  [{sev.upper()}] {msg}")
            zone_text.configure(state=tk.NORMAL)
            zone_text.delete("1.0", tk.END)
            zone_text.insert(tk.END, "\n".join(lines))
            zone_text.configure(state=tk.DISABLED)

        # Button bar
        btn_frame = ttk.Frame(win, padding=8)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Generate",
                    command=refresh).pack(side=tk.LEFT, padx=2)

        def export_csv():
            strategy = strategy_var.get()
            zones = plan_zones(self.prs, strategy=strategy)
            path = filedialog.asksaveasfilename(
                title="Export Zone Plan",
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv")],
                parent=win,
            )
            if path:
                export_zone_plan_csv(zones, path)
                self.status_set(f"Zone plan exported to {Path(path).name}")

        ttk.Button(btn_frame, text="Export CSV...",
                    command=export_csv).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Close",
                    command=win.destroy).pack(side=tk.RIGHT, padx=2)

        # Auto-generate on open
        refresh()

    # ─── Status bar ──────────────────────────────────────────────────

    def _build_status_bar(self):
        status_frame = ttk.Frame(self.root)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Separator(status_frame, orient=tk.HORIZONTAL).pack(fill=tk.X)

        # Left: action messages
        self._status_msg = ttk.Label(status_frame, text="Ready",
                                      padding=(4, 2))
        self._status_msg.pack(side=tk.LEFT)
        # Keep backward-compat alias
        self.status_label = self._status_msg

        # Center: modified indicator
        self._status_modified = ttk.Label(status_frame, text="",
                                           padding=(4, 2))
        self._status_modified.pack(side=tk.LEFT, padx=20)

        # Right: file stats
        self._status_stats = ttk.Label(status_frame, text="",
                                        foreground="gray", padding=(4, 2))
        self._status_stats.pack(side=tk.RIGHT, padx=(0, 8))
        # Keep backward-compat aliases
        self.stats_label = self._status_stats
        self.size_label = ttk.Label(status_frame, text="",
                                     padding=(4, 2))
        self.size_label.pack(side=tk.RIGHT)

    # ─── File operations ─────────────────────────────────────────────

    def _on_file_drop(self, files):
        """Handle file(s) dropped onto the window from the OS."""
        for raw in files:
            path = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
            if path.lower().endswith('.prs'):
                if self.modified:
                    result = messagebox.askyesnocancel(
                        "Unsaved Changes",
                        "You have unsaved changes. Save before opening?")
                    if result is None:
                        return
                    if result:
                        self.save_file()
                self._open_path(path)
                return
        # No .PRS file found in drop
        names = [Path(f.decode('utf-8') if isinstance(f, bytes) else str(f)).name
                 for f in files]
        self.status_set(f"Not a PRS file: {', '.join(names)}", color="orange")

    def open_file(self):
        if self.modified:
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before opening a new file?")
            if result is None:  # Cancel
                return
            if result:  # Yes
                self.save_file()

        initial_dir = self.settings.get("last_open_dir", "")
        path = filedialog.askopenfilename(
            title="Open Personality File",
            filetypes=[("PRS Files", "*.PRS *.prs"), ("All Files", "*.*")],
            initialdir=initial_dir or None,
        )
        if not path:
            return
        self._open_path(path)

    def _open_path(self, path):
        """Load a PRS file from a path string."""
        path = str(path)
        # Remember directory and add to recent files
        self.settings["last_open_dir"] = str(Path(path).parent)
        add_recent_file(self.settings, path)
        self._refresh_recent_menu()

        try:
            self.prs = parse_prs(Path(path))
            self.prs_path = Path(path)
            self.modified = False
            self._last_saved_bytes = self.prs.to_bytes()
            self._update_title()
            fg = "#e0e0e0" if self.dark_mode else "black"
            self.file_label.config(
                text=str(self.prs_path.name), foreground=fg)
            self.status_set(
                f"Loaded {self.prs_path.name} "
                f"({self.prs.file_size:,} bytes, "
                f"{len(self.prs.sections)} sections)")
            self.size_label.config(
                text=f"{self.prs.file_size:,} bytes")
            self.personality_view.refresh()
            self._update_stats()
            self._update_capacity_label()
            self._status_modified.config(text="")
            log_action("file_open",
                       path=str(path),
                       size=self.prs.file_size,
                       sections=len(self.prs.sections))
        except Exception as e:
            log_error("file_open", str(e), path=str(path))
            messagebox.showerror("Error", f"Failed to open file:\n{e}")

    def save_file(self):
        if not self.prs or not self.prs_path:
            self.save_as()
            return
        self._do_save(self.prs_path)

    def save_as(self):
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        initial_dir = self.settings.get("last_open_dir", "")
        path = filedialog.asksaveasfilename(
            title="Save Personality File",
            defaultextension=".PRS",
            filetypes=[("PRS Files", "*.PRS *.prs"), ("All Files", "*.*")],
            initialfile=self.prs_path.name if self.prs_path else "output.PRS",
            initialdir=initial_dir or None,
        )
        if not path:
            return
        self._do_save(Path(path))

    def _do_save(self, path):
        try:
            # Check if we have a previous state to diff against
            has_changes = (self._last_saved_bytes is not None
                           and self.prs.to_bytes() != self._last_saved_bytes)

            write_prs(self.prs, path, backup=True)
            self.prs_path = path
            self.modified = False
            self._update_title()
            self._status_modified.config(text="Saved", foreground="green")
            self.status_set(f"Saved to {path.name}")
            log_action("file_save",
                       path=str(path),
                       size=len(self.prs.to_bytes()))

            # Offer to view change report if there were modifications
            if has_changes:
                self._offer_change_report()

            # Update saved bytes snapshot
            self._last_saved_bytes = self.prs.to_bytes()
        except Exception as e:
            log_error("file_save", str(e), path=str(path))
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    def _offer_change_report(self):
        """Ask if the user wants to view a change report after save."""
        result = messagebox.askyesno(
            "Change Report",
            "File saved. View a report of what changed?")
        if result:
            self._show_change_report()

    def _show_change_report(self):
        """Show a change report dialog comparing saved state to current."""
        if not self._last_saved_bytes or not self.prs:
            return
        try:
            from ..diff_report import generate_diff_report
            report = generate_diff_report(self._last_saved_bytes, self.prs)
            self._show_report_dialog("Personality Change Report", report)
        except Exception as e:
            log_error("change_report", str(e))
            messagebox.showerror("Error",
                                 f"Failed to generate report:\n{e}")

    def _show_report_dialog(self, title, text):
        """Show a scrollable text dialog with a report."""
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.geometry("700x500")
        dlg.transient(self.root)

        text_widget = tk.Text(dlg, wrap=tk.WORD, padx=8, pady=8)
        scrollbar = ttk.Scrollbar(dlg, orient=tk.VERTICAL,
                                   command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)

        text_widget.insert("1.0", text)
        text_widget.config(state=tk.DISABLED)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=8)

        def _copy():
            dlg.clipboard_clear()
            dlg.clipboard_append(text)
            self.status_set("Report copied to clipboard")

        def _save():
            from tkinter import filedialog as fd
            path = fd.asksaveasfilename(
                parent=dlg,
                title="Save Change Report",
                defaultextension=".txt",
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            )
            if path:
                Path(path).write_text(text, encoding='utf-8')
                self.status_set(f"Report saved to {Path(path).name}")

        ttk.Button(btn_frame, text="Copy to Clipboard",
                    command=_copy).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Save As...",
                    command=_save).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Close",
                    command=dlg.destroy).pack(side=tk.RIGHT, padx=4)

    def save_undo_snapshot(self, description=""):
        """Save current PRS state for potential undo. Call BEFORE modifying."""
        if self.prs:
            self._undo_stack.push(self.prs.to_bytes(), description)
            self._update_undo_menu()

    def mark_modified(self):
        """Call after any injection/modification."""
        self.modified = True
        self._update_title()
        self._status_modified.config(text="Modified", foreground="red")
        if self.prs:
            new_size = len(self.prs.to_bytes())
            self.size_label.config(text=f"{new_size:,} bytes (modified)")
            self._update_stats()
            self._update_capacity_label()
            self._quick_validate()
        self._update_undo_menu()

    def _quick_validate(self):
        """Run quick validation after modifications and show in status bar."""
        if not self.prs:
            return
        try:
            issues = validate_prs(self.prs)
            errors = sum(1 for s, _ in issues if s == ERROR)
            warnings = sum(1 for s, _ in issues if s == WARNING)
            if errors:
                self.status_set(
                    f"Validation: {errors} errors, {warnings} warnings — "
                    "check Validation tab",
                    color="red")
            elif warnings:
                self.status_set(
                    f"Validation: {warnings} warnings — "
                    "check Validation tab",
                    color="orange")
        except Exception as e:
            log_error("validation", str(e))

    def _update_undo_menu(self):
        """Update Edit menu undo/redo labels and enabled state."""
        if not hasattr(self, '_edit_menu'):
            return
        menu = self._edit_menu

        # Undo label (index 0)
        if self._undo_stack.can_undo():
            desc = self._undo_stack.undo_description()
            label = f"Undo: {desc}" if desc else "Undo"
            menu.entryconfig(0, label=label, state=tk.NORMAL)
        else:
            menu.entryconfig(0, label="Undo", state=tk.DISABLED)

        # Redo label (index 1)
        if self._undo_stack.can_redo():
            desc = self._undo_stack.redo_description()
            label = f"Redo: {desc}" if desc else "Redo"
            menu.entryconfig(1, label=label, state=tk.NORMAL)
        else:
            menu.entryconfig(1, label="Redo", state=tk.DISABLED)

    def undo_injection(self):
        """Restore PRS to state before last modification."""
        if not self._undo_stack.can_undo():
            messagebox.showinfo("Undo", "Nothing to undo.")
            return

        desc = self._undo_stack.undo_description()
        if not messagebox.askyesno(
                "Undo",
                f"Undo: {desc}\n\n"
                "Restore personality to previous state?"
                if desc else
                "Restore personality to state before last modification?\n\n"
                "This will undo the most recent modification."):
            return

        try:
            from ..prs_parser import parse_prs_bytes
            current_bytes = self.prs.to_bytes()
            prev_bytes, undone_desc = self._undo_stack.undo(current_bytes)
            self.prs = parse_prs_bytes(prev_bytes)
            self.modified = True
            self._update_title()
            self._status_modified.config(text="Modified", foreground="red")
            self.personality_view.refresh()
            self._update_stats()
            self._update_capacity_label()
            new_size = len(self.prs.to_bytes())
            self.size_label.config(text=f"{new_size:,} bytes (modified)")
            msg = f"Undone: {undone_desc}" if undone_desc else "Undone"
            self.status_set(msg)
            self._update_undo_menu()
            log_action("undo_injection", description=undone_desc)
        except Exception as e:
            log_error("undo_injection", str(e))
            messagebox.showerror("Error", f"Undo failed:\n{e}")

    def redo(self):
        """Redo the last undone modification."""
        if not self._undo_stack.can_redo():
            messagebox.showinfo("Redo", "Nothing to redo.")
            return

        desc = self._undo_stack.redo_description()
        try:
            from ..prs_parser import parse_prs_bytes
            current_bytes = self.prs.to_bytes()
            next_bytes, redone_desc = self._undo_stack.redo(current_bytes)
            self.prs = parse_prs_bytes(next_bytes)
            self.modified = True
            self._update_title()
            self._status_modified.config(text="Modified", foreground="red")
            self.personality_view.refresh()
            self._update_stats()
            self._update_capacity_label()
            new_size = len(self.prs.to_bytes())
            self.size_label.config(text=f"{new_size:,} bytes (modified)")
            msg = f"Redone: {redone_desc}" if redone_desc else "Redone"
            self.status_set(msg)
            self._update_undo_menu()
            log_action("redo", description=redone_desc)
        except Exception as e:
            log_error("redo", str(e))
            messagebox.showerror("Error", f"Redo failed:\n{e}")

    # ─── Validation ──────────────────────────────────────────────────

    def validate(self):
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        self.notebook.select(1)  # Switch to validation tab
        detailed = validate_prs_detailed(self.prs)

        # Clear previous
        for item in self.val_tree.get_children():
            self.val_tree.delete(item)

        self.val_tree.tag_configure("error", foreground="red")
        self.val_tree.tag_configure("warning", foreground="orange")
        self.val_tree.tag_configure("info", foreground="blue")
        self.val_tree.tag_configure("pass", foreground="green")

        total_errors = 0
        total_warnings = 0
        total_issues = 0

        if not detailed:
            # No issues at all
            self.val_tree.insert("", tk.END, text="All checks passed",
                                  values=("", "No issues found"),
                                  tags=("pass",))
        else:
            for category, issues in sorted(detailed.items()):
                cat_errors = sum(1 for s, _ in issues if s == ERROR)
                cat_warnings = sum(1 for s, _ in issues if s == WARNING)
                total_errors += cat_errors
                total_warnings += cat_warnings
                total_issues += len(issues)

                # Category summary
                if cat_errors:
                    tag = "error"
                    summary = f"{cat_errors} errors"
                elif cat_warnings:
                    tag = "warning"
                    summary = f"{cat_warnings} warnings"
                else:
                    tag = "info"
                    summary = f"{len(issues)} info"

                cat_node = self.val_tree.insert(
                    "", tk.END, text=category,
                    values=("", summary),
                    tags=(tag,), open=True)

                for severity, msg in issues:
                    self.val_tree.insert(
                        cat_node, tk.END, text="",
                        values=(severity, msg),
                        tags=(severity.lower(),))

        self.val_summary.config(
            text=f"{total_errors} errors, {total_warnings} warnings, "
                 f"{total_issues} total issues")

        if total_errors == 0:
            self.status_set("Validation passed (no errors)")
        else:
            self.status_set(f"Validation: {total_errors} ERRORS found")

    # ─── Health Check ─────────────────────────────────────────────────

    def _show_health_check(self):
        """Show configuration health check results in the details tab."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        from ..health_check import (
            run_health_check, format_health_report,
            suggest_improvements, format_suggestions,
        )

        results = run_health_check(self.prs)
        health_lines = format_health_report(results)

        filepath = self.current_path or "file.PRS"
        suggestions = suggest_improvements(self.prs, filepath=filepath)
        suggest_lines = format_suggestions(suggestions, filepath=filepath)

        self.notebook.select(2)  # Details tab
        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)

        self.details_text.insert(tk.END, "\n".join(health_lines))
        self.details_text.insert(tk.END, "\n\n")
        self.details_text.insert(tk.END, "\n".join(suggest_lines))
        self.details_text.config(state=tk.DISABLED)

        issue_count = len(results)
        self.status_set(f"Health check: {issue_count} issue(s) found, "
                        f"{len(suggestions)} suggestion(s)")

    def _show_freq_map(self):
        """Show frequency spectrum map in the details tab."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        from ..freq_tools import generate_freq_map

        lines = generate_freq_map(self.prs)

        self.notebook.select(2)  # Details tab
        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert(tk.END, "\n".join(lines))
        self.details_text.config(state=tk.DISABLED)

        self.status_set("Frequency map generated")

    # ─── Summary ─────────────────────────────────────────────────────

    def show_summary(self):
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        from ..record_types import (
            parse_system_short_name, parse_system_long_name,
            is_system_config_data,
        )

        self.notebook.select(2)  # Switch to details tab
        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)

        prs = self.prs
        lines = []
        lines.append(f"File: {self.prs_path or 'unsaved'}")
        lines.append(f"Size: {len(prs.to_bytes()):,} bytes")
        lines.append(f"Sections: {len(prs.sections)}")
        lines.append("")

        # Systems with names
        system_types = [
            ('CP25TrkSystem', 'P25 Trunked'),
            ('CConvSystem', 'Conventional'),
            ('CP25ConvSystem', 'P25 Conv'),
        ]
        for cls, label in system_types:
            secs = prs.get_sections_by_class(cls)
            if not secs:
                continue
            names = []
            for s in secs:
                n = parse_system_short_name(s.raw)
                names.append(n or "?")
            lines.append(f"{label} ({len(secs)}): {', '.join(names)}")

        # Config data names
        config_names = []
        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                ln = parse_system_long_name(sec.raw)
                if ln:
                    config_names.append(ln)
        if config_names:
            lines.append(f"System configs: {', '.join(config_names)}")
        lines.append("")

        parsed = self._parse_sets()

        # Group sets
        if parsed['groups']:
            sets = parsed['groups']
            total_tgs = sum(len(s.groups) for s in sets)
            lines.append(f"Group Sets ({len(sets)}):")
            for gs in sets:
                scan_ct = sum(1 for g in gs.groups if g.scan)
                lines.append(f"  {gs.name}: {len(gs.groups)} TGs "
                             f"({scan_ct} scan-enabled)")
            lines.append(f"  Total: {total_tgs} talkgroups")
            lines.append("")

        # Trunk sets
        if parsed['trunk']:
            sets = parsed['trunk']
            total_freqs = sum(len(s.channels) for s in sets)
            lines.append(f"Trunk Sets ({len(sets)}):")
            for ts in sets:
                lines.append(f"  {ts.name}: {len(ts.channels)} freqs "
                             f"({ts.tx_min:.0f}-{ts.tx_max:.0f} MHz)")
            lines.append(f"  Total: {total_freqs} frequencies")
            lines.append("")

        # Conv sets
        if parsed['conv']:
            sets = parsed['conv']
            total_ch = sum(len(s.channels) for s in sets)
            lines.append(f"Conv Sets ({len(sets)}):")
            for cs in sets:
                lines.append(f"  {cs.name}: {len(cs.channels)} channels")
            lines.append(f"  Total: {total_ch} channels")
            lines.append("")

        # IDEN sets
        if parsed['iden']:
            sets = parsed['iden']
            lines.append(f"IDEN Sets ({len(sets)}):")
            for iset in sets:
                active_elems = [e for e in iset.elements
                                if not e.is_empty()]
                active = len(active_elems)
                fdma = sum(1 for e in active_elems if not e.iden_type)
                tdma = sum(1 for e in active_elems if e.iden_type)
                if fdma and tdma:
                    mode = "mixed FDMA+TDMA"
                elif tdma:
                    mode = "TDMA"
                else:
                    mode = "FDMA"
                lines.append(f"  {iset.name}: {active}/16 active ({mode})")
            lines.append("")

        # Options count
        opts = [s for s in prs.sections if s.class_name and (
                'Opts' in s.class_name or
                s.class_name.startswith('CT99'))]
        if opts:
            lines.append(f"Options/Config records: {len(opts)}")

        # All named sections
        named = [s for s in prs.sections if s.class_name]
        lines.append("")
        lines.append(f"All named records ({len(named)}):")
        for s in named:
            lines.append(f"  {s.class_name} ({len(s.raw):,} bytes)")

        self.details_text.insert("1.0", "\n".join(lines))
        self.details_text.config(state=tk.DISABLED)

    # ─── Export ──────────────────────────────────────────────────────

    def _add_standard_iden_set(self):
        """Delegate to personality view's IDEN template dialog."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return
        self.personality_view._add_standard_iden_set()

    def export_csv(self):
        """Export personality data to CSV files."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        from ..csv_export import (
            export_group_sets, export_trunk_sets, export_conv_sets,
            export_iden_sets, export_options, export_systems,
            export_ecc, export_preferred,
        )

        directory = filedialog.askdirectory(title="Export CSV to folder")
        if not directory:
            return

        out_dir = Path(directory)
        exported = []
        parsed = self._parse_sets()

        for key, fn, filename in [
            ('groups', export_group_sets, "GROUP_SET.csv"),
            ('trunk', export_trunk_sets, "TRK_SET.csv"),
            ('conv', export_conv_sets, "CONV_SET.csv"),
            ('iden', export_iden_sets, "IDEN_SET.csv"),
        ]:
            if parsed[key]:
                try:
                    exported.append(fn(out_dir / filename, parsed[key]))
                except Exception as e:
                    log_error("export_csv", f"{filename}: {e}")

        # Options and systems from PRS directly
        try:
            result = export_options(out_dir / "OPTIONS.csv", self.prs)
            if result:
                exported.append(result)
        except Exception as e:
            log_error("export_csv", f"OPTIONS: {e}")

        try:
            result = export_systems(out_dir / "SYSTEMS.csv", self.prs)
            if result:
                exported.append(result)
        except Exception as e:
            log_error("export_csv", f"SYSTEMS: {e}")

        try:
            result = export_ecc(out_dir / "ECC.csv", self.prs)
            if result:
                exported.append(result)
        except Exception as e:
            log_error("export_csv", f"ECC: {e}")

        try:
            result = export_preferred(out_dir / "PREFERRED.csv", self.prs)
            if result:
                exported.append(result)
        except Exception as e:
            log_error("export_csv", f"PREFERRED: {e}")

        if exported:
            log_action("export_csv", directory=directory,
                       files=len(exported))
            messagebox.showinfo(
                "Export Complete",
                f"Exported to {directory}:\n" +
                "\n".join(f"  {e}" for e in exported))
        else:
            messagebox.showwarning(
                "Warning", "No data to export.")

    # ─── Third-party format exports ──────────────────────────────────

    def _export_chirp(self):
        """Export conventional channels to CHIRP CSV."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return
        from ..export_formats import export_chirp_csv
        default_name = ""
        if self.prs_path:
            default_name = Path(self.prs_path).stem + "_chirp.csv"
        path = filedialog.asksaveasfilename(
            title="Export CHIRP CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if not path:
            return
        try:
            count = export_chirp_csv(self.prs, path)
            self.status_set(f"Exported {count} channels to CHIRP CSV")
            log_action("export_chirp", path=path, channels=count)
            messagebox.showinfo("Export Complete",
                                f"Exported {count} channels to:\n{path}")
        except Exception as e:
            log_error("export_chirp", str(e))
            messagebox.showerror("Error", f"CHIRP export failed:\n{e}")

    def _export_uniden(self):
        """Export conventional channels to Uniden CSV."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return
        from ..export_formats import export_uniden_csv
        default_name = ""
        if self.prs_path:
            default_name = Path(self.prs_path).stem + "_uniden.csv"
        path = filedialog.asksaveasfilename(
            title="Export Uniden CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if not path:
            return
        try:
            count = export_uniden_csv(self.prs, path)
            self.status_set(f"Exported {count} channels to Uniden CSV")
            log_action("export_uniden", path=path, channels=count)
            messagebox.showinfo("Export Complete",
                                f"Exported {count} channels to:\n{path}")
        except Exception as e:
            log_error("export_uniden", str(e))
            messagebox.showerror("Error", f"Uniden export failed:\n{e}")

    def _export_sdrtrunk(self):
        """Export P25 talkgroups to SDRTrunk CSV."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return
        from ..export_formats import export_sdrtrunk_csv
        default_name = ""
        if self.prs_path:
            default_name = Path(self.prs_path).stem + "_talkgroups.csv"
        path = filedialog.asksaveasfilename(
            title="Export SDRTrunk Talkgroups",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if not path:
            return
        try:
            count = export_sdrtrunk_csv(self.prs, path)
            self.status_set(f"Exported {count} talkgroups to SDRTrunk CSV")
            log_action("export_sdrtrunk", path=path, talkgroups=count)
            messagebox.showinfo("Export Complete",
                                f"Exported {count} talkgroups to:\n{path}")
        except Exception as e:
            log_error("export_sdrtrunk", str(e))
            messagebox.showerror("Error", f"SDRTrunk export failed:\n{e}")

    def _export_dsd(self):
        """Export trunk frequencies to DSD+ format."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return
        from ..export_formats import export_dsd_freqs
        default_name = ""
        if self.prs_path:
            default_name = Path(self.prs_path).stem + "_freqs.txt"
        path = filedialog.asksaveasfilename(
            title="Export DSD+ Frequencies",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")])
        if not path:
            return
        try:
            count = export_dsd_freqs(self.prs, path)
            self.status_set(f"Exported {count} frequencies to DSD+ format")
            log_action("export_dsd", path=path, frequencies=count)
            messagebox.showinfo("Export Complete",
                                f"Exported {count} frequencies to:\n{path}")
        except Exception as e:
            log_error("export_dsd", str(e))
            messagebox.showerror("Error", f"DSD+ export failed:\n{e}")

    def _export_markdown(self):
        """Export radio configuration to Markdown."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return
        from ..export_formats import export_markdown
        default_name = ""
        if self.prs_path:
            default_name = Path(self.prs_path).stem + ".md"
        path = filedialog.asksaveasfilename(
            title="Export Markdown",
            defaultextension=".md",
            initialfile=default_name,
            filetypes=[("Markdown Files", "*.md"), ("All Files", "*.*")])
        if not path:
            return
        try:
            export_markdown(self.prs, path)
            self.status_set(f"Exported Markdown: {Path(path).name}")
            log_action("export_markdown", path=path)
            messagebox.showinfo("Export Complete",
                                f"Exported Markdown to:\n{path}")
        except Exception as e:
            log_error("export_markdown", str(e))
            messagebox.showerror("Error", f"Markdown export failed:\n{e}")

    # ─── HTML Report ──────────────────────────────────────────────────

    def generate_report(self):
        """Generate an HTML report of the personality configuration."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        from ..reports import generate_html_report

        default_name = ""
        if self.prs_path:
            default_name = Path(self.prs_path).stem + ".html"

        path = filedialog.asksaveasfilename(
            title="Save HTML Report",
            defaultextension=".html",
            initialfile=default_name,
            filetypes=[("HTML Files", "*.html"), ("All Files", "*.*")])
        if not path:
            return

        try:
            generate_html_report(
                self.prs, filepath=path,
                source_path=self.prs_path)
            self.status_set(f"Report saved: {path}")
            log_action("generate_report", path=path)

            # Offer to open in browser
            if messagebox.askyesno(
                    "Report Generated",
                    f"Report saved to:\n{path}\n\nOpen in browser?"):
                import webbrowser
                webbrowser.open(str(Path(path).resolve()))

        except Exception as e:
            messagebox.showerror("Error", f"Report generation failed:\n{e}")

    def _generate_summary_card(self):
        """Generate a compact HTML summary card for printing."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        from ..reports import generate_summary_card

        default_name = ""
        if self.prs_path:
            default_name = Path(self.prs_path).stem + "_card.html"

        path = filedialog.asksaveasfilename(
            title="Save Summary Card",
            defaultextension=".html",
            initialfile=default_name,
            filetypes=[("HTML Files", "*.html"), ("All Files", "*.*")])
        if not path:
            return

        try:
            generate_summary_card(
                self.prs, filepath=path,
                source_path=self.prs_path)
            self.status_set(f"Summary card saved: {path}")
            log_action("generate_summary_card", path=path)

            if messagebox.askyesno(
                    "Summary Card Generated",
                    f"Card saved to:\n{path}\n\nOpen in browser?"):
                import webbrowser
                webbrowser.open(str(Path(path).resolve()))

        except Exception as e:
            messagebox.showerror("Error",
                                  f"Summary card generation failed:\n{e}")

    # ─── CSV Import ────────────────────────────────────────────────────

    def import_csv(self):
        """Import group/trunk/conv data from CSV files."""
        if not self.prs:
            messagebox.showwarning("Warning",
                                    "Load a PRS file first, then import CSV.")
            return

        path = filedialog.askopenfilename(
            title="Import CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if not path:
            return

        from ..csv_import import import_csv as do_import
        from ..injector import add_group_set, add_trunk_set, add_conv_set

        try:
            data_type, objects = do_import(path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read CSV:\n{e}")
            return

        if data_type == "unknown" or not objects:
            messagebox.showwarning(
                "Import",
                "Could not detect CSV format.\n\n"
                "Expected columns:\n"
                "  Groups: GroupID, ShortName, LongName, TX, Scan\n"
                "  Trunk: TxFreq, RxFreq\n"
                "  Conv: ShortName, TxFreq, RxFreq, TxTone, RxTone")
            return

        # Show what was found and confirm
        summaries = []
        for obj in objects:
            if data_type == "groups":
                summaries.append(f"Group Set '{obj.name}': "
                                  f"{len(obj.groups)} talkgroups")
            elif data_type == "trunk":
                summaries.append(f"Trunk Set '{obj.name}': "
                                  f"{len(obj.channels)} frequencies")
            elif data_type == "conv":
                summaries.append(f"Conv Set '{obj.name}': "
                                  f"{len(obj.channels)} channels")

        if not messagebox.askyesno(
                "Confirm Import",
                f"Import from {Path(path).name}:\n\n" +
                "\n".join(summaries) +
                "\n\nProceed?"):
            return

        self.save_undo_snapshot(f"Import CSV ({data_type})")

        try:
            for obj in objects:
                if data_type == "groups":
                    add_group_set(self.prs, obj)
                elif data_type == "trunk":
                    add_trunk_set(self.prs, obj)
                elif data_type == "conv":
                    add_conv_set(self.prs, obj)

            self.mark_modified()
            self.personality_view.refresh()
            self.status_set(
                f"Imported {len(objects)} {data_type} set(s) from CSV")
            log_action("csv_import", file=path, type=data_type,
                       sets=len(objects))
        except Exception as e:
            log_error("csv_import", str(e), file=path)
            messagebox.showerror("Error", f"Import failed:\n{e}")

    # ─── Scanner CSV Import ────────────────────────────────────────

    def import_scanner_csv(self):
        """Import channels from a scanner CSV file (Uniden, CHIRP, etc.)."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        path = filedialog.askopenfilename(
            title="Import Scanner CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not path:
            return

        try:
            from ..scanner_import import (
                detect_scanner_format, import_scanner_csv as do_import,
            )
            from ..injector import add_conv_system, make_conv_set
            from ..record_types import ConvSystemConfig

            fmt = detect_scanner_format(path)
            channels = do_import(path, fmt=fmt if fmt != 'unknown' else None)

            if not channels:
                messagebox.showinfo("Import",
                                    "No channels found in the CSV file.")
                return

            # Show preview
            preview_lines = []
            for ch in channels[:10]:
                preview_lines.append(
                    f"  {ch['short_name']:8s}  {ch['tx_freq']:.4f} MHz")
            if len(channels) > 10:
                preview_lines.append(f"  ... and {len(channels) - 10} more")

            fmt_label = fmt if fmt != 'unknown' else 'auto-detected'
            if not messagebox.askyesno(
                    "Confirm Scanner Import",
                    f"Format: {fmt_label}\n"
                    f"Channels: {len(channels)}\n\n"
                    + "\n".join(preview_lines) +
                    "\n\nInject as conventional channels?"):
                return

            # Use first 8 chars of filename as set name
            set_name = Path(path).stem[:8].upper()

            self.save_undo_snapshot("Import scanner CSV")

            conv_set = make_conv_set(set_name, channels)
            config = ConvSystemConfig(
                system_name=set_name,
                long_name=set_name,
                conv_set_name=set_name,
            )
            add_conv_system(self.prs, config, conv_set=conv_set)

            self.mark_modified()
            self.personality_view.refresh()
            self.status_set(
                f"Imported {len(channels)} channels from "
                f"{Path(path).name} ({fmt_label})")
            log_action("scanner_import", file=path, format=fmt,
                       channels=len(channels))

        except Exception as e:
            log_error("scanner_import", str(e), file=path)
            messagebox.showerror("Error",
                                 f"Scanner import failed:\n{e}")

    # ─── New Blank / Build from Config ──────────────────────────────

    def new_blank(self):
        """Create a new blank personality file."""
        if self.modified:
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before creating a new file?")
            if result is None:
                return
            if result:
                self.save_file()

        path = filedialog.asksaveasfilename(
            title="Create New Blank Personality",
            defaultextension=".PRS",
            filetypes=[("PRS Files", "*.PRS *.prs"), ("All Files", "*.*")],
            initialfile="New Personality.PRS",
        )
        if not path:
            return

        try:
            from ..builder import create_blank_prs
            name = Path(path).name
            self.prs = create_blank_prs(filename=name)
            self.prs_path = Path(path)
            self._do_save(self.prs_path)
            self.modified = False
            self._update_title()
            fg = "#e0e0e0" if self.dark_mode else "black"
            self.file_label.config(text=name, foreground=fg)
            self.personality_view.refresh()
            self._update_stats()
            self.size_label.config(
                text=f"{len(self.prs.to_bytes()):,} bytes")
            self.status_set("Created new blank personality")
            log_action("new_blank", path=str(path))
        except Exception as e:
            log_error("new_blank", str(e))
            messagebox.showerror("Error",
                                 f"Failed to create blank personality:\n{e}")

    def build_from_config(self):
        """Build a PRS personality from an INI config file."""
        if self.modified:
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before building?")
            if result is None:
                return
            if result:
                self.save_file()

        config_path = filedialog.askopenfilename(
            title="Select Config File",
            filetypes=[("Config files", "*.ini *.cfg"),
                       ("All Files", "*.*")],
        )
        if not config_path:
            return

        try:
            from ..config_builder import build_from_config as do_build
            prs = do_build(config_path)
        except Exception as e:
            log_error("build_from_config", str(e), path=config_path)
            messagebox.showerror("Error",
                                 f"Failed to build from config:\n{e}")
            return

        save_path = filedialog.asksaveasfilename(
            title="Save Built Personality",
            defaultextension=".PRS",
            filetypes=[("PRS Files", "*.PRS *.prs"), ("All Files", "*.*")],
            initialfile=Path(config_path).stem + ".PRS",
        )
        if not save_path:
            return

        try:
            self.prs = prs
            self.prs_path = Path(save_path)
            self._do_save(self.prs_path)
            self.modified = False
            self._update_title()
            fg = "#e0e0e0" if self.dark_mode else "black"
            self.file_label.config(
                text=self.prs_path.name, foreground=fg)
            self.personality_view.refresh()
            self._update_stats()
            self.size_label.config(
                text=f"{len(self.prs.to_bytes()):,} bytes")
            self.status_set(
                f"Built personality from {Path(config_path).name}")
            log_action("build_from_config", config=config_path,
                       output=save_path)
        except Exception as e:
            log_error("build_from_config", str(e), path=save_path)
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    # ─── JSON Export / Import ─────────────────────────────────────────

    def export_json(self):
        """Export the current PRS to a JSON file."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        initial_name = (self.prs_path.stem + ".json") if self.prs_path else "output.json"
        path = filedialog.asksaveasfilename(
            title="Export to JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All Files", "*.*")],
            initialfile=initial_name,
        )
        if not path:
            return

        try:
            from ..json_io import export_json as do_export
            do_export(self.prs, path)
            self.status_set(f"Exported to JSON: {Path(path).name}")
            log_action("export_json", path=path)
        except (PermissionError, FileNotFoundError) as e:
            messagebox.showerror("Error", f"File access error:\n{e}")
        except Exception as e:
            log_error("export_json", str(e), path=path)
            messagebox.showerror("Error", f"Failed to export JSON:\n{e}")

    def export_config(self):
        """Export the current PRS as an editable INI config file."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        initial_name = (self.prs_path.stem + ".ini") if self.prs_path else "config.ini"
        path = filedialog.asksaveasfilename(
            title="Export as Config",
            defaultextension=".ini",
            filetypes=[("Config files", "*.ini"), ("All Files", "*.*")],
            initialfile=initial_name,
        )
        if not path:
            return

        try:
            from ..config_builder import export_config as do_export
            source = str(self.prs_path) if self.prs_path else None
            do_export(self.prs, path, source_path=source)
            self.status_set(f"Exported config: {Path(path).name}")
            log_action("export_config", path=path)
        except (PermissionError, FileNotFoundError) as e:
            messagebox.showerror("Error", f"File access error:\n{e}")
        except Exception as e:
            log_error("export_config", str(e), path=path)
            messagebox.showerror("Error", f"Failed to export config:\n{e}")

    def import_json(self):
        """Import a PRS personality from a JSON file."""
        if self.modified:
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before importing?")
            if result is None:
                return
            if result:
                self.save_file()

        json_path = filedialog.askopenfilename(
            title="Import JSON",
            filetypes=[("JSON files", "*.json"), ("All Files", "*.*")],
        )
        if not json_path:
            return

        try:
            from ..json_io import json_to_dict, dict_to_prs
            d = json_to_dict(json_path)
            prs = dict_to_prs(d)
        except (PermissionError, FileNotFoundError) as e:
            messagebox.showerror("Error", f"File access error:\n{e}")
            return
        except Exception as e:
            log_error("import_json", str(e), path=json_path)
            messagebox.showerror("Error",
                                 f"Failed to import JSON:\n{e}")
            return

        save_path = filedialog.asksaveasfilename(
            title="Save Imported Personality",
            defaultextension=".PRS",
            filetypes=[("PRS Files", "*.PRS *.prs"), ("All Files", "*.*")],
            initialfile=Path(json_path).stem + ".PRS",
        )
        if not save_path:
            return

        try:
            self.prs = prs
            self.prs_path = Path(save_path)
            self._do_save(self.prs_path)
            self.modified = False
            self._update_title()
            fg = "#e0e0e0" if self.dark_mode else "black"
            self.file_label.config(
                text=self.prs_path.name, foreground=fg)
            self.personality_view.refresh()
            self._update_stats()
            self.size_label.config(
                text=f"{len(self.prs.to_bytes()):,} bytes")
            self.status_set(
                f"Imported from {Path(json_path).name}")
            log_action("import_json", json_path=json_path,
                       output=save_path)
        except Exception as e:
            log_error("import_json", str(e), path=save_path)
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    # ─── Merge PRS ───────────────────────────────────────────────────

    def merge_prs(self):
        """Merge systems from another PRS file into the current one."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        source_path = filedialog.askopenfilename(
            title="Select Source PRS to Merge From",
            filetypes=[("PRS Files", "*.PRS *.prs"), ("All Files", "*.*")],
        )
        if not source_path:
            return

        try:
            source_prs = parse_prs(Path(source_path))
        except Exception as e:
            messagebox.showerror("Error",
                                 f"Failed to read source file:\n{e}")
            return

        self.save_undo_snapshot("Merge PRS")

        try:
            from ..injector import merge_prs as do_merge
            stats = do_merge(self.prs, source_prs)
            total_added = stats['p25_added'] + stats['conv_added']
            total_skipped = stats['p25_skipped'] + stats['conv_skipped']

            self.mark_modified()
            self.personality_view.refresh()

            msg = f"Merged {total_added} systems from {Path(source_path).name}"
            if total_skipped:
                msg += f" ({total_skipped} skipped as duplicates)"
            self.status_set(msg)
            log_action("merge_prs", source=source_path,
                       p25_added=stats['p25_added'],
                       conv_added=stats['conv_added'],
                       p25_skipped=stats['p25_skipped'],
                       conv_skipped=stats['conv_skipped'])
        except Exception as e:
            log_error("merge_prs", str(e), source=source_path)
            messagebox.showerror("Error", f"Merge failed:\n{e}")

    # ─── Template Channels ────────────────────────────────────────────

    def add_template_channels(self):
        """Show dialog to add pre-built template channel sets."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        from ..templates import get_template_names, get_template_channels
        from ..injector import add_conv_system, make_conv_set
        from ..record_types import ConvSystemConfig

        templates = get_template_names()
        if not templates:
            messagebox.showinfo("Templates", "No templates available.")
            return

        win = tk.Toplevel(self.root)
        win.title("Add Template Channels")
        win.geometry("320x280")
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()

        frame = ttk.Frame(win, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Select a channel template to add:",
                  font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 8))

        selected = tk.StringVar(value=templates[0])
        for name in templates:
            ttk.Radiobutton(frame, text=name.upper(),
                            variable=selected,
                            value=name).pack(anchor=tk.W, padx=8, pady=2)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(16, 0))

        def on_ok():
            template_name = selected.get()
            win.destroy()

            try:
                channels_data = get_template_channels(template_name)
            except ValueError as e:
                messagebox.showerror("Error", str(e))
                return

            self.save_undo_snapshot("Add template channels")

            try:
                short_name = template_name.upper()[:8]
                conv_set = make_conv_set(short_name, channels_data)
                config = ConvSystemConfig(
                    system_name=short_name,
                    long_name=short_name,
                    conv_set_name=short_name,
                )
                add_conv_system(self.prs, config, conv_set=conv_set)

                self.mark_modified()
                self.personality_view.refresh()
                self.status_set(
                    f"Added {template_name.upper()} template "
                    f"({len(channels_data)} channels)")
                log_action("add_template", template=template_name,
                           channels=len(channels_data))
            except Exception as e:
                log_error("add_template", str(e),
                          template=template_name)
                messagebox.showerror("Error",
                                     f"Failed to add template:\n{e}")

        ttk.Button(btn_frame, text="Add", command=on_ok,
                   width=10).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=win.destroy,
                   width=10).pack(side=tk.RIGHT, padx=4)

    # ─── Radio Options Editor ─────────────────────────────────────────

    def edit_radio_options(self):
        """Open a dialog to view and edit platformConfig radio options."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        from ..option_maps import (
            list_platform_options, set_platform_option,
            extract_platform_xml, _create_default_platform_xml,
            _inject_platform_xml,
        )

        # Auto-create platformConfig XML if it doesn't exist
        xml_str = extract_platform_xml(self.prs)
        if xml_str is None:
            if messagebox.askyesno(
                    "No Platform Config",
                    "This personality has no platformConfig XML.\n"
                    "Create a default one?"):
                try:
                    default_xml = _create_default_platform_xml()
                    if not _inject_platform_xml(self.prs, default_xml):
                        messagebox.showerror(
                            "Error",
                            "Failed to create platform config.")
                        return
                    self.mark_modified()
                except Exception as e:
                    messagebox.showerror("Error",
                                         f"Failed to create config:\n{e}")
                    return
            else:
                return

        options = list_platform_options(self.prs)
        if not options:
            messagebox.showinfo("Radio Options",
                                "No platform options found.")
            return

        win = tk.Toplevel(self.root)
        win.title("Radio Options")
        win.geometry("700x500")
        win.transient(self.root)
        win.resizable(True, True)
        win.grab_set()

        # Header
        header = ttk.Frame(win, padding=(8, 4))
        header.pack(fill=tk.X)
        ttk.Label(header, text="Platform Configuration Options",
                  font=("", 11, "bold")).pack(anchor=tk.W)
        ttk.Label(header, text=f"{len(options)} options",
                  foreground="gray").pack(anchor=tk.W)

        # Scrollable options frame
        canvas = tk.Canvas(win, highlightthickness=0)
        vsb = ttk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4)

        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        # Track entry widgets and original values
        entries = {}
        current_section = None

        for i, (friendly, element, attr, val) in enumerate(options):
            # Section header
            if friendly != current_section:
                current_section = friendly
                sep_frame = ttk.Frame(inner)
                sep_frame.grid(row=i * 2, column=0, columnspan=3,
                               sticky=tk.EW, pady=(8, 2), padx=4)
                ttk.Label(sep_frame, text=friendly.upper(),
                          font=("", 9, "bold"),
                          foreground="gray").pack(anchor=tk.W)
                ttk.Separator(sep_frame,
                              orient=tk.HORIZONTAL).pack(fill=tk.X)

            row = ttk.Frame(inner)
            row.grid(row=i * 2 + 1, column=0, columnspan=3,
                     sticky=tk.EW, padx=8, pady=1)

            label_text = f"{element}.{attr}" if '/' in element else attr
            ttk.Label(row, text=label_text, width=35,
                      anchor=tk.W).pack(side=tk.LEFT)

            entry = ttk.Entry(row, width=30)
            entry.insert(0, val)
            entry.pack(side=tk.LEFT, padx=4)

            entries[(element, attr)] = (entry, val)

        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Buttons
        btn_frame = ttk.Frame(win, padding=8)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        def on_apply():
            changed = 0
            errors = []
            self.save_undo_snapshot("Edit radio options")

            for (element, attr), (entry_widget, orig_val) in entries.items():
                new_val = entry_widget.get().strip()
                if new_val != orig_val:
                    # Resolve the section name for set_platform_option
                    section = element.split('/')[0] if '/' in element else element
                    try:
                        set_platform_option(self.prs, section, attr, new_val)
                        changed += 1
                    except Exception as e:
                        errors.append(f"{element}.{attr}: {e}")

            if errors:
                messagebox.showerror(
                    "Errors",
                    f"Failed to set {len(errors)} option(s):\n\n" +
                    "\n".join(errors[:10]))

            if changed:
                self.mark_modified()
                self.status_set(f"Updated {changed} radio option(s)")
                log_action("edit_options", changed=changed)

            canvas.unbind_all("<MouseWheel>")
            win.destroy()

        def on_cancel():
            canvas.unbind_all("<MouseWheel>")
            win.destroy()

        ttk.Button(btn_frame, text="Apply", command=on_apply,
                   width=10).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=on_cancel,
                   width=10).pack(side=tk.RIGHT, padx=4)

        win.protocol("WM_DELETE_WINDOW", on_cancel)

    # ─── Button Configurator ──────────────────────────────────────────

    def _show_button_configurator(self):
        """Open the programmable button configurator dialog."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        from .button_config import ButtonConfigurator
        ButtonConfigurator(self.root, self)

    # ─── Compare ──────────────────────────────────────────────────────

    def compare_files(self):
        """Compare two PRS files and show side-by-side diff viewer."""
        from ..comparison import compare_prs, compare_prs_files, format_comparison
        from .diff_viewer import DiffViewer

        # If we have a file loaded, use it as file A
        if self.prs and self.prs_path:
            path_b = filedialog.askopenfilename(
                title="Select PRS file to compare against",
                filetypes=[("PRS Files", "*.PRS *.prs"),
                           ("All Files", "*.*")])
            if not path_b:
                return

            try:
                prs_b = parse_prs(Path(path_b))
                name_a = self.prs_path.name
                name_b = Path(path_b).name
                prs_a = self.prs
            except Exception as e:
                messagebox.showerror("Error", f"Compare failed:\n{e}")
                return
        else:
            # No file loaded — pick both files
            path_a = filedialog.askopenfilename(
                title="Select first PRS file (A)",
                filetypes=[("PRS Files", "*.PRS *.prs"),
                           ("All Files", "*.*")])
            if not path_a:
                return
            path_b = filedialog.askopenfilename(
                title="Select second PRS file (B)",
                filetypes=[("PRS Files", "*.PRS *.prs"),
                           ("All Files", "*.*")])
            if not path_b:
                return

            try:
                prs_a = parse_prs(Path(path_a))
                prs_b = parse_prs(Path(path_b))
                name_a = Path(path_a).name
                name_b = Path(path_b).name
            except Exception as e:
                messagebox.showerror("Error", f"Compare failed:\n{e}")
                return

        # Also populate the text-based details tab
        diffs = compare_prs(prs_a, prs_b)
        lines = format_comparison(
            diffs,
            str(self.prs_path) if self.prs and self.prs_path else name_a,
            path_b)
        self.notebook.select(2)  # Details tab
        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert("1.0", "\n".join(lines))
        self.details_text.config(state=tk.DISABLED)

        added = sum(1 for d in diffs if d[0] == "ADDED")
        removed = sum(1 for d in diffs if d[0] == "REMOVED")
        changed = sum(1 for d in diffs if d[0] == "CHANGED")
        self.status_set(
            f"Compare: {added} added, {removed} removed, {changed} changed")

        # Launch the side-by-side visual diff viewer
        DiffViewer(self.root, prs_a, prs_b, name_a, name_b)

    # ─── Settings ─────────────────────────────────────────────────────

    def show_settings(self):
        """Open the settings dialog."""
        dialog = SettingsDialog(self.root, self)
        if dialog.result:
            self.settings = dialog.result
            self.status_set("Settings saved")

    # ─── Quick-add toolbar actions ──────────────────────────────────

    def _quick_add_system(self):
        """Quick-add dialog: choose P25 Trunked or Conventional."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        win = tk.Toplevel(self.root)
        win.title("Add System")
        win.geometry("280x150")
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()

        frame = ttk.Frame(win, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Select system type:",
                  font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 8))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=4)

        def add_p25():
            win.destroy()
            self.personality_view._add_p25_system_dialog()

        def add_conv():
            win.destroy()
            self.personality_view._add_conv_system_dialog()

        ttk.Button(btn_frame, text="P25 Trunked", command=add_p25,
                   width=14).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Conventional", command=add_conv,
                   width=14).pack(side=tk.LEFT, padx=4)

        ttk.Button(frame, text="Cancel", command=win.destroy,
                   width=10).pack(pady=(12, 0))

        win.bind("<Escape>", lambda e: win.destroy())

    def _quick_add_talkgroups(self):
        """Quick-add talkgroups: pick target group set, then add dialog."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        parsed = self._parse_sets()
        groups = parsed.get('groups') or []

        if not groups:
            if messagebox.askyesno(
                    "No Group Sets",
                    "No group sets exist. Create a new one?"):
                self.personality_view._add_group_set_dialog()
            return

        if len(groups) == 1:
            self.personality_view._add_talkgroup_dialog(groups[0].name)
            return

        # Multiple sets -- ask which one
        win = tk.Toplevel(self.root)
        win.title("Select Group Set")
        win.geometry("300x160")
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()

        frame = ttk.Frame(win, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Add talkgroup to which set?",
                  font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 8))

        selected = tk.StringVar(value=groups[0].name)
        combo = ttk.Combobox(frame, textvariable=selected, state="readonly",
                             values=[g.name for g in groups])
        combo.pack(fill=tk.X, pady=4)

        def on_ok():
            name = selected.get()
            win.destroy()
            self.personality_view._add_talkgroup_dialog(name)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_frame, text="OK", command=on_ok,
                   width=10).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=win.destroy,
                   width=10).pack(side=tk.RIGHT, padx=4)

        win.bind("<Return>", lambda e: on_ok())
        win.bind("<Escape>", lambda e: win.destroy())

    def _quick_add_channels(self):
        """Quick-add channels: pick target conv set, then add dialog."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        parsed = self._parse_sets()
        conv = parsed.get('conv') or []

        if not conv:
            if messagebox.askyesno(
                    "No Conv Sets",
                    "No conventional channel sets exist. Create a new one?"):
                self.personality_view._add_conv_set_dialog()
            return

        if len(conv) == 1:
            self.personality_view._add_channel_dialog(conv[0].name)
            return

        # Multiple sets -- ask which one
        win = tk.Toplevel(self.root)
        win.title("Select Conv Set")
        win.geometry("300x160")
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()

        frame = ttk.Frame(win, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Add channel to which set?",
                  font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 8))

        selected = tk.StringVar(value=conv[0].name)
        combo = ttk.Combobox(frame, textvariable=selected, state="readonly",
                             values=[c.name for c in conv])
        combo.pack(fill=tk.X, pady=4)

        def on_ok():
            name = selected.get()
            win.destroy()
            self.personality_view._add_channel_dialog(name)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_frame, text="OK", command=on_ok,
                   width=10).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=win.destroy,
                   width=10).pack(side=tk.RIGHT, padx=4)

        win.bind("<Return>", lambda e: on_ok())
        win.bind("<Escape>", lambda e: win.destroy())

    def _quick_import_rr(self):
        """Switch to the Import tab's API section for RadioReference import."""
        if not self.prs:
            messagebox.showwarning("Warning",
                                    "Load a PRS file first, then import.")
            return

        # Switch to import tab and focus the API sub-tab
        self.notebook.select(0)  # Import tab
        if hasattr(self.import_panel, 'source_nb'):
            # Select the API tab (index 1)
            try:
                self.import_panel.source_nb.select(1)
            except Exception:
                pass
        self.status_set("Enter RadioReference URL/SID and credentials, "
                        "then click Fetch")

    # ─── Capacity indicator ──────────────────────────────────────────

    def _update_capacity_label(self):
        """Update the toolbar capacity indicator."""
        if not self.prs:
            self._capacity_label.config(text="")
            return
        try:
            from ..validation import estimate_capacity
            cap = estimate_capacity(self.prs)
            ch = cap.get('channels', {})
            pct = ch.get('pct', 0)
            self._capacity_label.config(
                text=f"Channels: {ch.get('used', 0)}/{ch.get('max', 1250)}"
                     f" ({pct:.0f}%)")
        except Exception:
            self._capacity_label.config(text="")

    def _capacity_report(self):
        """Show a detailed capacity report dialog."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        try:
            from ..validation import estimate_capacity
            cap = estimate_capacity(self.prs)
        except Exception as e:
            messagebox.showerror("Error", f"Capacity report failed:\n{e}")
            return

        self.notebook.select(2)  # Details tab
        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)

        lines = ["Capacity Report", "=" * 50, ""]

        for key, label in [
            ('systems', 'Systems'),
            ('channels', 'Channels'),
        ]:
            info = cap.get(key, {})
            used = info.get('used', 0)
            mx = info.get('max', 0)
            pct = info.get('pct', 0)
            remaining = mx - used
            lines.append(f"{label}: {used}/{mx} ({pct:.1f}%) "
                         f"-- {remaining} remaining")

        lines.append("")

        # Talkgroups
        tg = cap.get('talkgroups', {})
        if tg:
            lines.append(f"Talkgroups: {tg.get('used', 0)} total")
            for name, count in tg.get('details', {}).items():
                lines.append(f"  {name}: {count}")
            lines.append("")

        # Trunk freqs
        tf = cap.get('trunk_freqs', {})
        if tf:
            lines.append(f"Trunk Frequencies: {tf.get('used', 0)} total")
            for name, count in tf.get('details', {}).items():
                lines.append(f"  {name}: {count}")
            lines.append("")

        # Conv channels
        cc = cap.get('conv_channels', {})
        if cc:
            lines.append(f"Conv Channels: {cc.get('used', 0)} total")
            for name, count in cc.get('details', {}).items():
                lines.append(f"  {name}: {count}")
            lines.append("")

        # IDEN sets
        iden = cap.get('iden_sets', {})
        if iden:
            lines.append(f"IDEN Sets: {iden.get('used', 0)} total")
            for name, count in iden.get('details', {}).items():
                lines.append(f"  {name}: {count} active")
            lines.append("")

        # Scan TG headroom
        scan = cap.get('scan_tg_headroom', {})
        if scan:
            lines.append("Scan Talkgroup Headroom:")
            for name, info in scan.items():
                lines.append(f"  {name}: {info.get('used', 0)}/"
                             f"{info.get('max', 127)} "
                             f"({info.get('remaining', 0)} remaining)")
            lines.append("")

        # Zones
        zones = cap.get('zones_needed', {})
        if zones:
            lines.append(f"Zones needed: {zones.get('zones_min', 0)} "
                         f"(max {zones.get('max', 50)})")
            lines.append("")

        # File info
        fi = cap.get('file_size', {})
        if fi:
            lines.append(f"File size: {fi.get('bytes', 0):,} bytes, "
                         f"{fi.get('sections', 0)} sections")

        self.details_text.insert("1.0", "\n".join(lines))
        self.details_text.config(state=tk.DISABLED)
        self.status_set("Capacity report generated")

    # ─── Context-aware keyboard actions ──────────────────────────────

    def _delete_selected(self):
        """Delete the currently selected item(s) from the personality tree."""
        if not self.prs:
            return
        if not hasattr(self, 'personality_view'):
            return

        pv = self.personality_view
        selection = pv.tree.selection()
        if not selection:
            return

        iid = selection[0]
        meta = pv._item_meta.get(iid, {})
        item_type = meta.get("type", "")

        if item_type == "system":
            name = meta.get("name", "")
            cls = meta.get("class_name", "")
            if name and cls:
                pv._delete_system(cls, name)
        elif item_type == "system_config":
            long_name = meta.get("long_name", "")
            if long_name:
                pv._delete_system_config(long_name)
        elif item_type in ("group_set", "trunk_set", "conv_set", "iden_set"):
            name = meta.get("name", "")
            if name:
                pv._delete_set(item_type, name)
        elif item_type == "talkgroup":
            gid = meta.get("group_id", 0)
            parent_iid = pv.tree.parent(iid)
            parent_meta = pv._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            if set_name and gid:
                pv._delete_talkgroup(set_name, gid)

    def _rename_selected(self):
        """Rename the currently selected system or set."""
        if not self.prs:
            return
        if not hasattr(self, 'personality_view'):
            return

        pv = self.personality_view
        selection = pv.tree.selection()
        if not selection:
            return

        iid = selection[0]
        meta = pv._item_meta.get(iid, {})
        item_type = meta.get("type", "")

        if item_type == "system":
            name = meta.get("name", "")
            cls = meta.get("class_name", "")
            if name and cls:
                pv._rename_system(cls, name)
        elif item_type in ("group_set", "trunk_set", "conv_set", "iden_set"):
            name = meta.get("name", "")
            if name:
                pv._rename_set(item_type, name)

    def _insert_context_aware(self):
        """Insert key: add new item based on what's selected in the tree."""
        if not self.prs:
            return
        if not hasattr(self, 'personality_view'):
            return

        pv = self.personality_view
        selection = pv.tree.selection()

        if not selection:
            # Nothing selected -- show quick-add system menu
            self._quick_add_system()
            return

        iid = selection[0]
        meta = pv._item_meta.get(iid, {})
        item_type = meta.get("type", "")

        if item_type == "group_set":
            name = meta.get("name", "")
            if name:
                pv._add_talkgroup_dialog(name)
        elif item_type == "conv_set":
            name = meta.get("name", "")
            if name:
                pv._add_channel_dialog(name)
        elif item_type == "trunk_set":
            name = meta.get("name", "")
            if name:
                pv._add_frequency_dialog(name)
        elif item_type == "system_category":
            cls = meta.get("class_name", "")
            if cls == "CP25TrkSystem":
                pv._add_p25_system_dialog()
            elif cls == "CConvSystem":
                pv._add_conv_system_dialog()
        elif item_type == "set_category":
            set_type = meta.get("set_type", "")
            if set_type == "group":
                pv._add_group_set_dialog()
            elif set_type == "trunk":
                pv._add_trunk_set_dialog()
            elif set_type == "conv":
                pv._add_conv_set_dialog()
            elif set_type == "iden":
                pv._add_standard_iden_set()
        elif item_type == "talkgroup":
            # Add talkgroup to the parent set
            parent_iid = pv.tree.parent(iid)
            parent_meta = pv._item_meta.get(parent_iid, {})
            name = parent_meta.get("name", "")
            if name:
                pv._add_talkgroup_dialog(name)
        else:
            # Fallback: show quick-add menu
            self._quick_add_system()

    # ─── Keyboard Shortcuts ──────────────────────────────────────────

    def show_shortcuts(self):
        """Show keyboard shortcuts dialog."""
        shortcuts = [
            ("File:", ""),
            ("Ctrl+N", "New blank personality"),
            ("Ctrl+O", "Open PRS file"),
            ("Ctrl+S", "Save file"),
            ("Ctrl+Shift+S", "Save As..."),
            ("", ""),
            ("Edit:", ""),
            ("Ctrl+Z", "Undo last injection"),
            ("Ctrl+Y", "Redo"),
            ("Ctrl+Shift+Z", "Redo (alternative)"),
            ("Delete", "Delete selected item(s)"),
            ("F2", "Rename selected item"),
            ("Insert", "Add new item (context-aware)"),
            ("Alt+Up", "Move selected up"),
            ("Alt+Down", "Move selected down"),
            ("", ""),
            ("Navigation:", ""),
            ("Ctrl+F", "Search/filter personality tree"),
            ("Ctrl+D", "Compare PRS files"),
            ("", ""),
            ("Import/Export:", ""),
            ("Ctrl+E", "Export JSON"),
            ("Ctrl+I", "Import CSV or JSON"),
            ("Ctrl+M", "Merge PRS"),
            ("Ctrl+T", "Add template channels"),
            ("", ""),
            ("Tools:", ""),
            ("F5", "Validate"),
            ("F8", "Capacity report"),
            ("Ctrl+G", "Generate HTML report"),
            ("", ""),
            ("Personality Tree:", ""),
            ("Double-click", "Show item details"),
            ("Right-click", "Context menu (delete, export, copy)"),
            ("", ""),
            ("Import Panel:", ""),
            ("Double-click/Space", "Toggle talkgroup selection"),
            ("Right-click", "Select/deselect talkgroups"),
            ("", ""),
            ("General:", ""),
            ("Drag-and-drop", "Drop .PRS file onto window to open"),
            ("F1", "Show this dialog"),
        ]

        win = tk.Toplevel(self.root)
        win.title("Keyboard Shortcuts")
        win.geometry("440x580")
        win.transient(self.root)
        win.resizable(False, True)

        # Scrollable frame for many shortcuts
        canvas = tk.Canvas(win, highlightthickness=0)
        vsb = ttk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        frame = ttk.Frame(canvas, padding=16)
        canvas.create_window((0, 0), window=frame, anchor=tk.NW)

        for key, desc in shortcuts:
            row = ttk.Frame(frame)
            row.pack(fill=tk.X, pady=1)
            if not key and not desc:
                ttk.Separator(row, orient=tk.HORIZONTAL).pack(
                    fill=tk.X, pady=4)
            elif not desc:
                ttk.Label(row, text=key,
                          font=("", 10, "bold")).pack(anchor=tk.W)
            else:
                ttk.Label(row, text=key, width=20,
                          anchor=tk.W,
                          font=("Consolas", 10)).pack(side=tk.LEFT)
                ttk.Label(row, text=desc).pack(side=tk.LEFT, padx=4)

        btn = ttk.Button(frame, text="Close", command=win.destroy, width=10)
        btn.pack(pady=(12, 0))

        frame.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _on_close():
            canvas.unbind_all("<MouseWheel>")
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_close)
        win.bind("<Escape>", lambda e: _on_close())

    # ─── Log Viewer ──────────────────────────────────────────────────

    def show_log(self):
        """Show log file contents in a new window."""
        log_path = Path.home() / '.quickprs' / 'logs' / 'quickprs.log'

        win = tk.Toplevel(self.root)
        win.title("QuickPRS Log")
        win.geometry("800x500")
        win.transient(self.root)

        frame = ttk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        text = tk.Text(frame, wrap=tk.NONE, state=tk.DISABLED,
                       font=("Consolas", 9))
        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        def load_log():
            text.config(state=tk.NORMAL)
            text.delete("1.0", tk.END)
            if log_path.exists():
                try:
                    content = log_path.read_text(encoding='utf-8')
                    text.insert("1.0", content)
                    text.see(tk.END)  # Scroll to bottom
                except Exception as e:
                    text.insert("1.0", f"Error reading log: {e}")
            else:
                text.insert("1.0", f"No log file found at:\n{log_path}")
            text.config(state=tk.DISABLED)

        load_log()

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(btn_frame, text="Refresh", command=load_log,
                   width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Close", command=win.destroy,
                   width=10).pack(side=tk.RIGHT, padx=2)

    # ─── About ───────────────────────────────────────────────────────

    def show_about(self):
        messagebox.showinfo(
            "About QuickPRS",
            f"QuickPRS v{__version__}\n"
            "Harris RPM Personality Tool\n\n"
            "Reverse-engineers .PRS binary format for\n"
            "programmatic radio personality management.\n\n"
            "Supports: XG-100P / XG-75P\n"
            "RadioReference paste + SOAP API import\n\n"
            "Features:\n"
            "  - Binary-identical roundtrip parsing\n"
            "  - P25 trunked, conventional, P25 conv systems\n"
            "  - Bulk talkgroup/frequency injection\n"
            "  - IDEN table generation\n"
            "  - PRS file comparison\n"
            "  - CSV export")

    # ─── Frequency Reference ─────────────────────────────────────

    def _show_system_database(self):
        """Open the P25 system database browser dialog."""
        from .system_wizard import SystemDatabaseDialog
        SystemDatabaseDialog(self.root, self)

    def _show_system_wizard(self):
        """Open the multi-step system import wizard."""
        if not self.prs:
            from tkinter import messagebox
            messagebox.showwarning("Warning", "No file loaded.")
            return
        from .system_wizard import SystemWizard
        SystemWizard(self.root, self)

    def _show_import_wizard(self):
        """Open the unified import wizard dialog."""
        from .import_wizard import ImportWizard
        ImportWizard(self.root, self)

    def _show_cleanup_dialog(self):
        """Show the cleanup/duplicate detection dialog."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        from ..cleanup import (
            find_duplicates, find_unused_sets,
            format_duplicates_report, format_unused_report,
        )

        dupes = find_duplicates(self.prs)
        unused = find_unused_sets(self.prs)

        win = tk.Toplevel(self.root)
        win.title("Cleanup - Duplicate Detection")
        win.geometry("700x500")
        win.transient(self.root)

        # Results text
        text = tk.Text(win, wrap=tk.WORD, font=("Consolas", 10),
                       state=tk.DISABLED, padx=8, pady=8)
        vsb = ttk.Scrollbar(win, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=vsb.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        lines = []
        lines.append("=== Duplicate Detection Report ===")
        lines.append("")
        lines.extend(format_duplicates_report(dupes))
        lines.append("")
        lines.extend(format_unused_report(unused))

        # Summary
        total_dupes = (
            sum(c - 1 for _, _, c in dupes['duplicate_tgs']) +
            sum(c - 1 for _, _, c in dupes['duplicate_freqs']) +
            sum(c - 1 for _, _, c in dupes['duplicate_channels'])
        )
        total_cross = len(dupes['cross_set_tgs'])
        total_unused = sum(len(v) for v in unused.values())
        lines.append("")
        lines.append(f"Summary: {total_dupes} duplicates, "
                     f"{total_cross} cross-set TGs, "
                     f"{total_unused} unused sets")

        text.configure(state=tk.NORMAL)
        text.insert(tk.END, "\n".join(lines))
        text.configure(state=tk.DISABLED)

        # Button bar
        btn_frame = ttk.Frame(win, padding=8)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(btn_frame, text="Close",
                   command=win.destroy).pack(side=tk.RIGHT, padx=2)

        self.status_set("Cleanup report generated")

    def _show_scan_priority(self):
        """Delegate to personality view's scan priority dialog."""
        if not self.prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return
        self.personality_view._scan_priority_dialog()

    def _show_freq_reference(self):
        """Show frequency/tone reference dialog."""
        from ..freq_tools import (
            CTCSS_TONES, DCS_CODES,
            calculate_repeater_offset, freq_to_channel,
            format_ctcss_table, format_dcs_table,
        )

        win = tk.Toplevel(self.root)
        win.title("Frequency Reference")
        win.geometry("700x520")
        win.transient(self.root)

        nb = ttk.Notebook(win)
        nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # --- CTCSS tab ---
        ctcss_frame = ttk.Frame(nb, padding=8)
        nb.add(ctcss_frame, text="CTCSS Tones")

        ctcss_text = tk.Text(ctcss_frame, wrap=tk.NONE,
                             font=("Consolas", 10), state=tk.DISABLED,
                             height=20)
        ctcss_vsb = ttk.Scrollbar(ctcss_frame, orient=tk.VERTICAL,
                                  command=ctcss_text.yview)
        ctcss_text.configure(yscrollcommand=ctcss_vsb.set)
        ctcss_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ctcss_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        ctcss_text.config(state=tk.NORMAL)
        ctcss_text.insert("1.0", "\n".join(format_ctcss_table()))
        ctcss_text.config(state=tk.DISABLED)

        # --- DCS tab ---
        dcs_frame = ttk.Frame(nb, padding=8)
        nb.add(dcs_frame, text="DCS Codes")

        dcs_text = tk.Text(dcs_frame, wrap=tk.NONE,
                           font=("Consolas", 10), state=tk.DISABLED,
                           height=20)
        dcs_vsb = ttk.Scrollbar(dcs_frame, orient=tk.VERTICAL,
                                command=dcs_text.yview)
        dcs_text.configure(yscrollcommand=dcs_vsb.set)
        dcs_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        dcs_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        dcs_text.config(state=tk.NORMAL)
        dcs_text.insert("1.0", "\n".join(format_dcs_table()))
        dcs_text.config(state=tk.DISABLED)

        # --- Repeater Offset tab ---
        offset_frame = ttk.Frame(nb, padding=8)
        nb.add(offset_frame, text="Repeater Offset")

        input_row = ttk.Frame(offset_frame)
        input_row.pack(fill=tk.X, pady=4)
        ttk.Label(input_row, text="Frequency (MHz):").pack(side=tk.LEFT)
        offset_var = tk.StringVar()
        offset_entry = ttk.Entry(input_row, textvariable=offset_var,
                                 width=14)
        offset_entry.pack(side=tk.LEFT, padx=4)

        offset_result = tk.Text(offset_frame, wrap=tk.WORD,
                                font=("Consolas", 11), height=8,
                                state=tk.DISABLED)
        offset_result.pack(fill=tk.BOTH, expand=True, pady=4)

        def calc_offset():
            try:
                freq = float(offset_var.get().strip())
            except ValueError:
                return
            result = calculate_repeater_offset(freq)
            offset_result.config(state=tk.NORMAL)
            offset_result.delete("1.0", tk.END)
            if result is None:
                offset_result.insert("1.0",
                                     f"{freq:.4f} MHz is not in a "
                                     "standard repeater band.\n\n"
                                     "Supported bands:\n"
                                     "  2m:   144-148 MHz\n"
                                     "  220:  222-225 MHz\n"
                                     "  70cm: 420-450 MHz\n"
                                     "  900:  902-928 MHz")
            else:
                off, direction = result
                if direction == "+":
                    input_freq = freq + off
                else:
                    input_freq = freq - off
                offset_result.insert("1.0",
                                     f"Output (RX): {freq:.4f} MHz\n"
                                     f"Input  (TX): {input_freq:.4f} MHz\n"
                                     f"Offset:      {direction}{off:.1f} MHz")
            offset_result.config(state=tk.DISABLED)

        ttk.Button(input_row, text="Calculate", width=10,
                   command=calc_offset).pack(side=tk.LEFT, padx=4)
        offset_entry.bind("<Return>", lambda e: calc_offset())

        # --- Channel ID tab ---
        ch_frame = ttk.Frame(nb, padding=8)
        nb.add(ch_frame, text="Channel Identifier")

        ch_input_row = ttk.Frame(ch_frame)
        ch_input_row.pack(fill=tk.X, pady=4)
        ttk.Label(ch_input_row, text="Frequency (MHz):").pack(side=tk.LEFT)
        ch_var = tk.StringVar()
        ch_entry = ttk.Entry(ch_input_row, textvariable=ch_var, width=14)
        ch_entry.pack(side=tk.LEFT, padx=4)

        ch_result = tk.Text(ch_frame, wrap=tk.WORD,
                            font=("Consolas", 11), height=4,
                            state=tk.DISABLED)
        ch_result.pack(fill=tk.X, pady=4)

        def identify_channel():
            try:
                freq = float(ch_var.get().strip())
            except ValueError:
                return
            result = freq_to_channel(freq)
            ch_result.config(state=tk.NORMAL)
            ch_result.delete("1.0", tk.END)
            if result is None:
                ch_result.insert("1.0",
                                 f"{freq:.4f} MHz: not a recognized "
                                 "service channel\n\n"
                                 "Supported: FRS, GMRS, MURS, "
                                 "Marine VHF, NOAA")
            else:
                service, ch_num = result
                ch_result.insert("1.0",
                                 f"{freq:.4f} MHz = "
                                 f"{service} Channel {ch_num}")
            ch_result.config(state=tk.DISABLED)

        ttk.Button(ch_input_row, text="Identify", width=10,
                   command=identify_channel).pack(side=tk.LEFT, padx=4)
        ch_entry.bind("<Return>", lambda e: identify_channel())

        # Close button
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(btn_frame, text="Close", width=10,
                   command=win.destroy).pack(side=tk.RIGHT)

    # ─── Theme ─────────────────────────────────────────────────────

    def _apply_theme(self):
        """Apply theme based on system preference or current setting."""
        if HAS_DARKDETECT:
            system_theme = darkdetect.theme()
            self.dark_mode = (system_theme == "Dark")

        if HAS_SV_TTK:
            sv_ttk.set_theme("dark" if self.dark_mode else "light")
        else:
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

    def _toggle_theme(self):
        """Toggle between dark and light theme."""
        self.dark_mode = not self.dark_mode
        if HAS_SV_TTK:
            sv_ttk.set_theme("dark" if self.dark_mode else "light")

        # Update text widget colors for details tab
        if hasattr(self, 'details_text'):
            if self.dark_mode:
                self.details_text.config(bg="#1c1c1c", fg="#e0e0e0",
                                          insertbackground="#e0e0e0")
            else:
                self.details_text.config(bg="white", fg="black",
                                          insertbackground="black")

        # Update file label foreground
        if hasattr(self, 'file_label'):
            fg = "#e0e0e0" if self.dark_mode else "black"
            if not self.prs_path:
                fg = "gray"
            self.file_label.config(foreground=fg)

    # ─── Set parsing helper ────────────────────────────────────────

    def _parse_sets(self):
        """Parse all group/trunk/conv/iden sets from current PRS.

        Returns dict with keys 'groups', 'trunk', 'conv', 'iden'.
        Each value is a list of set objects, or None on error.
        """
        if not self.prs:
            return {'groups': None, 'trunk': None, 'conv': None, 'iden': None}

        from ..record_types import (
            parse_class_header, parse_group_section,
            parse_trunk_channel_section, parse_conv_channel_section,
            parse_iden_section,
        )
        from ..binary_io import read_uint16_le

        result = {'groups': None, 'trunk': None, 'conv': None, 'iden': None}

        # Group sets
        grp_sec = self.prs.get_section_by_class("CP25Group")
        set_sec = self.prs.get_section_by_class("CP25GroupSet")
        if grp_sec and set_sec:
            try:
                _, _, _, ds = parse_class_header(set_sec.raw, 0)
                fc, _ = read_uint16_le(set_sec.raw, ds)
                _, _, _, gd = parse_class_header(grp_sec.raw, 0)
                result['groups'] = parse_group_section(
                    grp_sec.raw, gd, len(grp_sec.raw), fc)
            except Exception as e:
                log_error("parse_sets", f"groups: {e}")

        # Trunk sets
        ch_sec = self.prs.get_section_by_class("CTrunkChannel")
        ts_sec = self.prs.get_section_by_class("CTrunkSet")
        if ch_sec and ts_sec:
            try:
                _, _, _, ds = parse_class_header(ts_sec.raw, 0)
                fc, _ = read_uint16_le(ts_sec.raw, ds)
                _, _, _, cd = parse_class_header(ch_sec.raw, 0)
                result['trunk'] = parse_trunk_channel_section(
                    ch_sec.raw, cd, len(ch_sec.raw), fc)
            except Exception as e:
                log_error("parse_sets", f"trunk: {e}")

        # Conv sets
        conv_sec = self.prs.get_section_by_class("CConvChannel")
        conv_set_sec = self.prs.get_section_by_class("CConvSet")
        if conv_sec and conv_set_sec:
            try:
                _, _, _, ds = parse_class_header(conv_set_sec.raw, 0)
                fc, _ = read_uint16_le(conv_set_sec.raw, ds)
                _, _, _, cd = parse_class_header(conv_sec.raw, 0)
                result['conv'] = parse_conv_channel_section(
                    conv_sec.raw, cd, len(conv_sec.raw), fc)
            except Exception as e:
                log_error("parse_sets", f"conv: {e}")

        # IDEN sets
        elem_sec = self.prs.get_section_by_class("CDefaultIdenElem")
        ids_sec = self.prs.get_section_by_class("CIdenDataSet")
        if elem_sec and ids_sec:
            try:
                _, _, _, ds = parse_class_header(ids_sec.raw, 0)
                fc, _ = read_uint16_le(ids_sec.raw, ds)
                _, _, _, ed = parse_class_header(elem_sec.raw, 0)
                result['iden'] = parse_iden_section(
                    elem_sec.raw, ed, len(elem_sec.raw), fc)
            except Exception as e:
                log_error("parse_sets", f"iden: {e}")

        return result

    # ─── Helpers ─────────────────────────────────────────────────────

    def _refresh_recent_menu(self):
        """Rebuild the recent files submenu."""
        self.recent_menu.delete(0, tk.END)
        recent = get_recent_files(self.settings)
        if not recent:
            self.recent_menu.add_command(label="(none)", state=tk.DISABLED)
        else:
            for filepath in recent:
                name = Path(filepath).name
                self.recent_menu.add_command(
                    label=f"{name}  ({filepath})",
                    command=lambda p=filepath: self._open_path(p))
            self.recent_menu.add_separator()
            self.recent_menu.add_command(
                label="Clear Recent Files",
                command=self._clear_recent_files)

    def _clear_recent_files(self):
        """Clear the recent files list."""
        self.settings["recent_files"] = []
        save_settings(self.settings)
        self._refresh_recent_menu()

    def _update_title(self):
        title = f"QuickPRS v{__version__}"
        if self.prs_path:
            title += f" - {self.prs_path.name}"
        if self.modified:
            title += " *"
        self.root.title(title)

    def status_set(self, text, color=""):
        self.status_label.config(text=text, foreground=color)
        self.root.update_idletasks()

    def _update_stats(self):
        """Update the status bar stats from current PRS data."""
        if not self.prs:
            self.stats_label.config(text="")
            return

        parts = []

        # Count systems
        sys_count = 0
        for cls in ('CP25TrkSystem', 'CConvSystem', 'CP25ConvSystem'):
            sys_count += len(self.prs.get_sections_by_class(cls))
        parts.append(f"{sys_count} sys")

        parsed = self._parse_sets()
        if parsed['groups']:
            total = sum(len(s.groups) for s in parsed['groups'])
            parts.append(f"{total} TGs")
        if parsed['trunk']:
            total = sum(len(s.channels) for s in parsed['trunk'])
            parts.append(f"{total} freqs")
        if parsed['conv']:
            total = sum(len(s.channels) for s in parsed['conv'])
            parts.append(f"{total} conv ch")

        self.stats_label.config(text=" | ".join(parts))

    def _restore_geometry(self):
        """Restore window size and position from settings."""
        w = self.settings.get("window_width", 1400)
        h = self.settings.get("window_height", 850)
        x = self.settings.get("window_x")
        y = self.settings.get("window_y")
        if x is not None and y is not None:
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        else:
            self.root.geometry(f"{w}x{h}")

    def _save_geometry(self):
        """Save current window size and position to settings."""
        from .settings import save_settings
        geo = self.root.geometry()
        # geometry string is "WxH+X+Y"
        parts = geo.replace('x', '+').split('+')
        if len(parts) >= 4:
            self.settings["window_width"] = int(parts[0])
            self.settings["window_height"] = int(parts[1])
            self.settings["window_x"] = int(parts[2])
            self.settings["window_y"] = int(parts[3])
            save_settings(self.settings)

    def _on_close(self):
        if self.modified:
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?")
            if result is None:  # Cancel
                return
            if result:  # Yes
                self.save_file()
        self._save_geometry()
        self.root.destroy()


def main(filepath=None):
    root = tk.Tk()
    app = QuickPRSApp(root)
    root.protocol("WM_DELETE_WINDOW", app._on_close)

    # Open file passed via command line (e.g., QuickPRS.exe "file.PRS")
    if filepath:
        root.after(100, lambda: app._open_path(filepath))

    root.mainloop()


if __name__ == "__main__":
    main()
