$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "requirements.txt"
$spec = Join-Path $PSScriptRoot "DiskRessurect.spec"
$innoScript = Join-Path $PSScriptRoot "DiskRessurect.iss"
$dist = Join-Path $repoRoot "dist"
$work = Join-Path $repoRoot "build\pyinstaller"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtualenv not found: $python. Create venv and install the project Python first."
}

& $python -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw "Could not install the PyInstaller build dependency." }

& $python -m PyInstaller --noconfirm --clean --distpath $dist --workpath $work $spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed to build the one-folder application." }

$localIscc = Join-Path $repoRoot "build\InnoSetup6\ISCC.exe"
$iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $localIscc) {
    $isccPath = $localIscc
} elseif ($iscc) {
    $isccPath = $iscc.Source
} else {
    $candidatePaths = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $isccPath = $candidatePaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $isccPath) {
    throw "Inno Setup 6 was not found. Install Inno Setup 6, then rerun this script to compile the installer."
}

& $isccPath $innoScript
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed to compile the installer." }

Write-Host "One-folder build: $(Join-Path $dist 'DiskRessurect')"
Write-Host "Installer: $(Join-Path $dist 'installer\DiskRessurect-Setup-0.1.0-test.exe')"
