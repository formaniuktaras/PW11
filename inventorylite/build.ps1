param(
    [string]$PythonPath = "python"
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $scriptDir "..")

Write-Host "Building InventoryLite..."

# Check python
try {
    & $PythonPath --version | Out-Null
} catch {
    Write-Error "Python not found. Install Python 3.12."; exit 1
}

$venvPath = ".\.venv"
if (-Not (Test-Path $venvPath)) {
    & $PythonPath -m venv $venvPath
}

. "$venvPath/Scripts/Activate.ps1"

python -m pip install --upgrade pip
python -m pip install -r inventorylite/requirements.txt

python -m compileall inventorylite
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python compileall failed"
    exit 1
}

$iconBase64 = Get-Content -Raw "inventorylite/icons/app_ico_base64.txt"
[IO.File]::WriteAllBytes("inventorylite/icons/app.ico", [Convert]::FromBase64String($iconBase64))

$iconPath = "inventorylite/icons/app.ico"
$fontArgs = ""
if (Test-Path "./inventorylite/assets/fonts/DejaVuSans.ttf") {
    $fontArgs = "--add-data \"inventorylite/assets/fonts/DejaVuSans.ttf;inventorylite/assets/fonts\""
    if (Test-Path "./inventorylite/assets/fonts/DejaVuSans-Bold.ttf") {
        $fontArgs = "$fontArgs --add-data \"inventorylite/assets/fonts/DejaVuSans-Bold.ttf;inventorylite/assets/fonts\""
    }
}

$cmd = "pyinstaller --onefile --noconsole --name InventoryLite --icon $iconPath $fontArgs inventorylite/app.py --collect-submodules inventorylite"
Write-Host "Running: $cmd"
Invoke-Expression $cmd

if (Test-Path "dist/InventoryLite.exe") {
    Write-Host "Build complete: $(Resolve-Path dist/InventoryLite.exe)"
} else {
    Write-Error "Build failed"
    exit 1
}
