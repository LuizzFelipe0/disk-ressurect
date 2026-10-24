import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from disk.raw_disk import RawDisk
from disk.carver import Carver
from ntfs.tree_builder import TreeBuilder
from disk.scanner import DiskScanner

DISK_NUM = 2
OUTPUT = r"D:\HD_Recuperado_DeepScan"

# O mesmo mapa da MFT usado no main.py
MFT_FRAGMENTS = [
    {"phys": 0xC6500000, "count": 113664, "base_idx": 0},
    {"phys": 0xfce823000, "count": 500000, "base_idx": 113664}
]

def generate_blacklist(vfs):
    """Mapeia os clusters ocupados por arquivos da pasta indesejada."""
    blocked_lcns = set()
    print("[*] Gerando mapa de clusters para ignorar arquivos do backup...")

    for node in vfs.values():
        if "bkp fotos notebook" in node.full_path.lower():
            if not node.record.is_dir:
                for lcn, length in node.record.data_runs:
                    if lcn is not None:
                        # Adiciona todos os clusters que compõem este arquivo na blacklist
                        for i in range(length):
                            blocked_lcns.add(lcn + i)

    return blocked_lcns

def run_smart_carver():
    disk = RawDisk(DISK_NUM)

    # 1. Monta o VFS para sabermos onde os arquivos indesejados estão
    print("[*] Construindo Sistema de Arquivos Virtual (VFS) para análise...")
    builder = TreeBuilder(disk, MFT_FRAGMENTS, mft_base_offset=MFT_FRAGMENTS[0]['phys'])
    vfs = builder.build()

    # 2. Gera a Blacklist
    blacklist = generate_blacklist(vfs)

    # 3. Inicia o Carver
    carver = Carver(disk)
    carver.set_blocked_clusters(blacklist)

    # Varre a zona de destruição (0 a 25GB)
    start = 0
    end = 25 * 1024 * 1024 * 1024

    carver.carve(start, end, OUTPUT)

    disk.close()

if __name__ == "__main__":
    run_smart_carver()