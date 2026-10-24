$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
$githubMain = Join-Path $repoRoot ".benchmark\github\src\main.py"
$codexMain = Join-Path $repoRoot "src\main.py"
$githubLog = Join-Path $env:TEMP "disk-ressurect-github-benchmark.log"
$codexLog = Join-Path $env:TEMP "disk-ressurect-codex-benchmark.log"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Abra o PowerShell como Administrador antes de executar esta comparação."
}
if (-not (Test-Path -LiteralPath $githubMain)) {
    throw "Cópia baseline do GitHub não encontrada: $githubMain"
}

Write-Host "=== GitHub baseline ==="
Push-Location (Split-Path -Parent $githubMain)
try {
    & $python $githubMain 2>&1 | Tee-Object -FilePath $githubLog
    if ($LASTEXITCODE -ne 0) { throw "Versão GitHub falhou com código $LASTEXITCODE" }
} finally {
    Pop-Location
}

Write-Host "=== Codex / branch feature/gui-interface ==="
$env:DISK_RESURRECT_OUTPUT_DIR = "D:\HD Interno\_benchmark_codex"
Push-Location (Join-Path $repoRoot "src")
try {
    & $python $codexMain 2>&1 | Tee-Object -FilePath $codexLog
    if ($LASTEXITCODE -ne 0) { throw "Versão Codex falhou com código $LASTEXITCODE" }
} finally {
    Pop-Location
    Remove-Item Env:\DISK_RESURRECT_OUTPUT_DIR -ErrorAction SilentlyContinue
}

Write-Host "Logs: $githubLog | $codexLog"
