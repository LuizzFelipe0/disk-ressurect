# Disk-Ressurect

![Disk-Ressurect Data Recovery](frontend/src/assets/disk-ressurect-github-banner.png)

A NTFS data recovery and forensic engine written in pure Python. This software is designed to recover files from formatted, corrupted, or partially overwritten disks using raw disk access and Master File Table (MFT) reconstruction.

## Features

Unlike basic file carvers that recover files without names, this engine reconstructs the original directory tree whenever possible.

* Virtual File System (VFS): Reads the $MFT and mounts the original folder structure in memory before extraction.
* Deleted and orphaned MFT entries: The catalog includes deleted records in the mapped MFT. An opt-in scan searches outside those mapped fragments for deleted records with complete, supported file data.
* NTFS recovery evidence: MFT record numbers and parent sequences are checked, orphan data runs are compared with `$Bitmap`, and known file-header mismatches are excluded from the orphan list.
* Bounded content carving: When the selected-volume `$Bitmap` is valid, the opt-in workflow searches trusted free ranges for contiguous JPEG, PNG and PDF candidates. Separate low-confidence passes target orphan MFT data runs whose allocation bits were not observed or may describe reused data. Generated names and format checks do not prove that files are deleted or fully recoverable.
* Smart Header Validation: Reads physical file signatures (magic numbers) during extraction to skip corrupted or overwritten files.
* Lost-partition discovery: Searches physical media for validated NTFS structures when the partition table is missing.
* Full-disk validation evidence: A read-only backend audit records disk identity, byte-range coverage, partition-table checks, filesystem signatures, and NTFS boot-sector, MFT mirror, deleted-record, and `$Bitmap` findings.
* User-controlled selection: The recovery catalog exposes the original folder tree, and users choose both folders and supported file types. No folder names are excluded by default.

## Architecture

The Python backend is organized as feature modules over a small set of low-level NTFS and disk primitives:

```text
backend/src/
├── modules/
│   ├── commands/       # RecoveryCommandHandler, command DTOs and session state
│   ├── disk_discovery/ # Disk discovery service, DTOs, models, ports and repository contract
│   ├── catalog/        # Catalog service, DTOs and catalog snapshot model
│   └── recovery/       # Recovery service, planner, extractor, DTOs and result models
├── infrastructure/
│   └── persistence/    # JSON deep-scan repository implementation
├── disk/
│   ├── access/         # Raw physical-disk reads
│   ├── enumeration/    # Windows and Linux disk inventory
│   ├── partition_table/# MBR, EBR and GPT parsing
│   ├── ntfs_discovery/ # NTFS volume scanning and MFT-anchor resolution
│   ├── scanning/       # Chunk sources, signatures and MFT-anchor scanning
│   ├── deep_scan/      # Lost-partition search, orphan-MFT and bounded content carving
│   ├── safety/         # Keep recovery output off the source disk
│   ├── models.py       # PhysicalDisk, PartitionEntry and NTFSVolume
│   └── inventory.py    # DiskInventory composition facade
├── ntfs/               # MFT parsing, VFS construction and extraction collaborators
├── domain/              # Framework-independent recovery rules
└── backend_orchestrator.py # Composition root and JSON-lines process adapter
```

Each feature module owns its use-case service and the contracts/models specific to that feature. `RecoveryCommandHandler` maps validated command DTOs to those services and returns stable response DTOs. Repository interfaces are used for persistence; physical sector access is represented by replaceable disk-reader ports, not by a CRUD repository abstraction. The entry point only composes production dependencies and adapts JSON lines to commands.

The low-level modules are deliberately separate from the feature slices: `disk/` enumerates physical disks on Windows and Linux, parses MBR/GPT, discovers NTFS partitions and reads raw sectors; `domain/` owns catalog eligibility and hierarchical selection; and `ntfs/` parses MFT records and builds the virtual tree. The recovery module composes the NTFS content reader, signature validator and output writer. The catalog can reuse audited orphan records and perform separate bounded scans of trusted `$Bitmap`-free ranges and low-confidence orphan data runs.

* frontend/src/ (React client): Contains typed domain contracts, services, hooks, reusable styled-components and page composition.
* frontend/electron/ (Desktop shell): Owns Electron main/preload processes and the context-isolated IPC contract.
* `DiskInventory` composes discovery components. Deep scan searches a bounded disk prefix for a validated `$MFT` record zero before falling back to NTFS boot-sector scanning.

Frontend pages and components each live in a folder named after the unit. Keep the React entry point in `index.tsx` and its styled-components definitions in a separate `style.ts` file in the same folder.

## Recovery catalog and selection

`TreeBuilder` creates the in-memory folder/file catalog and keeps parent/child links on each `FileNode`. `RecoveryCatalog` applies file type and minimum-size rules, while the React client lazily loads folder children and sends hierarchical selections to the Python adapter. `CatalogService` builds the catalog and `RecoveryWorkflow` extracts selected files; JSON-line progress events keep the interface responsive while disk operations run in the Python child process.

