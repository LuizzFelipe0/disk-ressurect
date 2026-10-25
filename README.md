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

* disk/ (I/O Layer): Enumerates Windows physical disks, parses MBR/GPT partition tables, discovers NTFS volumes and handles raw sector access via the Win32 API.
* application/ (Use cases): Coordinates catalog scans, extraction and reports through injected disk dependencies.
* domain/ (Recovery rules): Owns catalog eligibility and hierarchical selection, independent of the GUI toolkit.
* gui/ (Presentation): Provides the tkinter/ttk window, reusable controls, lazy folder/file browser and background task polling.
* disk/inventory.py (Discovery): Finds attached physical disks and NTFS partitions; deep scan first searches a bounded disk prefix for a validated `$MFT` record zero, then falls back to NTFS boot-sector scanning.
* ntfs/ (VFS Layer): Contains the MFT Parser and Tree Builder, responsible for linking parent-child relationships and resolving absolute paths.
* extractor.py (Extraction Layer): Applies filtering rules and safely extracts files to the destination drive.

## Recovery catalog and selection

`TreeBuilder` creates the in-memory folder/file catalog and keeps parent/child links on each `FileNode`. `RecoveryCatalog` applies file type and minimum-size rules, while `RecoverySelection` tracks checked files and ancestor counts. The GUI uses a folder-only navigation tree on the left and a table of the selected folder's direct files on the right, like a file browser. Folder rows are loaded as the user opens them, so the interface does not eagerly construct a widget for every MFT entry. Folder checkbox states update incrementally; file type filters are applied once from the selection dialog. `RecoveryWorkflow` runs scan and extraction use cases; a background Python thread sends progress events through a queue so disk operations do not block the interface.

The output directory is checked against the source physical disk before recovery starts. Extraction results carry a status and reason per file, and the report includes rejection counts by extension. Incomplete disk reads and MFT data extents are not counted as successful recoveries.

## Prerequisites

* Windows OS (Relies on `ctypes.windll.kernel32` API).
* Python 3.10 or higher.
* Administrator Privileges (Mandatory for reading raw physical drives via `\\.\PhysicalDrive`).
* Tkinter/ttk, included with the standard Windows Python installer (ensure Tcl/Tk is selected during Python setup).

## How to Use

Launch the desktop application from the repository root:

```powershell
.\venv\Scripts\python.exe src\gui_main.py
```

The GUI uses only Tkinter and ttk from Python's standard library. It provides a light, iOS-inspired theme, reusable cards and controls, a resizable folder/file browser, and scrollable file type choices. Users select a physical source disk, discover its NTFS partitions, choose an output folder and supported file types, then select folders or individual files. MBR (including logical partitions) and GPT partition tables are supported. If no partition is listed, **Deep scan lost partitions** first searches up to 8 GiB from the disk start for a validated `$MFT` root record. When it can derive a consistent partition start and runlist from that record, it offers a candidate whose end is estimated at the physical disk end; the boot sector and partition-table entry may have been overwritten. If this quick path finds no usable anchor, the scanner falls back to a full read-only search for NTFS primary/backup boot sectors. That fallback may take hours on large or slow disks.

Keep the output destination on a different physical disk from the source. The application requires Administrator privileges for raw disk reads and requests elevation when launched. A lost partition cannot be reconstructed if its NTFS boot sectors and MFT metadata have both been overwritten. This is a test build: validate on disposable images or duplicate media before relying on it for important recovery work.

## Tests

Run the unit suite without accessing a physical disk (discovery is exercised against synthetic media; Tkinter is needed for GUI tests):

```powershell
.\venv\Scripts\python.exe -m unittest discover -s src\tests -v
```
