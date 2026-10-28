<#
.SYNOPSIS
Builds a 100% Portable, Zero-Admin-Rights Windows x64 Bundle (`dist\cardio-tagger-portable`)
on the Unrestricted Development Workstation for deployment to a Locked-Down 16GB RAM Windows Target PC.

.DESCRIPTION
Assembles:
  1. Python 3.11 Windows Embeddable Package (`python-3.11.9-embed-amd64.zip`) with `_pth` configured for local `site-packages`
  2. Microsoft VC++ Redistributable User-Local DLLs (`vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140.dll`) placed directly in `runtime\python\`
  3. Pre-installed offline site-packages (`pymupdf`, `pyahocorasick`, `medspacy`, `gliner`, `onnxruntime`, `rapidfuzz`, `duckdb`, `pyarrow`, `rapidocr-onnxruntime`)
  4. Offline INT8 GLiNER-BioMed configuration (`models\gliner_biomed_int8\`)
  5. Application source code (`app\cardio_tagger`) and non-admin launcher (`run_cardio_tagger.bat`)
#>
$ErrorActionPreference = "Continue"

$DistRoot = Join-Path $PSScriptRoot "..\..\dist\cardio-tagger-portable"
Write-Host "Assembling portable distribution at: $DistRoot"

New-Item -ItemType Directory -Force -Path "$DistRoot\runtime\python\Lib\site-packages" | Out-Null
New-Item -ItemType Directory -Force -Path "$DistRoot\runtime\ollama" | Out-Null
New-Item -ItemType Directory -Force -Path "$DistRoot\models\gliner_biomed_int8" | Out-Null
New-Item -ItemType Directory -Force -Path "$DistRoot\models\ollama" | Out-Null
New-Item -ItemType Directory -Force -Path "$DistRoot\app" | Out-Null

# [1/6] Python Embeddable Package
Write-Host "[1/6] Extracting Python 3.11 Embeddable x64 runtime..."
$PyZip = Join-Path $PSScriptRoot "..\..\python-3.11.9-embed-amd64.zip"
if (-not (Test-Path $PyZip)) {
    Write-Host "Downloading Python 3.11.9 embed zip..."
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip" -OutFile $PyZip
}
tar -xf $PyZip -C "$DistRoot\runtime\python"

# [2/6] Enable local site-packages & app in ._pth
Write-Host "[2/6] Configuring python311._pth for local site-packages & app..."
$PthFile = "$DistRoot\runtime\python\python311._pth"
@"
python311.zip
.
Lib\site-packages
..\..\app
import site
"@ | Set-Content -Path $PthFile -Encoding UTF8

# [3/6] Bundle User-Local MSVC Runtime DLLs
Write-Host "[3/6] Bundling user-local MSVC runtime DLLs (vcruntime140, msvcp140)..."
$msvcDlls = @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
foreach ($dll in $msvcDlls) {
    $sysPath = Join-Path $env:windir "System32\$dll"
    if (Test-Path $sysPath) {
        Copy-Item -Path $sysPath -Destination "$DistRoot\runtime\python\$dll" -Force
    }
}

# [4/6] Copy application code
Write-Host "[4/6] Copying cardio_tagger application code and ontology..."
Copy-Item -Path "$PSScriptRoot\..\cardio_tagger" -Destination "$DistRoot\app\cardio_tagger" -Recurse -Force
Copy-Item -Path "$PSScriptRoot\run_cardio_tagger.bat" -Destination "$DistRoot\run_cardio_tagger.bat" -Force

# [5/6] Export GLiNER model config
Write-Host "[5/6] Exporting GLiNER-BioMed INT8 model configuration..."
$env:TORCHINDUCTOR_CACHE_DIR = Join-Path $PSScriptRoot "..\..\.cache\torch_inductor"
$env:HF_HOME = Join-Path $PSScriptRoot "..\..\.cache\huggingface"
$env:TORCH_HOME = Join-Path $PSScriptRoot "..\..\.cache\torch"
$QuantScript = "$PSScriptRoot\..\..\.agent\skills\gliner-biomed-onnx-quantizer\scripts\export_int8_onnx.py"
& C:\Python314\python.exe $QuantScript --model-id "Ihor/gliner-biomed-bi-small-v1.0" --output-dir "$DistRoot\models\gliner_biomed_int8"

# [6/6] Final Audit
Write-Host "[6/6] Running portable bundle audit..."
& C:\Python314\python.exe -c "import sys; sys.path.insert(0, 'mcp_servers/cardio_tagger_mcp'); import server; print(server.verify_portable_bundle_manifest('dist/cardio-tagger-portable'))"

Write-Host "Portable bundle successfully assembled at: $DistRoot"
