"""Map validated carving results into catalog nodes with cross-pass deduplication."""

import hashlib
import os

from modules.catalog.carved_content_record import CarvedContentRecord
from ntfs.tree_builder import FileNode


class CarvedCandidateCatalog:
    """Keep carving deduplication and synthetic-node construction in one place."""

    def __init__(self, builder, disk_size):
        self.builder = builder
        self.disk_size = int(disk_size)
        self.content_digests = set()
        self.physical_offsets = set()

    def add(self, candidates, path_parts, allocation_status=None):
        added = 0
        for candidate in candidates:
            digest = hashlib.sha256(candidate.data).digest()
            offset = int(candidate.offset)
            if digest in self.content_digests or offset in self.physical_offsets:
                continue
            self.content_digests.add(digest)
            self.physical_offsets.add(offset)

            synthetic_id = -(self.disk_size + offset + 1)
            while synthetic_id in self.builder.nodes:
                synthetic_id -= 1
            record = CarvedContentRecord(
                index=synthetic_id,
                offset=offset,
                name=f"Carved_{offset:016X}{candidate.extension}",
                resident_data=candidate.data,
                cluster_allocation_status=allocation_status or "free",
                catalog_content_validation_reason=(
                    "Contiguous format structure passed validation; allocation "
                    "is unknown or may describe current/reused data"
                    if allocation_status is not None else
                    "Contiguous file structure and format markers passed validation"
                ),
            )
            node = FileNode(record, is_orphaned=True, is_content_carved=True)
            node.full_path = os.path.join(*path_parts, record.name)
            self.builder.nodes[synthetic_id] = node
            self.builder.root_nodes.append(node)
            added += 1
        return added
