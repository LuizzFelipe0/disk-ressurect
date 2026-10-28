param(
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$spec = Join-Path $PSScriptRoot "DiskRessurect.spec"
$backendDist = Join-Path $repoRoot "dist\backend"
$work = Join-Path $repoRoot "build\pyinstaller"

if (-not $PythonExecutable) {
    $venvPython = Join-Path $repoRoot "venv\Scripts\python.exe"
    $PythonExecutable = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
}

& $PythonExecutable -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install the PyInstaller build dependency." }

& $PythonExecutable -m PyInstaller --noconfirm --clean --distpath $backendDist --workpath $work $spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed to build the Python recovery service." }

Push-Location (Join-Path $repoRoot "frontend")
try {
    npm test
    if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed." }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    npm run package:win
    if ($LASTEXITCODE -ne 0) { throw "Windows desktop packaging failed." }

    $version = (npm pkg get version | ConvertFrom-Json)
    $portableArchive = Join-Path $repoRoot "dist\DiskRessurect-$version-win-x64-portable.zip"
    $unpackedApp = Join-Path $repoRoot "dist\win-unpacked"
    if (Test-Path -LiteralPath $portableArchive) { Remove-Item -LiteralPath $portableArchive -Force }
    Compress-Archive -Path (Join-Path $unpackedApp "*") -DestinationPath $portableArchive
    $installer = Join-Path $repoRoot "dist\DiskRessurect-$version-win-x64-Setup.exe"
    $checksums = @($installer, $portableArchive) | ForEach-Object {
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_
        "$($hash.Hash)  $([System.IO.Path]::GetFileName($_))"
    }
    Set-Content -LiteralPath (Join-Path $repoRoot "dist\SHA256SUMS.txt") -Value $checksums -Encoding ascii
} finally {
    Pop-Location
}

Write-Host "Backend executable: $(Join-Path $backendDist 'backend_orchestrator.exe')"
Write-Host "Windows installer and portable ZIP: $(Join-Path $repoRoot 'dist')"
