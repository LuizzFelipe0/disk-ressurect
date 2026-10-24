import os
import sys
import subprocess

def select_physical_disk():
    """Lists connected physical disks and prompts the user to select one."""
    print("[*] Scanning connected physical disks...")
    try:
        # Replaced deprecated 'wmic' with native PowerShell command
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_DiskDrive | ForEach-Object { '{0} {1} {2}' -f $_.Index, $_.Model, $_.Size }"
        ]

        # Adding shell=True prevents WinError 2 on complex PATH environments
        output = subprocess.check_output(cmd, text=True, shell=True)
        lines = [line.strip() for line in output.split('\n') if line.strip()]

        print("\nID | Size (GB) | Disk Model")
        print("-" * 60)

        valid_disks = []

        # Parse the PowerShell output line by line
        for line in lines:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    disk_id = int(parts[0])
                    size_bytes = int(parts[-1])
                    model = " ".join(parts[1:-1])
                    size_gb = size_bytes / (1024**3)

                    valid_disks.append(disk_id)
                    print(f"[{disk_id}] | {size_gb:>8.2f} GB   | {model}")
                except ValueError:
                    continue # Skip empty or malformed lines

        print("-" * 60)

        while True:
            choice = input("\nEnter the ID of the disk to recover (or 'q' to quit): ")
            if choice.lower() == 'q':
                sys.exit(0)
            if choice.isdigit() and int(choice) in valid_disks:
                return int(choice)
            print("[!] Invalid option. Please enter a valid ID from the list.")

    except Exception as e:
        print(f"[!] Error listing disks: {e}")
        print("Make sure you are running the terminal as Administrator.")
        sys.exit(1)

def get_output_directory():
    """Prompts the user for a valid destination folder path."""
    while True:
        out_dir = input("\nEnter the output directory path (e.g., D:\\Recovered_Files): ").strip()

        if not out_dir:
            print("[!] Path cannot be empty.")
            continue

        try:
            # Attempt to create the directory to ensure we have write permissions
            os.makedirs(out_dir, exist_ok=True)
            return out_dir
        except Exception as e:
            print(f"[!] Invalid path or permission denied: {e}")
            print("Please try another folder.")