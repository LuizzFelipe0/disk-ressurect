# Recovery benchmarks

This development-only package measures recovery components on deterministic synthetic sources. It is not imported by the production recovery engine and is excluded from the default backend test discovery.

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = 'backend\benchmarks'
$env:PYTHONDONTWRITEBYTECODE = '1'
.\venv\Scripts\python.exe -m recovery --tier 1 --output 'C:\Users\lfcan\Documents\Obsidian Vault\01 - Projects\Disk-Ressurect\Phase 5B benchmark results.json'
.\venv\Scripts\python.exe -m recovery --tier 64 --output 'C:\Users\lfcan\Documents\Obsidian Vault\01 - Projects\Disk-Ressurect\Phase 5B benchmark results.json'
.\venv\Scripts\python.exe -m recovery --tier 256 --output 'C:\Users\lfcan\Documents\Obsidian Vault\01 - Projects\Disk-Ressurect\Phase 5B benchmark results.json'
```

The 256 MiB tier is conditional on a reproducible and bounded 64 MiB result. Datasets are created in a prefixed temporary directory under `TEMP` and removed after each run. A 1 GiB or larger tier is not implemented. Ground-truth manifests are serialized only after recovery calls finish; production readers and strategies receive the source and eligible ranges, not oracle hashes or true offsets.

Focused tests use small in-memory readers:

```powershell
$env:PYTHONPATH = 'backend\benchmarks'
$env:PYTHONDONTWRITEBYTECODE = '1'
.\venv\Scripts\python.exe -m unittest discover -s backend\benchmarks\tests -v
```

## Package boundary

The Python packager analyzes only `backend/src/bootstrap.py` and collects `application`, `infrastructure`, `modules` and `presentation` from `backend/src`. This package is a sibling of `src`, and production source has no imports from `recovery`. Test-only Pillow is listed in `backend/requirements-test.txt`; production packaging requirements do not install it. Electron Builder packages frontend `dist`, its package metadata and the separately built backend executable; it does not include the repository's `backend/benchmarks` directory.
