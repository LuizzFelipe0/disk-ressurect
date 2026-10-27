# disk-ressurect

A NTFS data recovery and forensic engine written in pure Python. This software is designed to recover files from formatted, corrupted, or partially overwritten disks using raw disk access and Master File Table (MFT) reconstruction.

## Features

Unlike basic file carvers that recover files without names, this engine reconstructs the original directory tree whenever possible.

* Virtual File System (VFS): Reads the $MFT and mounts the original folder structure in memory before extraction.
* Ghost MFT Carving: The orphan-record carver remains available as a later catalog enhancement; the desktop workflow builds the catalog from the selected volume's MFT fragments.
* Smart Header Validation: Reads physical file signatures (magic numbers) during extraction to skip corrupted or overwritten files.
* Deep Scan (File Carver): A fallback raw signature scanner for data located in unallocated space.
* User-controlled selection: The recovery catalog exposes the original folder tree, and users choose both folders and supported file types. No folder names are excluded by default.

## Architecture

The project is structured into independent layers to ensure scalability for future disk recoveries:

* backend/src/disk/ (I/O and discovery): Enumerates Windows physical disks, parses MBR/GPT, discovers NTFS partitions and reads raw sectors.
* backend/src/application/ (Use cases): Coordinates catalog scans, extraction and reports through injected disk dependencies.
* backend/src/domain/ (Recovery rules): Owns catalog eligibility and hierarchical selection.
* backend/src/ntfs/ (VFS and extraction): Parses MFT records, builds the virtual tree and safely extracts files.
* backend/src/electron_backend.py (Desktop adapter): Exposes disk discovery, catalog browsing and recovery over JSON lines.
* frontend/src/ (React client): Contains typed domain contracts, services, hooks, reusable styled-components and page composition.
* frontend/electron/ (Desktop shell): Owns Electron main/preload processes and the context-isolated IPC contract.
* backend/src/disk/inventory.py (Discovery): Deep scan searches a bounded disk prefix for a validated `$MFT` record zero before falling back to NTFS boot-sector scanning.

## Recovery catalog and selection

`TreeBuilder` creates the in-memory folder/file catalog and keeps parent/child links on each `FileNode`. `RecoveryCatalog` applies file type and minimum-size rules, while the React client lazily loads folder children and sends hierarchical selections to the Python adapter. `RecoveryWorkflow` runs scans and extraction; JSON-line progress events keep the interface responsive while disk operations run in the Python child process.

The output directory is checked against the source physical disk before recovery starts. Extraction results carry a status and reason per file, and the report includes rejection counts by extension. Incomplete disk reads and MFT data extents are not counted as successful recoveries.

## Prerequisites

* Windows OS for physical-disk discovery and raw reads (the current backend uses Win32 APIs).
* Python 3.10 or higher.
* Administrator Privileges (Mandatory for reading raw physical drives via `\\.\PhysicalDrive`).
* Node.js/npm for the Electron, React and TypeScript interface.
The Electron UI is the desktop frontend. It is portable to Linux, but the current Python disk inventory and raw-disk reader are Windows-specific. A Linux release will also need Linux disk enumeration, raw block-device reads and the appropriate privilege handling before it can recover disks there.

## Electron development UI

The Electron app keeps the recovery engine in Python and starts `backend/src/electron_backend.py` as a local child process. You do not start a separate Python server. From the `frontend` directory, install the dependencies and launch the development UI:

```powershell
npm install
npm run dev
```

`npm run dev` starts the Vite development server and Electron. Electron's main process launches the Python adapter automatically, using the repository `venv` when available or `python` otherwise. Set `DISK_RESURRECT_PYTHON` to override that executable. On Windows, the app asks whether to continue with Administrator access; approving it opens the standard UAC prompt and relaunches the app elevated. Source disks are opened read-only; recovered files are written only to the chosen destination. If elevation is declined, the app remains open and physical-disk operations stay unavailable. This development build is not yet a distributable installer; packaging must bundle the Python runtime and recovery modules with Electron.

## How to Use

Users select a physical source disk, discover its NTFS partitions, choose an output folder and supported file types, then select folders or individual files. MBR (including logical partitions) and GPT partition tables are supported. If no partition is listed, **Deep scan lost partitions** first searches up to 8 GiB from the disk start for a validated `$MFT` root record. When it can derive a consistent partition start and runlist from that record, it offers a candidate whose end is estimated at the physical disk end; the boot sector and partition-table entry may have been overwritten. If this quick path finds no usable anchor, the scanner falls back to a full read-only search for NTFS primary/backup boot sectors. That fallback may take hours on large or slow disks.

Keep the output destination on a different physical disk from the source. A lost partition cannot be reconstructed if its NTFS boot sectors and MFT metadata have both been overwritten. This is a test build: validate on disposable images or duplicate media before relying on it for important recovery work.

## Tests

Run the Python unit suite without accessing a physical disk (discovery uses synthetic media) and the React tests:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s backend\src\tests -v
Push-Location frontend
npm test
Pop-Location
```
