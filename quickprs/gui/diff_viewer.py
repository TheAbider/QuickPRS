"""Side-by-side PRS file comparison viewer.

Displays a visual diff between two PRS personality files using paired
Treeview widgets with synchronized scrolling and color-coded differences.
"""

import tkinter as tk
from tkinter import ttk

from ..comparison import detailed_comparison, compare_prs, ADDED, REMOVED


class DiffViewer(tk.Toplevel):
    """Side-by-side PRS file comparison viewer."""

    TAG_ADDED = "added"
    TAG_REMOVED = "removed"
    TAG_CHANGED = "changed"
    TAG_SAME = "same"
    TAG_HEADER = "header"
    TAG_PLACEHOLDER = "placeholder"

    def __init__(self, parent, prs_a, prs_b, name_a="File A", name_b="File B"):
        super().__init__(parent)
        self.title(f"Compare: {name_a}  vs  {name_b}")
        self.geometry("1100x700")
        self.minsize(800, 400)
        self.transient(parent)

        self.prs_a = prs_a
        self.prs_b = prs_b
        self.name_a = name_a
        self.name_b = name_b

        self._build_ui()
        self._populate()

    def _build_ui(self):
        """Build the side-by-side tree layout."""
        # Header bar
        header = ttk.Frame(self, padding=(8, 6))
        header.pack(fill=tk.X)
        ttk.Label(header, text="Side-by-Side Comparison",
                  font=("", 11, "bold")).pack(anchor=tk.W)

        # Legend
        legend = ttk.Frame(self, padding=(8, 2))
        legend.pack(fill=tk.X)
        for label_text, color in [("Only in A", "#ffcccc"),
                                  ("Only in B", "#ccffcc"),
                                  ("Changed", "#ffffaa"),
                                  ("Same", "")]:
            f = ttk.Frame(legend)
            f.pack(side=tk.LEFT, padx=(0, 12))
            if color:
                swatch = tk.Label(f, text="  ", bg=color,
                                  relief=tk.SOLID, borderwidth=1)
                swatch.pack(side=tk.LEFT, padx=(0, 3))
            ttk.Label(f, text=label_text).pack(side=tk.LEFT)

        # Main paned area
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Left tree (File A)
        left_frame = ttk.LabelFrame(paned, text=f"[A] {self.name_a}",
                                     padding=2)
        self.tree_a = self._make_tree(left_frame)
        paned.add(left_frame, weight=1)

        # Right tree (File B)
        right_frame = ttk.LabelFrame(paned, text=f"[B] {self.name_b}",
                                      padding=2)
        self.tree_b = self._make_tree(right_frame)
        paned.add(right_frame, weight=1)

        # Shared scrollbar (in a thin column between or at right)
        scroll_frame = ttk.Frame(self)
        scroll_frame.pack(side=tk.RIGHT, fill=tk.Y)

        self._scrollbar = ttk.Scrollbar(scroll_frame,
                                         command=self._sync_scroll)
        self._scrollbar.pack(fill=tk.Y, expand=True)

        self.tree_a.configure(yscrollcommand=self._on_scroll_a)
        self.tree_b.configure(yscrollcommand=self._on_scroll_b)

        # Summary bar
        self._summary = ttk.Label(self, text="", padding=(8, 4))
        self._summary.pack(fill=tk.X, side=tk.BOTTOM)

    def _make_tree(self, parent):
        """Create a Treeview for one side of the diff."""
        cols = ("detail",)
        tree = ttk.Treeview(parent, columns=cols, show="tree headings",
                            height=25, selectmode="none")
        tree.heading("#0", text="Name", anchor=tk.W)
        tree.heading("detail", text="Detail", anchor=tk.W)
        tree.column("#0", width=250, minwidth=120)
        tree.column("detail", width=250, minwidth=100)

        # Configure tags for coloring
        tree.tag_configure(self.TAG_ADDED, background="#ccffcc")
        tree.tag_configure(self.TAG_REMOVED, background="#ffcccc")
        tree.tag_configure(self.TAG_CHANGED, background="#ffffaa")
        tree.tag_configure(self.TAG_SAME, background="")
        tree.tag_configure(self.TAG_HEADER, font=("", 9, "bold"))
        tree.tag_configure(self.TAG_PLACEHOLDER, foreground="#999999")

        tree.pack(fill=tk.BOTH, expand=True)
        return tree

    def _sync_scroll(self, *args):
        """Scroll both trees together."""
        self.tree_a.yview(*args)
        self.tree_b.yview(*args)

    def _on_scroll_a(self, first, last):
        """Called when tree_a scrolls — sync tree_b and scrollbar."""
        self._scrollbar.set(first, last)
        self.tree_b.yview_moveto(first)

    def _on_scroll_b(self, first, last):
        """Called when tree_b scrolls — sync tree_a and scrollbar."""
        self._scrollbar.set(first, last)
        self.tree_a.yview_moveto(first)

    def _populate(self):
        """Run the comparison and populate both trees."""
        detail = detailed_comparison(self.prs_a, self.prs_b)
        diffs = compare_prs(self.prs_a, self.prs_b)

        # Count stats
        systems_a_only = detail.get('systems_a_only', [])
        systems_b_only = detail.get('systems_b_only', [])
        systems_both = detail.get('systems_both', [])
        tg_diffs = detail.get('talkgroup_diffs', {})
        freq_diffs = detail.get('freq_diffs', {})
        conv_diffs = detail.get('conv_diffs', {})
        option_diffs = detail.get('option_diffs', [])

        total_a = len(systems_a_only) + len(systems_both)
        total_b = len(systems_b_only) + len(systems_both)

        # ── Systems section
        sys_node_a = self.tree_a.insert(
            "", tk.END, text=f"Systems ({total_a})",
            values=("",), tags=(self.TAG_HEADER,))
        sys_node_b = self.tree_b.insert(
            "", tk.END, text=f"Systems ({total_b})",
            values=("",), tags=(self.TAG_HEADER,))

        # Systems in both
        for name in systems_both:
            tag_a = self.TAG_SAME
            tag_b = self.TAG_SAME
            detail_a = ""
            detail_b = ""
            if name in tg_diffs:
                td = tg_diffs[name]
                n_added = len(td.get('added', []))
                n_removed = len(td.get('removed', []))
                if n_added or n_removed:
                    tag_a = self.TAG_CHANGED
                    tag_b = self.TAG_CHANGED
                    detail_a = f"-{n_removed} TGs" if n_removed else ""
                    detail_b = f"+{n_added} TGs" if n_added else ""

            node_a = self.tree_a.insert(
                sys_node_a, tk.END, text=name,
                values=(detail_a,), tags=(tag_a,))
            node_b = self.tree_b.insert(
                sys_node_b, tk.END, text=name,
                values=(detail_b,), tags=(tag_b,))

            # Show individual TG diffs if any
            if name in tg_diffs:
                td = tg_diffs[name]
                for gid, short, long in td.get('removed', []):
                    self.tree_a.insert(
                        node_a, tk.END,
                        text=f"{short} ({gid})",
                        values=(long,), tags=(self.TAG_REMOVED,))
                    self.tree_b.insert(
                        node_b, tk.END,
                        text="(not in B)",
                        values=("",), tags=(self.TAG_PLACEHOLDER,))

                for gid, short, long in td.get('added', []):
                    self.tree_a.insert(
                        node_a, tk.END,
                        text="(not in A)",
                        values=("",), tags=(self.TAG_PLACEHOLDER,))
                    self.tree_b.insert(
                        node_b, tk.END,
                        text=f"{short} ({gid})",
                        values=(long,), tags=(self.TAG_ADDED,))

        # Systems only in A
        for name in systems_a_only:
            self.tree_a.insert(
                sys_node_a, tk.END, text=name,
                values=("only in A",), tags=(self.TAG_REMOVED,))
            self.tree_b.insert(
                sys_node_b, tk.END, text="(not in B)",
                values=("",), tags=(self.TAG_PLACEHOLDER,))

        # Systems only in B
        for name in systems_b_only:
            self.tree_a.insert(
                sys_node_a, tk.END, text="(not in A)",
                values=("",), tags=(self.TAG_PLACEHOLDER,))
            self.tree_b.insert(
                sys_node_b, tk.END, text=name,
                values=("only in B",), tags=(self.TAG_ADDED,))

        # ── Group Sets section (from high-level diffs)
        gs_diffs_a = [d for d in diffs if d[1] == "Group Set"]
        if gs_diffs_a:
            gs_node_a = self.tree_a.insert(
                "", tk.END, text="Group Sets",
                values=("",), tags=(self.TAG_HEADER,))
            gs_node_b = self.tree_b.insert(
                "", tk.END, text="Group Sets",
                values=("",), tags=(self.TAG_HEADER,))

            for dtype, cat, name, detail_str in gs_diffs_a:
                if dtype == REMOVED:
                    self.tree_a.insert(
                        gs_node_a, tk.END, text=name,
                        values=(detail_str,), tags=(self.TAG_REMOVED,))
                    self.tree_b.insert(
                        gs_node_b, tk.END, text="(not in B)",
                        values=("",), tags=(self.TAG_PLACEHOLDER,))
                elif dtype == ADDED:
                    self.tree_a.insert(
                        gs_node_a, tk.END, text="(not in A)",
                        values=("",), tags=(self.TAG_PLACEHOLDER,))
                    self.tree_b.insert(
                        gs_node_b, tk.END, text=name,
                        values=(detail_str,), tags=(self.TAG_ADDED,))
                else:
                    tag = (self.TAG_CHANGED if dtype == "CHANGED"
                           else self.TAG_SAME)
                    self.tree_a.insert(
                        gs_node_a, tk.END, text=name,
                        values=(detail_str,), tags=(tag,))
                    self.tree_b.insert(
                        gs_node_b, tk.END, text=name,
                        values=(detail_str,), tags=(tag,))

        # ── Trunk Sets section
        ts_diffs = [d for d in diffs if d[1] == "Trunk Set"]
        if ts_diffs:
            ts_node_a = self.tree_a.insert(
                "", tk.END, text="Trunk Sets",
                values=("",), tags=(self.TAG_HEADER,))
            ts_node_b = self.tree_b.insert(
                "", tk.END, text="Trunk Sets",
                values=("",), tags=(self.TAG_HEADER,))

            for dtype, cat, name, detail_str in ts_diffs:
                if dtype == REMOVED:
                    self.tree_a.insert(
                        ts_node_a, tk.END, text=name,
                        values=(detail_str,), tags=(self.TAG_REMOVED,))
                    self.tree_b.insert(
                        ts_node_b, tk.END, text="(not in B)",
                        values=("",), tags=(self.TAG_PLACEHOLDER,))
                elif dtype == ADDED:
                    self.tree_a.insert(
                        ts_node_a, tk.END, text="(not in A)",
                        values=("",), tags=(self.TAG_PLACEHOLDER,))
                    self.tree_b.insert(
                        ts_node_b, tk.END, text=name,
                        values=(detail_str,), tags=(self.TAG_ADDED,))
                else:
                    tag = (self.TAG_CHANGED if dtype == "CHANGED"
                           else self.TAG_SAME)
                    self.tree_a.insert(
                        ts_node_a, tk.END, text=name,
                        values=(detail_str,), tags=(tag,))
                    self.tree_b.insert(
                        ts_node_b, tk.END, text=name,
                        values=(detail_str,), tags=(tag,))

        # ── Freq diffs (for trunk sets in both)
        if freq_diffs:
            for set_name, fd in sorted(freq_diffs.items()):
                fd_node_a = self.tree_a.insert(
                    "", tk.END, text=f"Freqs: {set_name}",
                    values=("",), tags=(self.TAG_HEADER,))
                fd_node_b = self.tree_b.insert(
                    "", tk.END, text=f"Freqs: {set_name}",
                    values=("",), tags=(self.TAG_HEADER,))

                for freq in fd.get('removed', []):
                    self.tree_a.insert(
                        fd_node_a, tk.END,
                        text=f"{freq:.5f} MHz",
                        values=("",), tags=(self.TAG_REMOVED,))
                    self.tree_b.insert(
                        fd_node_b, tk.END,
                        text="(not in B)",
                        values=("",), tags=(self.TAG_PLACEHOLDER,))

                for freq in fd.get('added', []):
                    self.tree_a.insert(
                        fd_node_a, tk.END,
                        text="(not in A)",
                        values=("",), tags=(self.TAG_PLACEHOLDER,))
                    self.tree_b.insert(
                        fd_node_b, tk.END,
                        text=f"{freq:.5f} MHz",
                        values=("",), tags=(self.TAG_ADDED,))

        # ── Conv channel diffs
        if conv_diffs:
            for set_name, cd in sorted(conv_diffs.items()):
                cd_node_a = self.tree_a.insert(
                    "", tk.END, text=f"Conv: {set_name}",
                    values=("",), tags=(self.TAG_HEADER,))
                cd_node_b = self.tree_b.insert(
                    "", tk.END, text=f"Conv: {set_name}",
                    values=("",), tags=(self.TAG_HEADER,))

                for short, tx, rx in cd.get('removed', []):
                    self.tree_a.insert(
                        cd_node_a, tk.END,
                        text=short,
                        values=(f"TX:{tx:.5f} RX:{rx:.5f}",),
                        tags=(self.TAG_REMOVED,))
                    self.tree_b.insert(
                        cd_node_b, tk.END,
                        text="(not in B)",
                        values=("",), tags=(self.TAG_PLACEHOLDER,))

                for short, tx, rx in cd.get('added', []):
                    self.tree_a.insert(
                        cd_node_a, tk.END,
                        text="(not in A)",
                        values=("",), tags=(self.TAG_PLACEHOLDER,))
                    self.tree_b.insert(
                        cd_node_b, tk.END,
                        text=short,
                        values=(f"TX:{tx:.5f} RX:{rx:.5f}",),
                        tags=(self.TAG_ADDED,))

        # ── Option diffs
        if option_diffs:
            opt_node_a = self.tree_a.insert(
                "", tk.END, text="Options",
                values=(f"{len(option_diffs)} differences",),
                tags=(self.TAG_HEADER,))
            opt_node_b = self.tree_b.insert(
                "", tk.END, text="Options",
                values=(f"{len(option_diffs)} differences",),
                tags=(self.TAG_HEADER,))

            for field_name, val_a, val_b in option_diffs:
                self.tree_a.insert(
                    opt_node_a, tk.END, text=field_name,
                    values=(str(val_a),), tags=(self.TAG_CHANGED,))
                self.tree_b.insert(
                    opt_node_b, tk.END, text=field_name,
                    values=(str(val_b),), tags=(self.TAG_CHANGED,))

        # Expand all top-level nodes
        for item in self.tree_a.get_children():
            self.tree_a.item(item, open=True)
        for item in self.tree_b.get_children():
            self.tree_b.item(item, open=True)

        # Summary
        n_a_only = len(systems_a_only)
        n_b_only = len(systems_b_only)
        n_tg = sum(
            len(d.get('added', [])) + len(d.get('removed', []))
            for d in tg_diffs.values())
        n_freq = sum(
            len(d.get('added', [])) + len(d.get('removed', []))
            for d in freq_diffs.values())
        n_conv = sum(
            len(d.get('added', [])) + len(d.get('removed', []))
            for d in conv_diffs.values())
        n_opts = len(option_diffs)

        parts = []
        if n_a_only:
            parts.append(f"{n_a_only} system(s) only in A")
        if n_b_only:
            parts.append(f"{n_b_only} system(s) only in B")
        if n_tg:
            parts.append(f"{n_tg} TG change(s)")
        if n_freq:
            parts.append(f"{n_freq} freq change(s)")
        if n_conv:
            parts.append(f"{n_conv} conv change(s)")
        if n_opts:
            parts.append(f"{n_opts} option change(s)")

        if parts:
            self._summary.config(text="Summary: " + ", ".join(parts))
        else:
            self._summary.config(text="No differences found.")
