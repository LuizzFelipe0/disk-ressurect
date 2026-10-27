"""Use cases that orchestrate catalog scanning and selected-file recovery."""

import os
from dataclasses import dataclass
from typing import Callable

from disk.output_safety import OutputSafetyGuard
from disk.raw_disk import RawDisk
from disk.inventory import NTFSVolume
from domain.recovery_catalog import RecoveryCatalog
from ntfs.extractor import ExtractionResult, Extractor
from ntfs.tree_builder import TreeBuilder
from reports.report_generator import ReportGenerator


@dataclass(frozen=True)
class RecoveryProgress:
    stage: str
    completed: int
    total: int
    message: str = ""


@dataclass(frozen=True)
class RecoveryCatalogSnapshot:
    catalog: RecoveryCatalog
    volume: NTFSVolume

    @property
    def volume_start(self):
        return self.volume.partition_offset

    @property
    def cluster_size(self):
        return self.volume.cluster_size


@dataclass(frozen=True)
class ExtractionSummary:
    recovered_count: int
    results: tuple[ExtractionResult, ...]


ProgressCallback = Callable[[RecoveryProgress], None]


class RecoveryWorkflow:
    """Coordinates disk access, catalog construction, selection and extraction."""

    def __init__(
        self,
        disk_factory=RawDisk,
        output_guard=None,
    ):
        self.disk_factory = disk_factory
        self.output_guard = output_guard or OutputSafetyGuard()

    def scan_catalog(self, volume: NTFSVolume, progress_callback: ProgressCallback | None = None):
        disk = self.disk_factory(volume.disk_number)
        try:
            builder = TreeBuilder(
                disk,
                volume.fragments_as_dicts(),
                volume.partition_offset,
                volume.record_size,
            )
            nodes = builder.build(
                progress_callback=(
                    None if progress_callback is None else
                    lambda completed, total: self._notify(
                        progress_callback, "catalog", completed, total, "Reading MFT records"
                    )
                )
            )
            return RecoveryCatalogSnapshot(
                catalog=RecoveryCatalog(nodes, builder.root_nodes),
                volume=volume,
            )
        finally:
            disk.close()

    def extract_selection(
        self,
        snapshot: RecoveryCatalogSnapshot,
        selected_nodes,
        output_directory,
        extensions,
        min_file_size_kb=0,
        progress_callback: ProgressCallback | None = None,
    ):
        if not isinstance(output_directory, (str, os.PathLike)) or not os.fspath(output_directory).strip():
            raise ValueError("Choose a recovery destination folder before extracting files")
        self.output_guard.validate(output_directory, snapshot.volume.disk_number)
        disk = self.disk_factory(snapshot.volume.disk_number)
        try:
            extractor = Extractor(
                disk,
                snapshot.catalog.nodes,
                snapshot.volume_start,
                snapshot.cluster_size,
                snapshot.catalog.root_nodes,
            )
            extractor.set_filters(extensions, min_file_size_kb)
            result_callback = None
            if progress_callback is not None:
                result_callback = lambda completed, total, result: self._notify(
                    progress_callback,
                    "extract",
                    completed,
                    total,
                    f"{result.status}: {result.path}",
                )

            recovered_count = extractor.extract(
                output_directory,
                selected_nodes=selected_nodes,
                progress_callback=result_callback,
            )
            ReportGenerator.generate(
                snapshot.catalog.nodes,
                output_directory,
                recovered_count,
                extractor.results,
            )
            return ExtractionSummary(recovered_count, tuple(extractor.results))
        finally:
            disk.close()

    @staticmethod
    def _notify(callback, stage, completed, total, message):
        if callback is not None:
            callback(RecoveryProgress(stage, completed, total, message))
