from modules.disk_discovery.dto import DiskValidationDto, DiscoveredDiskDto, PartitionDto


class DiskDiscoveryMapper:
    @staticmethod
    def validation(report):
        disk = report["disk"]
        coverage = report["coverage"]
        is_complete = coverage.bytes_read == int(disk.size_bytes) and not coverage.issues
        unsupported = tuple(report["unsupported_filesystems"])
        assessment = "inconclusive" if not is_complete or report["capacity_mismatch"] else "evidence_collected"
        ntfs_checks = tuple(report["ntfs_checks"])
        metadata_problem = any(
            item.get("validationError")
            or not item.get("mftRecordZeroValid")
            or not item.get("mftMirrorMatchesFirstRecords")
            or not item.get("bitmapRecordValid")
            or not item.get("primaryAndBackupBootMatch")
            or not item.get("mftReadComplete")
            or int(item.get("mftRecords", {}).get("invalidFileRecords", 0)) > 0
            or int(item.get("mftRecords", {}).get("metadataInconsistent", 0)) > 0
            for item in ntfs_checks
        )
        metadata_problem = metadata_problem or any(
            not item.get("valid") for item in report["partition_table_checks"]
        )
        if not report["mbr_signature_found"] and not any(
            item.get("valid") for item in report["partition_table_checks"]
        ):
            metadata_problem = True
        candidates_found = any(
            int(item.get("orphanedFileRecordCount", 0)) > 0
            or int(item.get("mftRecords", {}).get("deleted", 0)) > 0
            for item in ntfs_checks
        )
        if (unsupported or metadata_problem or not ntfs_checks or candidates_found) and assessment == "evidence_collected":
            assessment = "inconclusive"
        return DiskValidationDto(
            number=disk.number,
            model=disk.model,
            size_bytes=disk.size_bytes,
            serial_number=disk.serial_number,
            coverage_status="complete" if is_complete else "incomplete",
            assessment=assessment,
            bytes_requested=coverage.bytes_requested,
            bytes_read=coverage.bytes_read,
            io_bytes_read=coverage.bytes_read_total,
            read_intervals=tuple(interval.to_dict() for interval in coverage.intervals_as_objects()),
            read_errors=tuple(issue.to_dict() for issue in coverage.issues),
            partitions=tuple(report["partitions"]),
            mbr_signature_found=bool(report["mbr_signature_found"]),
            partition_table_checks=tuple(report["partition_table_checks"]),
            ntfs_checks=tuple(report["ntfs_checks"]),
            unsupported_filesystems=unsupported,
            filesystem_signatures=tuple(report["filesystem_signatures"]),
            interpretation=(
                "This audit does not prove the disk contains no recoverable data. "
                + ("Review partition and NTFS findings and scan supported file systems."
                    if assessment == "evidence_collected"
                    else "Some disk areas or structures could not be fully validated; treat the result as inconclusive.")
            ),
        )

    @staticmethod
    def disk(discovered_disk, register_volume):
        disk = discovered_disk.disk
        scan = discovered_disk.cached_scan
        partitions = tuple(
            DiskDiscoveryMapper.partition(
                volume,
                register_volume(volume),
                scan.scanned_at,
            )
            for volume in (scan.volumes if scan else ())
        )
        return DiscoveredDiskDto(
            number=disk.number,
            model=disk.model,
            size_bytes=disk.size_bytes,
            serial_number=disk.serial_number,
            display_name=disk.display_name,
            cached_partitions=partitions,
            deep_scan_resume_available=bool(scan and getattr(scan, "checkpoint", None)),
        )

    @staticmethod
    def partition(volume, volume_id, scanned_at=None):
        return PartitionDto(
            id=volume_id,
            disk_number=volume.disk_number,
            partition_number=volume.partition_number,
            offset=volume.partition_offset,
            size_bytes=volume.partition_size,
            estimated_size=volume.partition_size_is_estimated,
            name=volume.display_name,
            scan_saved_at=scanned_at,
        )
