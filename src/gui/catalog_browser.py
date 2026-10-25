"""Explorer-like folder and file browser built with standard ttk Treeviews."""

import os
from tkinter import ttk

from domain.recovery_selection import RecoverySelection


UNCHECKED = "☐"
CHECKED = "☑"
PARTIAL = "▣"


class CatalogBrowser(ttk.Frame):
    """Folder-only navigation and direct-file listing for one recovery catalog."""

    def __init__(self, master, catalog, selection, on_selection_changed=None, **kwargs):
        super().__init__(master, **kwargs)
        self.catalog = catalog
        self.selection = selection
        self.on_selection_changed = on_selection_changed
        self.current_directory = None
        self._nodes_by_iid = {}
        self._folder_iids = {}
        self._file_iids = {}
        self._loaded_folders = set()
        self._build()
        self._insert_roots()
        self.selection.add_listener(self._selection_changed)

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.location = ttk.Label(self, text="Drive root", style="Muted.TLabel")
        self.location.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        split = ttk.Panedwindow(self, orient="horizontal")
        split.grid(row=1, column=0, sticky="nsew")

        folders = ttk.Frame(split, padding=8, style="Card.TFrame")
        folders.rowconfigure(0, weight=1)
        folders.columnconfigure(0, weight=1)
        self.folder_tree = ttk.Treeview(
            folders,
            columns=("pick", "eligible"),
            show="tree headings",
            selectmode="browse",
            cursor="hand2",
        )
        self.folder_tree.heading("#0", text="Folders")
        self.folder_tree.heading("pick", text="Select")
        self.folder_tree.heading("eligible", text="Files")
        self.folder_tree.column("#0", width=245, minwidth=120, stretch=True)
        self.folder_tree.column("pick", width=58, minwidth=52, stretch=False, anchor="center")
        self.folder_tree.column("eligible", width=78, minwidth=68, stretch=False, anchor="e")
        folder_scroll = ttk.Scrollbar(folders, orient="vertical", command=self.folder_tree.yview)
        self.folder_tree.configure(yscrollcommand=folder_scroll.set)
        self.folder_tree.grid(row=0, column=0, sticky="nsew")
        folder_scroll.grid(row=0, column=1, sticky="ns")
        self.folder_tree.bind("<Button-1>", self._folder_click, add=True)
        self.folder_tree.bind("<<TreeviewSelect>>", self._folder_selected, add=True)
        self.folder_tree.bind("<<TreeviewOpen>>", self._folder_opened, add=True)
        self.folder_tree.bind("<space>", self._toggle_focused_folder)
        split.add(folders, weight=1)

        listing = ttk.Frame(split, padding=8, style="Card.TFrame")
        listing.rowconfigure(0, weight=1)
        listing.columnconfigure(0, weight=1)
        columns = ("pick", "name", "size", "type", "status")
        self.file_table = ttk.Treeview(
            listing,
            columns=columns,
            show="headings",
            selectmode="extended",
            cursor="hand2",
        )
        headers = {"pick": "", "name": "Name", "size": "Size", "type": "Type", "status": "Recovery status"}
        widths = {"pick": 48, "name": 390, "size": 95, "type": 100, "status": 150}
        for column in columns:
            self.file_table.heading(column, text=headers[column])
            self.file_table.column(column, width=widths[column], minwidth=42 if column == "pick" else 70,
                                   stretch=column == "name", anchor="center" if column == "pick" else "w")
        file_scroll = ttk.Scrollbar(listing, orient="vertical", command=self.file_table.yview)
        self.file_table.configure(yscrollcommand=file_scroll.set)
        self.file_table.grid(row=0, column=0, sticky="nsew")
        file_scroll.grid(row=0, column=1, sticky="ns")
        self.file_table.bind("<Button-1>", self._file_click, add=True)
        self.file_table.bind("<space>", self._toggle_focused_file)
        self.file_table.tag_configure("recovered", foreground="#12805c")
        self.file_table.tag_configure("rejected", foreground="#b54738")
        split.add(listing, weight=3)

    def _iid(self, node):
        return f"n{id(node)}"

    def _checkbox(self, node):
        state = self.selection.check_state(node)
        return {None: UNCHECKED, RecoverySelection.UNCHECKED: UNCHECKED,
                RecoverySelection.PARTIALLY_CHECKED: PARTIAL,
                RecoverySelection.CHECKED: CHECKED}[state]

    def _insert_roots(self):
        for folder in self._sorted_folders(self.catalog.root_nodes):
            self._insert_folder("", folder)
        self.show_directory(None)

    @staticmethod
    def _sorted_folders(nodes):
        return sorted((node for node in nodes if node.record.is_dir), key=lambda n: n.record.name.casefold())

    def _insert_folder(self, parent_iid, folder):
        iid = self._iid(folder)
        self._nodes_by_iid[iid] = folder
        self._folder_iids[self.catalog.node_key(folder)] = iid
        count = self.selection.eligible_count_for(folder)
        self.folder_tree.insert(parent_iid, "end", iid=iid, text=folder.record.name,
                                values=(self._checkbox(folder), f"{count:,}"))
        if any(child.record.is_dir for child in folder.children):
            self.folder_tree.insert(iid, "end", iid=f"placeholder-{iid}", text="", values=("", ""))

    def _folder_opened(self, event=None):
        iid = self.folder_tree.focus()
        if not iid and self.folder_tree.selection():
            iid = self.folder_tree.selection()[0]
        self._load_folder(iid)

    def _load_folder(self, iid):
        folder = self._nodes_by_iid.get(iid)
        if folder is None or iid in self._loaded_folders:
            return
        placeholders = [child for child in self.folder_tree.get_children(iid) if child.startswith("placeholder-")]
        if placeholders:
            self.folder_tree.delete(*placeholders)
        for child in self._sorted_folders(folder.children):
            self._insert_folder(iid, child)
        self._loaded_folders.add(iid)

    def _folder_click(self, event):
        iid = self.folder_tree.identify_row(event.y)
        column = self.folder_tree.identify_column(event.x)
        element = self.folder_tree.identify_element(event.x, event.y)
        if iid and column == "#0" and "indicator" in element:
            # Load before Tk opens the item; virtual open events vary by theme/platform.
            self._load_folder(iid)
            return None
        if iid and column == "#1":
            folder = self._nodes_by_iid.get(iid)
            if folder is not None and self.selection.eligible_count_for(folder):
                checked = self.selection.check_state(folder) != RecoverySelection.CHECKED
                self.selection.set_checked(folder, checked)
            return "break"

    def _folder_selected(self, _event=None):
        selected = self.folder_tree.selection()
        if not selected:
            return
        folder = self._nodes_by_iid.get(selected[0])
        if folder is not None:
            self.show_directory(folder)

    def show_directory(self, directory):
        self.current_directory = directory
        self.location.configure(text=directory.full_path if directory is not None else "Drive root")
        old_rows = self.file_table.get_children()
        for iid in old_rows:
            self._nodes_by_iid.pop(iid, None)
        if old_rows:
            self.file_table.delete(*old_rows)
        self._file_iids.clear()
        for node in sorted(self.selection.files_in(directory), key=lambda n: n.record.name.casefold()):
            iid = self._iid(node)
            self._nodes_by_iid[iid] = node
            self._file_iids[self.catalog.node_key(node)] = iid
            result = self._results_by_key.get(self.catalog.node_key(node)) if hasattr(self, "_results_by_key") else None
            status = result.status if result else "Ready"
            tags = ("recovered",) if result and result.status == "recovered" else (("rejected",) if result and result.status != "recovered" else ())
            self.file_table.insert("", "end", iid=iid, values=(self._checkbox(node), node.record.name,
                                    self._format_size(node.record.file_size),
                                    os.path.splitext(node.record.name)[1].casefold() or "File", status), tags=tags)

    def _file_click(self, event):
        if self.file_table.identify_column(event.x) != "#1":
            return
        iid = self.file_table.identify_row(event.y)
        node = self._nodes_by_iid.get(iid)
        if node is not None:
            checked = self.selection.check_state(node) != RecoverySelection.CHECKED
            self.selection.set_checked(node, checked)
        return "break"

    def _toggle_focused_folder(self, _event=None):
        node = self._nodes_by_iid.get(self.folder_tree.focus())
        if node is not None and self.selection.eligible_count_for(node):
            self.selection.set_checked(node, self.selection.check_state(node) != RecoverySelection.CHECKED)
        return "break"

    def _toggle_focused_file(self, _event=None):
        node = self._nodes_by_iid.get(self.file_table.focus())
        if node is not None:
            self.selection.set_checked(node, self.selection.check_state(node) != RecoverySelection.CHECKED)
        return "break"

    def set_results(self, results):
        self._results_by_key = {self.catalog.node_key(result.node): result for result in results}
        self.show_directory(self.current_directory)

    def refresh(self):
        self._selection_changed(None)

    def _selection_changed(self, changed_nodes):
        if changed_nodes is None:
            for iid, node in tuple(self._nodes_by_iid.items()):
                if self.folder_tree.exists(iid):
                    self.folder_tree.set(iid, "pick", self._checkbox(node))
                    self.folder_tree.set(iid, "eligible", f"{self.selection.eligible_count_for(node):,}")
                elif self.file_table.exists(iid):
                    self.file_table.set(iid, "pick", self._checkbox(node))
            self.show_directory(self.current_directory)
        else:
            for node in changed_nodes:
                iid = self._iid(node)
                if self.folder_tree.exists(iid):
                    self.folder_tree.set(iid, "pick", self._checkbox(node))
                    self.folder_tree.set(iid, "eligible", f"{self.selection.eligible_count_for(node):,}")
                if self.file_table.exists(iid):
                    self.file_table.set(iid, "pick", self._checkbox(node))
        if self.on_selection_changed:
            self.on_selection_changed()

    @staticmethod
    def _format_size(size):
        amount = max(0, int(size))
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if amount < 1024 or unit == "TB":
                return f"{amount:,} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
            amount /= 1024
