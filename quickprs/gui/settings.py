"""Settings dialog — user preferences for QuickPRS.

Stores defaults for injection (home unit ID, system options),
auto-backup behavior, and display preferences.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import logging
from pathlib import Path

# Settings file location (next to executable or in user's home)
SETTINGS_DIR = Path.home() / ".quickprs"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULTS = {
    # Injection defaults
    "home_unit_id": 0,
    "default_nac": 0,
    "max_scan_talkgroups": 127,
    "scan_enabled_default": True,
    "tx_enabled_default": False,

    # P25 system defaults (NAS monitoring optimized)
    "roaming_mode": "enhanced_cc",     # fixed / dynamic / enhanced_cc
    "power_level": "low",              # low / high / max
    "encryption_type": "unencrypted",  # unencrypted / des / aes
    "auto_registration": "never",      # never / system
    "linear_simulcast": True,
    "tdma_capable": True,
    "adaptive_filter": True,
    "refresh_proscan_adj": True,
    "avoid_failsoft": False,
    "cc_tx_request": False,
    "vdoc_capable": False,
    "wb_filter": False,
    "confirmed_tx": False,
    "emer_disp": False,
    "emer_audio": False,
    "emer_user_only": False,
    "send_emer_alarm": False,
    "vr_activation": False,
    "keyback_on_ann": False,
    "link_layer_auth": False,
    "authenticate_fne": False,

    # Behavior
    "auto_backup": True,
    "auto_validate": True,
    "last_open_dir": "",
    "last_export_dir": "",
    "window_width": 1400,
    "window_height": 850,
    "recent_files": [],
}

MAX_RECENT_FILES = 10


def load_settings():
    """Load settings from disk, returning defaults for missing keys."""
    settings = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            settings.update(saved)
        except Exception as e:
            logging.getLogger("quickprs").warning(
                "Failed to load settings: %s", e)
    return settings


def save_settings(settings):
    """Save settings to disk."""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2)


def add_recent_file(settings, path):
    """Add a file path to the recent files list (most recent first)."""
    path_str = str(path)
    recent = settings.get("recent_files", [])
    # Remove if already present (to move to top)
    recent = [p for p in recent if p != path_str]
    recent.insert(0, path_str)
    settings["recent_files"] = recent[:MAX_RECENT_FILES]
    save_settings(settings)


def get_recent_files(settings):
    """Return list of recent file paths (most recent first), filtered to existing."""
    recent = settings.get("recent_files", [])
    return [p for p in recent if Path(p).exists()]


class SettingsDialog:
    """Modal settings dialog."""

    def __init__(self, parent, app):
        self.app = app
        self.settings = load_settings()
        self.result = None

        self.win = tk.Toplevel(parent)
        self.win.title("QuickPRS Settings")
        self.win.geometry("520x580")
        self.win.transient(parent)
        self.win.grab_set()
        self.win.resizable(False, False)

        self._build_ui()
        self.win.wait_window()

    def _build_ui(self):
        nb = ttk.Notebook(self.win)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

        # Injection defaults tab
        inj_frame = ttk.Frame(nb, padding=12)
        self._build_injection_tab(inj_frame)
        nb.add(inj_frame, text="Injection")

        # P25 System tab
        p25_frame = ttk.Frame(nb, padding=8)
        self._build_p25_tab(p25_frame)
        nb.add(p25_frame, text="P25 System")

        # Behavior tab
        beh_frame = ttk.Frame(nb, padding=12)
        self._build_behavior_tab(beh_frame)
        nb.add(beh_frame, text="Behavior")

        # Buttons
        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(btn_frame, text="Save", command=self._save,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Cancel", command=self.win.destroy,
                   width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Reset Defaults",
                   command=self._reset, width=14).pack(side=tk.LEFT, padx=2)

    def _build_injection_tab(self, parent):
        """Injection defaults."""
        # Home Unit ID
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Home Unit ID:", width=20,
                  anchor=tk.W).pack(side=tk.LEFT)
        self.home_unit_var = tk.StringVar(
            value=str(self.settings["home_unit_id"]))
        ttk.Entry(row, textvariable=self.home_unit_var,
                  width=15).pack(side=tk.LEFT, padx=4)
        ttk.Label(row, text="(0 = radio default)",
                  foreground="gray").pack(side=tk.LEFT)

        # Default NAC
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Default NAC:", width=20,
                  anchor=tk.W).pack(side=tk.LEFT)
        self.nac_var = tk.StringVar(
            value=str(self.settings["default_nac"]))
        ttk.Entry(row, textvariable=self.nac_var,
                  width=15).pack(side=tk.LEFT, padx=4)
        ttk.Label(row, text="(0 = default)",
                  foreground="gray").pack(side=tk.LEFT)

        # Max scan TGs
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Max Scan TGs/Set:", width=20,
                  anchor=tk.W).pack(side=tk.LEFT)
        self.max_scan_var = tk.StringVar(
            value=str(self.settings["max_scan_talkgroups"]))
        ttk.Entry(row, textvariable=self.max_scan_var,
                  width=15).pack(side=tk.LEFT, padx=4)
        ttk.Label(row, text="(128 breaks scanning)",
                  foreground="gray").pack(side=tk.LEFT)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(
            fill=tk.X, pady=8)

        # Checkboxes
        self.scan_default_var = tk.BooleanVar(
            value=self.settings["scan_enabled_default"])
        ttk.Checkbutton(parent, text="Enable Scan by default for new TGs",
                        variable=self.scan_default_var).pack(
                            anchor=tk.W, pady=2)

        self.tx_default_var = tk.BooleanVar(
            value=self.settings["tx_enabled_default"])
        ttk.Checkbutton(parent, text="Enable TX by default for new TGs",
                        variable=self.tx_default_var).pack(
                            anchor=tk.W, pady=2)

    def _build_p25_tab(self, parent):
        """P25 trunked system defaults — maps to RPM System Setup dialog."""
        # Use a canvas for scrolling if needed
        canvas = tk.Canvas(parent, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        def _wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _wheel)
        inner.bind("<MouseWheel>", _wheel)

        # ── Roaming ──
        roaming_lf = ttk.LabelFrame(inner, text="Roaming", padding=4)
        roaming_lf.pack(fill=tk.X, pady=(0, 4))

        self.roaming_var = tk.StringVar(
            value=self.settings.get("roaming_mode", "enhanced_cc"))
        for val, label in [("fixed", "Fixed ProScan"),
                           ("dynamic", "Dynamic ProScan"),
                           ("enhanced_cc", "Enhanced CC (Recommended)")]:
            ttk.Radiobutton(roaming_lf, text=label, variable=self.roaming_var,
                            value=val).pack(anchor=tk.W, padx=4)

        # ── Power & Encryption ──
        pe_frame = ttk.Frame(inner)
        pe_frame.pack(fill=tk.X, pady=(0, 4))

        power_lf = ttk.LabelFrame(pe_frame, text="Power", padding=4)
        power_lf.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.power_var = tk.StringVar(
            value=self.settings.get("power_level", "low"))
        for val, label in [("low", "Low"), ("high", "High"), ("max", "Max")]:
            ttk.Radiobutton(power_lf, text=label, variable=self.power_var,
                            value=val).pack(side=tk.LEFT, padx=4)

        enc_lf = ttk.LabelFrame(pe_frame, text="Encryption", padding=4)
        enc_lf.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.enc_type_var = tk.StringVar(
            value=self.settings.get("encryption_type", "unencrypted"))
        for val, label in [("unencrypted", "Unencrypted"),
                           ("des", "DES"), ("aes", "AES")]:
            ttk.Radiobutton(enc_lf, text=label, variable=self.enc_type_var,
                            value=val).pack(side=tk.LEFT, padx=4)

        # ── Auto Registration ──
        reg_lf = ttk.LabelFrame(inner, text="Auto Registration", padding=4)
        reg_lf.pack(fill=tk.X, pady=(0, 4))
        self.auto_reg_var = tk.StringVar(
            value=self.settings.get("auto_registration", "never"))
        for val, label in [("never", "Never (Recommended)"),
                           ("system", "System Determined")]:
            ttk.Radiobutton(reg_lf, text=label, variable=self.auto_reg_var,
                            value=val).pack(side=tk.LEFT, padx=4)

        # ── Critical Options ──
        crit_lf = ttk.LabelFrame(
            inner, text="System Options (checked = ON)", padding=4)
        crit_lf.pack(fill=tk.X, pady=(0, 4))

        self.p25_bool_vars = {}
        crit_opts = [
            ("linear_simulcast", "Linear Simulcast"),
            ("tdma_capable", "TDMA Capable (Phase II)"),
            ("adaptive_filter", "Adaptive Filter"),
            ("refresh_proscan_adj", "Refresh ProScan Adjacency List"),
        ]
        for key, label in crit_opts:
            var = tk.BooleanVar(value=self.settings.get(key, DEFAULTS[key]))
            self.p25_bool_vars[key] = var
            ttk.Checkbutton(crit_lf, text=label, variable=var).pack(
                anchor=tk.W, padx=4, pady=1)

        # ── TX/Control Options (usually OFF for NAS) ──
        tx_lf = ttk.LabelFrame(
            inner, text="TX/Control (OFF for listen-only)", padding=4)
        tx_lf.pack(fill=tk.X, pady=(0, 4))

        tx_opts = [
            ("cc_tx_request", "CC TX Request"),
            ("confirmed_tx", "Confirmed TX"),
            ("vdoc_capable", "VDOC Capable"),
        ]
        for key, label in tx_opts:
            var = tk.BooleanVar(value=self.settings.get(key, DEFAULTS[key]))
            self.p25_bool_vars[key] = var
            ttk.Checkbutton(tx_lf, text=label, variable=var).pack(
                anchor=tk.W, padx=4, pady=1)

        # ── Misc Options ──
        misc_lf = ttk.LabelFrame(inner, text="Misc Options", padding=4)
        misc_lf.pack(fill=tk.X, pady=(0, 4))

        misc_opts = [
            ("avoid_failsoft", "Avoid Failsoft"),
            ("wb_filter", "WB Filter"),
            ("emer_disp", "Emergency Display"),
            ("emer_audio", "Emergency Audio"),
            ("emer_user_only", "Emer User Only Clear"),
            ("send_emer_alarm", "Send Emergency Alarm"),
            ("vr_activation", "VR Activation"),
            ("keyback_on_ann", "Keyback On Announcement"),
        ]
        # Pack in 2 columns
        row_frame = None
        for i, (key, label) in enumerate(misc_opts):
            if i % 2 == 0:
                row_frame = ttk.Frame(misc_lf)
                row_frame.pack(fill=tk.X, pady=1)
            var = tk.BooleanVar(value=self.settings.get(key, DEFAULTS[key]))
            self.p25_bool_vars[key] = var
            ttk.Checkbutton(row_frame, text=label, variable=var,
                            width=28).pack(side=tk.LEFT, padx=4)

        # ── Link Layer Auth ──
        auth_lf = ttk.LabelFrame(
            inner, text="Link Layer Authentication", padding=4)
        auth_lf.pack(fill=tk.X, pady=(0, 4))

        auth_opts = [
            ("link_layer_auth", "Enable"),
            ("authenticate_fne", "Authenticate FNE"),
        ]
        for key, label in auth_opts:
            var = tk.BooleanVar(value=self.settings.get(key, DEFAULTS[key]))
            self.p25_bool_vars[key] = var
            ttk.Checkbutton(auth_lf, text=label, variable=var).pack(
                side=tk.LEFT, padx=4)

    def _build_behavior_tab(self, parent):
        """Application behavior settings."""
        self.auto_backup_var = tk.BooleanVar(
            value=self.settings["auto_backup"])
        ttk.Checkbutton(parent, text="Auto-backup before saving (.prs.bak)",
                        variable=self.auto_backup_var).pack(
                            anchor=tk.W, pady=4)

        self.auto_validate_var = tk.BooleanVar(
            value=self.settings["auto_validate"])
        ttk.Checkbutton(parent, text="Auto-validate after injection",
                        variable=self.auto_validate_var).pack(
                            anchor=tk.W, pady=4)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(
            fill=tk.X, pady=8)

        info = ttk.Label(
            parent,
            text=(f"Settings stored in:\n{SETTINGS_FILE}\n\n"
                  "These defaults are used when creating new systems\n"
                  "via Import or API. They do not affect existing\n"
                  "systems already in a .PRS file."),
            foreground="gray",
            justify=tk.LEFT)
        info.pack(anchor=tk.W, pady=4)

    def _save(self):
        """Validate and save settings."""
        try:
            home_id = int(self.home_unit_var.get())
            if home_id < 0:
                raise ValueError("negative")
        except ValueError:
            messagebox.showerror("Error", "Home Unit ID must be a number >= 0")
            return

        try:
            nac = int(self.nac_var.get())
            if nac < 0 or nac > 0xFFF:
                raise ValueError("out of range")
        except ValueError:
            messagebox.showerror("Error", "NAC must be 0-4095")
            return

        try:
            max_scan = int(self.max_scan_var.get())
            if max_scan < 1 or max_scan > 1024:
                raise ValueError("out of range")
        except ValueError:
            messagebox.showerror("Error", "Max Scan TGs must be 1-1024")
            return

        self.settings["home_unit_id"] = home_id
        self.settings["default_nac"] = nac
        self.settings["max_scan_talkgroups"] = max_scan
        self.settings["scan_enabled_default"] = self.scan_default_var.get()
        self.settings["tx_enabled_default"] = self.tx_default_var.get()
        self.settings["auto_backup"] = self.auto_backup_var.get()
        self.settings["auto_validate"] = self.auto_validate_var.get()

        # P25 system settings
        self.settings["roaming_mode"] = self.roaming_var.get()
        self.settings["power_level"] = self.power_var.get()
        self.settings["encryption_type"] = self.enc_type_var.get()
        self.settings["auto_registration"] = self.auto_reg_var.get()
        for key, var in self.p25_bool_vars.items():
            self.settings[key] = var.get()

        save_settings(self.settings)
        self.result = self.settings
        self.win.destroy()

    def _reset(self):
        """Reset all settings to defaults."""
        if messagebox.askyesno("Reset", "Reset all settings to defaults?"):
            self.home_unit_var.set(str(DEFAULTS["home_unit_id"]))
            self.nac_var.set(str(DEFAULTS["default_nac"]))
            self.max_scan_var.set(str(DEFAULTS["max_scan_talkgroups"]))
            self.scan_default_var.set(DEFAULTS["scan_enabled_default"])
            self.tx_default_var.set(DEFAULTS["tx_enabled_default"])
            self.auto_backup_var.set(DEFAULTS["auto_backup"])
            self.auto_validate_var.set(DEFAULTS["auto_validate"])
            # P25 system settings
            self.roaming_var.set(DEFAULTS["roaming_mode"])
            self.power_var.set(DEFAULTS["power_level"])
            self.enc_type_var.set(DEFAULTS["encryption_type"])
            self.auto_reg_var.set(DEFAULTS["auto_registration"])
            for key, var in self.p25_bool_vars.items():
                var.set(DEFAULTS[key])
