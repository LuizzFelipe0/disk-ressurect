$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
$baselineRef = "e5f170d"
$codexMain = Join-Path $repoRoot "src\main.py"
$githubLog = Join-Path $env:TEMP "disk-ressurect-github-benchmark.log"
$codexLog = Join-Path $env:TEMP "disk-ressurect-codex-benchmark.log"
$baselineOutput = "D:\HD Interno\_benchmark_github"
$codexOutput = "D:\HD Interno\_benchmark_codex"
$baselineRoot = Join-Path $env:TEMP ("disk-ressurect-baseline-" + [guid]::NewGuid().ToString("N"))
$archivePath = "$baselineRoot.zip"
$previousOutputDir = $env:DISK_RESURRECT_OUTPUT_DIR

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run PowerShell as Administrator before comparing physical disk scans."
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment was not found: $python"
}

try {
    # Materialize the historical source from Git into TEMP. This keeps only
    # one copy of project code in the repository.
    New-Item -ItemType Directory -Path $baselineRoot | Out-Null
    Push-Location $repoRoot
    try {
        & git archive --format=zip --output=$archivePath $baselineRef src
        if ($LASTEXITCODE -ne 0) { throw "Could not export baseline revision $baselineRef" }
    } finally {
        Pop-Location
    }
    Expand-Archive -LiteralPath $archivePath -DestinationPath $baselineRoot
    Remove-Item -LiteralPath $archivePath -Force

    $baselineSource = Join-Path $baselineRoot "src"
    $githubMain = Join-Path $baselineSource "main.py"
    $baselineMainText = Get-Content -LiteralPath $githubMain -Raw
    $baselineMainText = $baselineMainText.Replace(
        'OUTPUT_DIR = r"D:\HD Interno"',
        'OUTPUT_DIR = r"D:\HD Interno\_benchmark_github"'
    )
    if (-not $baselineMainText.Contains('_benchmark_github')) {
        throw "Could not set the baseline output directory in its temporary main.py"
    }
    [IO.File]::WriteAllText($githubMain, $baselineMainText, [Text.UTF8Encoding]::new($false))
    New-Item -ItemType Directory -Path $baselineOutput -Force | Out-Null
    New-Item -ItemType Directory -Path $codexOutput -Force | Out-Null

    Write-Host "=== GitHub baseline ($baselineRef) ==="
    Write-Host "Legacy baseline has no built-in progress bar; measuring its total runtime."
    $baselineTimer = [Diagnostics.Stopwatch]::StartNew()
    Push-Location $baselineSource
    try {
        & $python $githubMain 2>&1 | Tee-Object -FilePath $githubLog
        $baselineExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
        $baselineTimer.Stop()
    }
    Write-Host "[*] [Run] Baseline wall time: $($baselineTimer.Elapsed.ToString('hh\:mm\:ss'))"
    if ($baselineExitCode -ne 0) { throw "GitHub baseline failed with exit code $baselineExitCode" }

    Write-Host "=== Codex / branch feature/gui-interface ==="
    $env:DISK_RESURRECT_OUTPUT_DIR = $codexOutput
    Push-Location (Join-Path $repoRoot "src")
    try {
        & $python $codexMain 2>&1 | Tee-Object -FilePath $codexLog
        $codexExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
        if ($null -eq $previousOutputDir) {
            Remove-Item Env:\DISK_RESURRECT_OUTPUT_DIR -ErrorAction SilentlyContinue
        } else {
            $env:DISK_RESURRECT_OUTPUT_DIR = $previousOutputDir
        }
    }
    if ($codexExitCode -ne 0) { throw "Current branch failed with exit code $codexExitCode" }

    Write-Host "Logs: $githubLog | $codexLog"
} finally {
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    $tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
    $resolvedBaselineRoot = [IO.Path]::GetFullPath($baselineRoot)
    if ($resolvedBaselineRoot.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedBaselineRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($null -eq $previousOutputDir) {
        Remove-Item Env:\DISK_RESURRECT_OUTPUT_DIR -ErrorAction SilentlyContinue
    } else {
        $env:DISK_RESURRECT_OUTPUT_DIR = $previousOutputDir
    }
}
