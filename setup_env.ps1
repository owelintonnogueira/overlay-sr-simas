# Prepara o ambiente: Python (venv), pacotes e ferramentas (ffmpeg + deno). Usado pelo build e pelo modo "sem instalar".
param([switch]$CI)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-Location $PSScriptRoot

function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }

# ---------- Python ----------
Step "Procurando Python"
$pyExe = $null
if ($CI) {
    $pyExe = (Get-Command python).Source
} else {
    foreach ($v in @("3.11", "3.12")) {
        try {
            $p = & py "-$v" -c "import sys;print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $pyExe = $p.Trim(); break }
        } catch {}
    }
    if (-not $pyExe) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "Python 3.11 não encontrado. Instale em https://www.python.org/downloads/ (marque 'Add python.exe to PATH') e rode de novo."
        }
        Write-Host "Python 3.11 não encontrado. Instalando via winget (uma vez só)..."
        winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
        $cand = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
        if (Test-Path $cand) { $pyExe = $cand } else { throw "Instalei o Python, mas não o achei. Feche esta janela, abra de novo e rode outra vez." }
    }
}
Write-Host "Python: $pyExe"

Step "Criando ambiente virtual e instalando pacotes"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $pyExe -m venv .venv }
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar os pacotes." }

# ---------- ffmpeg / ffprobe ----------
New-Item -ItemType Directory -Force -Path vendor | Out-Null
if (-not ((Test-Path "vendor\ffmpeg.exe") -and (Test-Path "vendor\ffprobe.exe"))) {
    Step "Baixando ffmpeg (corte e legenda de vídeo)"
    $zip = Join-Path $env:TEMP "ffmpeg-win64.zip"
    $dir = Join-Path $env:TEMP "ffmpeg-win64"
    Invoke-WebRequest "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -OutFile $zip
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
    Expand-Archive $zip -DestinationPath $dir -Force
    $bin = Get-ChildItem $dir -Recurse -Filter ffmpeg.exe | Select-Object -First 1
    Copy-Item $bin.FullName "vendor\ffmpeg.exe" -Force
    Copy-Item (Join-Path $bin.DirectoryName "ffprobe.exe") "vendor\ffprobe.exe" -Force
}

# ---------- deno (necessário para baixar do YouTube) ----------
if (-not (Test-Path "vendor\deno.exe")) {
    Step "Baixando deno (necessário para links do YouTube)"
    $zip = Join-Path $env:TEMP "deno-win64.zip"
    Invoke-WebRequest "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath "vendor" -Force
}

Step "Ambiente pronto"