Deleted records inside the mapped MFT fragments already appear in the normal catalog. The optional **Search for deleted files missing from the list** setting audits the physical disk, validates NTFS metadata and searches gaps outside the mapped MFT fragments. It retains USA-validated deleted file records with consistent metadata, a supported extension and complete resident data or a complete in-volume runlist. Candidate headers are checked with bounded reads; known signature mismatches are filtered, while unknown content remains labeled as unverified. `$Bitmap` evidence reports whether each candidate's data clusters are free, allocated, mixed or unknown; allocated bits indicate possible reuse and do not automatically reject a candidate.

The same opt-in workflow scans up to 1 GiB of ranges proved free by a complete, valid `$Bitmap` for contiguous JPEG, PNG and PDF candidates. The `$Bitmap` file's own runs and allocation bits are checked before those free ranges are trusted. Candidates use generated names under `Lost_Files_DeepScan/ContentCarving` because original names and paths are unavailable. JPEG marker/frame/scan structure is checked but image entropy is not decoded. PNG chunks and CRCs are checked and the IDAT stream is bounded-decompressed to the expected scanline length, but pixels are not rendered. PDFs require a parseable classic xref table and trailer; xref streams are not currently accepted. The trusted-free scan is bounded to 32 MiB per file, 128 MiB retained content, 256 files, 768 MiB total candidate reads and 256 MiB candidate reads per format. A 64 MiB PNG decompressed-output cap also applies. Per-format and aggregate limit flags are reported separately.

Two additional passes target only locatable in-volume data runs named by orphan MFT records: `bitmap_unobserved` tails beyond the observed `$Bitmap` prefix, and `possibly_reused` runs containing allocated bits. These results are kept separately under `Lost_Files_DeepScan/LowConfidence/BitmapUnobserved` and `.../PossiblyReused`. They may refer to current or reused file content and are not marked as confirmed deleted. Each tier retains at most 128 MiB and 4,096 ranges, scans at most 128 MiB, reads at most 48 MiB of candidate data (16 MiB per format), retains at most 32 MiB across 64 files and limits an individual file to 16 MiB. Lower-confidence duplicates are omitted when a higher-confidence candidate with the same offset or content was already added. All carving is additional bounded I/O after the disk audit; it cannot restore overwritten data, reconstruct fragmentation or prove that a candidate will decode in its target application. The source remains read-only.

The output directory is checked against the source physical disk before recovery starts. Extraction results carry a status and reason per file. Incomplete disk reads and MFT data extents are not counted as successful recoveries.

## Full-disk validation

The JSON-lines backend exposes a `validate_disk` operation for a selected physical disk:

```json
{"id":"audit-1","operation":"validate_disk","payload":{"diskNumber":0}}
```

This operation reads the addressable disk sequentially, tracks uniquely covered byte intervals and read errors, checks MBR and primary/backup GPT structures, looks for NTFS boot sectors across the full disk, and reports FAT/exFAT boot-signature candidates for follow-up. For validated NTFS volumes it compares primary and backup boot sectors, compares the first MFT records with `$MFTMirr`, counts allocated/deleted and structurally inconsistent MFT records, checks `$Bitmap` size and allocation bits for MFT, mirror and bitmap-storage clusters, and reports per-orphan data-cluster allocation evidence. During catalog creation, the selected-volume orphan records, bitmap-derived free ranges and locatable uncertain orphan runs are passed forward for separate bounded carving tiers, avoiding a repeat of the full audit or selected-volume orphan scan.

The response's `coverageStatus` is `incomplete` when any bytes could not be read or a read failed. `assessment` remains `inconclusive` when coverage is incomplete, a partition/filesystem is unsupported or unvalidated, NTFS metadata checks fail, or recoverable deleted records are found. A complete read is evidence only; it does not prove that the disk is empty or contains no recoverable files. FAT/exFAT signatures are candidates only and are not yet fully parsed. The operation can take hours and performs additional reads during metadata checks; keep the source read-only and use a separate destination disk for any recovery.

## Prerequisites

* Windows or Linux for physical-disk discovery and raw reads.
* Python 3.10 or higher for backend development and package generation. The Windows and Linux desktop packages bundle the backend runtime.
* Administrator/root authorization for raw physical-disk reads. On Linux, a PolicyKit authentication agent and `pkexec` are used to authorize only the Python recovery service.
* Node.js/npm for the Electron, React and TypeScript interface.
The NTFS recovery pipeline is shared across platforms. Linux support uses sysfs for disk inventory and read-only positional I/O on `/dev` block devices. Linux x64 AppImage and Debian packaging is experimental; the build pipeline validates packages, but testing on physical Linux systems is still required before a distributable Linux release.

## Electron development UI

The Electron app keeps the recovery engine in Python and starts `backend/src/backend_orchestrator.py` as a local child process. You do not start a separate Python server. From the `frontend` directory, install the dependencies and launch the development UI:

