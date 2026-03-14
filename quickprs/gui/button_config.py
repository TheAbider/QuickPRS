"""Programmable Button Configurator dialog.

Unified dialog for editing XG-100P programmable buttons, position switches,
and short menu slots. Reads from and writes to the platformConfig XML
embedded in the PRS file.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import xml.etree.ElementTree as ET

from ..option_maps import (
    extract_platform_config, extract_platform_xml, write_platform_config,
    _create_default_platform_xml, _inject_platform_xml,
    BUTTON_FUNCTION_NAMES, BUTTON_NAME_DISPLAY,
    SHORT_MENU_NAMES, SWITCH_FUNCTION_NAMES,
    format_button_function, format_button_name,
    format_short_menu_name, format_switch_function,
)


class ButtonConfigurator(tk.Toplevel):
    """Unified programmable button, switch, and short menu editor."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Programmable Button Configurator")
        self.transient(parent)
        self.resizable(True, True)

        self._widgets = []  # (target, key, var, display_to_raw)
        self._menu_widgets = []  # (position, var)

        # Build lookup tables
        self._func_names = list(BUTTON_FUNCTION_NAMES.keys())
        self._func_display = [BUTTON_FUNCTION_NAMES[k] for k in self._func_names]
        self._func_d2r = dict(zip(self._func_display, self._func_names))

        self._switch_names = list(SWITCH_FUNCTION_NAMES.keys())
        self._switch_display = [SWITCH_FUNCTION_NAMES[k]
                                for k in self._switch_names]
        self._switch_d2r = dict(zip(self._switch_display, self._switch_names))

        self._menu_names = list(SHORT_MENU_NAMES.keys())
        self._menu_display = [SHORT_MENU_NAMES[k] for k in self._menu_names]
        self._menu_d2r = dict(zip(self._menu_display, self._menu_names))

        self._build_ui()

    def _ensure_platform_config(self):
        """Ensure platformConfig XML exists. Returns config dict or None."""
        prs = self.app.prs
        xml_str = extract_platform_xml(prs)
        if xml_str is None:
            if messagebox.askyesno(
                    "No Platform Config",
                    "This personality has no platformConfig XML.\n"
                    "Create a default one?",
                    parent=self):
                try:
                    default_xml = _create_default_platform_xml()
                    if not _inject_platform_xml(prs, default_xml):
                        messagebox.showerror(
                            "Error",
                            "Failed to create platform config.",
                            parent=self)
                        return None
                    self.app.mark_modified()
                except Exception as e:
                    messagebox.showerror("Error",
                                         f"Failed to create config:\n{e}",
                                         parent=self)
                    return None
            else:
                return None

        return extract_platform_config(prs)

    def _build_ui(self):
        """Build the full configurator UI."""
        config = self._ensure_platform_config()
        if config is None:
            self.destroy()
            return

        prog = config.get("progButtons", {})
        buttons = prog.get("progButton", [])
        if isinstance(buttons, dict):
            buttons = [buttons]

        acc_config = config.get("accessoryConfig", {})
        acc_wrap = acc_config.get("accessoryButtons", {})
        acc_btns = acc_wrap.get("accessoryButton", [])
        if isinstance(acc_btns, dict):
            acc_btns = [acc_btns]

        menu_config = config.get("shortMenu", {})
        menu_items = menu_config.get("shortMenuItem", [])
        if isinstance(menu_items, dict):
            menu_items = [menu_items]

        # ── Header
        header = ttk.Frame(self, padding=(12, 8))
        header.pack(fill=tk.X)
        ttk.Label(header, text="Programmable Button Configurator",
                  font=("", 11, "bold")).pack(anchor=tk.W)

        # ── Scrollable content area
        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True, padx=4)

        canvas = tk.Canvas(container, highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient=tk.VERTICAL,
                            command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = ttk.Frame(canvas, padding=(8, 4))
        canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        row = 0

        # ── Side Buttons section
        row = self._add_section_header(inner, "Side Buttons", row)
        for btn in buttons:
            btn_name = btn.get("buttonName", "")
            display_name = BUTTON_NAME_DISPLAY.get(btn_name, btn_name)
            cur_func = BUTTON_FUNCTION_NAMES.get(
                btn.get("function", ""), btn.get("function", ""))

            row = self._add_combo_row(
                inner, row, display_name, cur_func,
                self._func_display, "button", btn_name, self._func_d2r)

        # ── Accessory Buttons section (if present)
        if acc_btns:
            row = self._add_section_header(inner, "Accessory Buttons", row)
            for btn in acc_btns:
                btn_name = btn.get("buttonName", "")
                display_name = BUTTON_NAME_DISPLAY.get(btn_name, btn_name)
                cur_func = BUTTON_FUNCTION_NAMES.get(
                    btn.get("function", ""), btn.get("function", ""))

                row = self._add_combo_row(
                    inner, row, display_name, cur_func,
                    self._func_display, "acc_button", btn_name,
                    self._func_d2r)

        # ── 2-Position Switch section
        row = self._add_section_header(inner, "2-Position Switch", row)
        cur_2pos = SWITCH_FUNCTION_NAMES.get(
            prog.get("_2PosFunction", ""), prog.get("_2PosFunction", ""))
        row = self._add_combo_row(
            inner, row, "Function", cur_2pos,
            self._switch_display, "prog", "_2PosFunction", self._switch_d2r)

        # 2-pos values
        val_2a = prog.get("_2PosAValue", "")
        row = self._add_entry_row(
            inner, row, "A Value", val_2a, "prog_val", "_2PosAValue")
        val_2b = prog.get("_2PosBValue", "")
        row = self._add_entry_row(
            inner, row, "B Value", val_2b, "prog_val", "_2PosBValue")

        # ── 3-Position Switch section
        row = self._add_section_header(inner, "3-Position Switch", row)
        cur_3pos = SWITCH_FUNCTION_NAMES.get(
            prog.get("_3PosFunction", ""), prog.get("_3PosFunction", ""))
        row = self._add_combo_row(
            inner, row, "Function", cur_3pos,
            self._switch_display, "prog", "_3PosFunction", self._switch_d2r)

        # 3-pos values
        for pos_letter, label in [("A", "A Value"), ("B", "B Value"),
                                  ("C", "C Value")]:
            val = prog.get(f"_3Pos{pos_letter}Value", "")
            row = self._add_entry_row(
                inner, row, label, val,
                "prog_val", f"_3Pos{pos_letter}Value")

        # ── Short Menu section
        if menu_items:
            row = self._add_section_header(inner, "Short Menu (16 slots)", row)
            for i, item in enumerate(menu_items):
                pos = item.get("position", str(i))
                name = item.get("name", "empty")
                display = SHORT_MENU_NAMES.get(name, name)

                ttk.Label(inner, text=f"Slot {pos}",
                          anchor=tk.W).grid(row=row, column=0, sticky="w",
                                            padx=(8, 6), pady=2)
                var = tk.StringVar(value=display)
                combo = ttk.Combobox(inner, textvariable=var,
                                     values=self._menu_display,
                                     state="readonly", width=22)
                combo.grid(row=row, column=1, sticky="w", pady=2)
                self._menu_widgets.append((pos, var))
                row += 1

        inner.columnconfigure(0, weight=0, minsize=160)
        inner.columnconfigure(1, weight=1)

        # Update scroll region
        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # ── Button bar
        btn_frame = ttk.Frame(self, padding=(8, 8))
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="Apply", command=self._apply,
                   width=10).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy,
                   width=10).pack(side=tk.RIGHT, padx=4)

        # Size the window
        self.update_idletasks()
        w = max(480, inner.winfo_reqwidth() + 50)
        h = min(650, inner.winfo_reqheight() + 100)
        self.geometry(f"{w}x{h}")
        self.grab_set()

    def _add_section_header(self, parent, text, row):
        """Add a section header with separator line."""
        sep = ttk.Frame(parent)
        sep.grid(row=row, column=0, columnspan=2, sticky="ew",
                 pady=(10, 2), padx=4)
        ttk.Label(sep, text=text,
                  font=("TkDefaultFont", 9, "bold")).pack(side=tk.LEFT)
        ttk.Separator(sep).pack(side=tk.LEFT, fill=tk.X, expand=True,
                                padx=(6, 0))
        return row + 1

    def _add_combo_row(self, parent, row, label, current_value,
                       values, target, key, d2r):
        """Add a label + combobox row and register in _widgets."""
        ttk.Label(parent, text=label,
                  anchor=tk.W).grid(row=row, column=0, sticky="w",
                                    padx=(8, 6), pady=3)
        var = tk.StringVar(value=current_value)
        combo = ttk.Combobox(parent, textvariable=var,
                             values=values, state="readonly", width=22)
        combo.grid(row=row, column=1, sticky="w", pady=3)
        self._widgets.append((target, key, var, d2r))
        return row + 1

    def _add_entry_row(self, parent, row, label, current_value,
                       target, key):
        """Add a label + entry row and register in _widgets."""
        ttk.Label(parent, text=label,
                  anchor=tk.W).grid(row=row, column=0, sticky="w",
                                    padx=(8, 6), pady=3)
        var = tk.StringVar(value=current_value)
        entry = ttk.Entry(parent, textvariable=var, width=24)
        entry.grid(row=row, column=1, sticky="w", pady=3)
        self._widgets.append((target, key, var, None))
        return row + 1

    def _apply(self):
        """Write all changes back to the PRS file's XML."""
        prs = self.app.prs
        xml_str = extract_platform_xml(prs)
        if not xml_str:
            messagebox.showerror("Error", "No platform config found.",
                                 parent=self)
            return

        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as e:
            messagebox.showerror("Error", f"XML parse error:\n{e}",
                                 parent=self)
            return

        self.app.save_undo_snapshot("Edit buttons/menu")

        pb = root.find("progButtons")

        for target, key, var, d2r in self._widgets:
            raw_val = d2r.get(var.get(), var.get()) if d2r else var.get()

            if target == "prog":
                if pb is not None:
                    pb.set(key, raw_val)
            elif target == "prog_val":
                if pb is not None:
                    pb.set(key, raw_val)
            elif target == "button":
                if pb is not None:
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

        # Short menu
        sm = root.find("shortMenu")
        if sm is not None:
            for pos, var in self._menu_widgets:
                raw_val = self._menu_d2r.get(var.get(), var.get())
                for child in sm.findall("shortMenuItem"):
                    if child.get("position") == pos:
                        child.set("name", raw_val)
                        break

        new_xml = ET.tostring(root, encoding='unicode')
        if write_platform_config(prs, new_xml):
            self.app.mark_modified()
            if hasattr(self.app, 'personality_view'):
                self.app.personality_view.refresh()
            self.app.status_set("Button configuration saved")
            self.destroy()
        else:
            messagebox.showerror("Error",
                                 "Failed to write config back to PRS.",
                                 parent=self)
