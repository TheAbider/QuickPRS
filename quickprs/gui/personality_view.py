"""PRS Personality tree viewer widget.

Displays the loaded .PRS file as a hierarchical tree:
  Personality
  +-- P25 Trunked Systems
  |   +-- PSERN (CP25TrkSystem)
  |   +-- PSRS
  +-- Conventional Systems
  |   +-- FURRY WB (CConvSystem)
  +-- P25 Conv Systems
  |   +-- p25 conv (CP25ConvSystem)
  +-- Trunk Sets
  |   +-- PSERN (28 channels)
  |   |   +-- 806.88750 / 851.88750 MHz
  +-- Group Sets
  |   +-- PSERN PD (83 groups)
  |   |   +-- ALG PD 1 (2303)
  +-- IDEN Sets
  |   +-- BEE00 (16 elements)
  +-- Options (30 records)

Features:
  - Search/filter bar (Ctrl+F)
  - Right-click context menu (delete system/set, export CSV)
  - Double-click for details
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import csv
from pathlib import Path

from ..prs_parser import PRSFile
from ..binary_io import read_uint16_le
from ..record_types import (
    parse_class_header, parse_trunk_channel_section,
    parse_conv_channel_section, parse_group_section, parse_iden_section,
    parse_system_short_name, parse_system_long_name,
    is_system_config_data, parse_ecc_entries,
    ConvChannel, CONV_CHANNEL_SEP,
    P25TrkSystemConfig, ConvSystemConfig,
)
from ..option_maps import (
    OPTION_MAPS, extract_platform_config, extract_section_data,
    read_field, XML_FIELDS_BY_CATEGORY,
    format_button_function, format_button_name,
    format_short_menu_name, format_switch_function,
)
from ..logger import log_error

# Human-readable names for option/config class names (from RPM screenshots)
CLASS_DISPLAY_NAMES = {
    "CGenRadioOpts": "General Options",
    "CDTMFOpts": "DTMF Options",
    "CScanOpts": "Scan Options",
    "CAlertOpts": "Alert Options",
    "CAudioOpts": "Audio Options",
    "CBatteryOpts": "Battery Options",
    "CBluetoothOpts": "Bluetooth Options",
    "CClockOpts": "Clock Options",
    "CConvEmergencyOpts": "Conv Emergency Options",
    "CConvHomeOpts": "Conv Home Channel Options",
    "CCustomScanOpts": "Custom Scan Options",
    "CDataOpts": "Data Options",
    "CDiagnosticOpts": "Diagnostic Options",
    "CDigitalVoiceOpts": "Digital Voice Options",
    "CDisplayOpts": "Display Options",
    "CeDataOpts": "eData Options",
    "CGPSOpts": "GPS Options",
    "CKeyNamesOpts": "Key Names",
    "CP25OTAROpts": "P25 OTAR Options",
    "CP25WANOpts": "P25 WAN Options",
    "CPowerUpOpts": "Power Up Options",
    "CProgButtons": "Programmable Buttons",
    "CProScanOpts": "ProScan Options",
    "CRadioTextLinkOpts": "Radio TextLink Options",
    "CSecurityPolicy": "Security Policy",
    "CSignalingMDCOpts": "Signaling (MDC) Options",
    "CStatus": "Status/Message Options",
    "CSupervisoryOpts": "Supervisory Options",
    "CTimerOpts": "Timer Options",
    "CToneEncodeOpts": "Tone Encode Options",
    "CT99DecodeOpts": "Type 99 Decode Options",
    "CVoiceAnnunciation": "Voice Annunciation",
    "CAccessoryDevice": "Accessory Device Options",
    "CProgKnobOpts": "Programmable Knobs",
    "CProgShortcutOpts": "Programmable Shortcuts",
    "CProgICallOpts": "Programmable I-Call",
    "CProgPhoneOpts": "Programmable Phone",
    "CSystemScanOpts": "System Scan Options",
}

# Type abbreviations for system order display
TYPE_ABBREV = {
    "CP25TrkSystem": "P25T",
    "CConvSystem": "Conv",
    "CP25ConvSystem": "P25C",
}

def _format_xml_value(raw_val, field_def):
    """Format an XML attribute value for display in the tree."""
    if field_def.field_type == "onoff":
        return "On" if raw_val == "ON" else "Off"
    # Use field-specific display_map first
    if field_def.display_map:
        friendly = field_def.display_map.get(raw_val)
        if friendly:
            return friendly
    if field_def.field_type == "int":
        return raw_val
    return raw_val


def _format_field_value(val, field_def):
    """Format a binary field value for display in the tree."""
    if field_def.field_type == "bool":
        return "On" if val else "Off"
    if field_def.field_type == "enum" and isinstance(val, str):
        return val  # Binary enum_values already have friendly names
    return str(val)


class PersonalityView(ttk.Frame):
    """Treeview showing PRS personality structure."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        # Metadata for tree items: iid -> {type, name, class_name, ...}
        self._item_meta = {}

        # Search bar
        search_frame = ttk.Frame(self)
        search_frame.grid(row=0, column=0, columnspan=2, sticky="ew",
                          pady=(0, 2))
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)
        self.search_entry = ttk.Entry(search_frame,
                                       textvariable=self.search_var,
                                       width=20)
        self.search_entry.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(search_frame, text="X", width=2,
                   command=self._clear_search).pack(side=tk.LEFT)

        # Search/Filter mode toggle
        self._filter_mode = tk.BooleanVar(value=False)
        ttk.Checkbutton(search_frame, text="Hide non-matches",
                        variable=self._filter_mode,
                        command=self._on_search_changed).pack(
            side=tk.LEFT, padx=(6, 2))

        self.search_count = ttk.Label(search_frame, text="",
                                       foreground="gray")
        self.search_count.pack(side=tk.LEFT, padx=4)

        # Collapsible advanced filter panel
        self._filter_visible = False
        ttk.Button(search_frame, text="Filters",
                   width=7,
                   command=self._toggle_filter_panel).pack(
            side=tk.RIGHT, padx=2)

        self._filter_frame = ttk.LabelFrame(self, text="Advanced Filters",
                                             padding=4)
        # Not gridded by default — shown when toggled

        # Filter controls
        freq_row = ttk.Frame(self._filter_frame)
        freq_row.pack(fill=tk.X, pady=2)
        ttk.Label(freq_row, text="Freq range:").pack(side=tk.LEFT)
        self._freq_min_var = tk.StringVar()
        ttk.Entry(freq_row, textvariable=self._freq_min_var,
                  width=10).pack(side=tk.LEFT, padx=2)
        ttk.Label(freq_row, text="-").pack(side=tk.LEFT)
        self._freq_max_var = tk.StringVar()
        ttk.Entry(freq_row, textvariable=self._freq_max_var,
                  width=10).pack(side=tk.LEFT, padx=2)
        ttk.Label(freq_row, text="MHz").pack(side=tk.LEFT)

        tg_row = ttk.Frame(self._filter_frame)
        tg_row.pack(fill=tk.X, pady=2)
        ttk.Label(tg_row, text="TG ID range:").pack(side=tk.LEFT)
        self._tg_min_var = tk.StringVar()
        ttk.Entry(tg_row, textvariable=self._tg_min_var,
                  width=8).pack(side=tk.LEFT, padx=2)
        ttk.Label(tg_row, text="-").pack(side=tk.LEFT)
        self._tg_max_var = tk.StringVar()
        ttk.Entry(tg_row, textvariable=self._tg_max_var,
                  width=8).pack(side=tk.LEFT, padx=2)

        check_row = ttk.Frame(self._filter_frame)
        check_row.pack(fill=tk.X, pady=2)
        self._filter_tx_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(check_row, text="TX-enabled only",
                        variable=self._filter_tx_var).pack(
            side=tk.LEFT, padx=(0, 12))
        self._filter_scan_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(check_row, text="Scan-enabled only",
                        variable=self._filter_scan_var).pack(side=tk.LEFT)

        btn_row = ttk.Frame(self._filter_frame)
        btn_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(btn_row, text="Apply Filters",
                   command=self._apply_advanced_filters).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Clear Filters",
                   command=self._clear_advanced_filters).pack(
            side=tk.LEFT, padx=2)
        self._filter_indicator = ttk.Label(btn_row, text="",
                                            foreground="blue")
        self._filter_indicator.pack(side=tk.LEFT, padx=8)

        # Detached items storage for filter/restore
        self._detached_items = []  # [(iid, parent, index), ...]

        # Build tree (extended selection: Ctrl+Click, Shift+Click)
        self.tree = ttk.Treeview(self, show="tree headings",
                                  columns=("detail",), height=25,
                                  selectmode="extended")
        self.tree.heading("#0", text="Name", anchor=tk.W)
        self.tree.heading("detail", text="Detail", anchor=tk.W)
        self.tree.column("#0", width=280, minwidth=180)
        self.tree.column("detail", width=320, minwidth=150)

        vsb = ttk.Scrollbar(self, orient=tk.VERTICAL,
                             command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient=tk.HORIZONTAL,
                             command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set,
                             xscrollcommand=hsb.set)

        self.tree.grid(row=1, column=0, sticky="nsew")
        vsb.grid(row=1, column=1, sticky="ns")
        hsb.grid(row=2, column=0, sticky="ew")
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Status indicator tags
        self.tree.tag_configure("status_error", foreground="#cc3333")
        self.tree.tag_configure("status_warning", foreground="#cc8800")
        self.tree.tag_configure("status_near_capacity", foreground="#dd6600")
        self.tree.tag_configure("status_empty", foreground="#999999")
        self.tree.tag_configure("status_encrypted", foreground="#7744aa")

        # Double-click to show details
        self.tree.bind("<Double-1>", self._on_double_click)

        # Right-click context menu
        self.ctx_menu = tk.Menu(self.tree, tearoff=0)
        self.tree.bind("<Button-3>", self._on_right_click)

        # Ctrl+F to focus search
        self.app.root.bind('<Control-f>', lambda e: self._focus_search())

        # Alt+Up/Down to move items
        self.tree.bind('<Alt-Up>', self._on_move_up)
        self.tree.bind('<Alt-Down>', self._on_move_down)

        # Copy/paste clipboard
        self._clipboard = []  # list of copied item data dicts
        self._clipboard_type = None  # 'talkgroup' or 'conv_channel'
        self.tree.bind('<Control-c>', self._on_copy)
        self.tree.bind('<Control-v>', self._on_paste)

        # Drag-and-drop reordering
        self._drag_data = None  # {iid, type, parent_iid, start_y}
        self.tree.bind("<ButtonPress-1>", self._on_drag_start, add="+")
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_end)

    # ─── Expand state ────────────────────────────────────────────────

    def _stable_key(self, iid):
        """Return a hashable key that survives tree rebuild."""
        meta = self._item_meta.get(iid, {})
        t = meta.get("type", "")
        name = (meta.get("name") or meta.get("class_name")
                or meta.get("long_name") or "")
        return (t, name)

    def _get_expand_state(self):
        """Return set of stable keys for all currently-open nodes."""
        opened = set()
        stack = list(self.tree.get_children())
        while stack:
            iid = stack.pop()
            if self.tree.item(iid, "open"):
                opened.add(self._stable_key(iid))
            stack.extend(self.tree.get_children(iid))
        return opened

    def _restore_expand_state(self, opened):
        """Re-open nodes whose stable key was in the saved set."""
        stack = list(self.tree.get_children())
        while stack:
            iid = stack.pop()
            if self._stable_key(iid) in opened:
                self.tree.item(iid, open=True)
            stack.extend(self.tree.get_children(iid))

    # ─── Refresh ──────────────────────────────────────────────────────

    def refresh(self):
        """Rebuild tree from current PRS data."""
        opened = self._get_expand_state()
        self._detached_items.clear()  # tree rebuild invalidates detached refs
        self.tree.delete(*self.tree.get_children())
        self._item_meta.clear()

        prs = self.app.prs
        if not prs:
            return

        root = self._insert("", tk.END, text="Personality",
                             values=(f"{len(prs.sections)} sections",),
                             open=True, meta={"type": "root"})

        self._add_favorites(root)
        self._add_system_order(root, prs)
        self._add_systems(root, prs)
        self._add_trunk_sets(root, prs)
        self._add_conv_sets(root, prs)
        self._add_p25_conv_sets(root, prs)
        self._add_group_sets(root, prs)
        self._add_iden_sets(root, prs)
        self._add_options(root, prs)
        self._add_platform_config(root, prs)

        if opened:
            self._restore_expand_state(opened)

        # Apply status indicators after tree is built
        self._apply_status_indicators()

    def _apply_status_indicators(self):
        """Apply visual indicators to tree items based on validation results.

        Tags items with colored foreground text:
        - Systems/sets with validation errors: red
        - Systems/sets with validation warnings: orange
        - Group sets near capacity (>100 TGs): orange
        - Empty sets (0 items): gray
        - Encrypted talkgroups: purple
        """
        prs = self.app.prs
        if not prs:
            return

        try:
            from ..validation import validate_prs_detailed, ERROR, WARNING
            detailed = validate_prs_detailed(prs)
        except Exception:
            detailed = {}

        try:
            from ..health_check import run_health_check, CRITICAL, WARN
            health = run_health_check(prs)
        except Exception:
            health = []

        # Build lookup: category name -> worst severity
        # Categories look like "Group Set: PSERN PD", "Trunk Set: PSERN", etc.
        category_severity = {}
        for cat_name, issues in detailed.items():
            for severity, _msg in issues:
                prev = category_severity.get(cat_name, "")
                if severity == ERROR or prev != ERROR:
                    category_severity[cat_name] = severity

        # Health check items: (severity, category, message, suggestion)
        for item in health:
            sev, cat, _msg, _sug = item
            if sev == CRITICAL:
                mapped = ERROR
            elif sev == WARN:
                mapped = WARNING
            else:
                continue
            prev = category_severity.get(cat, "")
            if mapped == ERROR or prev != ERROR:
                category_severity[cat] = mapped

        # Walk all tree items and apply tags
        stack = list(self.tree.get_children())
        while stack:
            iid = stack.pop()
            meta = self._item_meta.get(iid, {})
            item_type = meta.get("type", "")
            name = meta.get("name", "")
            tags = list(self.tree.item(iid, "tags") or ())

            # Check group sets for capacity and emptiness
            if item_type == "group_set":
                set_data = meta.get("set_data")
                if set_data:
                    n_groups = len(set_data.groups)
                    if n_groups == 0 and "status_empty" not in tags:
                        tags.append("status_empty")
                    elif n_groups > 100 and "status_near_capacity" not in tags:
                        tags.append("status_near_capacity")
                # Check validation issues
                cat_key = f"Group Set: {name}"
                sev = category_severity.get(cat_key)
                if sev == ERROR and "status_error" not in tags:
                    tags.append("status_error")
                elif sev == WARNING and "status_warning" not in tags:
                    tags.append("status_warning")

            elif item_type in ("trunk_set", "conv_set", "iden_set",
                               "p25_conv_set"):
                set_data = meta.get("set_data")
                prefix_map = {
                    "trunk_set": "Trunk Set",
                    "conv_set": "Conv Set",
                    "iden_set": "IDEN Set",
                    "p25_conv_set": "P25 Conv Set",
                }
                prefix = prefix_map.get(item_type, "")
                cat_key = f"{prefix}: {name}"
                sev = category_severity.get(cat_key)
                if sev == ERROR and "status_error" not in tags:
                    tags.append("status_error")
                elif sev == WARNING and "status_warning" not in tags:
                    tags.append("status_warning")
                # Check empty sets
                if set_data:
                    items_attr = getattr(set_data, 'channels',
                                         getattr(set_data, 'groups',
                                                 getattr(set_data,
                                                         'elements',
                                                         None)))
                    if items_attr is not None and len(items_attr) == 0:
                        if "status_empty" not in tags:
                            tags.append("status_empty")

            elif item_type == "talkgroup":
                # Encrypted TGs get purple text
                long_name = meta.get("long_name", "")
                tree_values = self.tree.item(iid, "values")
                detail_str = tree_values[0] if tree_values else ""
                if "ENC" in detail_str and "status_encrypted" not in tags:
                    tags.append("status_encrypted")

            if tags:
                self.tree.item(iid, tags=tags)

            stack.extend(self.tree.get_children(iid))

    def _insert(self, parent, index, text="", values=(), open=False,
                meta=None, **kw):
        """Insert tree item with optional metadata tracking."""
        iid = self.tree.insert(parent, index, text=text, values=values,
                                open=open, **kw)
        if meta:
            self._item_meta[iid] = meta
        return iid

    # ─── Tree population ─────────────────────────────────────────────

    def _add_favorites(self, parent):
        """Show bookmarked items at the top of the tree."""
        try:
            from ..favorites import load_favorites
        except ImportError:
            return

        favorites = load_favorites()
        total = sum(len(v) for v in favorites.values())
        if total == 0:
            return

        node = self._insert(parent, tk.END,
                             text="Favorites",
                             values=(f"{total} bookmarks",),
                             meta={"type": "favorites_root"})

        for category in ('systems', 'talkgroups', 'channels', 'templates'):
            items = favorites.get(category, [])
            if not items:
                continue
            cat_node = self._insert(node, tk.END,
                                     text=category.title(),
                                     values=(f"{len(items)}",),
                                     meta={"type": "favorites_category",
                                           "category": category})
            for item in items:
                name = item.get('name', '?')
                note = item.get('note', '')
                detail_parts = []
                for k, v in item.items():
                    if k not in ('name', 'note') and v is not None:
                        detail_parts.append(f"{k}={v}")
                detail = ', '.join(detail_parts) if detail_parts else ''
                if note:
                    detail = f"{detail}  {note}" if detail else note
                self._insert(cat_node, tk.END,
                              text=name,
                              values=(detail,),
                              meta={"type": "favorite_item",
                                    "category": category,
                                    "name": name,
                                    "item_data": item})

    def _add_system_order(self, parent, prs):
        """Show systems in file order (matches radio display order).

        System class headers (CP25TrkSystem etc.) appear once per TYPE.
        Individual systems are in the config data sections that follow,
        identified by is_system_config_data().  The header's short name
        is used as fallback for the first config entry with no long name.
        """
        system_classes = {"CP25TrkSystem", "CConvSystem", "CP25ConvSystem"}
        systems = []
        current_type = None
        header_name = None
        header_used = False

        for sec in prs.sections:
            if sec.class_name in system_classes:
                current_type = sec.class_name
                header_name = parse_system_short_name(sec.raw)
                header_used = False
                continue

            if (not sec.class_name and current_type
                    and is_system_config_data(sec.raw)):
                long_name = parse_system_long_name(sec.raw) or ""
                if long_name:
                    name = long_name
                elif header_name and not header_used:
                    name = header_name
                    header_used = True
                else:
                    name = "(unnamed)"
                systems.append((name, current_type))

        if not systems:
            return
        node = self._insert(parent, tk.END,
                             text="System Order (as on radio)",
                             values=(f"{len(systems)} systems",),
                             meta={"type": "system_order"})
        for i, (name, cls) in enumerate(systems, 1):
            abbrev = TYPE_ABBREV.get(cls, cls)
            self._insert(node, tk.END,
                          text=f"{i}. {name}",
                          values=(f"[{abbrev}]",),
                          meta={"type": "system_order_entry",
                                 "name": name, "class_name": cls})

    def _add_systems(self, parent, prs):
        """Add system nodes with names from both header and config data."""
        system_types = [
            ("P25 Trunked Systems", "CP25TrkSystem"),
            ("Conventional Systems", "CConvSystem"),
            ("P25 Conv Systems", "CP25ConvSystem"),
        ]

        config_names = self._collect_system_config_names(prs)

        for label, class_name in system_types:
            sections = prs.get_sections_by_class(class_name)
            if not sections:
                continue

            names = config_names.get(class_name, [])
            count = max(len(sections), len(names))

            node = self._insert(parent, tk.END, text=label,
                                 values=(f"{count} systems",),
                                 meta={"type": "system_category",
                                        "class_name": class_name})

            shown_headers = set()
            for sec in sections:
                short = parse_system_short_name(sec.raw)
                if short:
                    shown_headers.add(short.upper())
                self._insert(node, tk.END,
                              text=short or class_name,
                              values=(f"{len(sec.raw)} bytes",),
                              meta={"type": "system",
                                     "class_name": class_name,
                                     "name": short or ""})

            for short, long_name, size, sec_raw in names:
                display = long_name or short or "(unnamed)"
                if short and short.upper() in shown_headers:
                    continue
                detail_parts = [f"{size} bytes"]
                # Show ECC + IDEN info for P25 trunked configs
                if class_name == "CP25TrkSystem" and sec_raw:
                    ecc_count, _, iden_name = parse_ecc_entries(sec_raw)
                    if ecc_count > 0:
                        ecc_label = f"ECC:{ecc_count}"
                        if ecc_count > 30:
                            ecc_label += " LIMIT!"
                        detail_parts.append(ecc_label)
                    if iden_name:
                        detail_parts.append(f"IDEN:{iden_name}")
                self._insert(node, tk.END,
                              text=display,
                              values=(", ".join(detail_parts),),
                              meta={"type": "system_config",
                                     "class_name": class_name,
                                     "long_name": long_name})

            # Show preferred system table entries under P25 trunked
            if class_name == "CP25TrkSystem":
                self._add_preferred_entries(node, prs)

    def _add_preferred_entries(self, parent, prs):
        """Add preferred system table entry node if present."""
        try:
            from ..injector import get_preferred_entries
            entries, iden, chain = get_preferred_entries(prs)
            if not entries:
                return
            pref_node = self._insert(
                parent, tk.END,
                text="Preferred System Table",
                values=(f"{len(entries)} entries",),
                meta={"type": "preferred_table"})
            for e in entries:
                self._insert(pref_node, tk.END,
                              text=f"SysID {e.system_id}",
                              values=(f"type={e.entry_type} "
                                      f"pri={e.field1} seq={e.field2}",),
                              meta={"type": "preferred_entry",
                                     "system_id": e.system_id})
            if iden:
                self._insert(pref_node, tk.END,
                              text=f"IDEN: {iden}",
                              values=("",),
                              meta={"type": "info"})
            if chain:
                self._insert(pref_node, tk.END,
                              text=f"Chain: {chain}",
                              values=("next system in scan chain",),
                              meta={"type": "info"})
        except Exception as e:
            log_error("tree_preferred", str(e))

    def _add_trunk_sets(self, parent, prs):
        """Add trunk set nodes with channels."""
        ch_sec = prs.get_section_by_class("CTrunkChannel")
        set_sec = prs.get_section_by_class("CTrunkSet")
        if not ch_sec or not set_sec:
            return

        try:
            _, _, _, data_start = parse_class_header(set_sec.raw, 0)
            first_count, _ = read_uint16_le(set_sec.raw, data_start)
            _, _, _, ch_data = parse_class_header(ch_sec.raw, 0)
            sets = parse_trunk_channel_section(
                ch_sec.raw, ch_data, len(ch_sec.raw), first_count)
        except Exception as e:
            log_error("tree_trunk", str(e))
            self._insert(parent, tk.END, text="Trunk Sets",
                          values=("parse error",))
            return

        total = sum(len(s.channels) for s in sets)
        node = self._insert(
            parent, tk.END, text="Trunk Sets",
            values=(f"{len(sets)} sets, {total} channels",),
            meta={"type": "set_category", "set_type": "trunk"})

        for tset in sets:
            set_node = self._insert(
                node, tk.END, text=tset.name,
                values=(f"{len(tset.channels)} ch, "
                        f"{tset.tx_min:.0f}-{tset.tx_max:.0f} MHz",),
                meta={"type": "trunk_set", "name": tset.name,
                       "set_data": tset})

            for ch in tset.channels:
                if ch.tx_freq == ch.rx_freq:
                    self._insert(
                        set_node, tk.END,
                        text=f"{ch.tx_freq:.5f} MHz",
                        values=("simplex",),
                        meta={"type": "trunk_channel",
                               "freq": ch.tx_freq})
                else:
                    self._insert(
                        set_node, tk.END,
                        text=f"TX:{ch.tx_freq:.5f}",
                        values=(f"RX:{ch.rx_freq:.5f} MHz",),
                        meta={"type": "trunk_channel",
                               "tx": ch.tx_freq, "rx": ch.rx_freq})

    def _add_group_sets(self, parent, prs):
        """Add group set nodes with talkgroups."""
        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        try:
            _, _, _, data_start = parse_class_header(set_sec.raw, 0)
            first_count, _ = read_uint16_le(set_sec.raw, data_start)
            _, _, _, g_data = parse_class_header(grp_sec.raw, 0)
            sets = parse_group_section(
                grp_sec.raw, g_data, len(grp_sec.raw), first_count)
        except Exception as e:
            log_error("tree_groups", str(e))
            self._insert(parent, tk.END, text="Group Sets",
                          values=("parse error",))
            return

        total = sum(len(s.groups) for s in sets)
        node = self._insert(
            parent, tk.END, text="Group Sets",
            values=(f"{len(sets)} sets, {total} talkgroups",),
            meta={"type": "set_category", "set_type": "group"})

        for gset in sets:
            n_grps = len(gset.groups)
            n_scan = sum(1 for g in gset.groups if g.scan)
            n_tx = sum(1 for g in gset.groups if g.tx)
            detail_parts = [f"{n_grps} TGs"]
            if n_scan < n_grps:
                detail_parts.append(f"scan:{n_scan}/{n_grps}")
            if n_tx > 0:
                detail_parts.append(f"TX:{n_tx}")
            if n_scan > 127:
                detail_parts.append("SCAN LIMIT EXCEEDED")
            elif n_scan > 120:
                detail_parts.append(f"near scan limit")
            set_node = self._insert(
                node, tk.END, text=gset.name,
                values=(", ".join(detail_parts),),
                meta={"type": "group_set", "name": gset.name,
                       "set_data": gset})

            for grp in gset.groups:
                tx_str = "TX" if grp.tx else "RX"
                scan_str = "Scan" if grp.scan else ""
                enc_str = "ENC" if grp.encrypted else ""
                flags = " ".join(f for f in [tx_str, scan_str, enc_str] if f)
                self._insert(
                    set_node, tk.END,
                    text=f"{grp.group_name} ({grp.group_id})",
                    values=(f"{grp.long_name} [{flags}]",),
                    meta={"type": "talkgroup",
                           "group_id": grp.group_id,
                           "name": grp.group_name,
                           "long_name": grp.long_name})

    def _add_iden_sets(self, parent, prs):
        """Add IDEN set nodes."""
        elem_sec = prs.get_section_by_class("CDefaultIdenElem")
        set_sec = prs.get_section_by_class("CIdenDataSet")
        if not elem_sec or not set_sec:
            return

        try:
            _, _, _, data_start = parse_class_header(set_sec.raw, 0)
            first_count, _ = read_uint16_le(set_sec.raw, data_start)
            _, _, _, e_data = parse_class_header(elem_sec.raw, 0)
            sets = parse_iden_section(
                elem_sec.raw, e_data, len(elem_sec.raw), first_count)
        except Exception as e:
            log_error("tree_iden", str(e))
            self._insert(parent, tk.END, text="IDEN Sets",
                          values=("parse error",))
            return

        node = self._insert(
            parent, tk.END, text="IDEN Sets",
            values=(f"{len(sets)} sets",),
            meta={"type": "set_category", "set_type": "iden"})

        for iset in sets:
            active_elems = [e for e in iset.elements if not e.is_empty()]
            active = len(active_elems)
            fdma = sum(1 for e in active_elems if not e.iden_type)
            tdma = sum(1 for e in active_elems if e.iden_type)
            if fdma and tdma:
                mode = "mixed FDMA+TDMA"
            elif tdma:
                mode = "TDMA"
            else:
                mode = "FDMA"
            set_node = self._insert(
                node, tk.END, text=iset.name,
                values=(f"{active}/16 active ({mode})",),
                meta={"type": "iden_set", "name": iset.name,
                       "set_data": iset})

            for i, elem in enumerate(iset.elements):
                if elem.is_empty():
                    continue
                mode = "TDMA" if elem.iden_type else "FDMA"
                base_mhz = elem.base_freq_hz / 1_000_000
                spacing_khz = elem.chan_spacing_hz / 1000
                offset = elem.tx_offset_mhz
                self._insert(
                    set_node, tk.END,
                    text=f"IDEN {i}",
                    values=(f"{base_mhz:.5f} MHz {mode} "
                            f"sp:{spacing_khz:.2f}kHz "
                            f"off:{offset:+.1f}MHz",),
                    meta={"type": "iden_element"})

    def _add_conv_sets(self, parent, prs):
        """Add conventional channel sets with channels."""
        conv_sec = prs.get_section_by_class("CConvChannel")
        conv_set_sec = prs.get_section_by_class("CConvSet")
        if not conv_sec or not conv_set_sec:
            return

        try:
            _, _, _, data_start = parse_class_header(conv_set_sec.raw, 0)
            first_count, _ = read_uint16_le(conv_set_sec.raw, data_start)
            _, _, _, ch_data = parse_class_header(conv_sec.raw, 0)
            sets = parse_conv_channel_section(
                conv_sec.raw, ch_data, len(conv_sec.raw), first_count)
        except Exception as e:
            log_error("tree_conv", str(e))
            self._insert(parent, tk.END, text="Conv Sets",
                          values=("parse error",))
            return

        total = sum(len(s.channels) for s in sets)
        node = self._insert(
            parent, tk.END, text="Conv Sets",
            values=(f"{len(sets)} sets, {total} channels",),
            meta={"type": "set_category", "set_type": "conv"})

        for cset in sets:
            set_node = self._insert(
                node, tk.END, text=cset.name,
                values=(f"{len(cset.channels)} channels",),
                meta={"type": "conv_set", "name": cset.name,
                       "set_data": cset})

            for ch_idx, ch in enumerate(cset.channels):
                if ch.tx_freq == ch.rx_freq:
                    parts = [f"{ch.tx_freq:.5f} MHz"]
                else:
                    parts = [f"TX:{ch.tx_freq:.5f} RX:{ch.rx_freq:.5f}"]
                if ch.tx_tone or ch.rx_tone:
                    if ch.tx_tone and ch.rx_tone and ch.tx_tone == ch.rx_tone:
                        parts.append(f"TxCG/RxCG:{ch.tx_tone}")
                    else:
                        tones = []
                        if ch.tx_tone:
                            tones.append(f"TxCG:{ch.tx_tone}")
                        if ch.rx_tone:
                            tones.append(f"RxCG:{ch.rx_tone}")
                        parts.append(" ".join(tones))
                self._insert(
                    set_node, tk.END,
                    text=ch.short_name,
                    values=(f"{' | '.join(parts)}",),
                    meta={"type": "conv_channel",
                           "name": ch.short_name,
                           "freq": ch.tx_freq,
                           "ch_idx": ch_idx})

    def _add_p25_conv_sets(self, parent, prs):
        """Add P25 conventional channel sets with channels and NAC info."""
        from ..record_types import (
            parse_p25_conv_channel_section, parse_class_header as _pch,
        )
        ch_sec = prs.get_section_by_class("CP25ConvChannel")
        set_sec = prs.get_section_by_class("CP25ConvSet")
        if not ch_sec or not set_sec:
            return

        try:
            _, _, _, data_start = _pch(set_sec.raw, 0)
            first_count, _ = read_uint16_le(set_sec.raw, data_start)
            _, _, _, ch_data = _pch(ch_sec.raw, 0)
            sets = parse_p25_conv_channel_section(
                ch_sec.raw, ch_data, len(ch_sec.raw), first_count)
        except Exception as e:
            log_error("tree_p25_conv", str(e))
            self._insert(parent, tk.END, text="P25 Conv Sets",
                          values=("parse error",))
            return

        total = sum(len(s.channels) for s in sets)
        node = self._insert(
            parent, tk.END, text="P25 Conv Sets",
            values=(f"{len(sets)} sets, {total} channels",),
            meta={"type": "set_category", "set_type": "p25_conv"})

        for cset in sets:
            set_node = self._insert(
                node, tk.END, text=cset.name,
                values=(f"{len(cset.channels)} channels",),
                meta={"type": "p25_conv_set", "name": cset.name,
                       "set_data": cset})

            for ch_idx, ch in enumerate(cset.channels):
                if ch.tx_freq == ch.rx_freq:
                    parts = [f"{ch.tx_freq:.5f} MHz"]
                else:
                    parts = [f"TX:{ch.tx_freq:.5f} RX:{ch.rx_freq:.5f}"]
                nac_str = f"NAC:{ch.nac_tx:03X}/{ch.nac_rx:03X}"
                parts.append(nac_str)
                self._insert(
                    set_node, tk.END,
                    text=ch.short_name,
                    values=(f"{' | '.join(parts)}",),
                    meta={"type": "p25_conv_channel",
                           "name": ch.short_name,
                           "freq": ch.tx_freq,
                           "ch_idx": ch_idx})

    def _add_options(self, parent, prs):
        """Add options records node."""
        opts_classes = [
            s.class_name for s in prs.sections
            if s.class_name and (
                'Opts' in s.class_name or
                s.class_name.startswith('CT99') or
                s.class_name in ('CProgButtons', 'CStatus',
                                  'CVoiceAnnunciation', 'CAccessoryDevice',
                                  'CSecurityPolicy'))
        ]

        if not opts_classes:
            return

        node = self._insert(
            parent, tk.END, text="Options/Config",
            values=(f"{len(opts_classes)} records",),
            meta={"type": "options_category"})

        for cls in opts_classes:
            sec = prs.get_section_by_class(cls)
            display = CLASS_DISPLAY_NAMES.get(cls, cls)
            opt_node = self._insert(
                node, tk.END, text=display,
                values=(f"{cls} — {len(sec.raw)} bytes",),
                meta={"type": "option", "class_name": cls})
            self._add_option_details(opt_node, sec.raw, cls)

    def _add_option_details(self, parent_node, raw, class_name=""):
        """Add child nodes showing parsed fields or hex preview."""
        try:
            _, _, _, data_start = parse_class_header(raw, 0)
        except (IndexError, ValueError):
            data_start = 0
        data = raw[data_start:]

        # If we have a field map with fields, show parsed values
        opt_map = OPTION_MAPS.get(class_name) if class_name else None
        if opt_map and opt_map.fields:
            for field_def in opt_map.fields:
                val = read_field(data, field_def)
                if val is not None:
                    display_val = _format_field_value(val, field_def)
                    self._insert(parent_node, tk.END,
                                  text=field_def.display_name,
                                  values=(display_val,),
                                  meta={"type": "option_field",
                                        "field_name": field_def.name})
            return

        # No field map — show hex preview
        preview = " ".join(f"{b:02X}" for b in data[:32])
        suffix = "..." if len(data) > 32 else ""
        self._insert(parent_node, tk.END,
                      text=f"Hex: {preview}{suffix}",
                      values=(f"{len(data)} data bytes",),
                      meta={"type": "option_detail"})

    def _add_platform_config(self, parent, prs):
        """Add platformConfig XML settings to the tree."""
        config = extract_platform_config(prs)
        if not config:
            return

        node = self._insert(
            parent, tk.END, text="Radio Settings",
            values=("double-click to edit",),
            meta={"type": "platform_config_root"})

        # Show fields grouped by category
        for category, fields in sorted(XML_FIELDS_BY_CATEGORY.items()):
            # Count fields with values
            field_count = sum(
                1 for f in fields
                if self._get_xml_field_value(config, f) is not None)
            n = "field" if field_count == 1 else "fields"

            cat_node = self._insert(
                node, tk.END, text=category,
                values=(f"{field_count} {n}",),
                meta={"type": "platform_config_category",
                      "category": category})

            for field_def in fields:
                val = self._get_xml_field_value(config, field_def)
                if val is not None:
                    display_val = _format_xml_value(val, field_def)
                    self._insert(
                        cat_node, tk.END,
                        text=field_def.display_name,
                        values=(display_val,),
                        meta={"type": "platform_config_field",
                              "element": field_def.element,
                              "attribute": field_def.attribute})

        # Programmable Buttons
        self._add_prog_buttons(node, config)

        # Short Menu
        self._add_short_menu(node, config)

    def _add_prog_buttons(self, parent, config):
        """Add programmable buttons section to the tree."""
        prog = config.get("progButtons")
        if not prog:
            return

        buttons = prog.get("progButton", [])
        if not isinstance(buttons, list):
            buttons = [buttons]

        # Count assigned buttons
        assigned = sum(
            1 for b in buttons if b.get("function", "UNASSIGNED") != "UNASSIGNED")

        # Also count accessory buttons
        acc_config = config.get("accessoryConfig", {})
        acc_btns_wrap = acc_config.get("accessoryButtons", {})
        acc_btns = acc_btns_wrap.get("accessoryButton", [])
        if not isinstance(acc_btns, list):
            acc_btns = [acc_btns]
        acc_assigned = sum(
            1 for b in acc_btns
            if b.get("function", "UNASSIGNED") != "UNASSIGNED")

        total = assigned + acc_assigned
        btn_node = self._insert(
            parent, tk.END, text="Programmable Buttons",
            values=(f"{total} assigned",),
            meta={"type": "platform_config_category",
                  "category": "Programmable Buttons"})

        # 2-position switch
        func_2p = prog.get("_2PosFunction", "")
        if func_2p:
            self._insert(
                btn_node, tk.END, text="2-Position Switch",
                values=(format_switch_function(func_2p),),
                meta={"type": "platform_config_field"})

        # 3-position switch
        func_3p = prog.get("_3PosFunction", "")
        if func_3p:
            labels = []
            for pos in ("A", "B", "C"):
                val = prog.get(f"_3Pos{pos}Value", "")
                if val:
                    labels.append(val)
            detail = format_switch_function(func_3p)
            if labels:
                detail += f" ({'/'.join(labels)})"
            self._insert(
                btn_node, tk.END, text="3-Position Switch",
                values=(detail,),
                meta={"type": "platform_config_field"})

        # Side buttons
        for btn in buttons:
            name = format_button_name(btn.get("buttonName", ""))
            func = format_button_function(btn.get("function", ""))
            self._insert(
                btn_node, tk.END, text=name,
                values=(func,),
                meta={"type": "platform_config_field"})

        # Accessory buttons
        for btn in acc_btns:
            name = format_button_name(btn.get("buttonName", ""))
            func = format_button_function(btn.get("function", ""))
            self._insert(
                btn_node, tk.END, text=name,
                values=(func,),
                meta={"type": "platform_config_field"})

    def _add_short_menu(self, parent, config):
        """Add short menu configuration to the tree."""
        menu = config.get("shortMenu")
        if not menu:
            return

        items = menu.get("shortMenuItem", [])
        if not isinstance(items, list):
            items = [items]

        # Count non-empty slots
        filled = sum(
            1 for item in items if item.get("name", "empty") != "empty")

        menu_node = self._insert(
            parent, tk.END, text="Short Menu",
            values=(f"{filled} of {len(items)} slots",),
            meta={"type": "platform_config_category",
                  "category": "Short Menu"})

        for item in items:
            pos = item.get("position", "?")
            name = item.get("name", "empty")
            display = format_short_menu_name(name)
            self._insert(
                menu_node, tk.END, text=f"Slot {pos}",
                values=(display,),
                meta={"type": "platform_config_field"})

    def _get_xml_field_value(self, config, field_def):
        """Get a value from parsed platformConfig for a given XmlFieldDef."""
        elem_path = field_def.element

        # Handle microphone sub-elements
        if "microphone[@micType=" in elem_path:
            mic_type = "INTERNAL" if "INTERNAL" in elem_path else "EXTERNAL"
            audio = config.get("audioConfig", {})
            mics = audio.get("microphone", [])
            if not isinstance(mics, list):
                mics = [mics]
            for mic in mics:
                if mic.get("micType") == mic_type:
                    return mic.get(field_def.attribute)
            return None

        # Direct element lookup
        elem_data = config.get(elem_path, {})
        if isinstance(elem_data, dict):
            return elem_data.get(field_def.attribute)
        return None

    def _collect_system_config_names(self, prs):
        """Collect system config long names from data sections."""
        result = {}
        current_type = None

        for sec in prs.sections:
            if sec.class_name in ('CP25TrkSystem', 'CConvSystem',
                                   'CP25ConvSystem'):
                current_type = sec.class_name
                if current_type not in result:
                    result[current_type] = []
                continue

            if not sec.class_name and is_system_config_data(sec.raw):
                long_name = parse_system_long_name(sec.raw) or ""
                if current_type and current_type not in result:
                    result[current_type] = []
                target = current_type or 'CP25TrkSystem'
                if target not in result:
                    result[target] = []
                result[target].append(
                    ("", long_name, len(sec.raw), sec.raw))

        return result

    # ─── Search ──────────────────────────────────────────────────────

    def _focus_search(self):
        """Focus the search entry."""
        self.search_entry.focus_set()
        self.search_entry.select_range(0, tk.END)

    def _clear_search(self):
        """Clear the search filter and restore all items."""
        self.search_var.set("")
        self.search_count.config(text="")
        self._restore_detached_items()
        self._clear_tags()

    def _on_search_changed(self, *args):
        """Filter tree when search text changes."""
        # Restore any previously detached items first
        self._restore_detached_items()
        self._clear_tags()

        query = self.search_var.get().strip().lower()
        if not query:
            self.search_count.config(text="")
            return

        # Find matching leaf items and their ancestors
        matches = self._find_matching_items(query)

        if self._filter_mode.get():
            # Filter mode: detach non-matching leaf items
            self._detach_non_matching(matches)
        else:
            # Search mode: highlight matching, dim non-matching
            self._highlight_matches(matches)

        # Count only actual leaf matches (not ancestors)
        leaf_count = self._count_leaf_matches(query)
        self.search_count.config(text=f"{leaf_count} matches")

    def _count_leaf_matches(self, query):
        """Count items that directly match (not ancestors)."""
        count = 0
        for iid in self._get_all_items():
            text = self.tree.item(iid, "text").lower()
            detail = str(self.tree.item(iid, "values")).lower()
            if query in text or query in detail:
                count += 1
        return count

    def _clear_tags(self):
        """Remove all search-related tags from tree items."""
        for tag in ("match", "nomatch"):
            self.tree.tag_configure(tag, foreground="")
        for iid in self._get_all_items():
            self.tree.item(iid, tags=())

    def _find_matching_items(self, query):
        """Find all tree items whose text or detail matches the query.

        Returns a set of iids including both direct matches and all
        their ancestor nodes (so branches stay visible).
        """
        matches = set()
        for iid in self._get_all_items():
            text = self.tree.item(iid, "text").lower()
            detail = str(self.tree.item(iid, "values")).lower()
            if query in text or query in detail:
                matches.add(iid)
                # Also add all ancestors
                parent = self.tree.parent(iid)
                while parent:
                    matches.add(parent)
                    parent = self.tree.parent(parent)
        return matches

    def _highlight_matches(self, matches):
        """Search mode: highlight matching items and dim non-matching."""
        self.tree.tag_configure("match", foreground="")
        self.tree.tag_configure("nomatch", foreground="gray")

        for iid in self._get_all_items():
            if iid in matches:
                self.tree.item(iid, tags=("match",))
                # Open parent so match is visible
                parent = self.tree.parent(iid)
                while parent:
                    self.tree.item(parent, open=True)
                    parent = self.tree.parent(parent)
            else:
                self.tree.item(iid, tags=("nomatch",))

    def _detach_non_matching(self, matches):
        """Filter mode: detach items that don't match."""
        for iid in self._get_all_items():
            if iid not in matches:
                parent = self.tree.parent(iid)
                idx = self.tree.index(iid)
                self._detached_items.append((iid, parent, idx))
                self.tree.detach(iid)

        # Open ancestors of remaining matches
        for iid in self._get_all_items():
            if iid in matches:
                parent = self.tree.parent(iid)
                while parent:
                    self.tree.item(parent, open=True)
                    parent = self.tree.parent(parent)

    def _restore_detached_items(self):
        """Reattach all previously detached items."""
        if not self._detached_items:
            return
        # Restore in reverse order to maintain indices
        for iid, parent, idx in reversed(self._detached_items):
            try:
                self.tree.reattach(iid, parent, idx)
            except tk.TclError:
                pass  # item or parent may no longer exist after refresh
        self._detached_items.clear()

    def _get_all_items(self):
        """Recursively get all tree item IDs (visible items only)."""
        items = []
        stack = list(self.tree.get_children())
        while stack:
            iid = stack.pop()
            items.append(iid)
            stack.extend(self.tree.get_children(iid))
        return items

    # ─── Advanced Filters ────────────────────────────────────────────

    def _toggle_filter_panel(self):
        """Show or hide the advanced filter panel."""
        if self._filter_visible:
            self._filter_frame.grid_forget()
            self._filter_visible = False
        else:
            # Insert filter frame between search bar (row 0) and tree (row 1)
            # Shift tree and scrollbars down
            self._filter_frame.grid(row=1, column=0, columnspan=2,
                                    sticky="ew", pady=(0, 2))
            self.tree.grid(row=2, column=0, sticky="nsew")
            # Update scrollbar positions
            for child in self.winfo_children():
                info = child.grid_info()
                if not info:
                    continue
                if isinstance(child, ttk.Scrollbar):
                    orient = str(child.cget("orient"))
                    if orient == "vertical":
                        child.grid(row=2, column=1, sticky="ns")
                    elif orient == "horizontal":
                        child.grid(row=3, column=0, sticky="ew")
            self.grid_rowconfigure(2, weight=1)
            self._filter_visible = True

    def _apply_advanced_filters(self):
        """Apply frequency/TG/TX/scan filters to the tree."""
        # First restore everything
        self._restore_detached_items()
        self._clear_tags()

        freq_min = self._safe_float(self._freq_min_var.get())
        freq_max = self._safe_float(self._freq_max_var.get())
        tg_min = self._safe_int(self._tg_min_var.get())
        tg_max = self._safe_int(self._tg_max_var.get())
        tx_only = self._filter_tx_var.get()
        scan_only = self._filter_scan_var.get()

        has_filter = any([freq_min is not None, freq_max is not None,
                          tg_min is not None, tg_max is not None,
                          tx_only, scan_only])

        if not has_filter:
            self._filter_indicator.config(text="")
            return

        # Collect items to detach
        to_detach = []
        for iid in self._get_all_items():
            meta = self._item_meta.get(iid, {})
            item_type = meta.get("type", "")

            # Only filter leaf items that have filterable properties
            if item_type == "talkgroup":
                gid = meta.get("group_id", 0)
                # TG ID range filter
                if tg_min is not None and gid < tg_min:
                    to_detach.append(iid)
                    continue
                if tg_max is not None and gid > tg_max:
                    to_detach.append(iid)
                    continue
                # TX/Scan filters require checking the tree detail text
                detail_text = str(self.tree.item(iid, "values"))
                if tx_only and "TX" not in detail_text:
                    to_detach.append(iid)
                    continue
                if scan_only and "Scan" not in detail_text:
                    to_detach.append(iid)
                    continue

            elif item_type in ("trunk_channel", "conv_channel"):
                freq = meta.get("freq") or meta.get("tx") or 0
                if freq_min is not None and freq < freq_min:
                    to_detach.append(iid)
                    continue
                if freq_max is not None and freq > freq_max:
                    to_detach.append(iid)
                    continue

        for iid in to_detach:
            parent = self.tree.parent(iid)
            idx = self.tree.index(iid)
            self._detached_items.append((iid, parent, idx))
            self.tree.detach(iid)

        active_filters = []
        if freq_min is not None or freq_max is not None:
            active_filters.append("freq")
        if tg_min is not None or tg_max is not None:
            active_filters.append("TG")
        if tx_only:
            active_filters.append("TX")
        if scan_only:
            active_filters.append("scan")

        self._filter_indicator.config(
            text=f"(filtered: {', '.join(active_filters)}, "
                 f"{len(to_detach)} hidden)")

    def _clear_advanced_filters(self):
        """Reset all advanced filter controls and restore tree."""
        self._freq_min_var.set("")
        self._freq_max_var.set("")
        self._tg_min_var.set("")
        self._tg_max_var.set("")
        self._filter_tx_var.set(False)
        self._filter_scan_var.set(False)
        self._filter_indicator.config(text="")
        self._restore_detached_items()
        self._clear_tags()

    @staticmethod
    def _safe_float(s):
        """Parse a string to float, returning None on failure."""
        try:
            return float(s) if s.strip() else None
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _safe_int(s):
        """Parse a string to int, returning None on failure."""
        try:
            return int(s) if s.strip() else None
        except (ValueError, AttributeError):
            return None

    # ─── Copy/Paste ──────────────────────────────────────────────────

    def _on_copy(self, event):
        """Ctrl+C: copy selected talkgroups or channels to clipboard."""
        selection = self.tree.selection()
        if not selection:
            return "break"

        items = []
        item_type = None
        for iid in selection:
            meta = self._item_meta.get(iid, {})
            t = meta.get("type", "")
            if t == "talkgroup":
                if item_type and item_type != "talkgroup":
                    continue  # mixed types, skip
                item_type = "talkgroup"
                items.append({
                    "group_id": meta.get("group_id"),
                    "name": meta.get("name", ""),
                    "long_name": meta.get("long_name", ""),
                })
            elif t == "conv_channel":
                if item_type and item_type != "conv_channel":
                    continue
                item_type = "conv_channel"
                items.append({
                    "name": meta.get("name", ""),
                    "freq": meta.get("freq"),
                    "ch_idx": meta.get("ch_idx"),
                    # Get parent set name for lookup
                    "set_name": self._item_meta.get(
                        self.tree.parent(iid), {}).get("name", ""),
                })

        if items:
            self._clipboard = items
            self._clipboard_type = item_type
            self.app.status_set(
                f"Copied {len(items)} {item_type.replace('_', ' ')}(s)")
        return "break"

    def _on_paste(self, event):
        """Ctrl+V: paste copied items into the selected set."""
        if not self._clipboard or not self._clipboard_type:
            self.app.status_set("Nothing to paste")
            return "break"

        iid = self.tree.focus()
        if not iid:
            return "break"

        meta = self._item_meta.get(iid, {})
        target_type = meta.get("type", "")

        # Determine the target set — either a set node or a child item
        if target_type in ("group_set", "conv_set"):
            set_name = meta.get("name", "")
            set_type = target_type
        elif target_type == "talkgroup":
            parent_iid = self.tree.parent(iid)
            parent_meta = self._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            set_type = "group_set"
        elif target_type == "conv_channel":
            parent_iid = self.tree.parent(iid)
            parent_meta = self._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            set_type = "conv_set"
        else:
            self.app.status_set("Select a set or item to paste into")
            return "break"

        if not set_name:
            return "break"

        prs = self.app.prs
        if not prs:
            return "break"

        # Paste talkgroups into a group set
        if self._clipboard_type == "talkgroup" and set_type == "group_set":
            self._paste_talkgroups(prs, set_name)
        elif self._clipboard_type == "conv_channel" and set_type == "conv_set":
            self._paste_conv_channels(prs, set_name)
        else:
            self.app.status_set(
                f"Cannot paste {self._clipboard_type} into {set_type}")
        return "break"

    def _paste_talkgroups(self, prs, set_name):
        """Paste copied talkgroups into a group set."""
        from ..injector import (
            _parse_section_data, _replace_group_sections,
            _get_header_bytes, _get_first_count, make_p25_group,
        )

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")
            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)

            target = None
            for gs in existing_sets:
                if gs.name == set_name:
                    target = gs
                    break
            if not target:
                self.app.status_set(f"Set '{set_name}' not found")
                return

            # Check for duplicate group IDs
            existing_ids = {g.group_id for g in target.groups}
            added = 0
            for item in self._clipboard:
                gid = item.get("group_id")
                if gid is not None and gid not in existing_ids:
                    new_grp = make_p25_group(
                        gid,
                        item.get("name", ""),
                        item.get("long_name", ""),
                    )
                    target.groups.append(new_grp)
                    existing_ids.add(gid)
                    added += 1

            if added == 0:
                self.app.status_set("No new TGs to paste (duplicates)")
                return

            self.app.save_undo_snapshot("Paste talkgroups")
            _replace_group_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Pasted {added} TG(s) into '{set_name}'")

        except Exception as e:
            messagebox.showerror("Error", f"Paste failed:\n{e}")

    def _paste_conv_channels(self, prs, set_name):
        """Paste copied conv channels into a conv set."""
        from ..injector import (
            _parse_section_data, _replace_conv_sections,
            _get_header_bytes, _get_first_count, make_conv_channel,
        )

        ch_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        if not ch_sec or not set_sec:
            return

        try:
            byte1, byte2 = _get_header_bytes(ch_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CConvSet")
            existing_sets = _parse_section_data(
                ch_sec, parse_conv_channel_section, first_count)

            target = None
            for cs in existing_sets:
                if cs.name == set_name:
                    target = cs
                    break
            if not target:
                self.app.status_set(f"Set '{set_name}' not found")
                return

            # To copy channels, we need the full channel data from source
            # Re-parse to get the actual channel objects
            source_channels = []
            for item in self._clipboard:
                src_set_name = item.get("set_name", "")
                src_idx = item.get("ch_idx")
                for cs in existing_sets:
                    if cs.name == src_set_name and src_idx is not None:
                        if src_idx < len(cs.channels):
                            source_channels.append(cs.channels[src_idx])
                        break

            if not source_channels:
                # Fallback: create new channels from clipboard metadata
                for item in self._clipboard:
                    freq = item.get("freq", 0.0)
                    if freq:
                        ch = make_conv_channel(
                            item.get("name", "CH"),
                            freq, freq)
                        source_channels.append(ch)

            if not source_channels:
                self.app.status_set("No channels to paste")
                return

            # Deep copy to avoid sharing references
            from copy import deepcopy
            for ch in source_channels:
                target.channels.append(deepcopy(ch))

            self.app.save_undo_snapshot("Paste channels")
            _replace_conv_sections(prs, existing_sets, byte1, byte2,
                                    set_byte1, set_byte2)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Pasted {len(source_channels)} channel(s) "
                f"into '{set_name}'")

        except Exception as e:
            messagebox.showerror("Error", f"Paste failed:\n{e}")

    # ─── Drag-and-drop reordering ─────────────────────────────────────

    _DRAGGABLE_TYPES = {"talkgroup", "group_set", "trunk_set",
                        "conv_set", "iden_set",
                        "trunk_channel", "conv_channel"}

    def _on_drag_start(self, event):
        """Begin drag if clicking on a draggable item."""
        iid = self.tree.identify_row(event.y)
        if not iid:
            self._drag_data = None
            return

        meta = self._item_meta.get(iid, {})
        item_type = meta.get("type", "")
        if item_type not in self._DRAGGABLE_TYPES:
            self._drag_data = None
            return

        parent_iid = self.tree.parent(iid)
        self._drag_data = {
            "iid": iid,
            "type": item_type,
            "parent_iid": parent_iid,
            "start_y": event.y,
            "dragging": False,
        }

    def _on_drag_motion(self, event):
        """Show visual drag feedback."""
        if not self._drag_data:
            return

        # Don't start drag until mouse moves 4+ pixels
        if not self._drag_data.get("dragging"):
            if abs(event.y - self._drag_data["start_y"]) < 4:
                return
            self._drag_data["dragging"] = True
            self.tree.configure(cursor="hand2")

        # Highlight the target row
        target_iid = self.tree.identify_row(event.y)
        # Auto-scroll near edges
        if event.y < 20:
            self.tree.yview_scroll(-1, "units")
        elif event.y > self.tree.winfo_height() - 20:
            self.tree.yview_scroll(1, "units")

    def _on_drag_end(self, event):
        """Complete the drag by reordering items."""
        if not self._drag_data or not self._drag_data.get("dragging"):
            self._drag_data = None
            return

        self.tree.configure(cursor="")
        drag = self._drag_data
        self._drag_data = None

        target_iid = self.tree.identify_row(event.y)
        if not target_iid or target_iid == drag["iid"]:
            return

        target_meta = self._item_meta.get(target_iid, {})
        target_type = target_meta.get("type", "")

        # Can only drop onto items of the same type under the same parent
        target_parent = self.tree.parent(target_iid)

        # Allow dropping TG onto same group set
        if drag["type"] == "talkgroup" and target_type == "talkgroup":
            if target_parent == drag["parent_iid"]:
                self._reorder_talkgroups(drag["parent_iid"],
                                          drag["iid"], target_iid)
                return

        # Allow dropping conv channel onto same conv set
        if drag["type"] == "conv_channel" and target_type == "conv_channel":
            if target_parent == drag["parent_iid"]:
                self._reorder_conv_channels(drag["parent_iid"],
                                             drag["iid"], target_iid)
                return

        # Allow dropping trunk channel onto same trunk set
        if drag["type"] == "trunk_channel" and target_type == "trunk_channel":
            if target_parent == drag["parent_iid"]:
                self._reorder_trunk_channels(drag["parent_iid"],
                                              drag["iid"], target_iid)
                return

        # Allow dropping set onto same set category
        if drag["type"] == target_type and target_parent == drag["parent_iid"]:
            set_type = drag["type"]
            if set_type in ("group_set", "trunk_set", "conv_set", "iden_set"):
                self._reorder_sets(drag["parent_iid"],
                                    drag["iid"], target_iid, set_type)
                return

    def _reorder_talkgroups(self, set_parent_iid, drag_iid, target_iid):
        """Reorder talkgroups within a group set in binary data."""
        prs = self.app.prs
        if not prs:
            return

        parent_meta = self._item_meta.get(set_parent_iid, {})
        set_name = parent_meta.get("name", "")
        if not set_name:
            return

        drag_meta = self._item_meta.get(drag_iid, {})
        target_meta = self._item_meta.get(target_iid, {})
        drag_gid = drag_meta.get("group_id")
        target_gid = target_meta.get("group_id")
        if drag_gid is None or target_gid is None:
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")

            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)

            target_set = None
            for gs in existing_sets:
                if gs.name == set_name:
                    target_set = gs
                    break

            if not target_set:
                return

            # Find indices
            drag_idx = None
            target_idx = None
            for i, g in enumerate(target_set.groups):
                if g.group_id == drag_gid:
                    drag_idx = i
                if g.group_id == target_gid:
                    target_idx = i
            if drag_idx is None or target_idx is None:
                return

            # Reorder: remove dragged, insert at target position
            self.app.save_undo_snapshot("Reorder talkgroup")
            grp = target_set.groups.pop(drag_idx)
            # Adjust target_idx if drag was before target
            if drag_idx < target_idx:
                target_idx -= 1
            target_set.groups.insert(target_idx, grp)

            _replace_group_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)

            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved TG {drag_gid} in '{set_name}'")

        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to reorder talkgroups:\n{e}")

    def _reorder_sets(self, category_iid, drag_iid, target_iid, set_type):
        """Reorder sets within a category in binary data."""
        prs = self.app.prs
        if not prs:
            return

        drag_meta = self._item_meta.get(drag_iid, {})
        target_meta = self._item_meta.get(target_iid, {})
        drag_name = drag_meta.get("name", "")
        target_name = target_meta.get("name", "")
        if not drag_name or not target_name:
            return

        if set_type == "group_set":
            self._reorder_group_sets(drag_name, target_name)
        elif set_type == "trunk_set":
            self._reorder_trunk_sets(drag_name, target_name)
        elif set_type == "conv_set":
            self._reorder_conv_sets(drag_name, target_name)

    def _reorder_group_sets(self, drag_name, target_name):
        """Reorder group sets in binary data."""
        prs = self.app.prs
        if not prs:
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")

            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)

            drag_idx = None
            target_idx = None
            for i, gs in enumerate(existing_sets):
                if gs.name == drag_name:
                    drag_idx = i
                if gs.name == target_name:
                    target_idx = i

            if drag_idx is None or target_idx is None:
                return

            self.app.save_undo_snapshot("Reorder group set")
            gs = existing_sets.pop(drag_idx)
            if drag_idx < target_idx:
                target_idx -= 1
            existing_sets.insert(target_idx, gs)

            _replace_group_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)

            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved group set '{drag_name}'")

        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to reorder group sets:\n{e}")

    def _reorder_trunk_sets(self, drag_name, target_name):
        """Reorder trunk sets in binary data."""
        prs = self.app.prs
        if not prs:
            return

        ch_sec = prs.get_section_by_class("CTrunkChannel")
        set_sec = prs.get_section_by_class("CTrunkSet")
        if not ch_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_trunk_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(ch_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CTrunkSet")

            existing_sets = _parse_section_data(
                ch_sec, parse_trunk_channel_section, first_count)

            drag_idx = None
            target_idx = None
            for i, ts in enumerate(existing_sets):
                if ts.name == drag_name:
                    drag_idx = i
                if ts.name == target_name:
                    target_idx = i

            if drag_idx is None or target_idx is None:
                return

            self.app.save_undo_snapshot("Reorder trunk set")
            ts = existing_sets.pop(drag_idx)
            if drag_idx < target_idx:
                target_idx -= 1
            existing_sets.insert(target_idx, ts)

            _replace_trunk_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)

            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved trunk set '{drag_name}'")

        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to reorder trunk sets:\n{e}")

    def _reorder_conv_sets(self, drag_name, target_name):
        """Reorder conv sets in binary data."""
        prs = self.app.prs
        if not prs:
            return

        conv_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        if not conv_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_conv_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(conv_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CConvSet")

            existing_sets = _parse_section_data(
                conv_sec, parse_conv_channel_section, first_count)

            drag_idx = None
            target_idx = None
            for i, cs in enumerate(existing_sets):
                if cs.name == drag_name:
                    drag_idx = i
                if cs.name == target_name:
                    target_idx = i

            if drag_idx is None or target_idx is None:
                return

            self.app.save_undo_snapshot("Reorder conv set")
            cs = existing_sets.pop(drag_idx)
            if drag_idx < target_idx:
                target_idx -= 1
            existing_sets.insert(target_idx, cs)

            _replace_conv_sections(prs, existing_sets, byte1, byte2,
                                    set_byte1, set_byte2)

            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved conv set '{drag_name}'")

        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to reorder conv sets:\n{e}")

    def _reorder_conv_channels(self, set_parent_iid, drag_iid, target_iid):
        """Reorder conv channels within a conv set via drag-and-drop."""
        prs = self.app.prs
        if not prs:
            return

        parent_meta = self._item_meta.get(set_parent_iid, {})
        set_name = parent_meta.get("name", "")
        if not set_name:
            return

        drag_meta = self._item_meta.get(drag_iid, {})
        target_meta = self._item_meta.get(target_iid, {})
        drag_idx = drag_meta.get("ch_idx")
        target_idx = target_meta.get("ch_idx")
        if drag_idx is None or target_idx is None:
            return

        try:
            from ..injector import reorder_conv_channel
            self.app.save_undo_snapshot("Reorder channel")
            reorder_conv_channel(prs, set_name, drag_idx, target_idx)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved channel in '{set_name}'")
        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to reorder channels:\n{e}")

    def _reorder_trunk_channels(self, set_parent_iid, drag_iid, target_iid):
        """Reorder trunk channels within a trunk set via drag-and-drop."""
        prs = self.app.prs
        if not prs:
            return

        parent_meta = self._item_meta.get(set_parent_iid, {})
        set_name = parent_meta.get("name", "")
        if not set_name:
            return

        # Get indices from tree position (trunk channels don't have ch_idx)
        parent_children = list(self.tree.get_children(set_parent_iid))
        drag_idx = None
        target_idx = None
        for i, child_iid in enumerate(parent_children):
            if child_iid == drag_iid:
                drag_idx = i
            if child_iid == target_iid:
                target_idx = i
        if drag_idx is None or target_idx is None:
            return

        try:
            from ..injector import reorder_trunk_channel
            self.app.save_undo_snapshot("Reorder trunk channel")
            reorder_trunk_channel(prs, set_name, drag_idx, target_idx)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved trunk channel in '{set_name}'")
        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to reorder trunk channels:\n{e}")

    # ─── Context Menu ────────────────────────────────────────────────

    def _on_right_click(self, event):
        """Show context menu for the clicked item(s)."""
        iid = self.tree.identify_row(event.y)
        if not iid:
            return

        # If right-clicked item is already in selection, keep selection
        # Otherwise, set selection to just this item
        selection = self.tree.selection()
        if iid not in selection:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            selection = (iid,)

        # Check if we have a multi-selection of talkgroups
        if len(selection) > 1:
            self._show_multi_select_menu(event, selection)
            return

        meta = self._item_meta.get(iid, {})
        item_type = meta.get("type", "")

        # Build context menu based on item type
        self.ctx_menu.delete(0, tk.END)

        if item_type == "system":
            name = meta.get("name", "")
            cls = meta.get("class_name", "")
            self.ctx_menu.add_command(
                label=f"Rename '{name}'...",
                command=lambda: self._rename_system(cls, name))
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label=f"Delete System '{name}'",
                command=lambda: self._delete_system(cls, name))

        elif item_type == "system_config":
            long_name = meta.get("long_name", "")
            self.ctx_menu.add_command(
                label=f"Delete System Config '{long_name}'",
                command=lambda: self._delete_system_config(long_name))

        elif item_type == "system_category":
            cls = meta.get("class_name", "")
            if cls == "CP25TrkSystem":
                self.ctx_menu.add_command(
                    label="Add P25 Trunked System...",
                    command=self._add_p25_system_dialog)
            elif cls == "CConvSystem":
                self.ctx_menu.add_command(
                    label="Add Conventional System...",
                    command=self._add_conv_system_dialog)
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label="Delete ALL systems of this type",
                command=lambda: self._delete_all_systems(cls))

        elif item_type == "set_category":
            set_type = meta.get("set_type", "")
            if set_type == "group":
                self.ctx_menu.add_command(
                    label="Add Group Set...",
                    command=self._add_group_set_dialog)
            elif set_type == "trunk":
                self.ctx_menu.add_command(
                    label="Add Trunk Set...",
                    command=self._add_trunk_set_dialog)
            elif set_type == "conv":
                self.ctx_menu.add_command(
                    label="Add Conv Set...",
                    command=self._add_conv_set_dialog)
            elif set_type == "iden":
                self.ctx_menu.add_command(
                    label="Add Standard IDEN Set...",
                    command=self._add_standard_iden_set)

        elif item_type in ("group_set", "trunk_set", "conv_set", "iden_set"):
            name = meta.get("name", "")
            set_data = meta.get("set_data")
            # Add item to this set
            if item_type == "group_set":
                self.ctx_menu.add_command(
                    label="Add Talkgroup...",
                    command=lambda: self._add_talkgroup_dialog(name))
            elif item_type == "trunk_set":
                self.ctx_menu.add_command(
                    label="Add Frequency...",
                    command=lambda: self._add_frequency_dialog(name))
            elif item_type == "conv_set":
                self.ctx_menu.add_command(
                    label="Add Channel...",
                    command=lambda: self._add_channel_dialog(name))
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label=f"Rename '{name}'...",
                command=lambda: self._rename_set(item_type, name))
            if item_type == "group_set":
                self.ctx_menu.add_command(
                    label="Select All TGs",
                    command=lambda: self._select_all_children(iid))
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label=f"Delete Set '{name}'",
                command=lambda: self._delete_set(item_type, name))
            self.ctx_menu.add_separator()
            if item_type == "group_set":
                self.ctx_menu.add_command(
                    label="Move Up",
                    command=lambda: self._move_group_set(name, -1))
                self.ctx_menu.add_command(
                    label="Move Down",
                    command=lambda: self._move_group_set(name, +1))
                self.ctx_menu.add_separator()
            elif item_type == "trunk_set":
                self.ctx_menu.add_command(
                    label="Move Up",
                    command=lambda: self._move_trunk_set(name, -1))
                self.ctx_menu.add_command(
                    label="Move Down",
                    command=lambda: self._move_trunk_set(name, +1))
                self.ctx_menu.add_separator()
            elif item_type == "conv_set":
                self.ctx_menu.add_command(
                    label="Move Up",
                    command=lambda: self._move_conv_set(name, -1))
                self.ctx_menu.add_command(
                    label="Move Down",
                    command=lambda: self._move_conv_set(name, +1))
                self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label=f"Export '{name}' to CSV...",
                command=lambda: self._export_set_csv(item_type, name,
                                                       set_data))
            if item_type == "group_set" and set_data:
                self.ctx_menu.add_separator()
                self.ctx_menu.add_command(
                    label="Enable TX for All TGs",
                    command=lambda: self._batch_group_set(
                        name, "tx", True))
                self.ctx_menu.add_command(
                    label="Disable TX for All TGs",
                    command=lambda: self._batch_group_set(
                        name, "tx", False))
                self.ctx_menu.add_separator()
                self.ctx_menu.add_command(
                    label="Enable Scan for All TGs",
                    command=lambda: self._batch_group_set(
                        name, "scan", True))
                self.ctx_menu.add_command(
                    label="Disable Scan for All TGs",
                    command=lambda: self._batch_group_set(
                        name, "scan", False))
                self.ctx_menu.add_separator()
                self.ctx_menu.add_command(
                    label="Encryption Settings...",
                    command=lambda: self._encryption_dialog(name))

        elif item_type == "p25_conv_set":
            name = meta.get("name", "")
            self.ctx_menu.add_command(
                label=f"Export '{name}' to CSV...",
                command=lambda: self._export_set_csv(item_type, name,
                                                       meta.get("set_data")))

        elif item_type == "p25_conv_channel":
            name = meta.get("name", "")
            parent_iid = self.tree.parent(iid)
            parent_meta = self._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            ch_idx = meta.get("ch_idx", 0)
            self.ctx_menu.add_command(
                label="Edit NAC...",
                command=lambda: self._edit_nac_dialog(set_name, ch_idx))

        elif item_type == "preferred_table":
            self.ctx_menu.add_command(
                label="Edit Scan Priority...",
                command=self._scan_priority_dialog)

        elif item_type == "conv_channel":
            name = meta.get("name", "")
            parent_iid = self.tree.parent(iid)
            parent_meta = self._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            ch_idx = meta.get("ch_idx", 0)
            self.ctx_menu.add_command(
                label="Edit Channel...",
                command=lambda: self._edit_conv_channel(set_name, ch_idx))
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label="Move Up",
                command=lambda: self._move_conv_channel(set_name, ch_idx, -1))
            self.ctx_menu.add_command(
                label="Move Down",
                command=lambda: self._move_conv_channel(set_name, ch_idx, +1))
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label=f"Copy Name ({name})",
                command=lambda: self._copy_to_clipboard(name))

        elif item_type == "trunk_channel":
            parent_iid = self.tree.parent(iid)
            parent_meta = self._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            siblings = list(self.tree.get_children(parent_iid))
            ch_idx = siblings.index(iid) if iid in siblings else 0
            freq = meta.get("freq") or meta.get("tx", "")
            self.ctx_menu.add_command(
                label="Move Up",
                command=lambda: self._move_trunk_channel(
                    set_name, ch_idx, -1))
            self.ctx_menu.add_command(
                label="Move Down",
                command=lambda: self._move_trunk_channel(
                    set_name, ch_idx, +1))
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label=f"Copy Freq ({freq})",
                command=lambda: self._copy_to_clipboard(str(freq)))

        elif item_type == "talkgroup":
            gid = meta.get("group_id", 0)
            name = meta.get("name", "")
            # Find parent set name
            parent_iid = self.tree.parent(iid)
            parent_meta = self._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            self.ctx_menu.add_command(
                label="Edit Talkgroup...",
                command=lambda: self._edit_talkgroup(set_name, gid))
            self.ctx_menu.add_command(
                label=f"Delete TG {gid}",
                command=lambda: self._delete_talkgroup(set_name, gid))
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label="Move Up",
                command=lambda: self._move_tg(set_name, gid, -1))
            self.ctx_menu.add_command(
                label="Move Down",
                command=lambda: self._move_tg(set_name, gid, +1))
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label=f"Copy ID ({gid})",
                command=lambda: self._copy_to_clipboard(str(gid)))
            self.ctx_menu.add_command(
                label=f"Copy Name ({name})",
                command=lambda: self._copy_to_clipboard(name))

        # View Hex for any section type that has raw data
        hex_class = meta.get("class_name", "")
        if hex_class and item_type in ("option", "system", "system_config"):
            prs = self.app.prs
            if prs:
                sec = prs.get_section_by_class(hex_class)
                if sec:
                    self.ctx_menu.add_separator()
                    self.ctx_menu.add_command(
                        label="View Hex...",
                        command=lambda c=hex_class: self._show_hex_viewer(c))
        elif item_type in ("group_set", "trunk_set", "conv_set", "iden_set"):
            # Show hex for the set's raw section data
            set_data = meta.get("set_data")
            if set_data and hasattr(set_data, 'sections'):
                raw_parts = b"".join(
                    s.raw for s in set_data.sections if hasattr(s, 'raw'))
                if raw_parts:
                    name_val = meta.get("name", "set")
                    self.ctx_menu.add_separator()
                    self.ctx_menu.add_command(
                        label="View Hex...",
                        command=lambda d=raw_parts, n=name_val:
                            self._show_hex_viewer_raw(
                                d, title=f"Hex Viewer — {n} "
                                f"({len(d)} bytes)"))

        # Favorites: Add to Favorites for bookmarkable items
        if item_type in ("system", "group_set", "trunk_set",
                         "conv_set", "iden_set"):
            fav_name = meta.get("name", "")
            if fav_name:
                fav_cat_map = {
                    "system": "systems",
                    "group_set": "talkgroups",
                    "trunk_set": "channels",
                    "conv_set": "channels",
                    "iden_set": "channels",
                }
                fav_cat = fav_cat_map.get(item_type, "systems")
                self.ctx_menu.add_separator()
                self.ctx_menu.add_command(
                    label=f"Add '{fav_name}' to Favorites",
                    command=lambda n=fav_name, c=fav_cat:
                        self._add_to_favorites(c, n))

        # Remove from favorites for favorite items
        if item_type == "favorite_item":
            fav_name = meta.get("name", "")
            fav_cat = meta.get("category", "")
            self.ctx_menu.add_command(
                label=f"Remove '{fav_name}' from Favorites",
                command=lambda n=fav_name, c=fav_cat:
                    self._remove_from_favorites(c, n))

        # Always add expand/collapse for branch nodes
        children = self.tree.get_children(iid)
        if children:
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label="Expand All",
                command=lambda: self._expand_all(iid))
            self.ctx_menu.add_command(
                label="Collapse All",
                command=lambda: self._collapse_all(iid))

        if self.ctx_menu.index(tk.END) is not None:
            try:
                self.ctx_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.ctx_menu.grab_release()

    def _add_to_favorites(self, category, name):
        """Add an item to favorites and refresh tree."""
        try:
            from ..favorites import add_favorite
            added = add_favorite(category, {'name': name})
            if added:
                self.app.status_set(f"Added '{name}' to favorites")
                self.refresh()
            else:
                self.app.status_set(
                    f"'{name}' is already in favorites")
        except Exception as e:
            log_error(f"Failed to add favorite: {e}")
            messagebox.showerror("Error", f"Could not add favorite: {e}")

    def _remove_from_favorites(self, category, name):
        """Remove an item from favorites and refresh tree."""
        try:
            from ..favorites import remove_favorite
            removed = remove_favorite(category, name)
            if removed:
                self.app.status_set(
                    f"Removed '{name}' from favorites")
                self.refresh()
            else:
                self.app.status_set(f"'{name}' not found in favorites")
        except Exception as e:
            log_error(f"Failed to remove favorite: {e}")
            messagebox.showerror("Error",
                                 f"Could not remove favorite: {e}")

    def _select_all_children(self, parent_iid):
        """Select all child items of the given tree node."""
        children = self.tree.get_children(parent_iid)
        if children:
            self.tree.selection_set(*children)
            count = len(children)
            self.app.status_set(f"Selected {count} items")

    def _show_multi_select_menu(self, event, selection):
        """Show context menu for multi-selected items."""
        # Categorize selected items
        tg_items = []  # [(iid, meta), ...]
        other_types = set()
        for iid in selection:
            meta = self._item_meta.get(iid, {})
            item_type = meta.get("type", "")
            if item_type == "talkgroup":
                tg_items.append((iid, meta))
            else:
                other_types.add(item_type)

        self.ctx_menu.delete(0, tk.END)

        if tg_items and not other_types:
            count = len(tg_items)
            # Get the set names involved
            set_names = set()
            for iid, meta in tg_items:
                parent_iid = self.tree.parent(iid)
                parent_meta = self._item_meta.get(parent_iid, {})
                sn = parent_meta.get("name", "")
                if sn:
                    set_names.add(sn)

            self.ctx_menu.add_command(
                label=f"{count} Talkgroups Selected",
                state=tk.DISABLED)
            self.ctx_menu.add_separator()

            # Batch property dialog
            self.ctx_menu.add_command(
                label="Edit Selected...",
                command=lambda: self._batch_edit_selected_tgs(
                    tg_items, set_names))
            self.ctx_menu.add_separator()

            # Quick toggles
            self.ctx_menu.add_command(
                label="Enable TX",
                command=lambda: self._batch_selected_tgs(
                    tg_items, set_names, "tx", True))
            self.ctx_menu.add_command(
                label="Disable TX",
                command=lambda: self._batch_selected_tgs(
                    tg_items, set_names, "tx", False))
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label="Enable Scan",
                command=lambda: self._batch_selected_tgs(
                    tg_items, set_names, "scan", True))
            self.ctx_menu.add_command(
                label="Disable Scan",
                command=lambda: self._batch_selected_tgs(
                    tg_items, set_names, "scan", False))
            self.ctx_menu.add_separator()
            self.ctx_menu.add_command(
                label="Delete Selected",
                command=lambda: self._batch_delete_selected_tgs(
                    tg_items, set_names))
            self.ctx_menu.add_separator()

            # Copy IDs
            ids = [str(m.get("group_id", ""))
                   for _, m in tg_items if m.get("group_id")]
            self.ctx_menu.add_command(
                label=f"Copy {count} IDs",
                command=lambda: self._copy_to_clipboard(
                    "\n".join(ids)))
        else:
            self.ctx_menu.add_command(
                label=f"{len(selection)} items selected",
                state=tk.DISABLED)

        if self.ctx_menu.index(tk.END) is not None:
            try:
                self.ctx_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.ctx_menu.grab_release()

    def _expand_all(self, iid):
        """Expand item and all descendants."""
        self.tree.item(iid, open=True)
        for child in self.tree.get_children(iid):
            self._expand_all(child)

    def _collapse_all(self, iid):
        """Collapse item and all descendants."""
        for child in self.tree.get_children(iid):
            self._collapse_all(child)
        self.tree.item(iid, open=False)

    def _copy_to_clipboard(self, text):
        """Copy text to system clipboard."""
        self.clipboard_clear()
        self.clipboard_append(text)
        self.app.status_set(f"Copied: {text}")

    # ─── Delete operations ───────────────────────────────────────────

    def _delete_system(self, class_name, system_name):
        """Delete a system header by class + name."""
        if not messagebox.askyesno(
                "Confirm Delete",
                f"Delete system '{system_name}' ({class_name})?\n\n"
                "This removes the system header. Associated sets\n"
                "(groups, trunk, IDEN) are NOT removed."):
            return

        self.app.save_undo_snapshot("Delete system")
        from ..injector import remove_system_by_class
        removed = remove_system_by_class(
            self.app.prs, class_name, system_name)
        if removed:
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Deleted system '{system_name}' ({removed} sections)")
        else:
            messagebox.showwarning("Warning", "System not found.")

    def _delete_system_config(self, long_name):
        """Delete a system config data section by long name."""
        if not messagebox.askyesno(
                "Confirm Delete",
                f"Delete system config '{long_name}'?\n\n"
                "This removes the system configuration data."):
            return

        self.app.save_undo_snapshot("Delete system config")
        from ..injector import remove_system_config
        if remove_system_config(self.app.prs, long_name):
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(f"Deleted system config '{long_name}'")
        else:
            messagebox.showwarning("Warning", "System config not found.")

    def _delete_all_systems(self, class_name):
        """Delete all systems of a given type."""
        count = len(self.app.prs.get_sections_by_class(class_name))
        label = {
            'CP25TrkSystem': 'P25 Trunked',
            'CConvSystem': 'Conventional',
            'CP25ConvSystem': 'P25 Conventional',
        }.get(class_name, class_name)

        if not messagebox.askyesno(
                "Confirm Delete",
                f"Delete ALL {count} {label} system(s)?\n\n"
                "Associated sets are NOT removed.\nUse Edit > Undo to revert."):
            return

        self.app.save_undo_snapshot("Delete all systems")
        from ..injector import remove_system_by_class
        removed = remove_system_by_class(self.app.prs, class_name)
        if removed:
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Deleted all {label} systems ({removed} sections)")

    # ─── Delete set ────────────────────────────────────────────────────

    def _delete_set(self, item_type, set_name):
        """Delete an entire set (group/trunk/conv/iden) from the PRS."""
        type_labels = {
            "group_set": "group",
            "trunk_set": "trunk",
            "conv_set": "conv",
            "iden_set": "IDEN",
        }
        label = type_labels.get(item_type, item_type)

        if not messagebox.askyesno(
                "Confirm Delete",
                f"Delete {label} set '{set_name}'?\n\n"
                "All data in this set will be removed."):
            return

        prs = self.app.prs
        if not prs:
            return

        self.app.save_undo_snapshot("Delete set")
        try:
            if item_type == "group_set":
                self._delete_group_set(prs, set_name)
            elif item_type == "trunk_set":
                self._delete_trunk_set(prs, set_name)
            elif item_type == "conv_set":
                self._delete_conv_set(prs, set_name)
            elif item_type == "iden_set":
                self._delete_iden_set(prs, set_name)

            self.app.mark_modified()
            self.refresh()
            self.app.status_set(f"Deleted {label} set '{set_name}'")

        except Exception as e:
            messagebox.showerror("Error", f"Delete failed:\n{e}")

    def _delete_group_set(self, prs, set_name):
        from ..injector import (_parse_section_data,
                                _replace_group_sections,
                                _get_header_bytes, _get_first_count)
        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            raise ValueError("No group sections found")
        byte1, byte2 = _get_header_bytes(grp_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CP25GroupSet")
        existing = _parse_section_data(
            grp_sec, parse_group_section, first_count)
        remaining = [gs for gs in existing if gs.name != set_name]
        if len(remaining) == len(existing):
            raise ValueError(f"Set '{set_name}' not found")
        if not remaining:
            raise ValueError("Cannot delete the last group set")
        _replace_group_sections(prs, remaining, byte1, byte2,
                                 set_byte1, set_byte2)

    def _delete_trunk_set(self, prs, set_name):
        from ..injector import (_parse_section_data,
                                _replace_trunk_sections,
                                _get_header_bytes, _get_first_count)
        ch_sec = prs.get_section_by_class("CTrunkChannel")
        set_sec = prs.get_section_by_class("CTrunkSet")
        if not ch_sec or not set_sec:
            raise ValueError("No trunk sections found")
        byte1, byte2 = _get_header_bytes(ch_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CTrunkSet")
        from ..record_types import parse_trunk_channel_section
        existing = _parse_section_data(
            ch_sec, parse_trunk_channel_section, first_count)
        remaining = [ts for ts in existing if ts.name != set_name]
        if len(remaining) == len(existing):
            raise ValueError(f"Set '{set_name}' not found")
        if not remaining:
            raise ValueError("Cannot delete the last trunk set")
        _replace_trunk_sections(prs, remaining, byte1, byte2,
                                 set_byte1, set_byte2)

    def _delete_conv_set(self, prs, set_name):
        from ..injector import (_parse_section_data,
                                _replace_conv_sections,
                                _get_header_bytes, _get_first_count)
        conv_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        if not conv_sec or not set_sec:
            raise ValueError("No conv sections found")
        byte1, byte2 = _get_header_bytes(conv_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CConvSet")
        from ..record_types import parse_conv_channel_section
        existing = _parse_section_data(
            conv_sec, parse_conv_channel_section, first_count)
        remaining = [cs for cs in existing if cs.name != set_name]
        if len(remaining) == len(existing):
            raise ValueError(f"Set '{set_name}' not found")
        if not remaining:
            raise ValueError("Cannot delete the last conv set")
        _replace_conv_sections(prs, remaining, byte1, byte2,
                                set_byte1, set_byte2)

    def _delete_iden_set(self, prs, set_name):
        from ..injector import (_parse_section_data,
                                _get_header_bytes, _get_first_count)
        from ..record_types import (parse_iden_section,
                                     build_iden_section,
                                     extract_iden_trailing_data)
        elem_sec = prs.get_section_by_class("CDefaultIdenElem")
        set_sec = prs.get_section_by_class("CIdenDataSet")
        if not elem_sec or not set_sec:
            raise ValueError("No IDEN sections found")
        byte1, byte2 = _get_header_bytes(elem_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CIdenDataSet")
        trailing = extract_iden_trailing_data(elem_sec.raw, first_count)
        existing = _parse_section_data(
            elem_sec, parse_iden_section, first_count)
        remaining = [i for i in existing if i.name != set_name]
        if len(remaining) == len(existing):
            raise ValueError(f"Set '{set_name}' not found")
        if not remaining:
            raise ValueError("Cannot delete the last IDEN set")
        # Rebuild using build_iden_section (preserving trailing data)
        new_raw = build_iden_section(remaining, byte1, byte2,
                                      trailing_data=trailing)
        from ..prs_parser import Section
        from ..injector import _find_section_index, _rebuild_set_section
        from ..binary_io import write_uint16_le
        elem_idx = _find_section_index(prs, "CDefaultIdenElem")
        set_idx = _find_section_index(prs, "CIdenDataSet")
        prs.sections[elem_idx] = Section(offset=0, raw=new_raw,
                                           class_name="CDefaultIdenElem")
        new_set_raw = _rebuild_set_section("CIdenDataSet",
                                            len(remaining[0].elements),
                                            set_byte1, set_byte2)
        prs.sections[set_idx] = Section(offset=0, raw=new_set_raw,
                                          class_name="CIdenDataSet")

    # ─── Add standard IDEN set ────────────────────────────────────────

    def _add_standard_iden_set(self):
        """Show dialog to pick a standard IDEN template and inject it."""
        prs = self.app.prs
        if not prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        from ..iden_library import (
            STANDARD_IDEN_TEMPLATES, get_template_keys, get_default_name,
        )
        from ..injector import make_iden_set, add_iden_set, _safe_add_iden_set

        keys = get_template_keys()
        templates = STANDARD_IDEN_TEMPLATES

        # Dialog
        dlg = tk.Toplevel(self)
        dlg.title("Add Standard IDEN Set")
        dlg.resizable(False, False)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        ttk.Label(dlg, text="Template:").grid(
            row=0, column=0, padx=8, pady=(8, 4), sticky="w")
        labels = [templates[k].label for k in keys]
        combo_var = tk.StringVar(value=labels[0])
        combo = ttk.Combobox(dlg, textvariable=combo_var,
                              values=labels, state="readonly", width=32)
        combo.grid(row=0, column=1, padx=8, pady=(8, 4), sticky="ew")

        ttk.Label(dlg, text="Set Name:").grid(
            row=1, column=0, padx=8, pady=4, sticky="w")
        name_var = tk.StringVar(value=get_default_name(keys[0]))
        name_entry = ttk.Entry(dlg, textvariable=name_var, width=16)
        name_entry.grid(row=1, column=1, padx=8, pady=4, sticky="w")

        desc_var = tk.StringVar(value=templates[keys[0]].description)
        desc_label = ttk.Label(dlg, textvariable=desc_var,
                                wraplength=300, foreground="gray")
        desc_label.grid(row=2, column=0, columnspan=2,
                         padx=8, pady=4, sticky="w")

        def on_combo_change(*_):
            idx = combo.current()
            if idx >= 0:
                key = keys[idx]
                name_var.set(get_default_name(key))
                desc_var.set(templates[key].description)

        combo.bind("<<ComboboxSelected>>", on_combo_change)

        def do_add():
            idx = combo.current()
            if idx < 0:
                return
            key = keys[idx]
            tmpl = templates[key]
            set_name = name_var.get().strip()
            if not set_name:
                messagebox.showwarning("Warning", "Enter a set name.",
                                        parent=dlg)
                return

            try:
                self.app.save_undo_snapshot("Add IDEN set")
                iden_set = make_iden_set(set_name, tmpl.entries)
                _safe_add_iden_set(prs, iden_set)
                self.app.mark_modified()
                self.refresh()
                self.app.status_set(
                    f"Added IDEN set '{set_name}' ({tmpl.label})")
                dlg.destroy()
            except Exception as e:
                messagebox.showerror("Error",
                                      f"Failed to add IDEN set:\n{e}",
                                      parent=dlg)

        btn_frame = ttk.Frame(dlg)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=8)
        ttk.Button(btn_frame, text="Add", command=do_add).pack(
            side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel",
                    command=dlg.destroy).pack(side=tk.LEFT, padx=4)

        dlg.update_idletasks()
        # Center on parent
        x = self.winfo_toplevel().winfo_x() + 100
        y = self.winfo_toplevel().winfo_y() + 100
        dlg.geometry(f"+{x}+{y}")
        name_entry.focus_set()

    # ─── Form dialog helper ──────────────────────────────────────────

    def _simple_form_dialog(self, title, fields):
        """Show a modal form dialog and return field values or None.

        Args:
            title: dialog window title
            fields: list of (label, default_value, field_type) tuples
                field_type: "str", "str8", "str16", "int", "float", "bool"

        Returns:
            list of values in field order, or None if cancelled.
        """
        dlg = tk.Toplevel(self.app.root)
        dlg.title(title)
        dlg.transient(self.app.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        main = ttk.Frame(dlg, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        vars_ = []
        row = 0
        for label_text, default, ftype in fields:
            ttk.Label(main, text=label_text).grid(
                row=row, column=0, sticky=tk.W, pady=2, padx=(0, 8))

            if ftype == "bool":
                var = tk.BooleanVar(value=bool(default))
                ttk.Checkbutton(main, variable=var).grid(
                    row=row, column=1, sticky=tk.W, pady=2)
                vars_.append(var)
            elif ftype in ("str8", "str16"):
                max_len = 8 if ftype == "str8" else 16
                var = tk.StringVar(value=str(default))
                entry = ttk.Entry(main, textvariable=var,
                                  width=max_len + 4,
                                  font=("Consolas", 10))
                entry.grid(row=row, column=1, sticky=tk.W, pady=2)
                count_lbl = ttk.Label(main, text=f"0/{max_len}",
                                      foreground="gray",
                                      font=("TkDefaultFont", 8))
                count_lbl.grid(row=row, column=2, sticky=tk.W,
                               padx=(4, 0))

                def _update_count(_a=None, _b=None, _c=None,
                                  lbl=count_lbl, v=var, mx=max_len):
                    n = len(v.get())
                    lbl.config(text=f"{n}/{mx}",
                               foreground="red" if n > mx else "gray")
                var.trace_add("write", _update_count)
                _update_count()
                vars_.append(var)
            elif ftype == "int":
                var = tk.StringVar(value=str(default))
                ttk.Entry(main, textvariable=var, width=10,
                          font=("Consolas", 10)).grid(
                    row=row, column=1, sticky=tk.W, pady=2)
                vars_.append(var)
            elif ftype == "float":
                var = tk.StringVar(value=str(default))
                ttk.Entry(main, textvariable=var, width=14,
                          font=("Consolas", 10)).grid(
                    row=row, column=1, sticky=tk.W, pady=2)
                vars_.append(var)
            else:  # plain str
                var = tk.StringVar(value=str(default))
                ttk.Entry(main, textvariable=var, width=20).grid(
                    row=row, column=1, sticky=tk.W, pady=2)
                vars_.append(var)
            row += 1

        result = [None]

        def _ok():
            vals = []
            for i, (_, _, ftype) in enumerate(fields):
                v = vars_[i]
                if ftype == "bool":
                    vals.append(v.get())
                else:
                    vals.append(v.get())
            result[0] = vals
            dlg.destroy()

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=(12, 0))
        ttk.Button(btn_frame, text="OK", command=_ok,
                   width=8).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy,
                   width=8).pack(side=tk.RIGHT)

        dlg.bind("<Return>", lambda e: _ok())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        # Center on parent
        dlg.update_idletasks()
        pw = self.app.root
        x = pw.winfo_x() + (pw.winfo_width() - dlg.winfo_width()) // 2
        y = pw.winfo_y() + (pw.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.wait_window()
        return result[0]

    # ─── Add system dialogs ──────────────────────────────────────────

    def _add_p25_system_dialog(self):
        """Dialog to add a new P25 trunked system."""
        prs = self.app.prs
        if not prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        vals = self._simple_form_dialog("Add P25 Trunked System", [
            ("System Name:", "", "str8"),
            ("Long Name:", "", "str16"),
            ("System ID:", "0", "int"),
            ("WACN:", "0", "int"),
        ])
        if vals is None:
            return

        sys_name = vals[0].strip().upper()
        long_name = vals[1].strip().upper()
        try:
            system_id = int(vals[2])
        except ValueError:
            messagebox.showerror("Error", "System ID must be a number.")
            return
        try:
            wacn = int(vals[3])
        except ValueError:
            messagebox.showerror("Error", "WACN must be a number.")
            return

        if not sys_name:
            messagebox.showerror("Error", "System name cannot be empty.")
            return
        if len(sys_name) > 8:
            sys_name = sys_name[:8]
        if len(long_name) > 16:
            long_name = long_name[:16]

        try:
            from ..injector import add_p25_trunked_system
            config = P25TrkSystemConfig(
                system_name=sys_name,
                long_name=long_name,
                system_id=system_id,
                wacn=wacn,
            )
            self.app.save_undo_snapshot("Add P25 system")
            add_p25_trunked_system(prs, config)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Added P25 trunked system '{sys_name}'")
        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to add system:\n{e}")

    def _add_conv_system_dialog(self):
        """Dialog to add a new conventional system."""
        prs = self.app.prs
        if not prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        vals = self._simple_form_dialog("Add Conventional System", [
            ("System Name:", "", "str8"),
            ("Long Name:", "", "str16"),
        ])
        if vals is None:
            return

        sys_name = vals[0].strip().upper()
        long_name = vals[1].strip().upper()

        if not sys_name:
            messagebox.showerror("Error", "System name cannot be empty.")
            return
        if len(sys_name) > 8:
            sys_name = sys_name[:8]
        if len(long_name) > 16:
            long_name = long_name[:16]

        try:
            from ..injector import add_conv_system
            config = ConvSystemConfig(
                system_name=sys_name,
                long_name=long_name,
                conv_set_name="",
            )
            self.app.save_undo_snapshot("Add conv system")
            add_conv_system(prs, config)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Added conventional system '{sys_name}'")
        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to add system:\n{e}")

    # ─── Add set dialogs ─────────────────────────────────────────────

    def _add_group_set_dialog(self):
        """Dialog to add a new empty group set."""
        prs = self.app.prs
        if not prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        vals = self._simple_form_dialog("Add Group Set", [
            ("Set Name:", "", "str8"),
        ])
        if vals is None:
            return

        set_name = vals[0].strip().upper()
        if not set_name:
            messagebox.showerror("Error", "Set name cannot be empty.")
            return
        if len(set_name) > 8:
            set_name = set_name[:8]

        try:
            from ..injector import add_group_set, make_group_set
            group_set = make_group_set(set_name, [
                (1, "TG 1", "TALKGROUP 1"),
            ])
            self.app.save_undo_snapshot("Add group set")
            add_group_set(prs, group_set)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(f"Added group set '{set_name}'")
        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to add group set:\n{e}")

    def _add_trunk_set_dialog(self):
        """Dialog to add a new trunk set with one dummy frequency."""
        prs = self.app.prs
        if not prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        vals = self._simple_form_dialog("Add Trunk Set", [
            ("Set Name:", "", "str8"),
        ])
        if vals is None:
            return

        set_name = vals[0].strip().upper()
        if not set_name:
            messagebox.showerror("Error", "Set name cannot be empty.")
            return
        if len(set_name) > 8:
            set_name = set_name[:8]

        try:
            from ..injector import add_trunk_set, make_trunk_set
            trunk_set = make_trunk_set(set_name, [
                (851.0125, 806.0125),
            ])
            self.app.save_undo_snapshot("Add trunk set")
            add_trunk_set(prs, trunk_set)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(f"Added trunk set '{set_name}'")
        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to add trunk set:\n{e}")

    def _add_conv_set_dialog(self):
        """Dialog to add a new conv set with one dummy channel."""
        prs = self.app.prs
        if not prs:
            messagebox.showwarning("Warning", "No file loaded.")
            return

        vals = self._simple_form_dialog("Add Conv Set", [
            ("Set Name:", "", "str8"),
        ])
        if vals is None:
            return

        set_name = vals[0].strip().upper()
        if not set_name:
            messagebox.showerror("Error", "Set name cannot be empty.")
            return
        if len(set_name) > 8:
            set_name = set_name[:8]

        try:
            from ..injector import add_conv_set, make_conv_set
            conv_set = make_conv_set(set_name, [
                {"short_name": "CH 1", "tx_freq": 462.5625},
            ])
            self.app.save_undo_snapshot("Add conv set")
            add_conv_set(prs, conv_set)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(f"Added conv set '{set_name}'")
        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to add conv set:\n{e}")

    # ─── Add item to set dialogs ─────────────────────────────────────

    def _add_talkgroup_dialog(self, set_name):
        """Dialog to add a new talkgroup to an existing group set."""
        prs = self.app.prs
        if not prs:
            return

        vals = self._simple_form_dialog(
            f"Add Talkgroup to '{set_name}'", [
                ("Talkgroup ID:", "1", "int"),
                ("Short Name:", "", "str8"),
                ("Long Name:", "", "str16"),
                ("TX Enabled:", False, "bool"),
                ("Scan Enabled:", True, "bool"),
            ])
        if vals is None:
            return

        try:
            tg_id = int(vals[0])
        except ValueError:
            messagebox.showerror("Error",
                                  "Talkgroup ID must be a number.")
            return
        if tg_id < 1 or tg_id > 65535:
            messagebox.showerror("Error",
                                  "Talkgroup ID must be 1-65535.")
            return

        short_name = vals[1].strip().upper()
        long_name = vals[2].strip().upper()
        tx = vals[3]
        scan = vals[4]

        if not short_name:
            messagebox.showerror("Error",
                                  "Short name cannot be empty.")
            return
        if len(short_name) > 8:
            short_name = short_name[:8]
        if len(long_name) > 16:
            long_name = long_name[:16]

        try:
            from ..injector import add_talkgroups, make_p25_group
            group = make_p25_group(tg_id, short_name, long_name,
                                   tx=tx, scan=scan)
            self.app.save_undo_snapshot("Add talkgroup")
            add_talkgroups(prs, set_name, [group])
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Added TG {tg_id} to '{set_name}'")
        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to add talkgroup:\n{e}")

    def _add_frequency_dialog(self, set_name):
        """Dialog to add a frequency to an existing trunk set."""
        prs = self.app.prs
        if not prs:
            return

        vals = self._simple_form_dialog(
            f"Add Frequency to '{set_name}'", [
                ("TX Frequency (MHz):", "", "float"),
                ("RX Frequency (MHz):", "", "float"),
            ])
        if vals is None:
            return

        try:
            tx_freq = float(vals[0])
            rx_freq = float(vals[1])
        except ValueError:
            messagebox.showerror("Error", "Invalid frequency value.")
            return

        if not (30.0 <= tx_freq <= 960.0):
            messagebox.showerror("Error",
                                  "TX frequency must be 30-960 MHz.")
            return
        if not (30.0 <= rx_freq <= 960.0):
            messagebox.showerror("Error",
                                  "RX frequency must be 30-960 MHz.")
            return

        try:
            from ..injector import add_trunk_channels, make_trunk_channel
            channel = make_trunk_channel(tx_freq, rx_freq)
            self.app.save_undo_snapshot("Add trunk channel")
            add_trunk_channels(prs, set_name, [channel])
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Added {tx_freq:.5f}/{rx_freq:.5f} MHz "
                f"to '{set_name}'")
        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to add frequency:\n{e}")

    def _add_channel_dialog(self, set_name):
        """Dialog to add a channel to an existing conv set."""
        prs = self.app.prs
        if not prs:
            return

        vals = self._simple_form_dialog(
            f"Add Channel to '{set_name}'", [
                ("Short Name:", "", "str8"),
                ("Long Name:", "", "str16"),
                ("TX Freq (MHz):", "", "float"),
                ("RX Freq (MHz):", "", "float"),
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
            messagebox.showerror("Error", "Invalid frequency value.")
            return
        tx_tone = vals[4].strip()
        rx_tone = vals[5].strip()

        if not short_name:
            messagebox.showerror("Error",
                                  "Short name cannot be empty.")
            return
        if len(short_name) > 8:
            short_name = short_name[:8]
        if len(long_name) > 16:
            long_name = long_name[:16]
        if not (30.0 <= tx_freq <= 960.0):
            messagebox.showerror("Error",
                                  "TX frequency must be 30-960 MHz.")
            return
        if not (30.0 <= rx_freq <= 960.0):
            messagebox.showerror("Error",
                                  "RX frequency must be 30-960 MHz.")
            return

        try:
            from ..injector import (
                _parse_section_data, _replace_conv_sections,
                _get_header_bytes, _get_first_count, make_conv_channel,
            )

            conv_sec = prs.get_section_by_class("CConvChannel")
            set_sec = prs.get_section_by_class("CConvSet")
            if not conv_sec or not set_sec:
                messagebox.showerror("Error",
                                      "No conv sections found.")
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
                                      f"Conv set '{set_name}' not found.")
                return

            channel = make_conv_channel(
                short_name, tx_freq, rx_freq,
                tx_tone, rx_tone, long_name)
            target.channels.append(channel)

            self.app.save_undo_snapshot("Add channel")
            _replace_conv_sections(prs, existing_sets, byte1, byte2,
                                    set_byte1, set_byte2)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Added channel '{short_name}' to '{set_name}'")
        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to add channel:\n{e}")

    # ─── Export single set ───────────────────────────────────────────

    def _export_set_csv(self, item_type, name, set_data):
        """Export a single set to CSV."""
        if not set_data:
            messagebox.showwarning("Warning", "No data to export.")
            return

        path = filedialog.asksaveasfilename(
            title=f"Export {name} to CSV",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile=f"{name.strip()}.csv")
        if not path:
            return

        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)

                if item_type == "group_set":
                    w.writerow(["GroupID", "ShortName", "LongName",
                                "TX", "RX", "Scan"])
                    for g in set_data.groups:
                        w.writerow([
                            g.group_id, g.group_name, g.long_name,
                            "Y" if g.tx else "N",
                            "Y" if g.rx else "N",
                            "Y" if g.scan else "N"])

                elif item_type == "trunk_set":
                    w.writerow(["TxFreq", "RxFreq"])
                    for ch in set_data.channels:
                        w.writerow([f"{ch.tx_freq:.5f}",
                                    f"{ch.rx_freq:.5f}"])

                elif item_type == "conv_set":
                    w.writerow(["ShortName", "TxFreq", "RxFreq",
                                "TxTone", "RxTone", "LongName"])
                    for ch in set_data.channels:
                        w.writerow([
                            ch.short_name,
                            f"{ch.tx_freq:.5f}",
                            f"{ch.rx_freq:.5f}",
                            ch.tx_tone, ch.rx_tone,
                            ch.long_name])

                elif item_type == "iden_set":
                    w.writerow(["Slot", "BaseFreqMHz", "Spacing",
                                "BW", "TxOffset", "Type"])
                    for i, e in enumerate(set_data.elements):
                        if e.is_empty():
                            continue
                        w.writerow([
                            i,
                            f"{e.base_freq_hz / 1e6:.5f}",
                            e.chan_spacing_hz,
                            e.bandwidth_hz,
                            f"{e.tx_offset_mhz:.4f}",
                            "TDMA" if e.iden_type else "FDMA"])

            self.app.status_set(f"Exported '{name}' to {Path(path).name}")

        except Exception as e:
            messagebox.showerror("Error", f"Export failed:\n{e}")

    # ─── Batch operations ────────────────────────────────────────────

    def _batch_group_set(self, set_name, field, value):
        """Batch-modify a field on all talkgroups in a group set.

        Parses current group sections, modifies the target set, rebuilds.
        """
        prs = self.app.prs
        if not prs:
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")

            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)

            target = None
            for gs in existing_sets:
                if gs.name == set_name:
                    target = gs
                    break

            if not target:
                messagebox.showwarning("Warning",
                                        f"Group set '{set_name}' not found.")
                return

            label = "TX" if field == "tx" else "Scan"
            action = "Enable" if value else "Disable"
            count = len(target.groups)

            if not messagebox.askyesno(
                    "Confirm Batch Operation",
                    f"{action} {label} for all {count} talkgroups "
                    f"in '{set_name}'?"):
                return

            self.app.save_undo_snapshot("Batch edit talkgroups")
            for g in target.groups:
                setattr(g, field, value)

            _replace_group_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)

            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"{action}d {label} for {count} TGs in '{set_name}'")

        except Exception as e:
            messagebox.showerror("Error", f"Batch operation failed:\n{e}")

    def _batch_selected_tgs(self, tg_items, set_names, field, value):
        """Batch-modify a field on specifically selected talkgroups."""
        prs = self.app.prs
        if not prs:
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")
            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)

            # Build set of selected group IDs
            selected_ids = set()
            for _, meta in tg_items:
                gid = meta.get("group_id")
                if gid is not None:
                    selected_ids.add(gid)

            label = "TX" if field == "tx" else "Scan"
            action = "Enable" if value else "Disable"

            if not messagebox.askyesno(
                    "Confirm Batch Operation",
                    f"{action} {label} for {len(selected_ids)} "
                    f"selected talkgroups?"):
                return

            self.app.save_undo_snapshot("Batch edit selected TGs")
            changed = 0
            for gs in existing_sets:
                if gs.name not in set_names:
                    continue
                for g in gs.groups:
                    if g.group_id in selected_ids:
                        setattr(g, field, value)
                        changed += 1

            _replace_group_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)

            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"{action}d {label} for {changed} selected TGs")

        except Exception as e:
            messagebox.showerror("Error", f"Batch operation failed:\n{e}")

    def _batch_delete_selected_tgs(self, tg_items, set_names):
        """Delete multiple selected talkgroups at once."""
        prs = self.app.prs
        if not prs:
            return

        count = len(tg_items)
        if not messagebox.askyesno(
                "Confirm Delete",
                f"Delete {count} selected talkgroups?\n\n"
                "Use Edit > Undo to revert."):
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")
            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)

            selected_ids = set()
            for _, meta in tg_items:
                gid = meta.get("group_id")
                if gid is not None:
                    selected_ids.add(gid)

            self.app.save_undo_snapshot("Delete selected TGs")
            removed = 0
            for gs in existing_sets:
                if gs.name not in set_names:
                    continue
                orig = len(gs.groups)
                gs.groups = [g for g in gs.groups
                             if g.group_id not in selected_ids]
                removed += orig - len(gs.groups)

            _replace_group_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)

            self.app.mark_modified()
            self.refresh()
            self.app.status_set(f"Deleted {removed} selected talkgroups")

        except Exception as e:
            messagebox.showerror("Error", f"Delete failed:\n{e}")

    def _batch_edit_selected_tgs(self, tg_items, set_names):
        """Show dialog to edit properties of multiple selected talkgroups."""
        prs = self.app.prs
        if not prs:
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")
            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse groups:\n{e}")
            return

        selected_ids = set()
        for _, meta in tg_items:
            gid = meta.get("group_id")
            if gid is not None:
                selected_ids.add(gid)

        count = len(selected_ids)

        # Build dialog
        dlg = tk.Toplevel(self.app.root)
        dlg.title(f"Edit {count} Talkgroups")
        dlg.transient(self.app.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        main = ttk.Frame(dlg, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text=f"Batch Edit {count} Talkgroups",
                  font=("", 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 8))

        ttk.Label(main,
                  text="Set each property to change, or leave unchanged.",
                  foreground="gray").grid(
            row=1, column=0, columnspan=3, sticky=tk.W, pady=(0, 8))

        # TX: Unchanged / Enable / Disable
        ttk.Label(main, text="TX:").grid(
            row=2, column=0, sticky=tk.W, pady=4)
        tx_var = tk.StringVar(value="unchanged")
        ttk.Radiobutton(main, text="No Change", variable=tx_var,
                         value="unchanged").grid(
            row=2, column=1, sticky=tk.W, padx=4)
        tx_frame = ttk.Frame(main)
        tx_frame.grid(row=2, column=2, sticky=tk.W)
        ttk.Radiobutton(tx_frame, text="Enable", variable=tx_var,
                         value="enable").pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(tx_frame, text="Disable", variable=tx_var,
                         value="disable").pack(side=tk.LEFT, padx=4)

        # Scan: Unchanged / Enable / Disable
        ttk.Label(main, text="Scan:").grid(
            row=3, column=0, sticky=tk.W, pady=4)
        scan_var = tk.StringVar(value="unchanged")
        ttk.Radiobutton(main, text="No Change", variable=scan_var,
                         value="unchanged").grid(
            row=3, column=1, sticky=tk.W, padx=4)
        scan_frame = ttk.Frame(main)
        scan_frame.grid(row=3, column=2, sticky=tk.W)
        ttk.Radiobutton(scan_frame, text="Enable", variable=scan_var,
                         value="enable").pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(scan_frame, text="Disable", variable=scan_var,
                         value="disable").pack(side=tk.LEFT, padx=4)

        result = [False]

        def _apply():
            tx_choice = tx_var.get()
            scan_choice = scan_var.get()

            if tx_choice == "unchanged" and scan_choice == "unchanged":
                dlg.destroy()
                return

            changes = []
            if tx_choice != "unchanged":
                changes.append(
                    f"TX={'ON' if tx_choice == 'enable' else 'OFF'}")
            if scan_choice != "unchanged":
                changes.append(
                    f"Scan={'ON' if scan_choice == 'enable' else 'OFF'}")

            if not messagebox.askyesno(
                    "Confirm",
                    f"Apply to {count} talkgroups:\n"
                    f"  {', '.join(changes)}",
                    parent=dlg):
                return

            applied = 0
            for gs in existing_sets:
                if gs.name not in set_names:
                    continue
                for g in gs.groups:
                    if g.group_id in selected_ids:
                        if tx_choice == "enable":
                            g.tx = True
                        elif tx_choice == "disable":
                            g.tx = False
                        if scan_choice == "enable":
                            g.scan = True
                        elif scan_choice == "disable":
                            g.scan = False
                        applied += 1

            result[0] = True
            dlg.destroy()

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=4, column=0, columnspan=3, pady=(12, 0))
        ttk.Button(btn_frame, text="Apply", command=_apply,
                   width=10).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy,
                   width=10).pack(side=tk.RIGHT)

        dlg.bind("<Return>", lambda e: _apply())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        dlg.update_idletasks()
        pw = self.app.root
        x = pw.winfo_x() + (pw.winfo_width() - dlg.winfo_width()) // 2
        y = pw.winfo_y() + (pw.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.wait_window()

        if result[0]:
            try:
                self.app.save_undo_snapshot("Batch edit talkgroups")
                _replace_group_sections(prs, existing_sets, byte1, byte2,
                                         set_byte1, set_byte2)
                self.app.mark_modified()
                self.refresh()
                self.app.status_set(
                    f"Batch-edited {count} talkgroups")
            except Exception as e:
                messagebox.showerror("Error", f"Batch edit failed:\n{e}")

    # ─── Talkgroup editing ─────────────────────────────────────────────

    def _edit_talkgroup(self, set_name, group_id):
        """Open dialog to edit a single talkgroup's properties."""
        prs = self.app.prs
        if not prs:
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")
            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse groups:\n{e}")
            return

        # Find the target talkgroup
        target_set = None
        target_grp = None
        for gs in existing_sets:
            if gs.name == set_name:
                target_set = gs
                for g in gs.groups:
                    if g.group_id == group_id:
                        target_grp = g
                        break
                break

        if not target_grp:
            messagebox.showwarning("Warning",
                                    f"TG {group_id} not found in '{set_name}'.")
            return

        # Show edit dialog
        dlg = tk.Toplevel(self.app.root)
        dlg.title(f"Edit Talkgroup {group_id}")
        dlg.transient(self.app.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        main = ttk.Frame(dlg, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text=f"Talkgroup {group_id} in '{set_name}'",
                  font=("", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))

        # Fields
        ttk.Label(main, text="Group ID:").grid(
            row=1, column=0, sticky=tk.W, pady=2)
        ttk.Label(main, text=str(group_id),
                  font=("Consolas", 10)).grid(
            row=1, column=1, sticky=tk.W, pady=2)

        ttk.Label(main, text="Short Name (8 char):").grid(
            row=2, column=0, sticky=tk.W, pady=2)
        short_var = tk.StringVar(value=target_grp.group_name)
        ttk.Entry(main, textvariable=short_var, width=12,
                  font=("Consolas", 10)).grid(
            row=2, column=1, sticky=tk.W, pady=2)

        ttk.Label(main, text="Long Name (16 char):").grid(
            row=3, column=0, sticky=tk.W, pady=2)
        long_var = tk.StringVar(value=target_grp.long_name)
        ttk.Entry(main, textvariable=long_var, width=20,
                  font=("Consolas", 10)).grid(
            row=3, column=1, sticky=tk.W, pady=2)

        tx_var = tk.BooleanVar(value=target_grp.tx)
        ttk.Checkbutton(main, text="TX Enabled",
                         variable=tx_var).grid(
            row=4, column=0, columnspan=2, sticky=tk.W, pady=2)

        scan_var = tk.BooleanVar(value=target_grp.scan)
        ttk.Checkbutton(main, text="Scan Enabled",
                         variable=scan_var).grid(
            row=5, column=0, columnspan=2, sticky=tk.W, pady=2)

        result = [False]

        def _save():
            new_short = short_var.get().strip()
            new_long = long_var.get().strip()
            if not new_short:
                messagebox.showwarning("Warning", "Short name cannot be empty.",
                                        parent=dlg)
                return
            if len(new_short) > 8:
                new_short = new_short[:8]
            if len(new_long) > 16:
                new_long = new_long[:16]

            target_grp.group_name = new_short.upper()
            target_grp.long_name = new_long.upper()
            target_grp.tx = tx_var.get()
            target_grp.scan = scan_var.get()
            result[0] = True
            dlg.destroy()

        def _cancel():
            dlg.destroy()

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn_frame, text="Save", command=_save,
                   width=10).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="Cancel", command=_cancel,
                   width=10).pack(side=tk.RIGHT)

        dlg.bind("<Return>", lambda e: _save())
        dlg.bind("<Escape>", lambda e: _cancel())

        # Center on parent
        dlg.update_idletasks()
        pw = self.app.root
        x = pw.winfo_x() + (pw.winfo_width() - dlg.winfo_width()) // 2
        y = pw.winfo_y() + (pw.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.wait_window()

        if result[0]:
            try:
                self.app.save_undo_snapshot("Edit talkgroup")
                _replace_group_sections(prs, existing_sets, byte1, byte2,
                                         set_byte1, set_byte2)
                self.app.mark_modified()
                self.refresh()
                self.app.status_set(
                    f"Updated TG {group_id} in '{set_name}'")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save:\n{e}")

    # ─── Delete talkgroup ──────────────────────────────────────────────

    def _delete_talkgroup(self, set_name, group_id):
        """Delete a single talkgroup from a group set."""
        prs = self.app.prs
        if not prs:
            return

        if not messagebox.askyesno(
                "Confirm Delete",
                f"Delete talkgroup {group_id} from '{set_name}'?"):
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")
            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)

            found = False
            for gs in existing_sets:
                if gs.name == set_name:
                    orig_count = len(gs.groups)
                    gs.groups = [g for g in gs.groups
                                 if g.group_id != group_id]
                    if len(gs.groups) < orig_count:
                        found = True
                    break

            if not found:
                messagebox.showwarning("Warning",
                                        f"TG {group_id} not found.")
                return

            self.app.save_undo_snapshot("Delete talkgroup")
            _replace_group_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Deleted TG {group_id} from '{set_name}'")

        except Exception as e:
            messagebox.showerror("Error", f"Delete failed:\n{e}")

    # ─── Move operations ─────────────────────────────────────────────

    def _on_move_up(self, event):
        """Alt+Up: move selected item up."""
        self._move_selected(-1)
        return "break"

    def _on_move_down(self, event):
        """Alt+Down: move selected item down."""
        self._move_selected(+1)
        return "break"

    def _move_selected(self, direction):
        """Move the selected item up or down."""
        iid = self.tree.focus()
        if not iid:
            return
        meta = self._item_meta.get(iid, {})
        item_type = meta.get("type", "")

        if item_type == "talkgroup":
            parent_iid = self.tree.parent(iid)
            parent_meta = self._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            gid = meta.get("group_id")
            if set_name and gid is not None:
                self._move_tg(set_name, gid, direction)
        elif item_type == "conv_channel":
            parent_iid = self.tree.parent(iid)
            parent_meta = self._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            ch_idx = meta.get("ch_idx")
            if set_name and ch_idx is not None:
                self._move_conv_channel(set_name, ch_idx, direction)
        elif item_type == "trunk_channel":
            parent_iid = self.tree.parent(iid)
            parent_meta = self._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            # Get index from tree position
            siblings = list(self.tree.get_children(parent_iid))
            ch_idx = siblings.index(iid) if iid in siblings else None
            if set_name and ch_idx is not None:
                self._move_trunk_channel(set_name, ch_idx, direction)
        elif item_type == "group_set":
            name = meta.get("name", "")
            if name:
                self._move_group_set(name, direction)
        elif item_type == "trunk_set":
            name = meta.get("name", "")
            if name:
                self._move_trunk_set(name, direction)
        elif item_type == "conv_set":
            name = meta.get("name", "")
            if name:
                self._move_conv_set(name, direction)

    def _move_tg(self, set_name, group_id, direction):
        """Move a talkgroup up (-1) or down (+1) within its group set."""
        prs = self.app.prs
        if not prs:
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")
            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)

            target_set = None
            for gs in existing_sets:
                if gs.name == set_name:
                    target_set = gs
                    break
            if not target_set:
                return

            idx = None
            for i, g in enumerate(target_set.groups):
                if g.group_id == group_id:
                    idx = i
                    break
            if idx is None:
                return

            new_idx = idx + direction
            if new_idx < 0 or new_idx >= len(target_set.groups):
                return

            self.app.save_undo_snapshot("Move talkgroup")
            target_set.groups[idx], target_set.groups[new_idx] = \
                target_set.groups[new_idx], target_set.groups[idx]

            _replace_group_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved TG {group_id} {'up' if direction < 0 else 'down'}")

        except Exception as e:
            messagebox.showerror("Error", f"Move failed:\n{e}")

    def _move_group_set(self, set_name, direction):
        """Move a group set up (-1) or down (+1) in the list."""
        prs = self.app.prs
        if not prs:
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")
            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)

            idx = None
            for i, gs in enumerate(existing_sets):
                if gs.name == set_name:
                    idx = i
                    break
            if idx is None:
                return

            new_idx = idx + direction
            if new_idx < 0 or new_idx >= len(existing_sets):
                return

            self.app.save_undo_snapshot("Move group set")
            existing_sets[idx], existing_sets[new_idx] = \
                existing_sets[new_idx], existing_sets[idx]

            _replace_group_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved group set '{set_name}' "
                f"{'up' if direction < 0 else 'down'}")

        except Exception as e:
            messagebox.showerror("Error", f"Move failed:\n{e}")

    def _move_conv_channel(self, set_name, ch_idx, direction):
        """Move a conv channel up (-1) or down (+1) within its set."""
        prs = self.app.prs
        if not prs:
            return

        try:
            from ..injector import reorder_conv_channel
            new_idx = ch_idx + direction
            if new_idx < 0:
                return
            self.app.save_undo_snapshot("Move channel")
            reorder_conv_channel(prs, set_name, ch_idx, new_idx)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved channel {'up' if direction < 0 else 'down'} "
                f"in '{set_name}'")
        except IndexError:
            return  # at boundary
        except Exception as e:
            messagebox.showerror("Error", f"Move failed:\n{e}")

    def _move_trunk_channel(self, set_name, ch_idx, direction):
        """Move a trunk channel up (-1) or down (+1) within its set."""
        prs = self.app.prs
        if not prs:
            return

        try:
            from ..injector import reorder_trunk_channel
            new_idx = ch_idx + direction
            if new_idx < 0:
                return
            self.app.save_undo_snapshot("Move trunk channel")
            reorder_trunk_channel(prs, set_name, ch_idx, new_idx)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved trunk channel {'up' if direction < 0 else 'down'} "
                f"in '{set_name}'")
        except IndexError:
            return  # at boundary
        except Exception as e:
            messagebox.showerror("Error", f"Move failed:\n{e}")

    def _move_trunk_set(self, set_name, direction):
        """Move a trunk set up (-1) or down (+1) in the list."""
        prs = self.app.prs
        if not prs:
            return

        ch_sec = prs.get_section_by_class("CTrunkChannel")
        set_sec = prs.get_section_by_class("CTrunkSet")
        if not ch_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_trunk_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(ch_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CTrunkSet")
            existing_sets = _parse_section_data(
                ch_sec, parse_trunk_channel_section, first_count)

            idx = None
            for i, ts in enumerate(existing_sets):
                if ts.name == set_name:
                    idx = i
                    break
            if idx is None:
                return

            new_idx = idx + direction
            if new_idx < 0 or new_idx >= len(existing_sets):
                return

            self.app.save_undo_snapshot("Move trunk set")
            existing_sets[idx], existing_sets[new_idx] = \
                existing_sets[new_idx], existing_sets[idx]

            _replace_trunk_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved trunk set '{set_name}' "
                f"{'up' if direction < 0 else 'down'}")

        except Exception as e:
            messagebox.showerror("Error", f"Move failed:\n{e}")

    def _move_conv_set(self, set_name, direction):
        """Move a conv set up (-1) or down (+1) in the list."""
        prs = self.app.prs
        if not prs:
            return

        conv_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        if not conv_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_conv_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(conv_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CConvSet")
            existing_sets = _parse_section_data(
                conv_sec, parse_conv_channel_section, first_count)

            idx = None
            for i, cs in enumerate(existing_sets):
                if cs.name == set_name:
                    idx = i
                    break
            if idx is None:
                return

            new_idx = idx + direction
            if new_idx < 0 or new_idx >= len(existing_sets):
                return

            self.app.save_undo_snapshot("Move conv set")
            existing_sets[idx], existing_sets[new_idx] = \
                existing_sets[new_idx], existing_sets[idx]

            _replace_conv_sections(prs, existing_sets, byte1, byte2,
                                    set_byte1, set_byte2)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Moved conv set '{set_name}' "
                f"{'up' if direction < 0 else 'down'}")

        except Exception as e:
            messagebox.showerror("Error", f"Move failed:\n{e}")

    # ─── Rename operations ────────────────────────────────────────────

    def _prompt_new_name(self, title, label, current, max_len=8):
        """Show a simple rename dialog. Returns new name or None."""
        from tkinter import simpledialog
        new_name = simpledialog.askstring(
            title, f"{label} (max {max_len} chars):",
            initialvalue=current,
            parent=self.app.root)
        if not new_name or new_name.strip() == current:
            return None
        new_name = new_name.strip().upper()
        if len(new_name) > max_len:
            new_name = new_name[:max_len]
        return new_name

    def _rename_system(self, class_name, old_name):
        """Rename a system header (change short name in raw bytes)."""
        from ..binary_io import write_lps, read_lps
        prs = self.app.prs
        if not prs:
            return

        new_name = self._prompt_new_name(
            "Rename System", f"New name for '{old_name}':", old_name)
        if not new_name:
            return

        # Find the section and replace the LPS name
        for sec in prs.get_sections_by_class(class_name):
            short = parse_system_short_name(sec.raw)
            if short and short.upper() == old_name.upper():
                try:
                    self.app.save_undo_snapshot("Rename system")
                    _, _, _, data_start = parse_class_header(sec.raw, 0)
                    # Read old LPS to find its end
                    _, after_name = read_lps(sec.raw, data_start)
                    # Replace: header + new LPS + rest of data
                    new_raw = (sec.raw[:data_start] +
                               write_lps(new_name) +
                               sec.raw[after_name:])
                    sec.raw = new_raw
                    self.app.mark_modified()
                    self.refresh()
                    self.app.status_set(
                        f"Renamed system '{old_name}' to '{new_name}'")
                    return
                except Exception as e:
                    messagebox.showerror("Error",
                                          f"Rename failed:\n{e}")
                    return

        messagebox.showwarning("Warning",
                                f"System '{old_name}' not found.")

    def _rename_set(self, set_type, old_name):
        """Dispatch rename to the appropriate handler."""
        if set_type == "group_set":
            self._rename_group_set(old_name)
        elif set_type == "trunk_set":
            self._rename_trunk_set(old_name)
        elif set_type == "conv_set":
            self._rename_conv_set(old_name)
        elif set_type == "iden_set":
            self._rename_iden_set(old_name)

    def _rename_group_set(self, old_name):
        """Rename a group set (change name in parsed data, rebuild)."""
        prs = self.app.prs
        if not prs:
            return

        new_name = self._prompt_new_name(
            "Rename Group Set", f"New name for '{old_name}':", old_name)
        if not new_name:
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")
            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)

            found = False
            for gs in existing_sets:
                if gs.name == old_name:
                    gs.name = new_name
                    found = True
                    break

            if not found:
                messagebox.showwarning("Warning",
                                        f"Group set '{old_name}' not found.")
                return

            self.app.save_undo_snapshot("Rename group set")
            _replace_group_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Renamed group set '{old_name}' to '{new_name}'")

        except Exception as e:
            messagebox.showerror("Error", f"Rename failed:\n{e}")

    def _rename_trunk_set(self, old_name):
        """Rename a trunk set."""
        prs = self.app.prs
        if not prs:
            return

        new_name = self._prompt_new_name(
            "Rename Trunk Set", f"New name for '{old_name}':", old_name)
        if not new_name:
            return

        ch_sec = prs.get_section_by_class("CTrunkChannel")
        set_sec = prs.get_section_by_class("CTrunkSet")
        if not ch_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_trunk_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(ch_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CTrunkSet")
            existing_sets = _parse_section_data(
                ch_sec, parse_trunk_channel_section, first_count)

            found = False
            for ts in existing_sets:
                if ts.name == old_name:
                    ts.name = new_name
                    found = True
                    break

            if not found:
                messagebox.showwarning("Warning",
                                        f"Trunk set '{old_name}' not found.")
                return

            self.app.save_undo_snapshot("Rename trunk set")
            _replace_trunk_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Renamed trunk set '{old_name}' to '{new_name}'")

        except Exception as e:
            messagebox.showerror("Error", f"Rename failed:\n{e}")

    def _rename_conv_set(self, old_name):
        """Rename a conv set."""
        prs = self.app.prs
        if not prs:
            return

        new_name = self._prompt_new_name(
            "Rename Conv Set", f"New name for '{old_name}':", old_name)
        if not new_name:
            return

        conv_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        if not conv_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_conv_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(conv_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CConvSet")
            existing_sets = _parse_section_data(
                conv_sec, parse_conv_channel_section, first_count)

            found = False
            for cs in existing_sets:
                if cs.name == old_name:
                    cs.name = new_name
                    found = True
                    break

            if not found:
                messagebox.showwarning("Warning",
                                        f"Conv set '{old_name}' not found.")
                return

            self.app.save_undo_snapshot("Rename conv set")
            _replace_conv_sections(prs, existing_sets, byte1, byte2,
                                    set_byte1, set_byte2)
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Renamed conv set '{old_name}' to '{new_name}'")

        except Exception as e:
            messagebox.showerror("Error", f"Rename failed:\n{e}")

    def _rename_iden_set(self, old_name):
        """Rename an IDEN set."""
        prs = self.app.prs
        if not prs:
            return

        new_name = self._prompt_new_name(
            "Rename IDEN Set", f"New name for '{old_name}':", old_name)
        if not new_name:
            return

        elem_sec = prs.get_section_by_class("CDefaultIdenElem")
        set_sec = prs.get_section_by_class("CIdenDataSet")
        if not elem_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _get_header_bytes
        from ..injector import _get_first_count, _find_section_index
        from ..record_types import (parse_iden_section, build_iden_section,
                                     extract_iden_trailing_data)

        try:
            byte1, byte2 = _get_header_bytes(elem_sec)
            first_count = _get_first_count(prs, "CIdenDataSet")
            trailing = extract_iden_trailing_data(elem_sec.raw, first_count)
            existing_sets = _parse_section_data(
                elem_sec, parse_iden_section, first_count)

            found = False
            for iset in existing_sets:
                if iset.name == old_name:
                    iset.name = new_name
                    found = True
                    break

            if not found:
                messagebox.showwarning("Warning",
                                        f"IDEN set '{old_name}' not found.")
                return

            self.app.save_undo_snapshot("Rename IDEN set")
            new_raw = build_iden_section(existing_sets, byte1, byte2,
                                          trailing_data=trailing)
            from ..prs_parser import Section
            elem_idx = _find_section_index(prs, "CDefaultIdenElem")
            prs.sections[elem_idx] = Section(
                offset=0, raw=new_raw, class_name="CDefaultIdenElem")
            self.app.mark_modified()
            self.refresh()
            self.app.status_set(
                f"Renamed IDEN set '{old_name}' to '{new_name}'")

        except Exception as e:
            messagebox.showerror("Error", f"Rename failed:\n{e}")

    # ─── Conv channel editing ──────────────────────────────────────────

    def _edit_conv_channel(self, set_name, ch_idx):
        """Open dialog to edit a conventional channel's properties."""
        prs = self.app.prs
        if not prs:
            return

        conv_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        if not conv_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_conv_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(conv_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CConvSet")
            existing_sets = _parse_section_data(
                conv_sec, parse_conv_channel_section, first_count)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse channels:\n{e}")
            return

        # Find the target channel
        target_ch = None
        for cset in existing_sets:
            if cset.name == set_name and ch_idx < len(cset.channels):
                target_ch = cset.channels[ch_idx]
                break
        if not target_ch:
            messagebox.showwarning("Warning", "Channel not found.")
            return

        # Build edit dialog
        dlg = tk.Toplevel(self.app.root)
        dlg.title(f"Edit Channel: {target_ch.short_name}")
        dlg.transient(self.app.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        main = ttk.Frame(dlg, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Label(main, text="Short Name (8 max):").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        sn_var = tk.StringVar(value=target_ch.short_name)
        ttk.Entry(main, textvariable=sn_var, width=12).grid(
            row=row, column=1, sticky=tk.W, padx=4)

        row += 1
        ttk.Label(main, text="Long Name (16 max):").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        ln_var = tk.StringVar(value=target_ch.long_name)
        ttk.Entry(main, textvariable=ln_var, width=20).grid(
            row=row, column=1, sticky=tk.W, padx=4)

        row += 1
        ttk.Label(main, text="TX Freq (MHz):").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        tx_var = tk.StringVar(value=f"{target_ch.tx_freq:.5f}")
        ttk.Entry(main, textvariable=tx_var, width=14).grid(
            row=row, column=1, sticky=tk.W, padx=4)

        row += 1
        ttk.Label(main, text="RX Freq (MHz):").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        rx_var = tk.StringVar(value=f"{target_ch.rx_freq:.5f}")
        ttk.Entry(main, textvariable=rx_var, width=14).grid(
            row=row, column=1, sticky=tk.W, padx=4)

        row += 1
        ttk.Label(main, text="TX Tone:").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        txt_var = tk.StringVar(value=target_ch.tx_tone)
        ttk.Entry(main, textvariable=txt_var, width=10).grid(
            row=row, column=1, sticky=tk.W, padx=4)

        row += 1
        ttk.Label(main, text="RX Tone:").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        rxt_var = tk.StringVar(value=target_ch.rx_tone)
        ttk.Entry(main, textvariable=rxt_var, width=10).grid(
            row=row, column=1, sticky=tk.W, padx=4)

        result = [False]

        def _apply():
            try:
                new_tx = float(tx_var.get())
                new_rx = float(rx_var.get())
            except ValueError:
                messagebox.showwarning("Error",
                                        "Invalid frequency value.",
                                        parent=dlg)
                return
            sn = sn_var.get().strip()[:8]
            ln = ln_var.get().strip()[:16]
            if not sn:
                messagebox.showwarning("Error",
                                        "Short name cannot be empty.",
                                        parent=dlg)
                return

            target_ch.short_name = sn
            target_ch.long_name = ln
            target_ch.tx_freq = new_tx
            target_ch.rx_freq = new_rx
            target_ch.tx_tone = txt_var.get().strip()
            target_ch.rx_tone = rxt_var.get().strip()
            result[0] = True
            dlg.destroy()

        row += 1
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn_frame, text="Apply", command=_apply,
                   width=10).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy,
                   width=10).pack(side=tk.RIGHT)

        dlg.bind("<Return>", lambda e: _apply())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        dlg.update_idletasks()
        pw = self.app.root
        x = pw.winfo_x() + (pw.winfo_width() - dlg.winfo_width()) // 2
        y = pw.winfo_y() + (pw.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.wait_window()

        if result[0]:
            try:
                self.app.save_undo_snapshot("Edit channel")
                _replace_conv_sections(prs, existing_sets, byte1, byte2,
                                        set_byte1, set_byte2)
                self.app.mark_modified()
                self.refresh()
                self.app.status_set(
                    f"Updated channel '{target_ch.short_name}' "
                    f"in '{set_name}'")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save:\n{e}")

    # ─── Events ──────────────────────────────────────────────────────

    def _on_double_click(self, event):
        """Handle double-click: inline edit for leaf items, dialog for others."""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        column = self.tree.identify_column(event.x)
        meta = self._item_meta.get(item, {})
        item_type = meta.get("type", "")

        # Try inline editing for editable leaf items on tree column (#0)
        if item_type in ("talkgroup", "conv_channel", "trunk_channel"):
            if column == "#0":
                if self._start_inline_edit(item, column, meta):
                    return  # inline edit started

        # Fall through to dialog-based editing
        text = self.tree.item(item, "text")
        detail = self.tree.item(item, "values")

        if item_type == "talkgroup":
            gid = meta.get("group_id", 0)
            parent_iid = self.tree.parent(item)
            parent_meta = self._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            if set_name:
                self._edit_talkgroup(set_name, gid)
        elif item_type == "conv_channel":
            ch_idx = meta.get("ch_idx", 0)
            parent_iid = self.tree.parent(item)
            parent_meta = self._item_meta.get(parent_iid, {})
            set_name = parent_meta.get("name", "")
            if set_name:
                self._edit_conv_channel(set_name, ch_idx)
        elif item_type == "option":
            cls = meta.get("class_name", "")
            opt_map = OPTION_MAPS.get(cls)
            if opt_map and opt_map.fields:
                self._show_option_editor(cls)
            else:
                self._show_hex_viewer(cls)
        elif item_type in ("platform_config_category",
                           "platform_config_field",
                           "platform_config_root"):
            category = meta.get("category", "")
            if not category and item_type == "platform_config_field":
                parent_iid = self.tree.parent(item)
                parent_meta = self._item_meta.get(parent_iid, {})
                category = parent_meta.get("category", "")
            if category in ("Programmable Buttons", "Accessory Buttons"):
                self._show_prog_button_editor()
            elif category == "Short Menu":
                self._show_short_menu_editor()
            elif category:
                self._show_xml_editor(category)
            elif item_type == "platform_config_root":
                self.tree.item(item, open=True)
        else:
            self.app.status_set(f"Selected: {text} - {detail}")

    # ─── Inline Editing ──────────────────────────────────────────────

    def _start_inline_edit(self, iid, column, meta):
        """Create an inline Entry overlay for quick editing.

        Returns True if inline edit was started, False otherwise.
        """
        bbox = self.tree.bbox(iid, column)
        if not bbox:
            return False

        item_type = meta.get("type", "")

        # Determine current text and max length
        if item_type == "talkgroup":
            current = meta.get("name", "")
            max_len = 8
        elif item_type == "conv_channel":
            current = meta.get("name", "")
            max_len = 8
        elif item_type == "trunk_channel":
            # Edit the TX frequency shown in the tree text
            freq = meta.get("freq") or meta.get("tx")
            if freq is None:
                return False
            current = f"{freq:.5f}"
            max_len = 12
        else:
            return False

        x, y, w, h = bbox
        # Ensure minimum width for the entry
        w = max(w, 100)

        entry = ttk.Entry(self.tree, font=("Consolas", 10))
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, current)
        entry.select_range(0, tk.END)
        entry.focus_set()

        def _commit(event=None):
            new_val = entry.get().strip()
            entry.destroy()
            if new_val and new_val != current:
                self._commit_inline_edit(iid, meta, new_val, max_len)

        def _cancel(event=None):
            entry.destroy()

        entry.bind('<Return>', _commit)
        entry.bind('<Escape>', _cancel)
        entry.bind('<FocusOut>', lambda e: entry.after(50, _cancel))

        return True

    def _commit_inline_edit(self, iid, meta, new_val, max_len):
        """Apply the inline edit to the binary data."""
        item_type = meta.get("type", "")

        parent_iid = self.tree.parent(iid)
        parent_meta = self._item_meta.get(parent_iid, {})
        set_name = parent_meta.get("name", "")

        if not set_name:
            return

        prs = self.app.prs
        if not prs:
            return

        try:
            if item_type == "talkgroup":
                self._inline_edit_talkgroup(
                    prs, set_name, meta.get("group_id"), new_val, max_len)
            elif item_type == "conv_channel":
                self._inline_edit_conv_channel(
                    prs, set_name, meta.get("ch_idx"), new_val, max_len)
            elif item_type == "trunk_channel":
                # Get channel index from tree position
                siblings = list(self.tree.get_children(parent_iid))
                ch_idx = siblings.index(iid) if iid in siblings else None
                if ch_idx is not None:
                    self._inline_edit_trunk_freq(
                        prs, set_name, ch_idx, new_val)
        except Exception as e:
            messagebox.showerror("Error", f"Inline edit failed:\n{e}")

    def _inline_edit_talkgroup(self, prs, set_name, group_id, new_name,
                               max_len):
        """Apply inline name edit for a talkgroup."""
        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        byte1, byte2 = _get_header_bytes(grp_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CP25GroupSet")
        existing_sets = _parse_section_data(
            grp_sec, parse_group_section, first_count)

        for gs in existing_sets:
            if gs.name == set_name:
                for grp in gs.groups:
                    if grp.group_id == group_id:
                        self.app.save_undo_snapshot("Edit talkgroup")
                        grp.group_name = new_name[:max_len].upper()
                        _replace_group_sections(prs, existing_sets,
                                                byte1, byte2,
                                                set_byte1, set_byte2)
                        self.app.mark_modified()
                        self.refresh()
                        self.app.status_set(
                            f"Renamed TG {group_id} to "
                            f"'{grp.group_name}'")
                        return

    def _inline_edit_conv_channel(self, prs, set_name, ch_idx, new_name,
                                  max_len):
        """Apply inline name edit for a conv channel."""
        from ..injector import _parse_section_data, _replace_conv_sections
        from ..injector import _get_header_bytes, _get_first_count

        conv_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        if not conv_sec or not set_sec:
            return

        byte1, byte2 = _get_header_bytes(conv_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CConvSet")
        existing_sets = _parse_section_data(
            conv_sec, parse_conv_channel_section, first_count)

        for cs in existing_sets:
            if cs.name == set_name and ch_idx < len(cs.channels):
                self.app.save_undo_snapshot("Edit channel")
                cs.channels[ch_idx].short_name = new_name[:max_len]
                _replace_conv_sections(prs, existing_sets,
                                       byte1, byte2,
                                       set_byte1, set_byte2)
                self.app.mark_modified()
                self.refresh()
                self.app.status_set(
                    f"Renamed channel to '{new_name[:max_len]}' "
                    f"in '{set_name}'")
                return

    def _inline_edit_trunk_freq(self, prs, set_name, ch_idx, new_freq_str):
        """Apply inline frequency edit for a trunk channel."""
        try:
            new_freq = float(new_freq_str)
        except ValueError:
            messagebox.showwarning("Warning", "Invalid frequency value.")
            return

        if new_freq < 100.0 or new_freq > 1000.0:
            messagebox.showwarning("Warning",
                                    "Frequency out of range (100-1000 MHz).")
            return

        from ..injector import _parse_section_data, _replace_trunk_sections
        from ..injector import _get_header_bytes, _get_first_count

        ch_sec = prs.get_section_by_class("CTrunkChannel")
        set_sec = prs.get_section_by_class("CTrunkSet")
        if not ch_sec or not set_sec:
            return

        byte1, byte2 = _get_header_bytes(ch_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CTrunkSet")
        existing_sets = _parse_section_data(
            ch_sec, parse_trunk_channel_section, first_count)

        for ts in existing_sets:
            if ts.name == set_name and ch_idx < len(ts.channels):
                self.app.save_undo_snapshot("Edit trunk frequency")
                old_freq = ts.channels[ch_idx].tx_freq
                ts.channels[ch_idx].tx_freq = new_freq
                # If it was simplex (tx==rx), update rx too
                if ts.channels[ch_idx].rx_freq == old_freq:
                    ts.channels[ch_idx].rx_freq = new_freq
                _replace_trunk_sections(prs, existing_sets,
                                         byte1, byte2,
                                         set_byte1, set_byte2)
                self.app.mark_modified()
                self.refresh()
                self.app.status_set(
                    f"Updated freq to {new_freq:.5f} MHz "
                    f"in '{set_name}'")
                return

    # ─── Hex Viewer ──────────────────────────────────────────────────

    @staticmethod
    def _add_tooltip(widget, text):
        """Add a hover tooltip to a widget."""
        tip = None

        def _show(event):
            nonlocal tip
            if tip:
                return
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            lbl = tk.Label(tip, text=text, background="#ffffe0",
                           relief=tk.SOLID, borderwidth=1,
                           font=("TkDefaultFont", 9), wraplength=300,
                           justify=tk.LEFT)
            lbl.pack()

        def _hide(_event):
            nonlocal tip
            if tip:
                tip.destroy()
                tip = None

        widget.bind("<Enter>", _show)
        widget.bind("<Leave>", _hide)

    def _show_xml_editor(self, category):
        """Show XML platformConfig editor for a given category."""
        from ..option_maps import (
            extract_platform_xml, write_platform_config,
        )
        import xml.etree.ElementTree as ET

        prs = self.app.prs
        if not prs:
            return

        config = extract_platform_config(prs)
        if not config:
            return

        fields = XML_FIELDS_BY_CATEGORY.get(category, [])
        if not fields:
            return

        win = tk.Toplevel(self.app.root)
        win.title(category)
        win.transient(self.app.root)

        # Buttons at top
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=10, pady=(8, 4))

        # Scrollable field area
        container = ttk.Frame(win)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        canvas = tk.Canvas(container, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL,
                                  command=canvas.yview)
        field_frame = ttk.Frame(canvas)
        field_frame.bind("<Configure>",
                         lambda e: canvas.configure(
                             scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=field_frame, anchor="nw",
                             tags="field_frame")
        canvas.configure(yscrollcommand=scrollbar.set)
        # Make field_frame fill canvas width
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig("field_frame",
                                                width=e.width))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Mouse wheel scrolling (only when this window is focused)
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>",
                                              _on_mousewheel))
        canvas.bind("<Leave>",
                    lambda e: canvas.unbind_all("<MouseWheel>"))
        win.bind("<Destroy>",
                 lambda e: canvas.unbind_all("<MouseWheel>")
                 if e.widget == win else None)

        # Track widgets and dependent widget refs
        widgets = []       # (field_def, wtype, var, display_to_raw)
        dependent_widgets = []  # (widget_list, depends_on_attr)
        current_group = None
        master_vars = {}   # attribute -> BooleanVar

        grid_row = 0
        for field_def in fields:
            val = self._get_xml_field_value(config, field_def)
            if val is None:
                continue

            # Group separator
            if field_def.group and field_def.group != current_group:
                current_group = field_def.group
                sep = ttk.Frame(field_frame)
                sep.grid(row=grid_row, column=0, columnspan=2,
                         sticky="ew", pady=(10, 2), padx=4)
                ttk.Label(sep, text=current_group,
                          font=("TkDefaultFont", 9, "bold")).pack(
                    side=tk.LEFT)
                ttk.Separator(sep).pack(
                    side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
                grid_row += 1

            # Label
            lbl = ttk.Label(field_frame, text=field_def.display_name,
                            anchor=tk.W)
            lbl.grid(row=grid_row, column=0, sticky="w", padx=(8, 6),
                     pady=3)
            if field_def.description:
                self._add_tooltip(lbl, field_def.description)

            w_list = []  # widgets for dependency disabling

            if field_def.field_type == "onoff":
                var = tk.BooleanVar(value=(val == "ON"))
                cb = ttk.Checkbutton(field_frame, variable=var)
                cb.grid(row=grid_row, column=1, sticky="w", pady=3)
                w_list.append(cb)
                master_vars[field_def.attribute] = var
                widgets.append((field_def, 'onoff', var, None))

            elif field_def.field_type == "enum":
                dmap = field_def.display_map
                raw_vals = field_def.enum_values
                if dmap:
                    display_vals = [dmap.get(v, v) for v in raw_vals]
                    display_to_raw = dict(zip(display_vals, raw_vals))
                    raw_to_display = dict(zip(raw_vals, display_vals))
                    current_display = raw_to_display.get(val, val)
                else:
                    display_vals = raw_vals
                    display_to_raw = {v: v for v in raw_vals}
                    current_display = val

                var = tk.StringVar(value=current_display)
                combo = ttk.Combobox(field_frame, textvariable=var,
                                      values=display_vals,
                                      state="readonly", width=20)
                combo.grid(row=grid_row, column=1, sticky="w", pady=3)
                w_list.append(combo)
                widgets.append((field_def, 'enum', var, display_to_raw))

            elif field_def.field_type == "int":
                var = tk.StringVar(value=val)
                mn = field_def.min_val if field_def.min_val is not None else 0
                mx = field_def.max_val if field_def.max_val is not None else 999
                spin = ttk.Spinbox(field_frame, textvariable=var, width=8,
                                    from_=mn, to=mx)
                spin.grid(row=grid_row, column=1, sticky="w", pady=3)
                w_list.append(spin)

                def _clamp(var=var, mn=mn, mx=mx):
                    try:
                        v = int(var.get())
                        var.set(str(max(mn, min(mx, v))))
                    except ValueError:
                        var.set(str(mn))
                spin.bind("<FocusOut>", lambda e, f=_clamp: f())
                widgets.append((field_def, 'int', var, None))

            elif field_def.field_type == "string":
                var = tk.StringVar(value=val)
                entry = ttk.Entry(field_frame, textvariable=var, width=22)
                entry.grid(row=grid_row, column=1, sticky="w", pady=3)
                w_list.append(entry)
                widgets.append((field_def, 'string', var, None))

            if field_def.depends_on and w_list:
                dependent_widgets.append((w_list, field_def.depends_on))

            grid_row += 1

        # Column weights
        field_frame.columnconfigure(0, weight=0, minsize=160)
        field_frame.columnconfigure(1, weight=1)

        # Wire up dependency: disable widgets when master is OFF
        def _update_dependencies(*_args):
            for w_list, dep_attr in dependent_widgets:
                master = master_vars.get(dep_attr)
                state = "normal" if master and master.get() else "disabled"
                for w in w_list:
                    try:
                        w.configure(state=state)
                    except tk.TclError:
                        pass

        for attr, var in master_vars.items():
            var.trace_add("write", _update_dependencies)
        _update_dependencies()

        # Save / Cancel buttons
        def _save():
            xml_str = extract_platform_xml(prs)
            if not xml_str:
                return
            try:
                root = ET.fromstring(xml_str)
            except ET.ParseError:
                return

            for field_def, wtype, var, d2r in widgets:
                if wtype == 'onoff':
                    new_val = "ON" if var.get() else "OFF"
                elif wtype == 'enum':
                    dv = var.get()
                    new_val = d2r.get(dv, dv) if d2r else dv
                elif wtype == 'int':
                    try:
                        v = int(var.get())
                        mn = field_def.min_val or 0
                        mx = field_def.max_val or 999
                        new_val = str(max(mn, min(mx, v)))
                    except ValueError:
                        continue
                elif wtype == 'string':
                    new_val = var.get()
                else:
                    continue
                self._set_xml_field(root, field_def, new_val)

            new_xml = ET.tostring(root, encoding='unicode')
            write_platform_config(prs, new_xml)
            self.app.mark_modified()
            self.refresh()
            win.destroy()
            self.app.status_set(f"Saved {category}")

        ttk.Button(btn_frame, text="Save", command=_save,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Cancel", command=win.destroy,
                   width=10).pack(side=tk.RIGHT, padx=2)

        # Size window to fit content, with max height
        win.update_idletasks()
        w = max(420, field_frame.winfo_reqwidth() + 40)
        h = min(550, field_frame.winfo_reqheight() + btn_frame.winfo_reqheight() + 40)
        win.geometry(f"{w}x{h}")

    def _set_xml_field(self, root, field_def, value):
        """Set a value in the XML Element tree for a given XmlFieldDef."""
        elem_path = field_def.element

        if "microphone[@micType=" in elem_path:
            mic_type = "INTERNAL" if "INTERNAL" in elem_path else "EXTERNAL"
            audio = root.find("audioConfig")
            if audio is not None:
                for mic in audio.findall("microphone"):
                    if mic.get("micType") == mic_type:
                        mic.set(field_def.attribute, value)
                        return
        else:
            elem = root.find(elem_path)
            if elem is not None:
                elem.set(field_def.attribute, value)

    # ─── Prog Button / Short Menu Editors ──────────────────────────

    def _show_prog_button_editor(self):
        """Show editor for programmable buttons and switch functions."""
        from ..option_maps import (
            extract_platform_xml, write_platform_config,
            config_to_xml, BUTTON_FUNCTION_NAMES, SWITCH_FUNCTION_NAMES,
            BUTTON_NAME_DISPLAY,
        )
        import xml.etree.ElementTree as ET

        prs = self.app.prs
        if not prs:
            return

        config = extract_platform_config(prs)
        if not config or "progButtons" not in config:
            self.app.status_set("No programmable buttons in this personality")
            return

        prog = config["progButtons"]
        buttons = prog.get("progButton", [])
        if not isinstance(buttons, list):
            buttons = [buttons]

        acc_config = config.get("accessoryConfig", {})
        acc_wrap = acc_config.get("accessoryButtons", {})
        acc_btns = acc_wrap.get("accessoryButton", [])
        if not isinstance(acc_btns, list):
            acc_btns = [acc_btns]

        # Build function choices
        func_names = list(BUTTON_FUNCTION_NAMES.keys())
        func_display = [BUTTON_FUNCTION_NAMES.get(k, k) for k in func_names]
        func_d2r = dict(zip(func_display, func_names))

        switch_names = list(SWITCH_FUNCTION_NAMES.keys())
        switch_display = [SWITCH_FUNCTION_NAMES.get(k, k) for k in switch_names]
        switch_d2r = dict(zip(switch_display, switch_names))

        win = tk.Toplevel(self.app.root)
        win.title("Programmable Buttons")
        win.transient(self.app.root)

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=10, pady=(8, 4))

        field_frame = ttk.Frame(win)
        field_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        widgets = []  # (target, key, var, display_to_raw)
        row = 0

        # ── Switches section
        sep = ttk.Frame(field_frame)
        sep.grid(row=row, column=0, columnspan=2, sticky="ew",
                 pady=(6, 2), padx=4)
        ttk.Label(sep, text="Switches",
                  font=("TkDefaultFont", 9, "bold")).pack(side=tk.LEFT)
        ttk.Separator(sep).pack(side=tk.LEFT, fill=tk.X, expand=True,
                                padx=(6, 0))
        row += 1

        # 2-pos switch
        ttk.Label(field_frame, text="2-Position Switch",
                  anchor=tk.W).grid(row=row, column=0, sticky="w",
                                     padx=(8, 6), pady=3)
        cur_2pos = SWITCH_FUNCTION_NAMES.get(
            prog.get("_2PosFunction", ""), prog.get("_2PosFunction", ""))
        var_2pos = tk.StringVar(value=cur_2pos)
        combo = ttk.Combobox(field_frame, textvariable=var_2pos,
                              values=switch_display, state="readonly",
                              width=20)
        combo.grid(row=row, column=1, sticky="w", pady=3)
        widgets.append(("prog", "_2PosFunction", var_2pos, switch_d2r))
        row += 1

        # 3-pos switch
        ttk.Label(field_frame, text="3-Position Switch",
                  anchor=tk.W).grid(row=row, column=0, sticky="w",
                                     padx=(8, 6), pady=3)
        cur_3pos = SWITCH_FUNCTION_NAMES.get(
            prog.get("_3PosFunction", ""), prog.get("_3PosFunction", ""))
        var_3pos = tk.StringVar(value=cur_3pos)
        combo3 = ttk.Combobox(field_frame, textvariable=var_3pos,
                               values=switch_display, state="readonly",
                               width=20)
        combo3.grid(row=row, column=1, sticky="w", pady=3)
        widgets.append(("prog", "_3PosFunction", var_3pos, switch_d2r))
        row += 1

        # ── Side Buttons section
        sep2 = ttk.Frame(field_frame)
        sep2.grid(row=row, column=0, columnspan=2, sticky="ew",
                  pady=(10, 2), padx=4)
        ttk.Label(sep2, text="Side Buttons",
                  font=("TkDefaultFont", 9, "bold")).pack(side=tk.LEFT)
        ttk.Separator(sep2).pack(side=tk.LEFT, fill=tk.X, expand=True,
                                 padx=(6, 0))
        row += 1

        for btn in buttons:
            btn_name = btn.get("buttonName", "")
            display_name = BUTTON_NAME_DISPLAY.get(btn_name, btn_name)
            cur_func = BUTTON_FUNCTION_NAMES.get(
                btn.get("function", ""), btn.get("function", ""))

            ttk.Label(field_frame, text=display_name,
                      anchor=tk.W).grid(row=row, column=0, sticky="w",
                                         padx=(8, 6), pady=3)
            var = tk.StringVar(value=cur_func)
            combo_btn = ttk.Combobox(field_frame, textvariable=var,
                                      values=func_display, state="readonly",
                                      width=20)
            combo_btn.grid(row=row, column=1, sticky="w", pady=3)
            widgets.append(("button", btn_name, var, func_d2r))
            row += 1

        # ── Accessory Buttons section
        if acc_btns:
            sep3 = ttk.Frame(field_frame)
            sep3.grid(row=row, column=0, columnspan=2, sticky="ew",
                      pady=(10, 2), padx=4)
            ttk.Label(sep3, text="Accessory Buttons",
                      font=("TkDefaultFont", 9, "bold")).pack(
                side=tk.LEFT)
            ttk.Separator(sep3).pack(side=tk.LEFT, fill=tk.X,
                                     expand=True, padx=(6, 0))
            row += 1

            for btn in acc_btns:
                btn_name = btn.get("buttonName", "")
                display_name = BUTTON_NAME_DISPLAY.get(btn_name, btn_name)
                cur_func = BUTTON_FUNCTION_NAMES.get(
                    btn.get("function", ""), btn.get("function", ""))

                ttk.Label(field_frame, text=display_name,
                          anchor=tk.W).grid(row=row, column=0, sticky="w",
                                             padx=(8, 6), pady=3)
                var = tk.StringVar(value=cur_func)
                combo_acc = ttk.Combobox(field_frame, textvariable=var,
                                          values=func_display,
                                          state="readonly", width=20)
                combo_acc.grid(row=row, column=1, sticky="w", pady=3)
                widgets.append(("acc_button", btn_name, var, func_d2r))
                row += 1

        field_frame.columnconfigure(0, weight=0, minsize=160)
        field_frame.columnconfigure(1, weight=1)

        def _save():
            xml_str = extract_platform_xml(prs)
            if not xml_str:
                return
            try:
                root = ET.fromstring(xml_str)
            except ET.ParseError:
                return

            pb = root.find("progButtons")
            if pb is None:
                return

            for target, key, var, d2r in widgets:
                raw_val = d2r.get(var.get(), var.get()) if d2r else var.get()
                if target == "prog":
                    pb.set(key, raw_val)
                elif target == "button":
                    for child in pb.findall("progButton"):
                        if child.get("buttonName") == key:
                            child.set("function", raw_val)
                            break
                elif target == "acc_button":
                    acc_cfg = root.find("accessoryConfig")
                    if acc_cfg is not None:
                        acc_btns_elem = acc_cfg.find("accessoryButtons")
                        if acc_btns_elem is not None:
                            for child in acc_btns_elem.findall(
                                    "accessoryButton"):
                                if child.get("buttonName") == key:
                                    child.set("function", raw_val)
                                    break

            new_xml = ET.tostring(root, encoding='unicode')
            write_platform_config(prs, new_xml)
            self.app.mark_modified()
            self.refresh()
            win.destroy()
            self.app.status_set("Saved Programmable Buttons")

        ttk.Button(btn_frame, text="Save", command=_save,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Cancel", command=win.destroy,
                   width=10).pack(side=tk.RIGHT, padx=2)

        win.update_idletasks()
        w = max(420, field_frame.winfo_reqwidth() + 40)
        h = min(500, field_frame.winfo_reqheight()
                + btn_frame.winfo_reqheight() + 40)
        win.geometry(f"{w}x{h}")

    def _show_short_menu_editor(self):
        """Show editor for the 16 short menu slots."""
        from ..option_maps import (
            extract_platform_xml, write_platform_config,
            SHORT_MENU_NAMES,
        )
        import xml.etree.ElementTree as ET

        prs = self.app.prs
        if not prs:
            return

        config = extract_platform_config(prs)
        if not config or "shortMenu" not in config:
            self.app.status_set("No short menu in this personality")
            return

        menu = config["shortMenu"]
        items = menu.get("shortMenuItem", [])
        if not isinstance(items, list):
            items = [items]

        # Build choices
        menu_names = list(SHORT_MENU_NAMES.keys())
        menu_display = [SHORT_MENU_NAMES.get(k, k) for k in menu_names]
        menu_d2r = dict(zip(menu_display, menu_names))

        win = tk.Toplevel(self.app.root)
        win.title("Short Menu")
        win.transient(self.app.root)

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=10, pady=(8, 4))

        field_frame = ttk.Frame(win)
        field_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        widgets = []  # (position, var)

        for i, item in enumerate(items):
            pos = item.get("position", str(i))
            name = item.get("name", "empty")
            display = SHORT_MENU_NAMES.get(name, name)

            ttk.Label(field_frame, text=f"Slot {pos}",
                      anchor=tk.W).grid(row=i, column=0, sticky="w",
                                         padx=(8, 6), pady=2)
            var = tk.StringVar(value=display)
            combo = ttk.Combobox(field_frame, textvariable=var,
                                  values=menu_display, state="readonly",
                                  width=22)
            combo.grid(row=i, column=1, sticky="w", pady=2)
            widgets.append((pos, var))

        field_frame.columnconfigure(0, weight=0, minsize=80)
        field_frame.columnconfigure(1, weight=1)

        def _save():
            xml_str = extract_platform_xml(prs)
            if not xml_str:
                return
            try:
                root = ET.fromstring(xml_str)
            except ET.ParseError:
                return

            sm = root.find("shortMenu")
            if sm is None:
                return

            for pos, var in widgets:
                raw_val = menu_d2r.get(var.get(), var.get())
                for child in sm.findall("shortMenuItem"):
                    if child.get("position") == pos:
                        child.set("name", raw_val)
                        break

            new_xml = ET.tostring(root, encoding='unicode')
            write_platform_config(prs, new_xml)
            self.app.mark_modified()
            self.refresh()
            win.destroy()
            self.app.status_set("Saved Short Menu")

        ttk.Button(btn_frame, text="Save", command=_save,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Cancel", command=win.destroy,
                   width=10).pack(side=tk.RIGHT, padx=2)

        win.update_idletasks()
        w = max(350, field_frame.winfo_reqwidth() + 40)
        h = min(520, field_frame.winfo_reqheight()
                + btn_frame.winfo_reqheight() + 40)
        win.geometry(f"{w}x{h}")

    def _show_option_editor(self, class_name):
        """Show parsed option fields in an editor dialog."""
        from ..option_maps import write_field

        prs = self.app.prs
        if not prs:
            return

        sec = prs.get_section_by_class(class_name)
        if not sec:
            return

        opt_map = OPTION_MAPS.get(class_name)
        if not opt_map:
            return

        data = extract_section_data(sec)
        if data is None:
            return

        display = CLASS_DISPLAY_NAMES.get(class_name, class_name)
        win = tk.Toplevel(self.app.root)
        win.title(display)
        win.transient(self.app.root)

        # Buttons at top
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=10, pady=(8, 4))

        # Field area (grid layout, no scroll needed for small forms)
        field_frame = ttk.Frame(win)
        field_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        widgets = {}
        grid_row = 0
        for field_def in opt_map.fields:
            val = read_field(data, field_def)

            lbl = ttk.Label(field_frame, text=field_def.display_name,
                            anchor=tk.W)
            lbl.grid(row=grid_row, column=0, sticky="w", padx=(8, 6),
                     pady=3)
            if field_def.description:
                self._add_tooltip(lbl, field_def.description)

            if field_def.field_type == 'bool':
                var = tk.BooleanVar(value=bool(val))
                cb = ttk.Checkbutton(field_frame, variable=var)
                cb.grid(row=grid_row, column=1, sticky="w", pady=3)
                widgets[field_def.name] = ('bool', var, field_def)
            elif field_def.field_type == 'enum':
                var = tk.StringVar(value=str(val))
                values = list(field_def.enum_values.values())
                combo = ttk.Combobox(field_frame, textvariable=var,
                                      values=values,
                                      state="readonly", width=20)
                combo.grid(row=grid_row, column=1, sticky="w", pady=3)
                widgets[field_def.name] = ('enum', var, field_def)
            elif field_def.field_type in ('uint8', 'int8', 'uint16'):
                var = tk.StringVar(value=str(val))
                mn = field_def.min_val if field_def.min_val is not None else 0
                mx = field_def.max_val if field_def.max_val is not None else 255
                spin = ttk.Spinbox(field_frame, textvariable=var, width=8,
                                    from_=mn, to=mx)
                spin.grid(row=grid_row, column=1, sticky="w", pady=3)

                def _clamp(var=var, mn=mn, mx=mx):
                    try:
                        v = int(var.get())
                        var.set(str(max(mn, min(mx, v))))
                    except ValueError:
                        var.set(str(mn))
                spin.bind("<FocusOut>", lambda e, f=_clamp: f())
                widgets[field_def.name] = ('num', var, field_def)

            grid_row += 1

        field_frame.columnconfigure(0, weight=0, minsize=160)
        field_frame.columnconfigure(1, weight=1)

        def _save():
            new_data = bytearray(data)
            for name, (wtype, var, fdef) in widgets.items():
                if wtype == 'bool':
                    new_data = bytearray(write_field(
                        bytes(new_data), fdef, var.get()))
                elif wtype == 'enum':
                    new_data = bytearray(write_field(
                        bytes(new_data), fdef, var.get()))
                elif wtype == 'num':
                    try:
                        v = int(var.get())
                        mn = fdef.min_val if fdef.min_val is not None else 0
                        mx = fdef.max_val if fdef.max_val is not None else 255
                        v = max(mn, min(mx, v))
                    except ValueError:
                        continue
                    new_data = bytearray(write_field(
                        bytes(new_data), fdef, v))

            # Rebuild section raw bytes
            try:
                _, _, _, ds = parse_class_header(sec.raw, 0)
            except Exception as e:
                log_error("option_save", str(e))
                return
            new_raw = sec.raw[:ds] + bytes(new_data)
            from ..prs_parser import Section
            idx = prs.sections.index(sec)
            prs.sections[idx] = Section(
                offset=sec.offset, raw=new_raw,
                class_name=sec.class_name)

            self.app.mark_modified()
            self.refresh()
            win.destroy()
            self.app.status_set(f"Saved {display}")

        ttk.Button(btn_frame, text="Save", command=_save,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Cancel", command=win.destroy,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="View Hex",
                   command=lambda: self._show_hex_viewer(class_name),
                   width=10).pack(side=tk.LEFT, padx=2)

        # Size window to fit content
        win.update_idletasks()
        w = max(380, field_frame.winfo_reqwidth() + 40)
        h = field_frame.winfo_reqheight() + btn_frame.winfo_reqheight() + 40
        win.geometry(f"{w}x{h}")

    # ─── Encryption Settings Dialog ──────────────────────────────────

    def _encryption_dialog(self, set_name):
        """Show encryption settings for all talkgroups in a group set."""
        prs = self.app.prs
        if not prs:
            return

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return

        from ..injector import _parse_section_data, _replace_group_sections
        from ..injector import _get_header_bytes, _get_first_count

        try:
            byte1, byte2 = _get_header_bytes(grp_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25GroupSet")
            existing_sets = _parse_section_data(
                grp_sec, parse_group_section, first_count)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse groups:\n{e}")
            return

        target = None
        for gs in existing_sets:
            if gs.name == set_name:
                target = gs
                break
        if not target:
            messagebox.showwarning("Warning",
                                    f"Group set '{set_name}' not found.")
            return

        dlg = tk.Toplevel(self.app.root)
        dlg.title(f"Encryption Settings: {set_name}")
        dlg.transient(self.app.root)
        dlg.grab_set()
        dlg.resizable(True, True)

        main = ttk.Frame(dlg, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text=f"Encryption Settings: {set_name}",
                  font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 8))

        # Scrollable frame for talkgroups
        canvas = tk.Canvas(main, height=300)
        scrollbar = ttk.Scrollbar(main, orient=tk.VERTICAL,
                                   command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind("<Configure>",
                           lambda e: canvas.configure(
                               scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Header row
        hdr = ttk.Frame(scroll_frame)
        hdr.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(hdr, text="TG ID", width=8,
                  font=("Consolas", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(hdr, text="Name", width=10,
                  font=("Consolas", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(hdr, text="Encrypted", width=10,
                  font=("Consolas", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(hdr, text="Key ID", width=10,
                  font=("Consolas", 9, "bold")).pack(side=tk.LEFT)

        # One row per talkgroup
        enc_vars = []
        key_vars = []
        for grp in target.groups:
            row = ttk.Frame(scroll_frame)
            row.pack(fill=tk.X, pady=1)

            ttk.Label(row, text=str(grp.group_id), width=8,
                      font=("Consolas", 9)).pack(side=tk.LEFT)
            ttk.Label(row, text=grp.group_name, width=10,
                      font=("Consolas", 9)).pack(side=tk.LEFT)

            enc_var = tk.BooleanVar(value=grp.encrypted)
            ttk.Checkbutton(row, variable=enc_var).pack(side=tk.LEFT, padx=20)
            enc_vars.append(enc_var)

            key_var = tk.StringVar(value=str(grp.key_id))
            ttk.Entry(row, textvariable=key_var, width=10,
                      font=("Consolas", 9)).pack(side=tk.LEFT)
            key_vars.append(key_var)

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(12, 0))

        def _select_all():
            for v in enc_vars:
                v.set(True)

        def _deselect_all():
            for v in enc_vars:
                v.set(False)

        def _apply():
            try:
                self.app.save_undo_snapshot("Encryption settings")
                for i, grp in enumerate(target.groups):
                    grp.encrypted = enc_vars[i].get()
                    try:
                        grp.key_id = int(key_vars[i].get())
                    except ValueError:
                        grp.key_id = 0
                    if not grp.encrypted:
                        grp.key_id = 0

                _replace_group_sections(prs, existing_sets, byte1, byte2,
                                         set_byte1, set_byte2)
                self.app.mark_modified()
                self.refresh()
                n_enc = sum(1 for v in enc_vars if v.get())
                self.app.status_set(
                    f"Updated encryption: {n_enc}/{len(target.groups)} "
                    f"TGs encrypted in '{set_name}'")
                dlg.destroy()
            except Exception as e:
                messagebox.showerror("Error",
                                      f"Failed to apply:\n{e}")

        ttk.Button(btn_frame, text="Select All",
                   command=_select_all, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Deselect All",
                   command=_deselect_all, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Apply",
                   command=_apply, width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Cancel",
                   command=dlg.destroy, width=10).pack(side=tk.RIGHT, padx=2)

        dlg.bind("<Escape>", lambda e: dlg.destroy())

        # Center on parent
        dlg.update_idletasks()
        pw = self.app.root
        x = pw.winfo_x() + (pw.winfo_width() - dlg.winfo_width()) // 2
        y = pw.winfo_y() + (pw.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")

    # ─── NAC Editor Dialog ───────────────────────────────────────────

    def _edit_nac_dialog(self, set_name, ch_idx):
        """Show NAC editor for a P25 conventional channel."""
        prs = self.app.prs
        if not prs:
            return

        from ..record_types import (
            parse_p25_conv_channel_section,
            build_p25_conv_channel_section,
            build_p25_conv_set_section,
        )
        from ..injector import (
            _get_header_bytes, _get_first_count, _parse_section_data,
            _find_section_index,
        )

        ch_sec = prs.get_section_by_class("CP25ConvChannel")
        set_sec = prs.get_section_by_class("CP25ConvSet")
        if not ch_sec or not set_sec:
            return

        try:
            byte1, byte2 = _get_header_bytes(ch_sec)
            set_byte1, set_byte2 = _get_header_bytes(set_sec)
            first_count = _get_first_count(prs, "CP25ConvSet")
            existing_sets = _parse_section_data(
                ch_sec, parse_p25_conv_channel_section, first_count)
        except Exception as e:
            messagebox.showerror("Error",
                                  f"Failed to parse P25 conv:\n{e}")
            return

        target_ch = None
        for cset in existing_sets:
            if cset.name == set_name and ch_idx < len(cset.channels):
                target_ch = cset.channels[ch_idx]
                break
        if not target_ch:
            messagebox.showwarning("Warning", "Channel not found.")
            return

        dlg = tk.Toplevel(self.app.root)
        dlg.title(f"Edit NAC: {target_ch.short_name}")
        dlg.transient(self.app.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        main = ttk.Frame(dlg, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text=f"NAC for '{target_ch.short_name}' "
                  f"in '{set_name}'",
                  font=("", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))

        # Common NAC values
        nac_presets = {
            "293 (Default)": 0x293,
            "F7E (Repeater)": 0xF7E,
            "F7F (All/Any)": 0xF7F,
            "000 (None)": 0x000,
        }

        ttk.Label(main, text="NAC TX (hex, 0-FFF):").grid(
            row=1, column=0, sticky=tk.W, pady=2)
        nac_tx_var = tk.StringVar(value=f"{target_ch.nac_tx:03X}")
        ttk.Entry(main, textvariable=nac_tx_var, width=8,
                  font=("Consolas", 10)).grid(
            row=1, column=1, sticky=tk.W, padx=4)

        ttk.Label(main, text="NAC RX (hex, 0-FFF):").grid(
            row=2, column=0, sticky=tk.W, pady=2)
        nac_rx_var = tk.StringVar(value=f"{target_ch.nac_rx:03X}")
        ttk.Entry(main, textvariable=nac_rx_var, width=8,
                  font=("Consolas", 10)).grid(
            row=2, column=1, sticky=tk.W, padx=4)

        ttk.Label(main, text="Common values:").grid(
            row=3, column=0, sticky=tk.W, pady=(8, 2))
        preset_var = tk.StringVar()
        combo = ttk.Combobox(main, textvariable=preset_var,
                              values=list(nac_presets.keys()),
                              state="readonly", width=16)
        combo.grid(row=3, column=1, sticky=tk.W, padx=4, pady=(8, 2))

        def _apply_preset(event=None):
            key = preset_var.get()
            if key in nac_presets:
                val = f"{nac_presets[key]:03X}"
                nac_tx_var.set(val)
                nac_rx_var.set(val)

        combo.bind("<<ComboboxSelected>>", _apply_preset)

        result = [False]

        def _save():
            try:
                tx_val = int(nac_tx_var.get(), 16)
                rx_val = int(nac_rx_var.get(), 16)
            except ValueError:
                messagebox.showwarning("Warning",
                                        "NAC must be a hex value (0-FFF).",
                                        parent=dlg)
                return
            if tx_val < 0 or tx_val > 0xFFF or rx_val < 0 or rx_val > 0xFFF:
                messagebox.showwarning("Warning",
                                        "NAC must be 0-FFF (hex).",
                                        parent=dlg)
                return

            target_ch.nac_tx = tx_val
            target_ch.nac_rx = rx_val
            result[0] = True
            dlg.destroy()

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn_frame, text="Save", command=_save,
                   width=10).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy,
                   width=10).pack(side=tk.RIGHT)

        dlg.bind("<Return>", lambda e: _save())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        # Center on parent
        dlg.update_idletasks()
        pw = self.app.root
        x = pw.winfo_x() + (pw.winfo_width() - dlg.winfo_width()) // 2
        y = pw.winfo_y() + (pw.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.wait_window()

        if result[0]:
            try:
                from ..prs_parser import Section
                self.app.save_undo_snapshot("Edit NAC")
                new_ch_raw = build_p25_conv_channel_section(
                    existing_sets, byte1, byte2)
                new_set_raw = build_p25_conv_set_section(
                    len(existing_sets[0].channels), set_byte1, set_byte2)

                ch_idx_sec = _find_section_index(prs, "CP25ConvChannel")
                set_idx = _find_section_index(prs, "CP25ConvSet")
                prs.sections[ch_idx_sec] = Section(
                    offset=0, raw=new_ch_raw,
                    class_name="CP25ConvChannel")
                prs.sections[set_idx] = Section(
                    offset=0, raw=new_set_raw,
                    class_name="CP25ConvSet")

                self.app.mark_modified()
                self.refresh()
                self.app.status_set(
                    f"Updated NAC on '{target_ch.short_name}' "
                    f"(TX:{nac_tx_var.get()} RX:{nac_rx_var.get()})")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save:\n{e}")

    # ─── Scan Priority Dialog ────────────────────────────────────────

    def _scan_priority_dialog(self):
        """Show scan priority editor for preferred system table entries."""
        prs = self.app.prs
        if not prs:
            return

        from ..injector import get_preferred_entries, reorder_preferred_entries

        entries, iden, chain = get_preferred_entries(prs)
        if not entries:
            messagebox.showinfo("Info", "No preferred system entries found.")
            return

        # Try to resolve system IDs to names
        sys_names = {}
        for sec in prs.sections:
            if sec.class_name in ('CP25TrkSystem', 'CConvSystem',
                                   'CP25ConvSystem'):
                sname = parse_system_short_name(sec.raw)
                # Check if this system's config data has a matching sysid
                # in the group sets
                if sname:
                    sys_names[sname] = sec.class_name

        dlg = tk.Toplevel(self.app.root)
        dlg.title("Scan Priority")
        dlg.transient(self.app.root)
        dlg.grab_set()
        dlg.resizable(False, True)

        main = ttk.Frame(dlg, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="Scan Priority Order",
                  font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 8))
        ttk.Label(main, text="Systems scanned in order from top to bottom.",
                  font=("", 9)).pack(anchor=tk.W, pady=(0, 8))

        # Listbox with entries
        list_frame = ttk.Frame(main)
        list_frame.pack(fill=tk.BOTH, expand=True)

        listbox = tk.Listbox(list_frame, font=("Consolas", 10),
                              height=min(len(entries) + 2, 15),
                              selectmode=tk.SINGLE, width=45)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lb_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                    command=listbox.yview)
        lb_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.configure(yscrollcommand=lb_scroll.set)

        # Track entry order
        order = list(range(len(entries)))

        def _refresh_list():
            listbox.delete(0, tk.END)
            for idx, i in enumerate(order):
                e = entries[i]
                type_str = {3: "P25 Trunk", 4: "Conv"}.get(
                    e.entry_type, f"Type{e.entry_type}")
                listbox.insert(tk.END,
                    f"  {idx + 1}. SysID {e.system_id:5d}  "
                    f"[{type_str}]  pri={e.field1}")

        _refresh_list()

        # Up/Down buttons
        btn_frame_lr = ttk.Frame(main)
        btn_frame_lr.pack(fill=tk.X, pady=(8, 0))

        def _move_up():
            sel = listbox.curselection()
            if not sel or sel[0] == 0:
                return
            idx = sel[0]
            order[idx], order[idx - 1] = order[idx - 1], order[idx]
            _refresh_list()
            listbox.selection_set(idx - 1)

        def _move_down():
            sel = listbox.curselection()
            if not sel or sel[0] >= len(order) - 1:
                return
            idx = sel[0]
            order[idx], order[idx + 1] = order[idx + 1], order[idx]
            _refresh_list()
            listbox.selection_set(idx + 1)

        ttk.Button(btn_frame_lr, text="Move Up",
                   command=_move_up, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame_lr, text="Move Down",
                   command=_move_down, width=10).pack(side=tk.LEFT, padx=2)

        def _apply():
            try:
                new_sysid_order = [entries[i].system_id for i in order]
                self.app.save_undo_snapshot("Reorder scan priority")
                reorder_preferred_entries(prs, new_sysid_order)
                self.app.mark_modified()
                self.refresh()
                self.app.status_set(
                    f"Reordered {len(entries)} scan priority entries")
                dlg.destroy()
            except Exception as e:
                messagebox.showerror("Error",
                                      f"Failed to reorder:\n{e}")

        btn_frame_action = ttk.Frame(main)
        btn_frame_action.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(btn_frame_action, text="Apply",
                   command=_apply, width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame_action, text="Cancel",
                   command=dlg.destroy, width=10).pack(side=tk.RIGHT, padx=2)

        dlg.bind("<Escape>", lambda e: dlg.destroy())

        # Center on parent
        dlg.update_idletasks()
        pw = self.app.root
        x = pw.winfo_x() + (pw.winfo_width() - dlg.winfo_width()) // 2
        y = pw.winfo_y() + (pw.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")

    def _show_hex_viewer(self, class_name):
        """Show raw hex dump of a section using the enhanced HexViewer."""
        prs = self.app.prs
        if not prs:
            return

        sec = prs.get_section_by_class(class_name)
        if not sec:
            return

        display = CLASS_DISPLAY_NAMES.get(class_name, class_name)
        title = f"Hex Viewer — {display} ({len(sec.raw)} bytes)"

        from .hex_viewer import HexViewer
        HexViewer(self.app.root, sec.raw, title=title,
                  offset_in_file=sec.offset)

    def _show_hex_viewer_raw(self, data, title="Hex Viewer",
                             file_offset=0):
        """Show hex viewer for arbitrary raw data."""
        from .hex_viewer import HexViewer
        HexViewer(self.app.root, data, title=title,
                  offset_in_file=file_offset)

    def _copy_hex(self, data):
        """Copy raw hex to clipboard."""
        self.clipboard_clear()
        self.clipboard_append(data.hex())
        self.app.status_set(f"Copied {len(data)} bytes as hex")
