@echo off
REM ============================================================================
REM Zero-Admin-Rights Windows Portable Launcher for Cardio-PDF-Tagger
REM 100% Native cmd.exe Batch Launcher - Zero PowerShell Dependencies
REM Bound strictly to 16GB RAM CPU ceiling (4 Workers + 2 ONNX Intra-Op Threads)
REM ============================================================================
SETLOCAL EnableDelayedExpansion

SET "APP_ROOT=%~dp0"
SET "PYTHON_BIN=%APP_ROOT%runtime\python\python.exe"
SET "PYTHONHOME=%APP_ROOT%runtime\python"
SET "PYTHONPATH=%APP_ROOT%app;%APP_ROOT%runtime\python\Lib\site-packages"
SET "PATH=%APP_ROOT%runtime\python;%APP_ROOT%runtime\ollama;%PATH%"

REM Offline Model & Temp Redirection (Zero %USERPROFILE% / %APPDATA% writes)
SET "HF_HUB_OFFLINE=1"
SET "TRANSFORMERS_OFFLINE=1"
SET "GLINER_MODEL_DIR=%APP_ROOT%models\gliner_biomed_int8"
SET "OLLAMA_MODELS=%APP_ROOT%models\ollama"
SET "OLLAMA_HOST=127.0.0.1:11435"
SET "OLLAMA_NUM_PARALLEL=1"
SET "OLLAMA_MAX_LOADED_MODELS=1"

REM Redirect runtime caches into local portable directory
SET "TORCHINDUCTOR_CACHE_DIR=%APP_ROOT%.cache\torch_inductor"
SET "HF_HOME=%APP_ROOT%.cache\huggingface"
SET "TORCH_HOME=%APP_ROOT%.cache\torch"
if not exist "%APP_ROOT%.cache" mkdir "%APP_ROOT%.cache"

REM CPU Thread Pinning to Prevent Memory Thrashing on 16GB RAM Windows Workstation
SET "OMP_NUM_THREADS=2"
SET "MKL_NUM_THREADS=2"
SET "ORT_INTRA_OP_NUM_THREADS=2"

REM Check if Python embeddable executable is present
if not exist "%PYTHON_BIN%" (
    echo [ERROR] Embedded Python executable not found at:
    echo         %PYTHON_BIN%
    echo Please ensure the bundle was extracted with its complete folder structure.
    pause
    exit /b 1
)

REM If arguments were passed on command line, execute CLI directly
if not [%1]==[] goto :RUN_CLI

REM Interactive menu if double-clicked without arguments
echo ============================================================================
echo   Cardio-PDF-Tagger: 1M-PDF Clinical Cardiology & Staged PCI Portable Tagger
echo   (Running in zero-admin mode on 100%% offline Windows - Zero PowerShell)
echo ============================================================================
echo.
echo Usage:
echo   run_cardio_tagger.bat --input-dir "C:\path\to\pdfs" [options]
echo.
echo Common Options:
echo   --input-dir DIR        Directory containing clinical PDFs or text notes
echo   --output-csv FILE      Output summary CSV path (default: staged_pci_results.csv)
echo   --output-parquet FILE  Output columnar Parquet path (default: staged_pci_results.parquet)
echo   --output-jsonl FILE    Detailed per-concept JSONL path (default: staged_pci_detailed.jsonl)
echo   --resume               Resume interrupted run from checkpoint.duckdb
echo   --workers N            Worker process count (default: 4 for 16GB RAM)
echo   --all-sections         Scan all sections in addition to Conclusion/Impression/Plan
echo.
set /p "USER_INPUT_DIR=Enter path to PDF directory (or drag & drop folder here): "
if "!USER_INPUT_DIR!"=="" (
    echo No directory entered. To run sample verification, run run_sample_verification.bat
    pause
    exit /b 0
)
set "USER_INPUT_DIR=!USER_INPUT_DIR:"=!"
"%PYTHON_BIN%" -m cardio_tagger.cli --input-dir "!USER_INPUT_DIR!"
echo.
pause
exit /b 0

:RUN_CLI
"%PYTHON_BIN%" -m cardio_tagger.cli %*
ENDLOCAL
