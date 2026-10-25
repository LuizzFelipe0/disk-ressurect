"""Responsive desktop recovery interface built only on tkinter and ttk."""

import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from application.recovery_workflow import RecoveryProgress, RecoveryWorkflow
from disk.inventory import DiskInventory, NTFSVolume, PhysicalDisk
from domain.recovery_selection import RecoverySelection
from gui.catalog_browser import CatalogBrowser
from gui.widgets import (
    ChoiceDialog,
    LabeledDropdown,
    PanelCard,
    PrimaryButton,
    SecondaryButton,
    TextInput,
    center_window,
    configure_theme,
)
from ntfs.extractor import Extractor


class RecoveryMainWindow(tk.Tk):
    """Main app window; disk I/O remains off Tk's single-threaded event loop."""

    def __init__(self, workflow=None, inventory=None):
        super().__init__(className="DiskRessurect")
        self.workflow = workflow or RecoveryWorkflow()
        self.inventory = inventory or DiskInventory()
        self.snapshot = None
        self.selection = None
        self.browser = None
        self.disks = []
        self.volumes = []
        self._disks_by_label = {}
        self._volumes_by_label = {}
        self.selected_disk: PhysicalDisk | None = None
        self.selected_volume: NTFSVolume | None = None
        self.available_extensions = ()
        self._selected_extensions = set()
        self._worker_thread = None
        self._events = queue.Queue()
        self._success_handler = None
        configure_theme(self)
        self._build_ui()
        center_window(self)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._refresh_disks)

    def _build_ui(self):
        self.title("Disk Ressurect")
        screen_width = max(560, self.winfo_screenwidth() - 40)
        screen_height = max(440, self.winfo_screenheight() - 80)
        width, height = min(1120, screen_width), min(760, screen_height)
        self.geometry(f"{width}x{height}")
        self.minsize(min(780, width), min(560, height))
        self.configure(padx=20, pady=16)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        title_box = ttk.Frame(header)
        title_box.grid(row=0, column=0, sticky="w")
        ttk.Label(title_box, text="Disk Ressurect", style="Hero.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="Browse recoverable files and choose what to restore",
                  style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        self.source_badge = ttk.Label(header, text="Select a source disk", style="Badge.TLabel")
        self.source_badge.grid(row=0, column=1, sticky="e")

        source = PanelCard(self)
        source.grid(row=1, column=0, sticky="ew", pady=(0, 9))
        source.columnconfigure(1, weight=1)
        ttk.Label(source, text="Source disk", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        self.disk_var = tk.StringVar(master=self)
        self.disk_combo = LabeledDropdown(source, textvariable=self.disk_var, width=42, values=())
        self.disk_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(0, 8))
        self.disk_combo.bind("<<ComboboxSelected>>", self._disk_selected)
        self.refresh_disks_button = SecondaryButton(source, "Refresh", command=self._refresh_disks)
        self.refresh_disks_button.grid(row=0, column=2, padx=(0, 8), pady=(0, 8))
        ttk.Label(source, text="NTFS partition", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.partition_var = tk.StringVar(master=self)
        self.partition_combo = LabeledDropdown(source, textvariable=self.partition_var, width=42, values=())
        self.partition_combo.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        self.partition_combo.bind("<<ComboboxSelected>>", self._partition_selected)
        self.discover_partitions_button = SecondaryButton(
            source, "Find partitions", command=self._discover_partitions, state="disabled"
        )
        self.discover_partitions_button.grid(row=1, column=2, padx=(0, 8))
        self.deep_scan_button = SecondaryButton(
            source, "Deep scan lost partitions", command=self._deep_scan_partitions, state="disabled"
        )
        self.deep_scan_button.grid(row=2, column=0, sticky="w", pady=(9, 0))
        ttk.Label(
            source,
            text="Searches for surviving MFT metadata first, then scans the disk if needed.",
            style="CardMuted.TLabel",
        ).grid(row=2, column=1, columnspan=2, sticky="w", pady=(9, 0))

        destination = PanelCard(self)
        destination.grid(row=2, column=0, sticky="ew", pady=(0, 9))
        destination.columnconfigure(1, weight=1)
        ttk.Label(destination, text="Save recovered files to", style="CardMuted.TLabel").grid(row=0, column=0, padx=(0, 10))
        self.output_var = tk.StringVar(master=self, value="")
        self.output_entry = TextInput(destination, textvariable=self.output_var)
        self.output_entry.grid(row=0, column=1, sticky="ew", padx=(0, 9))
        self.browse_button = SecondaryButton(destination, "Choose folder…", command=self._choose_output)
        self.browse_button.grid(row=0, column=2)

        toolbar = PanelCard(self)
        toolbar.grid(row=3, column=0, sticky="ew", pady=(0, 9))
        for column in range(4):
            toolbar.columnconfigure(column, weight=0)
        toolbar.columnconfigure(3, weight=1)
        row_one = ttk.Frame(toolbar, style="Card.TFrame")
        row_one.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 7))
        self.scan_button = PrimaryButton(row_one, "Build file catalog", command=self._scan_catalog, state="disabled")
        self.scan_button.pack(side="left", padx=(0, 7))
        self.recover_button = PrimaryButton(row_one, "Recover selected", command=self._recover_selected, success=True)
        self.recover_button.pack(side="left", padx=7)
        self.recover_button.configure(state="disabled")
        self.types_button = SecondaryButton(row_one, "File types · all", command=self._choose_types)
        self.types_button.pack(side="left", padx=7)
        self.types_button.configure(state="disabled")
        ttk.Label(row_one, text="Minimum size", style="CardMuted.TLabel").pack(side="left", padx=(12, 6))
        self.minimum_var = tk.StringVar(master=self, value="Any size")
        self.minimum_combo = LabeledDropdown(
            row_one, textvariable=self.minimum_var, width=11,
            values=("Any size", "5 KB", "25 KB", "100 KB", "1 MB"),
        )
        self.minimum_combo.pack(side="left")
        self.minimum_combo.configure(state="disabled")
        self.minimum_combo.bind("<<ComboboxSelected>>", self._filters_changed)

        row_two = ttk.Frame(toolbar, style="Card.TFrame")
        row_two.grid(row=1, column=0, columnspan=4, sticky="ew")
        self.select_all_button = SecondaryButton(row_two, "Select all", command=self._select_all, state="disabled")
        self.select_all_button.pack(side="left", padx=(0, 6))
        self.clear_button = SecondaryButton(row_two, "Clear selection", command=self._clear_selection, state="disabled")
        self.clear_button.pack(side="left", padx=6)
        self.selection_label = ttk.Label(row_two, text="Scan to view folders", style="Badge.TLabel", anchor="e")
        self.selection_label.pack(side="right")

        self.browser_card = PanelCard(self)
        self.browser_card.grid(row=4, column=0, sticky="nsew", pady=(0, 9))
        self.browser_card.rowconfigure(0, weight=1)
        self.browser_card.columnconfigure(0, weight=1)
        self.empty_hint = ttk.Label(
            self.browser_card, text="Scan the source drive to build its folder catalog",
            style="CardMuted.TLabel", anchor="center",
        )
        self.empty_hint.grid(row=0, column=0, sticky="nsew")

        footer = PanelCard(self)
        footer.grid(row=5, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(master=self, value="Choose a destination, then scan to build the folder catalog.")
        ttk.Label(footer, textvariable=self.status_var, style="CardMuted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 7))
        self.progress = ttk.Progressbar(footer, mode="determinate", maximum=100, style="Horizontal.TProgressbar")
        self.progress.grid(row=1, column=0, sticky="ew")

    def _choose_output(self):
        directory = filedialog.askdirectory(title="Choose recovery destination", initialdir=self.output_var.get())
        if directory:
            self.output_var.set(directory)

    def _scan_catalog(self):
        volume = self.selected_volume
        if volume is None:
            return
        self._run_task(lambda progress: self.workflow.scan_catalog(volume, progress), self._catalog_ready,
                       f"Reading the MFT on partition {volume.partition_number}…")

    def _refresh_disks(self):
        self._run_task(lambda _progress: self.inventory.list_disks(), self._disks_ready,
                       "Finding connected physical disks…")

    def _disks_ready(self, disks):
        self.disks = list(disks)
        self._disks_by_label = {disk.display_name: disk for disk in self.disks}
        labels = list(self._disks_by_label)
        self.disk_combo.configure(values=labels)
        self.disk_var.set("")
        self.selected_disk = None
        self._clear_volumes()
        self.status_var.set(f"Found {len(disks)} physical disk(s). Choose a source disk.")

    def _disk_selected(self, _event=None):
        self.selected_disk = self._disks_by_label.get(self.disk_var.get())
        self._clear_volumes()
        self._reset_catalog()
        self.discover_partitions_button.configure(state="normal" if self.selected_disk and not self._worker_thread else "disabled")
        self.deep_scan_button.configure(state="normal" if self.selected_disk and not self._worker_thread else "disabled")
        self.source_badge.configure(text=(f"PhysicalDrive{self.selected_disk.number}" if self.selected_disk else "Select a source disk"))

    def _discover_partitions(self):
        if self.selected_disk is None:
            return
        disk = self.selected_disk

        def scan(progress):
            def report(completed, total, message):
                progress(RecoveryProgress("partitions", completed, total, message))
            return self.inventory.list_ntfs_volumes(disk.number, report)

        self._run_task(scan, self._volumes_ready, f"Inspecting partitions on disk {disk.number}…")

    def _deep_scan_partitions(self):
        if self.selected_disk is None:
            return
        disk = self.selected_disk

        def scan(progress):
            def report(completed, total, message):
                progress(RecoveryProgress("lost-partition-scan", completed, total, message))
            return self.inventory.deep_scan_ntfs_volumes(disk.number, report)

        self._run_task(
            scan,
            self._lost_volumes_ready,
            f"Searching PhysicalDrive{disk.number} for surviving NTFS metadata…",
        )

    def _lost_volumes_ready(self, discovered):
        by_offset = {volume.partition_offset: volume for volume in self.volumes}
        for volume in discovered:
            by_offset.setdefault(volume.partition_offset, volume)
        self._volumes_ready(sorted(by_offset.values(), key=lambda volume: volume.partition_offset))
        lost_count = sum(volume.partition_number == 0 for volume in discovered)
        if lost_count:
            self.status_var.set(
                f"Deep scan found {lost_count} lost NTFS volume candidate(s). Choose one to build its file catalog."
            )
        else:
            self.status_var.set(
                "Deep scan finished without finding a readable lost NTFS MFT. No disk data was changed."
            )

    def _volumes_ready(self, volumes):
        self.volumes = list(volumes)
        self._volumes_by_label = {volume.display_name: volume for volume in self.volumes}
        self.partition_combo.configure(values=list(self._volumes_by_label))
        self.partition_var.set("")
        self.selected_volume = None
        self.scan_button.configure(state="disabled")
        if self.volumes:
            self.status_var.set(f"Found {len(self.volumes)} NTFS partition(s). Choose one to build its file catalog.")
        else:
            self.status_var.set("No readable NTFS partition found. Try the read-only deep scan for lost partitions.")

    def _partition_selected(self, _event=None):
        self.selected_volume = self._volumes_by_label.get(self.partition_var.get())
        self._reset_catalog()
        can_scan = self.selected_volume is not None and self._worker_thread is None
        self.scan_button.configure(state="normal" if can_scan else "disabled")
        if self.selected_volume:
            self.source_badge.configure(
                text=f"PhysicalDrive{self.selected_volume.disk_number} · Partition {self.selected_volume.partition_number}"
            )

    def _clear_volumes(self):
        self.volumes = []
        self._volumes_by_label = {}
        self.partition_combo.configure(values=())
        self.partition_var.set("")
        self.selected_volume = None
        self.scan_button.configure(state="disabled")

    def _reset_catalog(self):
        self.snapshot = None
        self.selection = None
        self.available_extensions = ()
        self._selected_extensions.clear()
        self.recover_button.configure(state="disabled")
        self.types_button.configure(state="disabled", text="File types · all")
        self.minimum_combo.configure(state="disabled")
        self.select_all_button.configure(state="disabled")
        self.clear_button.configure(state="disabled")
        if self.browser is not None:
            self.browser.destroy()
            self.browser = None
        self.empty_hint.configure(text="Scan the source drive to build its folder catalog")
        self.empty_hint.grid()
        self.selection_label.configure(text="Scan to view folders")

    def _catalog_ready(self, snapshot):
        self.snapshot = snapshot
        self.available_extensions = tuple(snapshot.catalog.available_extensions(Extractor.supported_extensions()))
        self._selected_extensions = set(self.available_extensions)
        self.selection = RecoverySelection(
            snapshot.catalog, Extractor.supported_extensions(), self._selected_extensions,
            self._minimum_size_kb(),
        )
        self.selection.add_listener(lambda _nodes: self._update_selection_label())
        if self.browser is not None:
            self.browser.destroy()
        self.empty_hint.grid_remove()
        self.browser = CatalogBrowser(
            self.browser_card, snapshot.catalog, self.selection,
            on_selection_changed=self._update_selection_label,
        )
        self.browser.grid(row=0, column=0, sticky="nsew")
        self._update_type_button()
        self._set_catalog_controls(True)
        self.status_var.set(
            f"Catalog ready · {len(snapshot.catalog.nodes):,} MFT records · "
            f"{self.selection.eligible_count:,} supported files"
        )
        self.progress.configure(value=100)

    def _choose_types(self):
        if not self.selection or self._worker_thread:
            return
        ChoiceDialog(self, "Choose file types", self.available_extensions,
                     self._selected_extensions, self._apply_types)

    def _apply_types(self, selected):
        self._selected_extensions = set(selected)
        self.selection.set_filters(self._selected_extensions, self._minimum_size_kb())
        self._update_type_button()
        self._update_selection_label()

    def _update_type_button(self):
        total = len(self.available_extensions)
        selected = len(self._selected_extensions)
        label = "all" if selected == total else f"{selected}/{total}"
        self.types_button.configure(text=f"File types · {label}")

    def _minimum_size_kb(self):
        return {"Any size": 0, "5 KB": 5, "25 KB": 25, "100 KB": 100, "1 MB": 1024}.get(self.minimum_var.get(), 0)

    def _filters_changed(self, _event=None):
        if self.selection:
            self.selection.set_filters(self._selected_extensions, self._minimum_size_kb())
            self._update_selection_label()

    def _update_selection_label(self):
        if self.selection is None:
            return
        self.selection_label.configure(
            text=f"{self.selection.selected_count:,} selected · {self.selection.eligible_count:,} available"
        )
        state = "normal" if self.selection.selected_count and not self._worker_thread else "disabled"
        self.recover_button.configure(state=state)

    def _select_all(self):
        if self.selection:
            self.selection.select_all()
            self._update_selection_label()

    def _clear_selection(self):
        if self.selection:
            self.selection.clear()
            self._update_selection_label()

    def _recover_selected(self):
        if self.snapshot is None or self.selection is None:
            return
        selected = self.selection.selected_nodes()
        if not selected:
            messagebox.showinfo("No files selected", "Select at least one file or folder in the catalog.", parent=self)
            return
        output_directory = self.output_var.get().strip()
        extensions = set(self.selection.extensions)
        minimum_size_kb = self.selection.min_file_size_kb
        self._run_task(
            lambda progress: self.workflow.extract_selection(
                snapshot=self.snapshot, selected_nodes=selected, output_directory=output_directory,
                extensions=extensions, min_file_size_kb=minimum_size_kb, progress_callback=progress,
            ), self._recovery_finished, f"Recovering {len(selected):,} selected files…",
        )

    def _recovery_finished(self, summary):
        if self.browser:
            self.browser.set_results(summary.results)
        self.status_var.set(
            f"Recovery finished · {summary.recovered_count:,}/{len(summary.results):,} files recovered · "
            "See Recovery_Report.txt for per-file outcomes."
        )
        self.progress.configure(value=100)

    def _run_task(self, task, success_handler, initial_message):
        if self._worker_thread is not None:
            return
        self._success_handler = success_handler
        self._set_busy(True)
        self.status_var.set(initial_message)
        self.progress.configure(value=0)

        def run():
            try:
                result = task(lambda event: self._events.put(("progress", event)))
            except Exception as exc:
                self._events.put(("failed", f"{type(exc).__name__}: {exc}"))
            else:
                self._events.put(("succeeded", result))
            finally:
                self._events.put(("finished", None))

        self._worker_thread = threading.Thread(target=run, name="recovery-workflow", daemon=True)
        self._worker_thread.start()
        self.after(80, self._poll_worker)

    def _poll_worker(self):
        finished = False
        while True:
            try:
                kind, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self._update_progress(payload)
            elif kind == "succeeded":
                if self._success_handler:
                    self._success_handler(payload)
            elif kind == "failed":
                self.status_var.set("The recovery task failed.")
                messagebox.showerror("Recovery error", payload, parent=self)
            elif kind == "finished":
                finished = True
        if finished:
            self._worker_thread = None
            self._success_handler = None
            self._set_busy(False)
            self._update_selection_label()
        elif self._worker_thread is not None:
            self.after(80, self._poll_worker)

    def _update_progress(self, event: RecoveryProgress):
        value = 0 if event.total <= 0 else min(100, int(event.completed * 100 / event.total))
        self.progress.configure(value=value)
        self.status_var.set(
            event.message or (f"{event.stage}: {event.completed:,}/{event.total:,}" if event.total else event.stage)
        )

    def _set_busy(self, busy):
        self.disk_combo.configure(state="disabled" if busy else "readonly")
        self.refresh_disks_button.configure(state="disabled" if busy else "normal")
        self.partition_combo.configure(state="disabled" if busy or not self.volumes else "readonly")
        self.discover_partitions_button.configure(
            state="normal" if not busy and self.selected_disk else "disabled"
        )
        self.deep_scan_button.configure(
            state="normal" if not busy and self.selected_disk else "disabled"
        )
        self.scan_button.configure(state="normal" if not busy and self.selected_volume else "disabled")
        self.browse_button.configure(state="disabled" if busy else "normal")
        self.output_entry.configure(state="disabled" if busy else "normal")
        self.types_button.configure(state="normal" if not busy and self.selection else "disabled")
        self.minimum_combo.configure(state="disabled" if busy or not self.selection else "readonly")
        self.select_all_button.configure(state="normal" if not busy and self.selection else "disabled")
        self.clear_button.configure(state="normal" if not busy and self.selection else "disabled")
        if self.selection:
            self.recover_button.configure(
                state="normal" if not busy and self.selection.selected_count else "disabled"
            )
        if self.browser:
            for widget in (self.browser.folder_tree, self.browser.file_table):
                widget.state(["disabled"] if busy else ["!disabled"])

    def _set_catalog_controls(self, enabled):
        state = "normal" if enabled else "disabled"
        self.types_button.configure(state=state)
        self.minimum_combo.configure(state="readonly" if enabled else "disabled")
        self.select_all_button.configure(state=state)
        self.clear_button.configure(state=state)
        self._update_selection_label()

    def _close(self):
        if self._worker_thread is not None:
            if not messagebox.askyesno("Task in progress", "A disk operation is still running. Exit anyway?", parent=self):
                return
        self.destroy()


def run_gui():
    app = RecoveryMainWindow()
    app.mainloop()
    return 0