```powershell
npm install
npm run dev
```

`npm run dev` starts the Vite development server and Electron. Electron's main process launches the Python adapter automatically, using the repository virtual environment when available or the platform Python executable otherwise. Set `DISK_RESURRECT_PYTHON` to override that executable. On Windows, the app can request UAC elevation. On Linux, it can request PolicyKit authorization for the Python service through `pkexec`; the Electron UI remains at the user's normal privilege level. Source disks are opened read-only; recovered files are written only to the chosen destination. If authorization is declined, physical-disk operations stay unavailable.

## Downloads

Pushing a version tag such as `v0.2.0` runs the release workflow. It builds Windows and Linux x64 packages in parallel and publishes the resulting files together in one GitHub Release:

* `DiskRessurect-<version>-win-x64-Setup.exe` installs the Windows app.
* `DiskRessurect-<version>-win-x64-portable.zip` contains the one-folder Windows app for users who prefer not to install it.
* `SHA256SUMS.txt` contains checksums for the Windows downloads.
* `DiskRessurect-<version>-linux-x86_64.AppImage` is a portable Linux x64 package.
* `DiskRessurect-<version>-linux-amd64.deb` installs the Linux x64 app on Debian-based distributions.
* `SHA256SUMS-linux-x64.txt` contains checksums for the Linux downloads.

Download the packages from the [GitHub Releases page](https://github.com/LuizzFelipe0/disk-ressurect/releases). Tags containing a prerelease suffix, such as `v0.2.0-test`, are published as prereleases. To build the same files locally on Windows, run `packaging/windows/build.ps1` from PowerShell; to build Linux packages locally, run `bash packaging/linux/build.sh` on Linux x64. The release executables are unsigned, so Windows may show a SmartScreen publisher warning.

## Linux packages (experimental)

Linux builds currently target x64 AppImage and Debian packages. The version-tag release workflow builds these packages automatically and attaches them to the same GitHub Release as the Windows downloads. To build locally on a Linux x64 machine, place the `disk-ressurect` and `belagio-styles-lib` checkouts in the sibling layout expected by `frontend/package.json`, then run:

```bash
bash packaging/linux/build.sh
```

The script builds the shared PyInstaller backend, runs backend and frontend tests, builds the Electron app, creates both packages and writes `SHA256SUMS-linux-x64.txt` under `dist/`. The release workflow checks out `belagio-styles-lib` from its `development` branch and publishes the packages automatically. Keep that library branch current with the UI API used here before expecting the workflow to pass. The AppImage is configured with electron-builder's static runtime toolset `1.0.3`; its launcher can add `--no-sandbox` only when user namespaces are unavailable. Debian packages declare `policykit-1`; AppImage users need `pkexec` and an active PolicyKit authentication agent for physical-disk access. Launch the desktop app as the normal user; only the Python recovery service requests elevated access, and recovered files and scan-cache files are returned to the authorizing user. These Linux packages are experimental until they are tested on physical Linux systems and disposable recovery media.

## How to Use

Users select a physical source disk, discover its NTFS partitions, choose an output folder and supported file types, then select folders or individual files. Enable **Search for deleted files missing from the list** before building the catalog to search areas outside the normal file list; this can take a long time. MBR (including logical partitions) and GPT partition tables are supported. If no partition is listed, **Deep scan lost partitions** first searches up to 8 GiB from the disk start for a validated `$MFT` root record. When it can derive a consistent partition start and runlist from that record, it offers a candidate whose end is estimated at the physical disk end; the boot sector and partition-table entry may have been overwritten. If this quick path finds no usable anchor, the scanner falls back to a full read-only search for NTFS primary/backup boot sectors. That fallback may take hours on large or slow disks.

Validated candidates found during deep scans are checkpointed to `deep_scan_cache.json` under Electron's per-user `userData` directory. Cache entries are keyed by disk model, capacity and serial number (or disk number when no serial is available), so candidates are restored only for the matching source disk. A scan interruption keeps already discovered candidates; completed scans replace the old candidate set. Selecting the same disk after reopening the app restores those candidates without rerunning the scan.

Keep the output destination on a different physical disk from the source. A lost partition cannot be reconstructed if its NTFS boot sectors and MFT metadata have both been overwritten. When **Search for deleted files missing from the list** is enabled, building the catalog audits the selected disk, reuses its selected-volume orphan scan and tries the bounded trusted-free and low-confidence carving tiers described above. The UI shows audit coverage, read errors, MFT counts, orphan cluster-allocation evidence, per-format carving counts and any reached limits. The process can take hours, and even complete coverage or structurally valid carving candidates are evidence only; they do not prove successful recovery or that a disk is empty. This is a test build: validate on disposable images or duplicate media before relying on it for important recovery work.

## Tests

Run the Python unit suite without accessing a physical disk (discovery uses synthetic media) and the React tests:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s backend\src\tests -v
Push-Location frontend
npm test
Pop-Location
```
