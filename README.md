# disk-ressurect

A NTFS data recovery and forensic engine written in pure Python. This software is designed to recover files from formatted, corrupted, or partially overwritten disks using raw disk access and Master File Table (MFT) reconstruction.

## Features

Unlike basic file carvers that recover files without names, this engine reconstructs the original directory tree whenever possible.

* Virtual File System (VFS): Reads the $MFT and mounts the original folder structure in memory before extraction.
* Ghost MFT Carving: Hunts for orphaned MFT records in unallocated space to rescue files whose directory references were destroyed.
* Smart Header Validation: Reads physical file signatures (magic numbers) during extraction to skip corrupted or overwritten files.
* Deep Scan (File Carver): A fallback raw signature scanner for data located in unallocated space.
* Extraction Filters: Allows whitelisting specific extensions and blacklisting system directories to avoid extracting useless data.

## Architecture

The project is structured into independent layers to ensure scalability for future disk recoveries:

* disk/ (I/O Layer): Handles raw sector access via the Win32 API.
* scanner.py (Discovery): Uses mathematical triangulation and VBR scanning to discover partition offsets (VOL_START).
* ntfs/ (VFS Layer): Contains the MFT Parser and Tree Builder, responsible for linking parent-child relationships and resolving absolute paths.
* extractor.py (Extraction Layer): Applies filtering rules and safely extracts files to the destination drive.

## Prerequisites

* Windows OS (Relies on `ctypes.windll.kernel32` API).
* Python 3.8 or higher.
* Administrator Privileges (Mandatory for reading raw physical drives via `\\.\PhysicalDrive`).

## How to Use

To scale and use this engine on a new disk, you only need to adjust the configuration in the main script.

1. Identify the Physical Disk Number
Open Windows Disk Management (`diskmgmt.msc`) or use `diskpart` to find the target disk number (e.g., Disk 2).

2. Configure the Engine
Edit the main variables inside `src/main.py`:

```python
# Set the target disk and the safe destination folder
DISK_NUM = 2
OUTPUT_DIR = r"X:\Safe\Destination\Path"

# Define the physical MFT fragments
# (You can use the DiskScanner class to find these offsets dynamically)
MFT_FRAGS = [
    {"phys": 0xC6500000, "count": 113664, "base_idx": 0}
]