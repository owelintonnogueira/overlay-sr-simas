# Gera o instalador: installer_output\CortesLive-Setup.exe
param([switch]$CI)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-Location $PSScriptRoot
function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }

if ($CI) { & "$PSScriptRoot\setup_env.ps1" -CI } else { & "$PSScriptRoot\setup_env.ps1" }
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "Falha no setup." }
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Step "Empacotando o programa (PyInstaller) - pode levar alguns minutos"
& $venvPy -m pip install pyinstaller
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
& $venvPy -m PyInstaller CortesLive.spec --noconfirm --clean
if (-not (Test-Path "dist\CortesLive\CortesLive.exe")) { throw "O PyInstaller não gerou o .exe." }

Step "Criando o instalador (Inno Setup)"
function Find-Iscc {
    $c = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    foreach ($p in $c) { if ($p -and (Test-Path $p)) { return $p } }
    return $null
}
$iscc = Find-Iscc
if (-not $iscc) {
    Write-Host "Inno Setup não encontrado. Instalando..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install innosetup -y --no-progress
    }
    $iscc = Find-Iscc
}
if (-not $iscc) { throw "Não consegui instalar o Inno Setup. Instale em https://jrsoftware.org/isdl.php e rode de novo." }
& $iscc installer.iss
if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o instalador." }

Step "PRONTO"
Write-Host "Instalador: $PSScriptRoot\installer_output\CortesLive-Setup.exe" -ForegroundColor Green
