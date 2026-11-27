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

Tier 1 also includes an in-memory session-continuation workload. It compares the existing contiguous carver with the `RecoverySession` → `CatalogScanWorkflow` → `CatalogBuilder` path for a complete PNG made of two cluster-aligned `IDAT` chunks separated by a foreign chunk. The fifth-signature case demonstrates continuation beyond the four-signature strategy pass; the SHA-256 is read by the benchmark oracle only after the workflow finishes. This is a narrow synthetic gain, not general PNG defragmentation or a physical-media performance claim.

That workload reports total and unique source reads, reconstruction reads, evaluated combinations, session/checkpoint retained-memory estimates, `tracemalloc`/process-memory measurements and stop reasons. The PNG reconstructor's declared limits are reported independently: 64 candidate evaluations per pass, four passes (256 cumulative), 8 MiB reads per pass (32 MiB cumulative), 2 MiB per candidate, 2 seconds per pass (8 seconds cumulative), and a 16 MiB retained-object estimate. These are separate from the 4-signature strategy batch, 256-signature retained window, and dataset-size ceiling. Retained-object accounting is an estimate and does not represent process RSS. Tiny in-memory timings are smoke measurements only.

## Package boundary

The Python packager analyzes only `backend/src/bootstrap.py` and collects `application`, `infrastructure`, `modules` and `presentation` from `backend/src`. This package is a sibling of `src`, and production source has no imports from `recovery`. Test-only Pillow is listed in `backend/requirements-test.txt`; production packaging requirements do not install it. Electron Builder packages frontend `dist`, its package metadata and the separately built backend executable; it does not include the repository's `backend/benchmarks` directory.
