$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = if (Test-Path '.venv/Scripts/python.exe') { '.venv/Scripts/python.exe' } else { 'python' }
& $python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE) { throw 'Dependency installation failed' }
& $python scripts/check_publication.py --source .
if ($LASTEXITCODE) { throw 'Source publication checks failed' }
& $python -m pytest -q -W error
if ($LASTEXITCODE) { throw 'Tests failed' }
& $python scripts/verify_gui.py
if ($LASTEXITCODE) { throw 'Real GUI workflow failed' }
& $python -m PyInstaller --clean --noconfirm --windowed --onedir --name FolderPilot --add-data 'LICENSE;.' --add-data 'THIRD_PARTY_NOTICES.md;.' --add-data 'licenses;licenses' --add-data 'README.md;.' --add-data 'QUICK_START.md;.' --add-data 'FEATURES.md;.' --add-data 'examples;examples' --add-data 'docs/screenshots;docs/screenshots' run_app.py
if ($LASTEXITCODE) { throw 'Windows build failed' }
$exe = (Resolve-Path 'dist/FolderPilot/FolderPilot.exe').Path
$p = Start-Process -FilePath $exe -ArgumentList '--smoke-test' -WindowStyle Hidden -PassThru
if (-not $p.WaitForExit(30000)) { $p.Kill(); throw 'EXE GUI startup timeout' }
if ($p.ExitCode -ne 0) { throw 'EXE GUI startup failed' }

$probe = Join-Path (Get-Location) 'dist/packaged-verification.json'
$p = Start-Process -FilePath $exe -ArgumentList @('--self-test','--verification-output',('"' + $probe + '"')) -WindowStyle Hidden -PassThru
if (-not $p.WaitForExit(60000)) { $p.Kill(); throw 'EXE core workflow timeout' }
if ($p.ExitCode -ne 0 -or -not (Test-Path $probe)) { throw 'EXE core workflow failed' }

& $python scripts/check_publication.py --package dist/FolderPilot --output dist/publication-check.json
if ($LASTEXITCODE) { throw 'Package publication checks failed; no ZIP produced' }
Compress-Archive -Path 'dist/FolderPilot' -DestinationPath 'dist/FolderPilot-v0.1.1-windows-x64.zip' -Force
$hash = (Get-FileHash 'dist/FolderPilot-v0.1.1-windows-x64.zip' -Algorithm SHA256).Hash.ToLower()
Set-Content 'dist/SHA256SUMS.txt' ($hash + '  FolderPilot-v0.1.1-windows-x64.zip') -Encoding ascii
Write-Output "Verified Windows package SHA256 $hash"
