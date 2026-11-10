#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
frontend_dir="$repo_root/frontend"
belagio_dir="$(cd "$frontend_dir/../../belagio-solutions/belagio-styles-lib" 2>/dev/null && pwd)" || {
  echo "belagio-styles-lib checkout not found at the sibling path expected by frontend/package.json." >&2
  exit 1
}

cd "$repo_root"

if [[ ! -x "$repo_root/venv/bin/python" ]]; then
  python3 -m venv "$repo_root/venv"
fi
python_exec="$repo_root/venv/bin/python"
"$python_exec" -m pip install -r packaging/backend/requirements.txt

if [[ -f "$belagio_dir/package-lock.json" ]]; then
  npm ci --prefix "$belagio_dir"
else
  npm install --prefix "$belagio_dir"
fi
npm run --prefix "$belagio_dir" build

"$python_exec" -m unittest discover -s backend/src/tests -v

cd "$frontend_dir"
npm ci
npm test
npm run build

cd "$repo_root"
"$python_exec" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath dist/backend \
  --workpath build/pyinstaller \
  packaging/backend/DiskRessurect.spec
chmod 755 dist/backend/backend_orchestrator

cd "$frontend_dir"
npm run package:linux

shopt -s nullglob
artifacts=("$repo_root"/dist/DiskRessurect-*-linux-x64.AppImage "$repo_root"/dist/DiskRessurect-*-linux-x64.deb)
if [[ ${#artifacts[@]} -ne 2 ]]; then
  echo "Expected one x64 AppImage and one x64 deb package under $repo_root/dist." >&2
  exit 1
fi
artifact_names=()
for artifact in "${artifacts[@]}"; do
  artifact_names+=("${artifact##*/}")
done
(cd "$repo_root/dist" && sha256sum "${artifact_names[@]}") > "$repo_root/dist/SHA256SUMS-linux-x64.txt"
printf 'Linux packages created:\n'
printf '  %s\n' "${artifacts[@]}"
printf '  %s\n' "$repo_root/dist/SHA256SUMS-linux-x64.txt"
