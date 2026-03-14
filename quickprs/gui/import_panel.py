"""Import panel — paste or API-based import + injection controls.

Primary workflow (Paste):
  1. Go to RadioReference.com system page
  2. Ctrl+A, Ctrl+C to copy the whole page
  3. Paste into text area, click Parse Page
  4. Filter by category/tag, set a name
  5. Click Inject — creates group set, trunk set, and IDEN set

API workflow (requires premium account + app key):
  1. Enter RadioReference URL or system ID
  2. Enter API credentials
  3. Click Fetch, browse/filter by category
  4. Click Inject
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading

from ..radioreference import (
    RadioReferenceAPI, RadioReferenceScraper,
    parse_rr_url, build_injection_data,
    parse_pasted_talkgroups, parse_pasted_frequencies,
    parse_full_page, parse_pasted_conv_channels,
    conv_channels_to_set_data,
    make_short_name, make_long_name, make_set_name,
    calculate_tx_freq, build_standard_iden_entries,
    build_ecc_from_sites,
    HAS_ZEEP, HAS_SCRAPING,
    RRSystem, RRTalkgroup,
    MODE_CODES, MODE_GROUPS, ENCRYPTION_LEVELS,
)
from ..iden_library import (
    auto_select_template_key, find_matching_iden_set, get_template,
    get_default_name,
)
from ..injector import (
    add_group_set, add_trunk_set,
    make_group_set, make_trunk_set, make_iden_set, make_conv_set,
    add_iden_set, add_p25_trunked_system, add_conv_system,
)
from ..record_types import (
    P25TrkSystemConfig, ConvSystemConfig, EnhancedCCEntry,
    build_sys_flags, detect_band_limits, detect_wan_config,
)
from ..validation import (
    validate_group_set, validate_trunk_set, validate_iden_set, ERROR,
)
from ..logger import log_action, log_error
from ..cache import save_system, load_system, list_cached_systems


class ImportPanel(ttk.Frame):
    """Import panel with paste and API tabs."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        # State for API tab
        self.rr_system = None
        self.category_vars = {}
        self.tag_vars = {}

        # State for paste tab
        self.paste_system = None
        self.paste_cat_vars = {}
        self.paste_tag_vars = {}
        self.paste_mode_vars = {}       # mode group -> BooleanVar
        self.paste_enc_vars = {}        # encryption level -> BooleanVar
        self._tg_iid_map = {}

        # Source notebook (Paste vs API)
        self.source_nb = ttk.Notebook(self)
        self.source_nb.pack(fill=tk.BOTH, expand=True)

        # Paste tab
        paste_frame = ttk.Frame(self.source_nb, padding=4)
        self._build_paste_tab(paste_frame)
        self.source_nb.add(paste_frame, text="Paste Import")

        # API tab
        api_frame = ttk.Frame(self.source_nb, padding=4)
        self._build_api_tab(api_frame)
        self.source_nb.add(api_frame, text="API Import")

    # =================================================================
    # PASTE TAB
    # =================================================================

    def _build_paste_tab(self, parent):
        # Instructions
        instructions = ttk.Label(
            parent,
            text=("Go to RadioReference.com system page, Ctrl+A to select "
                  "all, Ctrl+C to copy, then Ctrl+V to paste below. "
                  "QuickPRS extracts system info, talkgroups, and "
                  "frequencies automatically."),
            wraplength=600)
        instructions.pack(fill=tk.X, pady=(0, 4))

        # Paned window: text area top, filter/talkgroups bottom
        paned = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        # Top: text area for full page paste
        text_frame = ttk.Frame(paned)
        self.paste_text = tk.Text(text_frame, wrap=tk.NONE,
                                  font=("Consolas", 9))
        paste_vsb = ttk.Scrollbar(text_frame, orient=tk.VERTICAL,
                                   command=self.paste_text.yview)
        paste_hsb = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL,
                                   command=self.paste_text.xview)
        self.paste_text.configure(yscrollcommand=paste_vsb.set,
                                  xscrollcommand=paste_hsb.set)
        self.paste_text.grid(row=0, column=0, sticky="nsew")
        paste_vsb.grid(row=0, column=1, sticky="ns")
        paste_hsb.grid(row=1, column=0, sticky="ew")
        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)
        paned.add(text_frame, weight=1)

        # Bottom: filter + talkgroup selection area
        self.paste_bottom_frame = ttk.Frame(paned)
        paned.add(self.paste_bottom_frame, weight=2)

        # Buttons row (between panes)
        btn_row = ttk.Frame(parent)
        btn_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(btn_row, text="Parse Page",
                   command=self._parse_full_page,
                   width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Clear",
                   command=self._paste_clear,
                   width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Load file...",
                   command=self._load_paste_file,
                   width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Load cache...",
                   command=self._load_from_cache,
                   width=11).pack(side=tk.LEFT, padx=2)
        self.paste_parse_status = ttk.Label(btn_row, text="")
        self.paste_parse_status.pack(side=tk.LEFT, padx=8)

        # Filter section — hidden until parsing
        self.paste_filter_frame = ttk.LabelFrame(
            self.paste_bottom_frame, text="Filter Talkgroups", padding=4)
        # Not packed yet — shown after parsing

        # Data notebook (talkgroups + frequencies) — hidden until parsing
        self.paste_data_nb = ttk.Notebook(self.paste_bottom_frame)
        # Not packed yet — shown after parsing

        # Talkgroup treeview
        self.tg_tree_frame = ttk.Frame(self.paste_data_nb, padding=4)

        # Frequency treeview
        self.freq_tree_frame = ttk.Frame(self.paste_data_nb, padding=4)

        # Sites treeview (with county filter)
        self.sites_tree_frame = ttk.Frame(self.paste_data_nb, padding=4)
        self.site_county_vars = {}   # county -> BooleanVar
        self.site_deselected = set()  # site_ids deselected by user

        # Conventional channels treeview
        self.conv_tree_frame = ttk.Frame(self.paste_data_nb, padding=4)
        self.conv_deselected = set()  # indices of deselected channels

        # Action bar (always at bottom)
        self.paste_action_frame = ttk.Frame(parent)
        self.paste_action_frame.pack(fill=tk.X)

        ttk.Label(self.paste_action_frame, text="Set Name:").pack(
            side=tk.LEFT)
        self.paste_set_name = tk.StringVar()
        ttk.Entry(self.paste_action_frame,
                  textvariable=self.paste_set_name,
                  width=12).pack(side=tk.LEFT, padx=4)

        ttk.Button(self.paste_action_frame, text="Inject into PRS",
                   command=self._paste_inject,
                   width=16).pack(side=tk.RIGHT, padx=2)
        ttk.Button(self.paste_action_frame, text="Preview",
                   command=self._paste_preview,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(self.paste_action_frame, text="Save to cache",
                   command=self._save_to_cache,
                   width=12).pack(side=tk.RIGHT, padx=2)

        self.paste_status = ttk.Label(self.paste_action_frame, text="")
        self.paste_status.pack(side=tk.RIGHT, padx=8)

        # Track per-talkgroup deselection (IDs deselected by user)
        self.tg_deselected = set()

    # --- Paste parse handlers ---

    def _paste_clear(self):
        """Clear paste text and reset filter state."""
        self.paste_text.delete("1.0", tk.END)
        self.paste_system = None
        self.paste_cat_vars.clear()
        self.paste_tag_vars.clear()
        self.paste_mode_vars.clear()
        self.paste_enc_vars.clear()
        self.tg_deselected.clear()
        self.site_county_vars.clear()
        self.site_deselected.clear()
        self.conv_deselected.clear()
        self.paste_filter_frame.pack_forget()
        # Remove tabs from notebook and hide it
        for tab_id in self.paste_data_nb.tabs():
            self.paste_data_nb.forget(tab_id)
        self.paste_data_nb.pack_forget()
        self.paste_parse_status.config(text="")
        self.paste_status.config(text="")

    def _parse_full_page(self):
        """Parse the full pasted RadioReference page."""
        text = self.paste_text.get("1.0", tk.END)
        if not text.strip():
            self.paste_parse_status.config(
                text="Paste a RadioReference page first.",
                foreground="red")
            return

        log_action("parse_page", text_length=len(text))

        system = parse_full_page(text)
        self.paste_system = system

        parts = []
        if system.name:
            parts.append(system.name)
            self.paste_set_name.set(make_set_name(system.name))
        if system.wacn:
            parts.append(f"WACN:{system.wacn}")
        if system.sysid:
            parts.append(f"SysID:{system.sysid}")

        tg_count = len(system.talkgroups)
        freq_count = sum(len(s.freqs) for s in system.sites)
        conv_count = len(system.conv_channels)
        parts.append(f"{tg_count} TGs")
        parts.append(f"{freq_count} freqs")
        if conv_count > 0:
            parts.append(f"{conv_count} conv ch")

        if tg_count > 0 or freq_count > 0 or conv_count > 0:
            cats = set(tg.category for tg in system.talkgroups
                       if tg.category)
            if cats:
                parts.append(f"{len(cats)} categories")
            self.paste_parse_status.config(
                text=" | ".join(parts), foreground="green")
            self._populate_paste_filters()
            log_action("parse_complete",
                       system=system.name,
                       talkgroups=tg_count,
                       frequencies=freq_count,
                       conv_channels=conv_count,
                       categories=len(cats))
        else:
            self.paste_parse_status.config(
                text="No talkgroups or frequencies found. "
                     "Try Ctrl+A, Ctrl+C on the full page.",
                foreground="red")
            self.paste_filter_frame.pack_forget()

    def _populate_paste_filters(self):
        """Populate category/tag filters and talkgroup/frequency views."""
        for w in self.paste_filter_frame.winfo_children():
            w.destroy()
        for w in self.tg_tree_frame.winfo_children():
            w.destroy()
        for w in self.freq_tree_frame.winfo_children():
            w.destroy()
        for w in self.conv_tree_frame.winfo_children():
            w.destroy()
        # Remove existing tabs from notebook
        for tab_id in self.paste_data_nb.tabs():
            self.paste_data_nb.forget(tab_id)
        self.paste_cat_vars.clear()
        self.paste_tag_vars.clear()
        self.paste_mode_vars.clear()
        self.paste_enc_vars.clear()
        self.tg_deselected.clear()
        self.site_county_vars.clear()
        self.site_deselected.clear()
        self.conv_deselected.clear()

        has_tgs = (self.paste_system and self.paste_system.talkgroups)
        has_conv = (self.paste_system and self.paste_system.conv_channels)
        has_freqs = (self.paste_system and self.paste_system.sites
                     and sum(len(s.freqs) for s in self.paste_system.sites) > 0)

        if not has_tgs and not has_conv and not has_freqs:
            self.paste_filter_frame.pack_forget()
            self.paste_data_nb.pack_forget()
            return

        # Show filter frame only if there are talkgroups to filter
        if has_tgs:
            self.paste_filter_frame.pack(fill=tk.X, pady=(0, 4))
        else:
            self.paste_filter_frame.pack_forget()

        if not has_tgs:
            # Skip TG filter setup — jump to data notebook
            pass
        else:
            self._build_tg_filters()

        # Data notebook — talkgroups + frequencies + conv channels
        tg_count = len(self.paste_system.talkgroups) if has_tgs else 0
        freq_count = (sum(len(s.freqs) for s in self.paste_system.sites)
                      if has_freqs else 0)
        conv_count = len(self.paste_system.conv_channels) if has_conv else 0
        site_count = len(self.paste_system.sites) if has_freqs else 0

        for w in self.tg_tree_frame.winfo_children():
            w.destroy()
        for w in self.freq_tree_frame.winfo_children():
            w.destroy()
        for w in self.sites_tree_frame.winfo_children():
            w.destroy()
        for w in self.conv_tree_frame.winfo_children():
            w.destroy()

        self.paste_data_nb.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        if tg_count > 0:
            self.paste_data_nb.add(
                self.tg_tree_frame,
                text=f"Talkgroups ({tg_count})")
        if freq_count > 0:
            self.paste_data_nb.add(
                self.freq_tree_frame,
                text=f"Frequencies ({freq_count})")
        if site_count > 0:
            self.paste_data_nb.add(
                self.sites_tree_frame,
                text=f"Sites ({site_count})")
        if conv_count > 0:
            self.paste_data_nb.add(
                self.conv_tree_frame,
                text=f"Conventional ({conv_count})")

        if tg_count > 0:
            self._build_tg_treeview()
        if freq_count > 0:
            self._build_freq_treeview()
        if site_count > 0:
            self._build_sites_tree()
        if conv_count > 0:
            self._build_conv_treeview()

        if has_tgs:
            self._refresh_tg_tree()
            self._update_paste_counts()

        return  # All setup done in sub-methods above

    def _build_tg_filters(self):
        """Build talkgroup filter controls (categories, tags, modes)."""

        # Quick filter buttons
        btn_frame = ttk.Frame(self.paste_filter_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(btn_frame, text="All", width=5,
                   command=self._paste_select_all).pack(
                       side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="None", width=5,
                   command=self._paste_select_none).pack(
                       side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Law", width=5,
                   command=self._paste_select_law).pack(
                       side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Fire/EMS", width=8,
                   command=self._paste_select_fire_ems).pack(
                       side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Clear Only", width=9,
                   command=self._paste_select_clear_only).pack(
                       side=tk.LEFT, padx=2)
        self.paste_count_label = ttk.Label(btn_frame, text="")
        self.paste_count_label.pack(side=tk.LEFT, padx=8)

        # Service tags (horizontal row with wrapping)
        tags = sorted(set(
            tg.tag for tg in self.paste_system.talkgroups if tg.tag))
        if tags:
            tag_frame = ttk.LabelFrame(
                self.paste_filter_frame, text="Service Tags", padding=2)
            tag_frame.pack(fill=tk.X, pady=(0, 4))
            for tag in tags:
                var = tk.BooleanVar(value=True)
                self.paste_tag_vars[tag] = var
                ttk.Checkbutton(
                    tag_frame, text=tag, variable=var,
                    command=self._on_filter_changed).pack(
                        side=tk.LEFT, padx=4)

        # Mode and Encryption filters (horizontal)
        modes_present = set(
            tg.mode for tg in self.paste_system.talkgroups if tg.mode)
        if modes_present:
            mode_enc_frame = ttk.Frame(self.paste_filter_frame)
            mode_enc_frame.pack(fill=tk.X, pady=(0, 4))

            # Mode filter
            mode_lf = ttk.LabelFrame(mode_enc_frame, text="Mode", padding=2)
            mode_lf.pack(side=tk.LEFT, padx=(0, 8))
            # Build mode group checkboxes based on what's present
            for group_name, group_codes in MODE_GROUPS.items():
                if modes_present & group_codes:
                    count = sum(
                        1 for tg in self.paste_system.talkgroups
                        if tg.mode in group_codes)
                    var = tk.BooleanVar(value=True)
                    self.paste_mode_vars[group_name] = var
                    ttk.Checkbutton(
                        mode_lf, text=f"{group_name} ({count})",
                        variable=var,
                        command=self._on_filter_changed).pack(
                            side=tk.LEFT, padx=4)
            # "Other" mode for any mode not in standard groups
            all_grouped = set()
            for codes in MODE_GROUPS.values():
                all_grouped |= codes
            other_modes = modes_present - all_grouped
            if other_modes:
                count = sum(
                    1 for tg in self.paste_system.talkgroups
                    if tg.mode in other_modes)
                var = tk.BooleanVar(value=True)
                self.paste_mode_vars["Other"] = var
                ttk.Checkbutton(
                    mode_lf, text=f"Other ({count})",
                    variable=var,
                    command=self._on_filter_changed).pack(
                        side=tk.LEFT, padx=4)

            # Encryption filter
            enc_lf = ttk.LabelFrame(
                mode_enc_frame, text="Encryption", padding=2)
            enc_lf.pack(side=tk.LEFT)
            # Determine encryption levels present
            enc_present = set()
            for tg in self.paste_system.talkgroups:
                info = MODE_CODES.get(tg.mode)
                if info:
                    enc_present.add(info[1])
                else:
                    enc_present.add(False)  # unknown mode = clear
            for level_name, level_vals in ENCRYPTION_LEVELS.items():
                if enc_present & level_vals:
                    count = sum(
                        1 for tg in self.paste_system.talkgroups
                        if MODE_CODES.get(tg.mode, ("", False))[1]
                        in level_vals)
                    var = tk.BooleanVar(value=True)
                    self.paste_enc_vars[level_name] = var
                    ttk.Checkbutton(
                        enc_lf, text=f"{level_name} ({count})",
                        variable=var,
                        command=self._on_filter_changed).pack(
                            side=tk.LEFT, padx=4)

        # Categories — scrollable canvas
        cat_counts = {}
        for tg in self.paste_system.talkgroups:
            cat = tg.category or "Uncategorized"
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        if cat_counts:
            cat_outer = ttk.LabelFrame(
                self.paste_filter_frame, text="Categories", padding=2)
            cat_outer.pack(fill=tk.X)

            cat_canvas = tk.Canvas(cat_outer, height=120,
                                   highlightthickness=0)
            cat_scrollbar = ttk.Scrollbar(
                cat_outer, orient=tk.VERTICAL, command=cat_canvas.yview)
            cat_inner = ttk.Frame(cat_canvas)

            cat_inner.bind("<Configure>",
                           lambda e: cat_canvas.configure(
                               scrollregion=cat_canvas.bbox("all")))
            cat_canvas.create_window((0, 0), window=cat_inner,
                                     anchor=tk.NW)
            cat_canvas.configure(yscrollcommand=cat_scrollbar.set)

            cat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            cat_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            # Mousewheel scrolling
            def _on_cat_mousewheel(event):
                cat_canvas.yview_scroll(
                    int(-1 * (event.delta / 120)), "units")

            cat_canvas.bind("<MouseWheel>", _on_cat_mousewheel)
            cat_inner.bind("<MouseWheel>", _on_cat_mousewheel)

            for cat, count in sorted(cat_counts.items()):
                var = tk.BooleanVar(value=True)
                self.paste_cat_vars[cat] = var
                cb = ttk.Checkbutton(
                    cat_inner, text=f"{cat} ({count})",
                    variable=var,
                    command=self._on_filter_changed)
                cb.pack(anchor=tk.W, pady=1)
                cb.bind("<MouseWheel>", _on_cat_mousewheel)

    def _build_tg_treeview(self):
        """Build the talkgroup treeview in the TG tab."""
        # Talkgroup search filter
        tg_search_frame = ttk.Frame(self.tg_tree_frame)
        tg_search_frame.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(tg_search_frame, text="Search:").pack(side=tk.LEFT)
        self.tg_search_var = tk.StringVar()
        self.tg_search_var.trace_add("write", lambda *a: self._refresh_tg_tree())
        tg_search_entry = ttk.Entry(
            tg_search_frame, textvariable=self.tg_search_var, width=20)
        tg_search_entry.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(tg_search_frame, text="X", width=2,
                   command=lambda: self.tg_search_var.set("")).pack(
                       side=tk.LEFT)
        self.tg_search_count = ttk.Label(tg_search_frame, text="",
                                          foreground="gray")
        self.tg_search_count.pack(side=tk.LEFT, padx=4)

        # Talkgroup treeview
        cols = ("dec_id", "alpha_tag", "description", "mode",
                "category", "tag")
        self.paste_tg_tree = ttk.Treeview(
            self.tg_tree_frame, columns=cols, show="headings",
            height=10, selectmode="extended")

        # Sortable column headers
        self._tg_sort_col = "dec_id"
        self._tg_sort_reverse = False
        for col, label, width in [
            ("dec_id", "ID", 60),
            ("alpha_tag", "Name", 100),
            ("description", "Description", 160),
            ("mode", "Mode", 45),
            ("category", "Category", 130),
            ("tag", "Tag", 100),
        ]:
            self.paste_tg_tree.heading(
                col, text=label,
                command=lambda c=col: self._sort_tg_tree(c))
            self.paste_tg_tree.column(col, width=width, minwidth=50)

        tg_vsb = ttk.Scrollbar(self.tg_tree_frame, orient=tk.VERTICAL,
                                command=self.paste_tg_tree.yview)
        self.paste_tg_tree.configure(yscrollcommand=tg_vsb.set)
        self.paste_tg_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tg_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Toggle selection on double-click or space
        self.paste_tg_tree.bind("<Double-1>", self._toggle_tg_selection)
        self.paste_tg_tree.bind("<space>", self._toggle_tg_selection)

        # Right-click context menu
        self.paste_tg_menu = tk.Menu(self.paste_tg_tree, tearoff=0)
        self.paste_tg_menu.add_command(
            label="Deselect", command=self._deselect_tg_selection)
        self.paste_tg_menu.add_command(
            label="Select", command=self._select_tg_selection)
        self.paste_tg_menu.add_separator()
        self.paste_tg_menu.add_command(
            label="Select All Visible",
            command=self._select_all_visible_tgs)
        self.paste_tg_menu.add_command(
            label="Deselect All Visible",
            command=self._deselect_all_visible_tgs)
        self.paste_tg_menu.add_separator()
        self.paste_tg_menu.add_command(
            label="Copy Selected IDs",
            command=self._copy_tg_ids)
        self.paste_tg_menu.add_command(
            label="Copy All as TSV",
            command=self._copy_tg_tsv)
        self.paste_tg_tree.bind("<Button-3>", self._show_tg_menu)

        # Configure tags for visual styling
        self.paste_tg_tree.tag_configure("deselected", foreground="gray")

    def _build_freq_treeview(self):
        """Build the frequency treeview in the Frequencies tab."""
        freq_cols = ("site", "freq", "tx_freq", "use")
        self.paste_freq_tree = ttk.Treeview(
            self.freq_tree_frame, columns=freq_cols,
            show="headings", height=10)
        self.paste_freq_tree.heading("site", text="Site")
        self.paste_freq_tree.heading("freq", text="RX Freq (MHz)")
        self.paste_freq_tree.heading("tx_freq", text="TX Freq (MHz)")
        self.paste_freq_tree.heading("use", text="Use")
        self.paste_freq_tree.column("site", width=150, minwidth=80)
        self.paste_freq_tree.column("freq", width=120, minwidth=80)
        self.paste_freq_tree.column("tx_freq", width=120, minwidth=80)
        self.paste_freq_tree.column("use", width=80, minwidth=50)

        freq_vsb = ttk.Scrollbar(
            self.freq_tree_frame, orient=tk.VERTICAL,
            command=self.paste_freq_tree.yview)
        self.paste_freq_tree.configure(yscrollcommand=freq_vsb.set)
        self.paste_freq_tree.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True)
        freq_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        for site in self.paste_system.sites:
            for sf in site.freqs:
                tx = calculate_tx_freq(sf.freq)
                self.paste_freq_tree.insert("", tk.END, values=(
                    site.name or f"Site {site.site_number}",
                    f"{sf.freq:.5f}",
                    f"{tx:.5f}",
                    sf.use or "",
                ))

    def _build_conv_treeview(self):
        """Build the conventional channels treeview."""
        conv_cols = ("inc", "freq", "tx_freq", "name", "tone",
                     "mode", "description")
        self.paste_conv_tree = ttk.Treeview(
            self.conv_tree_frame, columns=conv_cols,
            show="headings", height=10, selectmode="extended")

        for col, label, width in [
            ("inc", "Inc", 35),
            ("freq", "RX Freq", 90),
            ("tx_freq", "TX Freq", 90),
            ("name", "Name", 100),
            ("tone", "Tone", 70),
            ("mode", "Mode", 55),
            ("description", "Description", 180),
        ]:
            self.paste_conv_tree.heading(col, text=label)
            self.paste_conv_tree.column(col, width=width, minwidth=30)

        conv_vsb = ttk.Scrollbar(
            self.conv_tree_frame, orient=tk.VERTICAL,
            command=self.paste_conv_tree.yview)
        self.paste_conv_tree.configure(yscrollcommand=conv_vsb.set)
        self.paste_conv_tree.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True)
        conv_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Toggle include on double-click or space
        self.paste_conv_tree.bind(
            "<Double-1>", self._toggle_conv_selection)
        self.paste_conv_tree.bind(
            "<space>", self._toggle_conv_selection)

        # Tag for deselected channels
        self.paste_conv_tree.tag_configure(
            "deselected", foreground="gray")

        # Populate
        for i, ch in enumerate(self.paste_system.conv_channels):
            tx_str = (f"{ch.tx_freq:.5f}" if ch.tx_freq > 0
                      else f"{ch.freq:.5f}")
            inc = "N" if i in self.conv_deselected else "Y"
            tags = ("deselected",) if i in self.conv_deselected else ()
            self.paste_conv_tree.insert("", tk.END, iid=str(i),
                                         values=(
                inc, f"{ch.freq:.5f}", tx_str,
                ch.name, ch.tone, ch.mode,
                ch.description,
            ), tags=tags)

    def _toggle_conv_selection(self, event=None):
        """Toggle include/exclude for selected conventional channels."""
        for iid in self.paste_conv_tree.selection():
            idx = int(iid)
            if idx in self.conv_deselected:
                self.conv_deselected.discard(idx)
                self.paste_conv_tree.item(
                    iid, tags=())
                vals = list(self.paste_conv_tree.item(iid, "values"))
                vals[0] = "Y"
                self.paste_conv_tree.item(iid, values=vals)
            else:
                self.conv_deselected.add(idx)
                self.paste_conv_tree.item(
                    iid, tags=("deselected",))
                vals = list(self.paste_conv_tree.item(iid, "values"))
                vals[0] = "N"
                self.paste_conv_tree.item(iid, values=vals)

    def _get_selected_conv_channels(self):
        """Get list of ConvChannelData not deselected by user."""
        if not self.paste_system or not self.paste_system.conv_channels:
            return []
        return [ch for i, ch in enumerate(self.paste_system.conv_channels)
                if i not in self.conv_deselected]

    def _build_sites_tree(self):
        """Build the sites tab with county filter and site treeview."""
        for w in self.sites_tree_frame.winfo_children():
            w.destroy()
        self.site_county_vars.clear()
        self.site_deselected.clear()

        if not self.paste_system or not self.paste_system.sites:
            return

        sites = self.paste_system.sites

        # County filter bar
        counties = sorted(set(
            s.county for s in sites if s.county))
        if counties:
            county_lf = ttk.LabelFrame(
                self.sites_tree_frame, text="Filter by County", padding=2)
            county_lf.pack(fill=tk.X, pady=(0, 4))

            # Quick buttons
            btn_row = ttk.Frame(county_lf)
            btn_row.pack(fill=tk.X, pady=(0, 2))
            ttk.Button(btn_row, text="All", width=5,
                       command=self._sites_select_all_counties).pack(
                           side=tk.LEFT, padx=2)
            ttk.Button(btn_row, text="None", width=5,
                       command=self._sites_select_no_counties).pack(
                           side=tk.LEFT, padx=2)
            self.sites_count_label = ttk.Label(btn_row, text="")
            self.sites_count_label.pack(side=tk.LEFT, padx=8)

            # Scrollable county checkboxes
            county_canvas = tk.Canvas(
                county_lf, height=80, highlightthickness=0)
            county_vsb = ttk.Scrollbar(
                county_lf, orient=tk.VERTICAL,
                command=county_canvas.yview)
            county_inner = ttk.Frame(county_canvas)
            county_inner.bind(
                "<Configure>",
                lambda e: county_canvas.configure(
                    scrollregion=county_canvas.bbox("all")))
            county_canvas.create_window(
                (0, 0), window=county_inner, anchor=tk.NW)
            county_canvas.configure(yscrollcommand=county_vsb.set)
            county_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            county_vsb.pack(side=tk.RIGHT, fill=tk.Y)

            def _wheel(event):
                county_canvas.yview_scroll(
                    int(-1 * (event.delta / 120)), "units")
            county_canvas.bind("<MouseWheel>", _wheel)
            county_inner.bind("<MouseWheel>", _wheel)

            # Count sites per county
            county_counts = {}
            for s in sites:
                c = s.county or "Unknown"
                county_counts[c] = county_counts.get(c, 0) + 1

            # Two-column layout for counties
            row_frame = None
            for i, county in enumerate(sorted(county_counts.keys())):
                if i % 3 == 0:
                    row_frame = ttk.Frame(county_inner)
                    row_frame.pack(fill=tk.X, pady=1)
                count = county_counts[county]
                var = tk.BooleanVar(value=True)
                self.site_county_vars[county] = var
                cb = ttk.Checkbutton(
                    row_frame,
                    text=f"{county} ({count})",
                    variable=var,
                    command=self._refresh_sites_tree,
                    width=25)
                cb.pack(side=tk.LEFT, padx=2)
                cb.bind("<MouseWheel>", _wheel)

        # Site treeview
        site_cols = ("select", "site_num", "name", "county",
                     "rfss", "nac", "freqs")
        self.paste_site_tree = ttk.Treeview(
            self.sites_tree_frame, columns=site_cols,
            show="headings", height=10, selectmode="extended")

        for col, label, width in [
            ("select", "Inc", 35),
            ("site_num", "Site#", 50),
            ("name", "Name", 180),
            ("county", "County", 120),
            ("rfss", "RFSS", 45),
            ("nac", "NAC", 45),
            ("freqs", "Frequencies", 200),
        ]:
            self.paste_site_tree.heading(col, text=label)
            self.paste_site_tree.column(col, width=width, minwidth=30)

        site_vsb = ttk.Scrollbar(
            self.sites_tree_frame, orient=tk.VERTICAL,
            command=self.paste_site_tree.yview)
        self.paste_site_tree.configure(yscrollcommand=site_vsb.set)
        self.paste_site_tree.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True)
        site_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Toggle include on double-click
        self.paste_site_tree.bind(
            "<Double-1>", self._toggle_site_selection)
        self.paste_site_tree.bind(
            "<space>", self._toggle_site_selection)

        # Tag for deselected sites
        self.paste_site_tree.tag_configure(
            "deselected", foreground="gray")

        # Right-click menu
        self.site_menu = tk.Menu(self.paste_site_tree, tearoff=0)
        self.site_menu.add_command(
            label="Include Site", command=self._include_site)
        self.site_menu.add_command(
            label="Exclude Site", command=self._exclude_site)
        self.site_menu.add_separator()
        self.site_menu.add_command(
            label="Include All Visible",
            command=self._include_all_visible_sites)
        self.site_menu.add_command(
            label="Exclude All Visible",
            command=self._exclude_all_visible_sites)
        self.paste_site_tree.bind("<Button-3>", self._show_site_menu)

        self._refresh_sites_tree()

    def _refresh_sites_tree(self):
        """Populate sites tree with county filter applied."""
        if not hasattr(self, 'paste_site_tree'):
            return

        for item in self.paste_site_tree.get_children():
            self.paste_site_tree.delete(item)

        if not self.paste_system or not self.paste_system.sites:
            return

        selected_counties = {
            c for c, var in self.site_county_vars.items() if var.get()}

        shown = 0
        for site in self.paste_system.sites:
            county = site.county or "Unknown"
            if self.site_county_vars and county not in selected_counties:
                continue

            is_deselected = site.site_id in self.site_deselected
            inc_text = "" if is_deselected else "Y"
            tags = ("deselected",) if is_deselected else ()

            freq_strs = []
            for sf in site.freqs[:6]:
                suffix = "c" if sf.use == "c" else ""
                freq_strs.append(f"{sf.freq:.5f}{suffix}")
            freq_text = ", ".join(freq_strs)
            if len(site.freqs) > 6:
                freq_text += f" +{len(site.freqs) - 6}"

            iid = f"site_{site.site_id}"
            self.paste_site_tree.insert(
                "", tk.END, iid=iid,
                values=(inc_text,
                        site.site_number,
                        site.name or f"Site {site.site_id}",
                        county,
                        site.rfss or "",
                        site.nac or "",
                        freq_text),
                tags=tags)
            shown += 1

        # Update count label
        total = len(self.paste_system.sites)
        included = shown - len([
            s for s in self.paste_system.sites
            if s.site_id in self.site_deselected
            and (not self.site_county_vars or
                 (s.county or "Unknown") in selected_counties)])
        if hasattr(self, 'sites_count_label'):
            self.sites_count_label.config(
                text=f"{included}/{total} sites included")

    def _toggle_site_selection(self, event=None):
        """Toggle selected sites between included/excluded."""
        sel = self.paste_site_tree.selection()
        if not sel:
            return
        for iid in sel:
            site_id = int(iid.replace("site_", ""))
            if site_id in self.site_deselected:
                self.site_deselected.discard(site_id)
                self.paste_site_tree.item(iid, tags=())
                self.paste_site_tree.set(iid, "select", "Y")
            else:
                self.site_deselected.add(site_id)
                self.paste_site_tree.item(iid, tags=("deselected",))
                self.paste_site_tree.set(iid, "select", "")
        self._refresh_sites_tree()

    def _include_site(self):
        for iid in self.paste_site_tree.selection():
            site_id = int(iid.replace("site_", ""))
            self.site_deselected.discard(site_id)
        self._refresh_sites_tree()

    def _exclude_site(self):
        for iid in self.paste_site_tree.selection():
            site_id = int(iid.replace("site_", ""))
            self.site_deselected.add(site_id)
        self._refresh_sites_tree()

    def _include_all_visible_sites(self):
        for iid in self.paste_site_tree.get_children():
            site_id = int(iid.replace("site_", ""))
            self.site_deselected.discard(site_id)
        self._refresh_sites_tree()

    def _exclude_all_visible_sites(self):
        for iid in self.paste_site_tree.get_children():
            site_id = int(iid.replace("site_", ""))
            self.site_deselected.add(site_id)
        self._refresh_sites_tree()

    def _sites_select_all_counties(self):
        for var in self.site_county_vars.values():
            var.set(True)
        self._refresh_sites_tree()

    def _sites_select_no_counties(self):
        for var in self.site_county_vars.values():
            var.set(False)
        self._refresh_sites_tree()

    def _show_site_menu(self, event):
        iid = self.paste_site_tree.identify_row(event.y)
        if iid:
            sel = self.paste_site_tree.selection()
            if iid not in sel:
                self.paste_site_tree.selection_set(iid)
        try:
            self.site_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.site_menu.grab_release()

    def get_selected_sites(self):
        """Return list of sites that are included (not deselected, pass county filter)."""
        if not self.paste_system:
            return []
        selected_counties = {
            c for c, var in self.site_county_vars.items() if var.get()}
        result = []
        for site in self.paste_system.sites:
            county = site.county or "Unknown"
            if self.site_county_vars and county not in selected_counties:
                continue
            if site.site_id in self.site_deselected:
                continue
            result.append(site)
        return result

    def _tg_passes_mode_filter(self, tg):
        """Check if a talkgroup passes the mode/encryption filters."""
        if not self.paste_mode_vars and not self.paste_enc_vars:
            return True

        # Mode filter
        if self.paste_mode_vars:
            mode_ok = False
            all_grouped = set()
            for group_name, group_codes in MODE_GROUPS.items():
                all_grouped |= group_codes
                if self.paste_mode_vars.get(group_name) and \
                        self.paste_mode_vars[group_name].get():
                    if tg.mode in group_codes:
                        mode_ok = True
                        break
            if not mode_ok:
                # Check "Other" mode group
                other_var = self.paste_mode_vars.get("Other")
                if other_var and other_var.get() and \
                        tg.mode not in all_grouped:
                    mode_ok = True
                elif not other_var and tg.mode not in all_grouped:
                    mode_ok = True  # no Other checkbox = allow
            if not mode_ok:
                return False

        # Encryption filter
        if self.paste_enc_vars:
            info = MODE_CODES.get(tg.mode, ("", False))
            enc_level = info[1]
            enc_ok = False
            for level_name, level_vals in ENCRYPTION_LEVELS.items():
                if self.paste_enc_vars.get(level_name) and \
                        self.paste_enc_vars[level_name].get():
                    if enc_level in level_vals:
                        enc_ok = True
                        break
            if not enc_ok:
                return False

        return True

    def _get_filtered_paste_tgs(self):
        """Get talkgroups filtered by category/tag/mode/enc + deselection."""
        if not self.paste_system:
            return []

        selected_cats = {
            cat for cat, var in self.paste_cat_vars.items() if var.get()}
        selected_tags = {
            tag for tag, var in self.paste_tag_vars.items() if var.get()}

        filtered = []
        for tg in self.paste_system.talkgroups:
            cat = tg.category or "Uncategorized"
            if self.paste_cat_vars and cat not in selected_cats:
                continue
            if tg.tag and self.paste_tag_vars and tg.tag not in selected_tags:
                continue
            if not self._tg_passes_mode_filter(tg):
                continue
            # Per-talkgroup deselection
            if tg.dec_id in self.tg_deselected:
                continue
            filtered.append(tg)
        return filtered

    def _update_paste_counts(self):
        """Update the paste TG count label with scan limit awareness."""
        filtered = self._get_filtered_paste_tgs()
        total = len(self.paste_system.talkgroups) if self.paste_system else 0
        n = len(filtered)
        if hasattr(self, 'paste_count_label'):
            text = f"{n}/{total} talkgroups selected"
            color = ""
            if n > 127:
                text += " — EXCEEDS 127 SCAN LIMIT"
                color = "red"
            elif n > 120:
                text += f" — near 127 scan limit"
                color = "orange"
            self.paste_count_label.config(text=text)
            if color:
                self.paste_count_label.config(foreground=color)
            else:
                self.paste_count_label.config(foreground="")

    def _paste_select_all(self):
        for var in self.paste_cat_vars.values():
            var.set(True)
        for var in self.paste_tag_vars.values():
            var.set(True)
        for var in self.paste_mode_vars.values():
            var.set(True)
        for var in self.paste_enc_vars.values():
            var.set(True)
        self.tg_deselected.clear()
        self._on_filter_changed()

    def _paste_select_none(self):
        for var in self.paste_cat_vars.values():
            var.set(False)
        for var in self.paste_tag_vars.values():
            var.set(False)
        self._on_filter_changed()

    def _paste_select_law(self):
        law_tags = {"Law Dispatch", "Law Tac", "Law Talk", "Corrections"}
        for tag, var in self.paste_tag_vars.items():
            var.set(tag in law_tags)
        self._on_filter_changed()

    def _paste_select_fire_ems(self):
        fire_ems = {"Fire Dispatch", "Fire-Tac", "Fire-Talk",
                    "Fire Tac", "Fire Talk",
                    "EMS Dispatch", "EMS-Tac", "EMS-Talk",
                    "EMS Tac", "EMS Talk", "Hospital"}
        for tag, var in self.paste_tag_vars.items():
            var.set(tag in fire_ems)
        self._on_filter_changed()

    def _paste_select_clear_only(self):
        """Select only unencrypted talkgroups."""
        for level_name, var in self.paste_enc_vars.items():
            var.set(level_name == "Clear")
        self._on_filter_changed()

    # --- Talkgroup tree helpers ---

    def _on_filter_changed(self):
        """Called when category/tag checkboxes change."""
        self._refresh_tg_tree()
        self._update_paste_counts()

    def _refresh_tg_tree(self):
        """Populate treeview with talkgroups matching current filters."""
        if not hasattr(self, 'paste_tg_tree'):
            return

        for item in self.paste_tg_tree.get_children():
            self.paste_tg_tree.delete(item)

        # Map iid → dec_id for selection tracking
        self._tg_iid_map = {}

        if not self.paste_system:
            return

        selected_cats = {
            cat for cat, var in self.paste_cat_vars.items() if var.get()}
        selected_tags = {
            tag for tag, var in self.paste_tag_vars.items() if var.get()}

        # Text search filter
        search_text = ""
        if hasattr(self, 'tg_search_var'):
            search_text = self.tg_search_var.get().strip().lower()

        shown = 0
        for idx, tg in enumerate(self.paste_system.talkgroups):
            cat = tg.category or "Uncategorized"
            if self.paste_cat_vars and cat not in selected_cats:
                continue
            if tg.tag and self.paste_tag_vars and tg.tag not in selected_tags:
                continue
            if not self._tg_passes_mode_filter(tg):
                continue

            # Text search filter
            if search_text:
                searchable = f"{tg.dec_id} {tg.alpha_tag} {tg.description} {tg.mode or ''} {cat} {tg.tag or ''}".lower()
                if search_text not in searchable:
                    continue

            iid = f"tg_{idx}"
            self._tg_iid_map[iid] = tg.dec_id
            is_deselected = tg.dec_id in self.tg_deselected
            tags = ("deselected",) if is_deselected else ()
            self.paste_tg_tree.insert(
                "", tk.END, iid=iid,
                values=(tg.dec_id, tg.alpha_tag, tg.description,
                        tg.mode or "", cat, tg.tag or ""),
                tags=tags)
            shown += 1

        # Update search count
        if hasattr(self, 'tg_search_count') and search_text:
            total_filtered = len([
                tg for tg in self.paste_system.talkgroups
                if (not self.paste_cat_vars or
                    (tg.category or "Uncategorized") in selected_cats)
                and (not tg.tag or not self.paste_tag_vars or
                     tg.tag in selected_tags)])
            self.tg_search_count.config(
                text=f"{shown}/{total_filtered} shown")
        elif hasattr(self, 'tg_search_count'):
            self.tg_search_count.config(text="")

    def _toggle_tg_selection(self, event=None):
        """Toggle selected talkgroups between selected/deselected."""
        sel = self.paste_tg_tree.selection()
        if not sel:
            return
        for iid in sel:
            tg_id = self._tg_iid_map.get(iid, 0)
            if tg_id in self.tg_deselected:
                self.tg_deselected.discard(tg_id)
                self.paste_tg_tree.item(iid, tags=())
            else:
                self.tg_deselected.add(tg_id)
                self.paste_tg_tree.item(iid, tags=("deselected",))
        self._update_paste_counts()

    def _deselect_tg_selection(self):
        """Deselect highlighted talkgroups (context menu)."""
        sel = self.paste_tg_tree.selection()
        for iid in sel:
            tg_id = self._tg_iid_map.get(iid, 0)
            self.tg_deselected.add(tg_id)
            self.paste_tg_tree.item(iid, tags=("deselected",))
        self._update_paste_counts()

    def _select_tg_selection(self):
        """Re-select highlighted talkgroups (context menu)."""
        sel = self.paste_tg_tree.selection()
        for iid in sel:
            tg_id = self._tg_iid_map.get(iid, 0)
            self.tg_deselected.discard(tg_id)
            self.paste_tg_tree.item(iid, tags=())
        self._update_paste_counts()

    def _select_all_visible_tgs(self):
        """Select all currently visible talkgroups in the tree."""
        for iid in self.paste_tg_tree.get_children():
            tg_id = self._tg_iid_map.get(iid, 0)
            self.tg_deselected.discard(tg_id)
            self.paste_tg_tree.item(iid, tags=())
        self._update_paste_counts()

    def _deselect_all_visible_tgs(self):
        """Deselect all currently visible talkgroups in the tree."""
        for iid in self.paste_tg_tree.get_children():
            tg_id = self._tg_iid_map.get(iid, 0)
            self.tg_deselected.add(tg_id)
            self.paste_tg_tree.item(iid, tags=("deselected",))
        self._update_paste_counts()

    def _show_tg_menu(self, event):
        """Show the right-click context menu for talkgroup tree."""
        # Select row under cursor if not already selected
        iid = self.paste_tg_tree.identify_row(event.y)
        if iid:
            sel = self.paste_tg_tree.selection()
            if iid not in sel:
                self.paste_tg_tree.selection_set(iid)
        try:
            self.paste_tg_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.paste_tg_menu.grab_release()

    # --- Copy operations ---

    def _copy_tg_ids(self):
        """Copy selected (non-deselected) talkgroup IDs to clipboard."""
        filtered = self._get_filtered_paste_tgs()
        if not filtered:
            return
        ids = "\n".join(str(tg.dec_id) for tg in filtered)
        self.clipboard_clear()
        self.clipboard_append(ids)
        self.app.status_set(f"Copied {len(filtered)} TG IDs to clipboard")

    def _copy_tg_tsv(self):
        """Copy all visible talkgroup data as tab-separated text."""
        if not self.paste_system:
            return
        lines = ["ID\tName\tDescription\tMode\tCategory\tTag"]
        for iid in self.paste_tg_tree.get_children():
            vals = self.paste_tg_tree.item(iid, 'values')
            lines.append("\t".join(str(v) for v in vals))
        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.app.status_set(
            f"Copied {len(lines) - 1} rows to clipboard (TSV)")

    # --- Column sorting ---

    def _sort_tg_tree(self, col):
        """Sort the talkgroup treeview by clicking column header."""
        if col == self._tg_sort_col:
            self._tg_sort_reverse = not self._tg_sort_reverse
        else:
            self._tg_sort_col = col
            self._tg_sort_reverse = False

        # Get all items with their values
        items = []
        for iid in self.paste_tg_tree.get_children():
            values = self.paste_tg_tree.item(iid, 'values')
            tags = self.paste_tg_tree.item(iid, 'tags')
            items.append((iid, values, tags))

        # Determine column index
        col_idx = {"dec_id": 0, "alpha_tag": 1, "description": 2,
                    "mode": 3, "category": 4, "tag": 5}.get(col, 0)

        # Sort — numeric for ID, alpha for everything else
        if col == "dec_id":
            items.sort(key=lambda x: int(x[1][col_idx]) if x[1][col_idx] else 0,
                       reverse=self._tg_sort_reverse)
        else:
            items.sort(key=lambda x: str(x[1][col_idx]).lower(),
                       reverse=self._tg_sort_reverse)

        # Reorder in tree
        for idx, (iid, _, _) in enumerate(items):
            self.paste_tg_tree.move(iid, '', idx)

        # Update header to show sort indicator
        arrow = " v" if self._tg_sort_reverse else " ^"
        labels = {"dec_id": "ID", "alpha_tag": "Name",
                  "description": "Description", "mode": "Mode",
                  "category": "Category", "tag": "Tag"}
        for c, label in labels.items():
            suffix = arrow if c == col else ""
            self.paste_tg_tree.heading(c, text=label + suffix)

    # --- Cache ---

    def _save_to_cache(self):
        """Save the parsed system to local cache."""
        if not self.paste_system:
            messagebox.showwarning("Warning", "Parse a page first.")
            return
        try:
            filepath = save_system(self.paste_system)
            log_action("cache_save",
                       system=self.paste_system.name,
                       path=str(filepath))
            self.paste_status.config(
                text=f"Cached: {filepath.name}", foreground="green")
        except Exception as e:
            log_error("cache_save", str(e))
            messagebox.showerror("Error", f"Failed to save cache:\n{e}")

    def _load_from_cache(self):
        """Load a previously cached system."""
        cached = list_cached_systems()
        if not cached:
            messagebox.showinfo("Cache", "No cached systems found.")
            return

        # Simple selection dialog
        win = tk.Toplevel(self.winfo_toplevel())
        win.title("Load Cached System")
        win.geometry("500x300")
        win.transient(self.winfo_toplevel())
        win.grab_set()

        ttk.Label(win, text="Select a cached system:").pack(
            fill=tk.X, padx=8, pady=(8, 4))

        cols = ("name", "date", "talkgroups")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=10)
        tree.heading("name", text="System Name")
        tree.heading("date", text="Cached")
        tree.heading("talkgroups", text="TGs")
        tree.column("name", width=250)
        tree.column("date", width=150)
        tree.column("talkgroups", width=60)

        for filepath, name, cached_at, tg_count in cached:
            tree.insert("", tk.END,
                        values=(name, cached_at[:16], tg_count),
                        tags=(str(filepath),))
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        def _load_selected():
            sel = tree.selection()
            if not sel:
                return
            tags = tree.item(sel[0], "tags")
            if not tags:
                return
            filepath = tags[0]
            try:
                system = load_system(filepath)
                self.paste_system = system
                self.paste_set_name.set(make_set_name(system.name))
                self._populate_paste_filters()

                tg_count = len(system.talkgroups)
                freq_count = sum(len(s.freqs) for s in system.sites)
                self.paste_parse_status.config(
                    text=f"Loaded from cache: {system.name} | "
                         f"{tg_count} TGs | {freq_count} freqs",
                    foreground="green")
                log_action("cache_load",
                           system=system.name, path=filepath)
                win.destroy()
            except Exception as e:
                log_error("cache_load", str(e))
                messagebox.showerror("Error", f"Failed to load:\n{e}")

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=8, pady=(0, 8))
        ttk.Button(btn_frame, text="Load", command=_load_selected,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Cancel", command=win.destroy,
                   width=10).pack(side=tk.RIGHT, padx=2)

    def _load_paste_file(self):
        """Load page data from a saved text file."""
        path = filedialog.askopenfilename(
            title="Load Page Data",
            filetypes=[("Text/CSV/HTML", "*.txt *.csv *.tsv *.html *.htm"),
                       ("All Files", "*.*")])
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.paste_text.delete("1.0", tk.END)
            self.paste_text.insert("1.0", content)
            log_action("load_file", path=path, size=len(content))
            self._parse_full_page()
        except Exception as e:
            log_error("load_file", str(e), path=path)
            messagebox.showerror("Error", f"Failed to load file:\n{e}")

    # --- Paste preview & inject ---

    def _paste_preview(self):
        """Preview what will be injected from paste data."""
        if not self.paste_system:
            messagebox.showwarning(
                "Warning", "Parse a page first (click Parse Page).")
            return

        filtered_tgs = self._get_filtered_paste_tgs()
        selected_sites = self.get_selected_sites()
        freq_count = sum(len(s.freqs) for s in selected_sites)
        total_sites = len(self.paste_system.sites)

        # Collect NACs from selected sites
        site_nacs = sorted(set(
            s.nac for s in selected_sites if s.nac))
        sys_nac = self.paste_system.nac or ""

        lines = [
            f"System: {self.paste_system.name}",
            f"WACN: {self.paste_system.wacn or '(none)'} | "
            f"SysID: {self.paste_system.sysid or '(none)'}",
        ]
        if sys_nac or site_nacs:
            nac_str = sys_nac or ", ".join(site_nacs)
            lines.append(f"NAC: {nac_str}")
        lines.extend([
            f"Set Name: {self.paste_set_name.get() or '(not set)'}",
            f"Talkgroups: {len(filtered_tgs)} "
            f"(of {len(self.paste_system.talkgroups)} total)",
            f"Sites: {len(selected_sites)} of {total_sites}",
            f"Frequencies: {freq_count} (from selected sites)",
            "",
        ])

        if filtered_tgs:
            lines.append("Talkgroups to inject:")
            for tg in filtered_tgs[:30]:
                short = make_short_name(tg.alpha_tag)
                long = make_long_name(tg.description, tg.alpha_tag)
                lines.append(
                    f"  {tg.dec_id:5d}  {short:<8s}  {long}")
            if len(filtered_tgs) > 30:
                lines.append(
                    f"  ... and {len(filtered_tgs) - 30} more")
            lines.append("")

        if selected_sites:
            # Show selected sites summary
            counties = sorted(set(
                s.county for s in selected_sites if s.county))
            if counties:
                lines.append(f"Counties: {', '.join(counties)}")
                lines.append("")

        if freq_count > 0:
            lines.append("Frequencies (first 20):")
            shown = 0
            for site in selected_sites:
                for sf in site.freqs:
                    if shown >= 20:
                        break
                    tx = calculate_tx_freq(sf.freq)
                    if abs(tx - sf.freq) > 0.001:
                        lines.append(
                            f"  TX:{tx:.5f}  RX:{sf.freq:.5f} MHz")
                    else:
                        lines.append(f"  {sf.freq:.5f} MHz")
                    shown += 1
            if freq_count > 20:
                lines.append(f"  ... and {freq_count - 20} more")

        # IDEN table info
        rx_freqs = [sf.freq for s in selected_sites
                    for sf in s.freqs]
        if rx_freqs:
            from ..radioreference import detect_p25_band
            band, offset = detect_p25_band(rx_freqs[0])
            lines.append("")
            lines.append(f"Band: {band or 'unknown'} "
                         f"(TX offset: {offset:+.0f} MHz)")
            sys_type = self.paste_system.system_type or ""
            is_tdma = "Phase II" in sys_type
            lines.append(f"IDEN: {'TDMA' if is_tdma else 'FDMA'} "
                         f"({'6.25' if is_tdma else '12.5'} kHz)")

        # Conventional channels
        selected_conv = self._get_selected_conv_channels()
        if selected_conv:
            lines.append("")
            lines.append(f"Conventional Channels: {len(selected_conv)}")
            for ch in selected_conv[:20]:
                tx_str = (f"TX:{ch.tx_freq:.5f} "
                          if ch.tx_freq > 0 else "")
                tone_str = f" [{ch.tone}]" if ch.tone else ""
                lines.append(
                    f"  {ch.freq:.5f} {tx_str}"
                    f"{ch.name or ''}{tone_str}")
            if len(selected_conv) > 20:
                lines.append(
                    f"  ... and {len(selected_conv) - 20} more")

        messagebox.showinfo("Preview", "\n".join(lines))

    def _show_inject_confirm(self, set_name, tg_count, freq_count,
                             iden_count, sys_name="", wacn="",
                             sysid="", nac="", tg_samples=None,
                             conv_count=0, ecc_count=0,
                             reused_iden_name=""):
        """Show injection confirmation dialog. Returns True if user OKs."""
        dlg = tk.Toplevel(self)
        dlg.title("Confirm Injection")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        dlg.resizable(False, False)

        result = [False]

        main = ttk.Frame(dlg, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="Inject the following into PRS?",
                  font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 8))

        info = ttk.Frame(main)
        info.pack(fill=tk.X, pady=(0, 8))

        rows = [
            ("System:", sys_name or set_name),
            ("Set Name:", set_name),
        ]
        if wacn:
            rows.append(("WACN:", wacn))
        if sysid:
            rows.append(("SysID:", sysid))
        if nac:
            rows.append(("NAC:", nac))
        if tg_count:
            tg_label = str(tg_count)
            scan_default = self.app.settings.get("scan_enabled_default", True)
            if scan_default and tg_count > 127:
                tg_label += "  ** EXCEEDS 127 SCAN LIMIT **"
            elif scan_default and tg_count > 120:
                tg_label += f"  (near 127 scan limit)"
            rows.append(("Talkgroups:", tg_label))
        if freq_count:
            rows.append(("Frequencies:", str(freq_count)))
        if iden_count:
            if reused_iden_name:
                rows.append(("IDEN:", f"reused '{reused_iden_name}' "
                              f"({iden_count} entries)"))
            else:
                rows.append(("IDEN Entries:", str(iden_count)))
        if ecc_count:
            ecc_label = str(ecc_count)
            if ecc_count >= 30:
                ecc_label += "  (max 30)"
            rows.append(("Enhanced CC:", ecc_label))
        if conv_count:
            rows.append(("Conv Channels:", str(conv_count)))

        for i, (label, value) in enumerate(rows):
            ttk.Label(info, text=label, font=("", 9, "bold")).grid(
                row=i, column=0, sticky=tk.W, padx=(0, 8))
            ttk.Label(info, text=value).grid(
                row=i, column=1, sticky=tk.W)

        # Show talkgroup samples if available
        if tg_samples:
            ttk.Separator(main, orient=tk.HORIZONTAL).pack(
                fill=tk.X, pady=4)
            ttk.Label(main, text="Talkgroups (sample):").pack(
                anchor=tk.W)
            sample_frame = ttk.Frame(main)
            sample_frame.pack(fill=tk.X, pady=(2, 8))
            sample_text = tk.Text(
                sample_frame, height=min(8, len(tg_samples)),
                width=50, font=("Consolas", 9), state=tk.NORMAL)
            sample_text.pack(fill=tk.X)
            for gid, short, long_name in tg_samples[:15]:
                sample_text.insert(
                    tk.END, f"  {gid:5d}  {short:<8s}  {long_name}\n")
            if len(tg_samples) > 15:
                sample_text.insert(
                    tk.END,
                    f"  ... and {len(tg_samples) - 15} more\n")
            sample_text.config(state=tk.DISABLED)

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(8, 0))

        def _ok():
            result[0] = True
            dlg.destroy()

        def _cancel():
            dlg.destroy()

        ttk.Button(btn_frame, text="Inject", command=_ok,
                   width=10).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="Cancel", command=_cancel,
                   width=10).pack(side=tk.RIGHT)

        dlg.bind("<Return>", lambda e: _ok())
        dlg.bind("<Escape>", lambda e: _cancel())
        dlg.update_idletasks()
        # Center on parent
        pw = self.winfo_toplevel()
        x = pw.winfo_x() + (pw.winfo_width() - dlg.winfo_width()) // 2
        y = pw.winfo_y() + (pw.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.wait_window()
        return result[0]

    def _paste_inject(self):
        """Inject parsed paste data — auto-detects P25 trunked vs conventional."""
        if not self.app.prs:
            messagebox.showwarning(
                "Warning", "Open a .PRS file first (File > Open).")
            return

        if not self.paste_system:
            messagebox.showwarning(
                "Warning", "Parse a page first (click Parse Page).")
            return

        filtered_tgs = self._get_filtered_paste_tgs()
        selected_sites = self.get_selected_sites()
        rx_freqs = [sf.freq for s in selected_sites for sf in s.freqs]
        selected_conv = self._get_selected_conv_channels()

        if not filtered_tgs and not rx_freqs and not selected_conv:
            messagebox.showwarning(
                "Warning",
                "No talkgroups, frequencies, or channels to inject.")
            return

        set_name = self.paste_set_name.get().strip()
        if not set_name:
            messagebox.showwarning("Warning", "Enter a set name.")
            return
        if len(set_name) > 8:
            set_name = set_name[:8]

        # Save undo snapshot before modifying
        self.app.save_undo_snapshot("Import P25 system")

        try:
            tg_count = 0
            freq_count = 0
            iden_count = 0

            # Build group set from filtered talkgroups
            new_gset = None
            if filtered_tgs:
                tg_tuples = []
                for tg in filtered_tgs:
                    if tg.dec_id <= 0 or tg.dec_id > 65535:
                        continue
                    short = make_short_name(tg.alpha_tag)
                    long = make_long_name(tg.description, tg.alpha_tag)
                    tg_tuples.append((tg.dec_id, short, long))

                if tg_tuples:
                    s = self.app.settings
                    new_gset = make_group_set(
                        set_name, tg_tuples,
                        tx_default=s.get("tx_enabled_default", False),
                        scan_default=s.get("scan_enabled_default", True))
                    issues = validate_group_set(new_gset)
                    errors = [i for i in issues if i[0] == ERROR]
                    if errors:
                        msg = "\n".join(f"  {m}" for _, m in errors)
                        if not messagebox.askyesno(
                                "Validation Errors",
                                f"Group set has errors:\n{msg}\n\n"
                                "Inject anyway?"):
                            return
                    tg_count = len(tg_tuples)

            # Build trunk set from frequencies with TX offsets
            new_tset = None
            if rx_freqs:
                freq_tuples = [
                    (calculate_tx_freq(f), f) for f in rx_freqs]
                seen = set()
                unique_freqs = []
                for tx, rx in freq_tuples:
                    key = (round(tx, 5), round(rx, 5))
                    if key not in seen:
                        seen.add(key)
                        unique_freqs.append((tx, rx))

                new_tset = make_trunk_set(set_name, unique_freqs)
                issues = validate_trunk_set(new_tset)
                errors = [i for i in issues if i[0] == ERROR]
                if errors:
                    msg = "\n".join(f"  {m}" for _, m in errors)
                    if not messagebox.askyesno(
                            "Validation Errors",
                            f"Trunk set has errors:\n{msg}\n\n"
                            "Inject anyway?"):
                        return
                freq_count = len(unique_freqs)

            # Build IDEN set — check for existing match first
            new_iset = None
            reused_iden_name = ""
            if rx_freqs:
                sys_type = self.paste_system.system_type or ""
                template_key = auto_select_template_key(
                    rx_freqs, sys_type)

                # Check if PRS already has a matching IDEN set
                if template_key and self.app.prs:
                    existing_name = find_matching_iden_set(
                        self.app.prs, template_key)
                    if existing_name:
                        reused_iden_name = existing_name
                        iden_count = sum(
                            1 for e in get_template(template_key).entries
                            if e.get('base_freq_hz', 0) > 0)

                # No existing match — create new IDEN set
                if not reused_iden_name:
                    iden_entries = build_standard_iden_entries(
                        rx_freqs, sys_type)
                    if iden_entries:
                        iden_name = self.paste_system.wacn or set_name
                        if len(iden_name) > 8:
                            iden_name = iden_name[:8]
                        new_iset = make_iden_set(iden_name, iden_entries)
                        issues = validate_iden_set(new_iset)
                        errors = [i for i in issues if i[0] == ERROR]
                        if errors and not messagebox.askyesno(
                                "IDEN Validation",
                                "IDEN set has errors. Inject anyway?"):
                            new_iset = None
                        else:
                            iden_count = sum(
                                1 for e in new_iset.elements
                                if not e.is_empty())

            # Parse system ID from hex string
            sys_id = 0
            if self.paste_system.sysid:
                try:
                    sys_id = int(self.paste_system.sysid, 16)
                except ValueError:
                    pass

            # Build system long name (16 char max)
            long_name = self.paste_system.name or set_name
            if len(long_name) > 16:
                long_name = long_name[:16]

            # WAN name — use WACN if available, else set name
            wan_name = self.paste_system.wacn or set_name
            if len(wan_name) > 8:
                wan_name = wan_name[:8]

            # Build Enhanced CC entries from selected sites
            ecc_entries = []
            ecc_count = 0
            if selected_sites and sys_id:
                sys_type = self.paste_system.system_type or ""
                ecc_tuples = build_ecc_from_sites(
                    selected_sites, sys_id, sys_type)
                for etype, sid, ch1, ch2 in ecc_tuples:
                    ecc_entries.append(EnhancedCCEntry(
                        entry_type=etype,
                        system_id=sid,
                        channel_ref1=ch1,
                        channel_ref2=ch2,
                    ))
                ecc_count = len(ecc_entries)

            # Show confirmation preview
            tg_samples = None
            if new_gset and filtered_tgs:
                tg_samples = [
                    (tg.dec_id,
                     make_short_name(tg.alpha_tag),
                     make_long_name(tg.description, tg.alpha_tag))
                    for tg in filtered_tgs]
            # Collect NAC for display
            nac_display = self.paste_system.nac or ""
            if not nac_display and selected_sites:
                site_nacs = sorted(set(
                    s.nac for s in selected_sites if s.nac))
                if site_nacs:
                    nac_display = ", ".join(site_nacs)

            if not self._show_inject_confirm(
                    set_name=set_name,
                    tg_count=tg_count,
                    freq_count=freq_count,
                    iden_count=iden_count,
                    ecc_count=ecc_count,
                    sys_name=self.paste_system.name or "",
                    wacn=wan_name,
                    sysid=self.paste_system.sysid or "",
                    nac=nac_display,
                    tg_samples=tg_samples,
                    conv_count=len(selected_conv),
                    reused_iden_name=reused_iden_name):
                return

            # Create the full P25 trunked system with all settings
            s = self.app.settings
            home_id = s.get("home_unit_id", 0)

            # Build sys_flags from P25 settings
            sys_flags = build_sys_flags(s)

            # Detect band limits and WAN config from frequencies
            sys_type = self.paste_system.system_type or ""
            band_lo, band_hi = detect_band_limits(rx_freqs)
            wan_spacing, wan_base = detect_wan_config(
                rx_freqs, sys_type)

            # IDEN set name — reuse existing or use new set name
            iden_name = reused_iden_name
            if not iden_name and new_iset:
                iden_name = new_iset.name

            config = P25TrkSystemConfig(
                system_name=set_name,
                long_name=long_name.upper(),
                trunk_set_name=set_name,
                group_set_name=set_name,
                wan_name=wan_name,
                home_unit_id=home_id,
                system_id=sys_id,
                sys_flags=sys_flags,
                iden_set_name=iden_name,
                band_low_hz=band_lo,
                band_high_hz=band_hi,
                wan_chan_spacing_hz=wan_spacing,
                wan_base_freq_hz=wan_base,
                ecc_entries=ecc_entries,
            )

            # Inject P25 trunked system if we have talkgroups or trunk freqs
            if filtered_tgs or rx_freqs:
                add_p25_trunked_system(
                    self.app.prs, config,
                    trunk_set=new_tset,
                    group_set=new_gset,
                    iden_set=new_iset,
                )

            # Inject conventional system if we have conv channels
            conv_count = 0
            if selected_conv:
                conv_data = conv_channels_to_set_data(selected_conv)
                conv_set = make_conv_set(set_name, conv_data)
                conv_long = (self.paste_system.name or set_name)[:16]
                conv_config = ConvSystemConfig(
                    system_name=set_name,
                    long_name=conv_long.upper(),
                    conv_set_name=set_name,
                )
                add_conv_system(
                    self.app.prs, conv_config,
                    conv_set=conv_set)
                conv_count = len(conv_data)

            self.app.mark_modified()
            self.app.personality_view.refresh()

            # Build summary
            parts = []
            if tg_count:
                parts.append(f"{tg_count} TGs")
            if freq_count:
                parts.append(f"{freq_count} freqs")
            if iden_count:
                if reused_iden_name:
                    parts.append(f"IDEN reused '{reused_iden_name}'")
                else:
                    parts.append(f"{iden_count} IDEN")
            if ecc_count:
                parts.append(f"{ecc_count} ECC")
            if conv_count:
                parts.append(f"{conv_count} conv ch")

            summary = f"Injected '{set_name}': " + ", ".join(parts)
            self.app.status_set(summary)
            self.paste_status.config(
                text=" + ".join(parts), foreground="green")

            log_action("inject_system",
                       set_name=set_name,
                       talkgroups=tg_count,
                       frequencies=freq_count,
                       iden_entries=iden_count,
                       ecc_entries=ecc_count,
                       conv_channels=conv_count,
                       system_id=sys_id,
                       system=self.paste_system.name)

            # Build success message
            msg_lines = [f"Injected into PRS as '{set_name}':"]
            if tg_count or freq_count:
                msg_lines.append(f"  P25 System: {set_name}")
                if tg_count:
                    msg_lines.append(f"  {tg_count} talkgroups")
                if freq_count:
                    msg_lines.append(f"  {freq_count} frequencies")
                if iden_count:
                    if reused_iden_name:
                        msg_lines.append(
                            f"  IDEN: reused '{reused_iden_name}' "
                            f"({iden_count} entries)")
                    else:
                        msg_lines.append(f"  {iden_count} IDEN entries")
                if ecc_count:
                    msg_lines.append(f"  {ecc_count} Enhanced CC entries")
                if wan_name:
                    msg_lines.append(f"  WAN: {wan_name}")
            if conv_count:
                msg_lines.append(f"  Conv System: {set_name}")
                msg_lines.append(f"  {conv_count} conventional channels")
            msg_lines.append("")
            msg_lines.append(
                "Save the file and verify in RPM before "
                "loading to radio.")

            messagebox.showinfo("Success", "\n".join(msg_lines))

            # Auto-validate if enabled
            if self.app.settings.get("auto_validate", True):
                self.app.validate()

        except Exception as e:
            log_error("inject_system", str(e))
            messagebox.showerror("Injection Error", str(e))

    # =================================================================
    # API TAB
    # =================================================================

    def _build_api_tab(self, parent):
        self._build_url_section(parent)
        self._build_credentials_section(parent)
        self._build_results_section(parent)
        self._build_api_action_section(parent)

    def _build_url_section(self, parent):
        frame = ttk.LabelFrame(
            parent, text="RadioReference System", padding=4)
        frame.pack(fill=tk.X, pady=(0, 4))

        row = ttk.Frame(frame)
        row.pack(fill=tk.X)

        ttk.Label(row, text="URL or SID:").pack(side=tk.LEFT)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(
            row, textvariable=self.url_var, width=40)
        self.url_entry.pack(
            side=tk.LEFT, padx=4, fill=tk.X, expand=True)

        self.fetch_btn = ttk.Button(
            row, text="Fetch", command=self._fetch, width=8)
        self.fetch_btn.pack(side=tk.LEFT, padx=2)

        self.fetch_status = ttk.Label(
            frame, text="", foreground="gray")
        self.fetch_status.pack(fill=tk.X, pady=(2, 0))

    def _build_credentials_section(self, parent):
        frame = ttk.LabelFrame(
            parent, text="API Credentials (Premium)", padding=4)
        frame.pack(fill=tk.X, pady=(0, 4))

        grid = ttk.Frame(frame)
        grid.pack(fill=tk.X)

        ttk.Label(grid, text="Username:").grid(
            row=0, column=0, sticky=tk.W)
        self.user_var = tk.StringVar()
        ttk.Entry(grid, textvariable=self.user_var, width=25).grid(
            row=0, column=1, padx=4, sticky=tk.W)

        ttk.Label(grid, text="Password:").grid(
            row=0, column=2, sticky=tk.W, padx=(8, 0))
        self.pass_var = tk.StringVar()
        ttk.Entry(grid, textvariable=self.pass_var, show="*",
                  width=25).grid(
            row=0, column=3, padx=4, sticky=tk.W)

        ttk.Label(grid, text="App Key:").grid(
            row=1, column=0, sticky=tk.W, pady=(2, 0))
        self.key_var = tk.StringVar()
        ttk.Entry(grid, textvariable=self.key_var, width=40).grid(
            row=1, column=1, columnspan=3,
            padx=4, sticky=tk.W, pady=(2, 0))

        ttk.Label(
            frame,
            text=("Requires premium subscription + API key. "
                  "Email support@radioreference.com for a key."),
            foreground="gray",
            font=("", 8)).pack(anchor=tk.W, pady=(2, 0))

    def _build_results_section(self, parent):
        frame = ttk.LabelFrame(
            parent, text="System Data", padding=4)
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        self.sys_info = ttk.Label(
            frame, text="No system loaded", wraplength=500)
        self.sys_info.pack(fill=tk.X, pady=(0, 4))

        nb = ttk.Notebook(frame)
        nb.pack(fill=tk.BOTH, expand=True)

        cat_frame = ttk.Frame(nb, padding=4)
        self._build_category_list(cat_frame)
        nb.add(cat_frame, text="Categories")

        tg_frame = ttk.Frame(nb, padding=4)
        self._build_talkgroup_list(tg_frame)
        nb.add(tg_frame, text="Talkgroups")

        freq_frame = ttk.Frame(nb, padding=4)
        self._build_freq_list(freq_frame)
        nb.add(freq_frame, text="Sites/Freqs")

    def _build_category_list(self, parent):
        header = ttk.Frame(parent)
        header.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(header, text="Select All",
                   command=self._select_all_cats).pack(
                       side=tk.LEFT, padx=2)
        ttk.Button(header, text="Select None",
                   command=self._select_no_cats).pack(
                       side=tk.LEFT, padx=2)
        ttk.Button(header, text="Law Only",
                   command=self._select_law).pack(
                       side=tk.LEFT, padx=2)
        ttk.Button(header, text="Fire/EMS",
                   command=self._select_fire_ems).pack(
                       side=tk.LEFT, padx=2)

        self.tag_frame = ttk.LabelFrame(
            parent, text="Service Tags", padding=2)
        self.tag_frame.pack(fill=tk.X, pady=(0, 4))
        self.tag_inner = ttk.Frame(self.tag_frame)
        self.tag_inner.pack(fill=tk.X)

        canvas_frame = ttk.Frame(parent)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.cat_canvas = tk.Canvas(
            canvas_frame, highlightthickness=0)
        cat_vsb = ttk.Scrollbar(
            canvas_frame, orient=tk.VERTICAL,
            command=self.cat_canvas.yview)
        self.cat_inner_frame = ttk.Frame(self.cat_canvas)

        self.cat_inner_frame.bind(
            "<Configure>",
            lambda e: self.cat_canvas.configure(
                scrollregion=self.cat_canvas.bbox("all")))

        self.cat_canvas.create_window(
            (0, 0), window=self.cat_inner_frame, anchor=tk.NW)
        self.cat_canvas.configure(yscrollcommand=cat_vsb.set)

        self.cat_canvas.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True)
        cat_vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_talkgroup_list(self, parent):
        cols = ("id", "name", "description", "mode", "tag")
        self.tg_tree = ttk.Treeview(
            parent, columns=cols, show="headings", height=12)
        self.tg_tree.heading("id", text="ID")
        self.tg_tree.heading("name", text="Alpha Tag")
        self.tg_tree.heading("description", text="Description")
        self.tg_tree.heading("mode", text="Mode")
        self.tg_tree.heading("tag", text="Service")

        self.tg_tree.column("id", width=60, minwidth=50)
        self.tg_tree.column("name", width=120, minwidth=80)
        self.tg_tree.column("description", width=200, minwidth=100)
        self.tg_tree.column("mode", width=50, minwidth=40)
        self.tg_tree.column("tag", width=100, minwidth=60)

        vsb = ttk.Scrollbar(
            parent, orient=tk.VERTICAL,
            command=self.tg_tree.yview)
        self.tg_tree.configure(yscrollcommand=vsb.set)
        self.tg_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_freq_list(self, parent):
        cols = ("site", "rfss", "nac", "freqs")
        self.freq_tree = ttk.Treeview(
            parent, columns=cols, show="headings", height=12)
        self.freq_tree.heading("site", text="Site")
        self.freq_tree.heading("rfss", text="RFSS")
        self.freq_tree.heading("nac", text="NAC")
        self.freq_tree.heading("freqs", text="Frequencies")

        self.freq_tree.column("site", width=150, minwidth=80)
        self.freq_tree.column("rfss", width=50, minwidth=40)
        self.freq_tree.column("nac", width=50, minwidth=40)
        self.freq_tree.column("freqs", width=300, minwidth=100)

        vsb = ttk.Scrollbar(
            parent, orient=tk.VERTICAL,
            command=self.freq_tree.yview)
        self.freq_tree.configure(yscrollcommand=vsb.set)
        self.freq_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_api_action_section(self, parent):
        frame = ttk.Frame(parent, padding=4)
        frame.pack(fill=tk.X)

        ttk.Label(frame, text="Set Name:").pack(side=tk.LEFT)
        self.api_set_name = tk.StringVar()
        ttk.Entry(frame, textvariable=self.api_set_name,
                  width=12).pack(side=tk.LEFT, padx=4)

        ttk.Button(frame, text="Inject into PRS",
                   command=self._api_inject,
                   width=16).pack(side=tk.RIGHT, padx=2)
        ttk.Button(frame, text="Preview",
                   command=self._api_preview,
                   width=10).pack(side=tk.RIGHT, padx=2)

        self.tg_count_label = ttk.Label(frame, text="")
        self.tg_count_label.pack(side=tk.RIGHT, padx=8)

    # --- API Fetch handler ---

    def _fetch(self):
        url = self.url_var.get().strip()
        sid = parse_rr_url(url) if url else None

        if not sid:
            messagebox.showwarning(
                "Warning",
                "Enter a valid RadioReference URL or SID.")
            return

        username = self.user_var.get().strip()
        password = self.pass_var.get().strip()
        app_key = self.key_var.get().strip()

        if not all([username, password, app_key]):
            messagebox.showwarning(
                "Warning",
                "Enter API credentials (username, password, app key).")
            return

        if not HAS_ZEEP:
            messagebox.showerror(
                "Error",
                "zeep library not installed.\nRun: pip install zeep")
            return

        log_action("api_fetch", sid=sid)
        self.fetch_status.config(
            text="Connecting to RadioReference API...",
            foreground="blue")
        self.fetch_btn.config(state=tk.DISABLED)

        def _do_fetch():
            try:
                api = RadioReferenceAPI(username, password, app_key)
                system = api.get_system(sid)
                self.winfo_toplevel().after(
                    0, self._on_fetch_complete, system, None)
            except Exception as e:
                self.winfo_toplevel().after(
                    0, self._on_fetch_complete, None, str(e))

        threading.Thread(target=_do_fetch, daemon=True).start()

    def _on_fetch_complete(self, system, error):
        self.fetch_btn.config(state=tk.NORMAL)

        if error:
            log_error("api_fetch", error)
            self.fetch_status.config(
                text=f"Error: {error}", foreground="red")
            return

        self.rr_system = system
        has_tgs = len(system.talkgroups) > 0

        log_action("api_fetch_complete",
                   system=system.name,
                   talkgroups=len(system.talkgroups),
                   sites=len(system.sites))

        if has_tgs:
            self.fetch_status.config(
                text=f"Loaded: {system.name} "
                     f"({len(system.talkgroups)} talkgroups, "
                     f"{len(system.sites)} sites)",
                foreground="green")
        else:
            self.fetch_status.config(
                text=f"Loaded: {system.name} (0 talkgroups — "
                     "check credentials/subscription)",
                foreground="orange")

        info_parts = [system.name]
        if system.system_type:
            info_parts.append(system.system_type)
        if system.wacn:
            info_parts.append(f"WACN: {system.wacn}")
        if system.sysid:
            info_parts.append(f"SysID: {system.sysid}")
        info_parts.append(
            f"{len(system.talkgroups)} talkgroups, "
            f"{len(system.sites)} sites")
        self.sys_info.config(text=" | ".join(info_parts))

        self.api_set_name.set(make_set_name(system.name))
        self._populate_categories()
        self._populate_tags()
        self._populate_talkgroups()
        self._populate_frequencies()
        self._update_counts()

    # --- Populate API results ---

    def _populate_categories(self):
        for w in self.cat_inner_frame.winfo_children():
            w.destroy()
        self.category_vars.clear()

        if not self.rr_system:
            return

        cat_counts = {}
        for tg in self.rr_system.talkgroups:
            cat_id = tg.category_id
            cat_name = tg.category or f"Category {cat_id}"
            if cat_id not in cat_counts:
                cat_counts[cat_id] = (cat_name, 0)
            name, count = cat_counts[cat_id]
            cat_counts[cat_id] = (name, count + 1)

        for cat_id, (cat_name, count) in sorted(
                cat_counts.items(), key=lambda x: x[1][0]):
            var = tk.BooleanVar(value=True)
            self.category_vars[cat_id] = var
            cb = ttk.Checkbutton(
                self.cat_inner_frame,
                text=f"{cat_name} ({count})",
                variable=var,
                command=self._update_counts)
            cb.pack(anchor=tk.W, pady=1)

    def _populate_tags(self):
        for w in self.tag_inner.winfo_children():
            w.destroy()
        self.tag_vars.clear()

        if not self.rr_system:
            return

        tags = set(tg.tag for tg in self.rr_system.talkgroups
                   if tg.tag)
        for tag in sorted(tags):
            var = tk.BooleanVar(value=True)
            self.tag_vars[tag] = var
            cb = ttk.Checkbutton(
                self.tag_inner, text=tag, variable=var,
                command=self._update_counts)
            cb.pack(side=tk.LEFT, padx=4)

    def _populate_talkgroups(self):
        for item in self.tg_tree.get_children():
            self.tg_tree.delete(item)

        if not self.rr_system:
            return

        for tg in self.rr_system.talkgroups:
            self.tg_tree.insert("", tk.END, values=(
                tg.dec_id, tg.alpha_tag, tg.description,
                tg.mode, tg.tag))

    def _populate_frequencies(self):
        for item in self.freq_tree.get_children():
            self.freq_tree.delete(item)

        if not self.rr_system:
            return

        for site in self.rr_system.sites:
            freq_strs = []
            for sf in site.freqs:
                use_mark = f"({sf.use})" if sf.use else ""
                freq_strs.append(f"{sf.freq:.5f}{use_mark}")
            self.freq_tree.insert("", tk.END, values=(
                f"{site.site_number} - {site.name}",
                site.rfss, site.nac,
                ", ".join(freq_strs[:8]) +
                ("..." if len(freq_strs) > 8 else ""),
            ))

    # --- API Category helpers ---

    def _get_selected_categories(self):
        return {cid for cid, var in self.category_vars.items()
                if var.get()}

    def _get_selected_tags(self):
        return {tag for tag, var in self.tag_vars.items()
                if var.get()}

    def _select_all_cats(self):
        for var in self.category_vars.values():
            var.set(True)
        for var in self.tag_vars.values():
            var.set(True)
        self._update_counts()

    def _select_no_cats(self):
        for var in self.category_vars.values():
            var.set(False)
        self._update_counts()

    def _select_law(self):
        law_tags = {"Law Dispatch", "Law Tac", "Law Talk",
                    "Corrections"}
        for tag, var in self.tag_vars.items():
            var.set(tag in law_tags)
        self._update_counts()

    def _select_fire_ems(self):
        fire_ems = {"Fire Dispatch", "Fire-Tac", "Fire-Talk",
                    "Fire Tac", "Fire Talk",
                    "EMS Dispatch", "EMS-Tac", "EMS-Talk",
                    "EMS Tac", "EMS Talk", "Hospital"}
        for tag, var in self.tag_vars.items():
            var.set(tag in fire_ems)
        self._update_counts()

    def _update_counts(self):
        if not self.rr_system:
            return

        selected_cats = self._get_selected_categories()
        selected_tags = self._get_selected_tags()

        count = sum(
            1 for tg in self.rr_system.talkgroups
            if tg.category_id in selected_cats
            and (not tg.tag or tg.tag in selected_tags))
        total = len(self.rr_system.talkgroups)
        self.tg_count_label.config(
            text=f"{count}/{total} talkgroups selected")

    # --- API Preview & Inject ---

    def _api_preview(self):
        if not self.rr_system:
            messagebox.showwarning(
                "Warning", "No system data loaded.")
            return

        data = build_injection_data(
            self.rr_system,
            selected_categories=self._get_selected_categories(),
            selected_tags=self._get_selected_tags())

        lines = [
            f"System: {data['full_name']}",
            f"WACN: {data['wacn']} | SysID: {data['sysid']}",
            f"Set Name: {self.api_set_name.get() or data['system_name']}",
            f"Talkgroups: {len(data['talkgroups'])}",
            f"Frequencies: {len(data['frequencies'])}",
            f"IDEN entries: {sum(1 for e in data.get('iden_entries', []) if e.get('base_freq_hz', 0) > 0)}",
            "",
            "Talkgroups to inject:",
        ]
        for gid, short, long in data['talkgroups'][:30]:
            lines.append(f"  {gid:5d}  {short:<8s}  {long}")
        if len(data['talkgroups']) > 30:
            lines.append(
                f"  ... and {len(data['talkgroups']) - 30} more")

        messagebox.showinfo("Preview", "\n".join(lines))

    def _api_inject(self):
        if not self.app.prs:
            messagebox.showwarning(
                "Warning",
                "Open a .PRS file first (File > Open).")
            return

        if not self.rr_system:
            messagebox.showwarning(
                "Warning", "No system data loaded.")
            return

        set_name = self.api_set_name.get().strip()
        if not set_name:
            messagebox.showwarning("Warning", "Enter a set name.")
            return
        if len(set_name) > 8:
            set_name = set_name[:8]

        data = build_injection_data(
            self.rr_system,
            selected_categories=self._get_selected_categories(),
            selected_tags=self._get_selected_tags())

        if not data['talkgroups'] and not data['frequencies']:
            messagebox.showwarning(
                "Warning",
                "No talkgroups or frequencies selected.")
            return

        # Show confirmation preview before modifying
        iden_entries = data.get('iden_entries', [])
        preview_iden = sum(
            1 for e in iden_entries if e.get('base_freq_hz', 0) > 0)
        if not self._show_inject_confirm(
                set_name=set_name,
                tg_count=len(data['talkgroups']),
                freq_count=len(data['frequencies']),
                iden_count=preview_iden,
                sys_name=data.get('full_name', ''),
                wacn=data.get('wacn', ''),
                sysid=data.get('sysid', ''),
                tg_samples=data['talkgroups'][:50] if data['talkgroups'] else None):
            return

        # Save undo snapshot before modifying
        self.app.save_undo_snapshot("Import RadioReference system")

        try:
            s = self.app.settings
            tg_count = 0
            freq_count = 0
            iden_count = 0

            # Build sets
            new_gset = None
            new_tset = None
            new_iset = None

            if data['talkgroups']:
                new_gset = make_group_set(
                    set_name, data['talkgroups'],
                    tx_default=s.get("tx_enabled_default", False),
                    scan_default=s.get("scan_enabled_default", True))
                issues = validate_group_set(new_gset)
                errors = [i for i in issues if i[0] == ERROR]
                if errors:
                    msg = "\n".join(f"  {m}" for _, m in errors)
                    if not messagebox.askyesno(
                            "Validation Errors",
                            f"Group set has errors:\n{msg}\n\n"
                            "Inject anyway?"):
                        return
                tg_count = len(data['talkgroups'])

            if data['frequencies']:
                new_tset = make_trunk_set(
                    set_name, data['frequencies'])
                issues = validate_trunk_set(new_tset)
                errors = [i for i in issues if i[0] == ERROR]
                if errors:
                    msg = "\n".join(f"  {m}" for _, m in errors)
                    if not messagebox.askyesno(
                            "Validation Errors",
                            f"Trunk set has errors:\n{msg}\n\n"
                            "Inject anyway?"):
                        return
                freq_count = len(data['frequencies'])

            # Build IDEN set — check for existing match first
            iden_entries = data.get('iden_entries', [])
            iden_name = ""
            reused_iden_name = ""
            rx_freqs_for_iden = [f for _, f in data['frequencies']] \
                if data['frequencies'] else []
            if rx_freqs_for_iden:
                sys_type = data.get('system_type', '')
                template_key = auto_select_template_key(
                    rx_freqs_for_iden, sys_type)
                if template_key and self.app.prs:
                    existing_name = find_matching_iden_set(
                        self.app.prs, template_key)
                    if existing_name:
                        reused_iden_name = existing_name
                        iden_name = existing_name
                        iden_count = sum(
                            1 for e in get_template(
                                template_key).entries
                            if e.get('base_freq_hz', 0) > 0)

            if not reused_iden_name and iden_entries:
                iden_name = self.rr_system.wacn or set_name
                if len(iden_name) > 8:
                    iden_name = iden_name[:8]
                new_iset = make_iden_set(iden_name, iden_entries)
                iden_count = sum(
                    1 for e in new_iset.elements
                    if not e.is_empty())

            # Build full P25 trunked system (not just orphan sets)
            rx_freqs = [f for _, f in data['frequencies']] if data['frequencies'] else []
            wan_name = data.get('wacn', '') or set_name
            if len(wan_name) > 8:
                wan_name = wan_name[:8]

            long_name = (data.get('full_name', '') or set_name)[:16]
            sys_id = 0
            try:
                sys_id = int(data.get('sysid', '0'), 16)
            except (ValueError, TypeError):
                pass

            sys_flags = build_sys_flags(s)
            band_lo, band_hi = detect_band_limits(rx_freqs)
            wan_spacing, wan_base = detect_wan_config(
                rx_freqs, data.get('system_type', ''))

            config = P25TrkSystemConfig(
                system_name=set_name,
                long_name=long_name.upper(),
                trunk_set_name=set_name,
                group_set_name=set_name,
                wan_name=wan_name,
                home_unit_id=s.get("home_unit_id", 0),
                system_id=sys_id,
                sys_flags=sys_flags,
                iden_set_name=iden_name,
                band_low_hz=band_lo,
                band_high_hz=band_hi,
                wan_chan_spacing_hz=wan_spacing,
                wan_base_freq_hz=wan_base,
            )

            add_p25_trunked_system(
                self.app.prs, config,
                trunk_set=new_tset,
                group_set=new_gset,
                iden_set=new_iset,
            )

            self.app.mark_modified()
            self.app.personality_view.refresh()

            summary = (f"Injected: {tg_count} talkgroups, "
                       f"{freq_count} frequencies")
            if iden_count:
                if reused_iden_name:
                    summary += f", IDEN reused '{reused_iden_name}'"
                else:
                    summary += f", {iden_count} IDEN entries"
            self.app.status_set(summary + f" as '{set_name}'")

            log_action("inject_api",
                       set_name=set_name,
                       talkgroups=tg_count,
                       frequencies=freq_count,
                       iden_entries=iden_count)

            iden_msg = f"  {iden_count} IDEN entries"
            if reused_iden_name:
                iden_msg = (f"  IDEN: reused '{reused_iden_name}' "
                            f"({iden_count} entries)")
            messagebox.showinfo(
                "Success",
                f"Injected into PRS:\n"
                f"  {tg_count} talkgroups\n"
                f"  {freq_count} frequencies\n"
                f"{iden_msg}\n"
                f"  Set name: {set_name}\n\n"
                "Save the file and verify in RPM before "
                "loading to radio.")

            # Auto-validate if enabled
            if self.app.settings.get("auto_validate", True):
                self.app.validate()

        except Exception as e:
            log_error("inject_api", str(e))
            messagebox.showerror("Injection Error", str(e))
