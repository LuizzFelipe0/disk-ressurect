"""Match USN deletion metadata to bounded, recoverable MFT records."""

import copy
import os
import re

from ntfs.tree_builder import FileNode


class UsnMftCorrelator:
    """Correlate exact file-reference generations and add validated name aliases."""

    MAX_SIGNATURE_CHECKS = 4096
    MAX_ALIASES = 512
    MAX_BASENAME_LENGTH = 120

    def correlate(self, events, builder, content_validator, allowed_extensions):
        allowed = {str(extension).casefold() for extension in allowed_extensions}
        records_by_number = {}
        for node in tuple(builder.nodes.values()):
            record = getattr(node, "record", None)
            try:
                record_number = int(getattr(record, "index", -1))
            except (TypeError, ValueError, OverflowError):
                continue
            if record_number < 0 or not bool(getattr(record, "is_valid", False)):
                continue
            records_by_number.setdefault(record_number, []).append(node)

        summary = {
            "deleteEvents": 0,
            "matchedMftRecords": 0,
            "matchedDeletedMftRecords": 0,
            "staleReferences": 0,
            "unmatchedReferences": 0,
            "unresolvedReferences": 0,
            "signatureChecks": 0,
            "signatureMatchedRecords": 0,
            "signatureMismatches": 0,
            "incompleteRecords": 0,
            "aliasesAdded": 0,
            "correlationLimitReached": False,
        }
        seen_events = set()
        for event in events:
            if not getattr(event, "indicates_delete", False):
                continue
            summary["deleteEvents"] += 1
            reference = getattr(event, "file_reference", None)
            record_number = getattr(reference, "record_number", None)
            sequence_number = getattr(reference, "sequence_number", None)
            if record_number is None or sequence_number is None:
                summary["unresolvedReferences"] += 1
                continue
            event_key = (int(record_number), int(sequence_number), event.name, event.usn)
            if event_key in seen_events:
                continue
            seen_events.add(event_key)

            candidates = records_by_number.get(int(record_number), ())
            if not candidates:
                summary["unmatchedReferences"] += 1
                continue
            exact_matches = [
                node for node in candidates
                if int(getattr(node.record, "sequence_number", -1)) == int(sequence_number)
            ]
            if not exact_matches:
                summary["staleReferences"] += 1
                continue

            summary["matchedMftRecords"] += 1
            node = next((item for item in exact_matches
                         if not bool(getattr(item.record, "is_allocated", True))), exact_matches[0])
            record = node.record
            is_deleted = not bool(getattr(record, "is_allocated", True))
            if is_deleted:
                summary["matchedDeletedMftRecords"] += 1

            name = self._safe_basename(getattr(event, "name", None))
            extension = os.path.splitext(name)[1].casefold()
            if (not is_deleted or not name or extension not in allowed
                    or bool(getattr(record, "is_dir", False))):
                continue
            if (name.casefold() == str(getattr(record, "name", "") or "").casefold()
                    or getattr(record, "data_is_complete", True) is False
                    or int(getattr(record, "file_size", 0) or 0) <= 0
                    or not bool(getattr(record, "is_metadata_consistent", False))):
                summary["incompleteRecords"] += 1
                continue
            if summary["signatureChecks"] >= self.MAX_SIGNATURE_CHECKS:
                summary["correlationLimitReached"] = True
                break

            summary["signatureChecks"] += 1
            alias_record = copy.copy(record)
            alias_record.name = name
            validation = content_validator.validate(alias_record)
            if validation.status != "signature_match":
                if validation.status == "signature_mismatch":
                    summary["signatureMismatches"] += 1
                else:
                    summary["incompleteRecords"] += 1
                continue

            summary["signatureMatchedRecords"] += 1
            if summary["aliasesAdded"] >= self.MAX_ALIASES:
                summary["correlationLimitReached"] = True
                break
            synthetic_id = -(abs(int(record.index)) + 1_000_000_000)
            while synthetic_id in builder.nodes:
                synthetic_id -= 1
            alias_record.index = synthetic_id
            alias_record.recovery_source = "usn_journal_mft"
            alias_record.usn_deletion_timestamp_utc = (
                event.timestamp_utc.isoformat() if event.timestamp_utc is not None else None
            )
            alias = FileNode(alias_record, is_orphaned=True)
            alias.full_path = os.path.join("Lost_Files_DeepScan", "USNJournal", name)
            builder.nodes[synthetic_id] = alias
            builder.root_nodes.append(alias)
            summary["aliasesAdded"] += 1

        return summary

    @classmethod
    def _safe_basename(cls, value):
        parts = re.split(r"[\\/]", str(value or ""))
        basename = parts[-1] if parts else ""
        safe = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "_", basename).strip().rstrip(". ")
        if safe in {"", ".", ".."}:
            return ""
        if len(safe) > cls.MAX_BASENAME_LENGTH:
            stem, separator, extension = safe.rpartition(".")
            safe = (stem[:cls.MAX_BASENAME_LENGTH - len(extension) - 1] + separator + extension
                    if separator else safe[:cls.MAX_BASENAME_LENGTH])
        return safe
