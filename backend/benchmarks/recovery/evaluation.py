"""Oracle-only evaluation of recovered candidates against synthetic truth."""

from __future__ import annotations

import hashlib


def evaluate_carving(files, manifest):
    """Compare candidates to known truth after the carver has finished."""
    expected_by_hash = {}
    eligible_entries = []
    for entry in manifest.entries:
        if entry.negative_reason is None and entry.expected_recovery not in {
                "miss_without_metadata", "ntfs_runlist_component"}:
            expected_by_hash.setdefault(entry.sha256, []).append(entry)
            if entry.expected_recovery == "contiguous_carving":
                eligible_entries.append(entry)

    found_hashes = {}
    for candidate in files:
        digest = hashlib.sha256(candidate.data).hexdigest()
        found_hashes.setdefault(digest, []).append({
            "offset": candidate.offset,
            "format": candidate.extension,
            "strategy": candidate.strategy,
        })

    exact = {digest: found_hashes[digest] for digest in expected_by_hash if digest in found_hashes}
    recovered_ids = set()
    for entry in eligible_entries:
        if any(
            item["offset"] == start
            for start, _end in entry.physical_ranges
            for item in found_hashes.get(entry.sha256, ())
        ):
            recovered_ids.add(entry.file_id)

    duplicate_candidates = sum(max(0, len(items) - 1) for items in found_hashes.values())
    false_candidates = [digest for digest in found_hashes if digest not in expected_by_hash]
    negative_entries = [entry for entry in manifest.entries if entry.negative_reason]
    false_candidate_details = []
    for digest in false_candidates:
        for candidate in found_hashes[digest]:
            matched_negative = next((entry for entry in negative_entries if any(
                start == candidate["offset"] for start, _end in entry.physical_ranges
            )), None)
            candidate_file = next(item for item in files
                                  if item.offset == candidate["offset"]
                                  and item.extension == candidate["format"])
            false_candidate_details.append({
                **candidate,
                "sizeBytes": len(candidate_file.data),
                "sha256": digest,
                "groundTruthNegativeId": matched_negative.file_id if matched_negative else None,
                "groundTruthNegativeReason": matched_negative.negative_reason if matched_negative else None,
            })

    expected_ids = sorted(entry.file_id for entry in eligible_entries)
    recovered_ids = sorted(recovered_ids)
    return {
        "originalFilesInContiguousRecoveryDenominator": len(expected_ids),
        "completeOriginalFilesRecoveredByteForByte": len(recovered_ids),
        "originalFileIdentitiesWithDuplicateContentAreEvaluatedByKnownPhysicalOffset": True,
        "recoveredOriginalIds": recovered_ids,
        "missedOriginalIds": sorted(set(expected_ids) - set(recovered_ids)),
        "falseAcceptedCandidateCount": sum(len(found_hashes[digest]) for digest in false_candidates),
        "falseAcceptedCandidates": false_candidate_details,
        "duplicateCandidateCount": duplicate_candidates,
        "candidateCount": sum(map(len, found_hashes.values())),
        "candidateMatches": exact,
    }
