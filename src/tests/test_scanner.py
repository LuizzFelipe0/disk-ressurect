import sys
import os

# 1. Pega o caminho absoluto de onde este script (test_1.py) está
current_dir = os.path.dirname(os.path.abspath(__file__))
# 2. Volta uma pasta para chegar na raiz 'src'
src_dir = os.path.dirname(current_dir)
# 3. Adiciona a pasta 'src' aos caminhos que o Python reconhece
sys.path.append(src_dir)

# Agora podemos fazer a importação absoluta sem o ponto
from disk.scanner import DiskScanner

print("[*] Iniciando testes do Scanner...")
scanner = DiskScanner(disk_number=2)

# Tenta o método 1
vol_start = scanner.discover_via_mft_record(0xC6500000)

# Se falhar, tenta o método 2
if not vol_start:
    vol_start = scanner.discover_via_vbr(expected_mft_phys=0xC6500000)

# O "Fundo do baú" estatístico
if not vol_start:
    vol_start = scanner.discover_via_triangulation(0xfce823000)

scanner.close()