import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)
sys.path.append(src_dir)

from disk.raw_disk import RawDisk
from ntfs.tree_builder import TreeBuilder

print("[*] Testando a montagem do Sistema de Arquivos Virtual (VFS)...")

disk = RawDisk(2)

MFT_FRAGMENTS = [
    {"phys": 0xC6500000, "count": 113664, "base_idx": 0},
    {"phys": 0xfce823000, "count": 200000, "base_idx": 113664}
]

builder = TreeBuilder(disk, MFT_FRAGMENTS)
vfs = builder.build()

print("\n--- AMOSTRAGEM DO SISTEMA DE ARQUIVOS ---")
fotos_encontradas = 0

for idx, node in vfs.items():
    if not node.record.is_dir and node.full_path.lower().endswith(".jpg"):
        print(f"ID: {idx:6} | Caminho Virtual: {node.full_path} | Tamanho: {node.record.file_size // 1024} KB")
        fotos_encontradas += 1
        if fotos_encontradas >= 20:
            break

print(f"\n[!] VFS Montado com sucesso. Ele agora gerencia {len(vfs)} itens na memória.")
disk.close()