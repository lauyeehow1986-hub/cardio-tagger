@echo off
REM ============================================================================
REM 1-Click Verification Launcher for Locked-Down Non-Admin Target Machine
REM Pure cmd.exe Batch - Zero PowerShell Required
REM ============================================================================
SETLOCAL EnableDelayedExpansion

SET "APP_ROOT=%~dp0"
SET "PYTHON_BIN=%APP_ROOT%runtime\python\python.exe"
SET "PYTHONHOME=%APP_ROOT%runtime\python"
SET "PYTHONPATH=%APP_ROOT%app;%APP_ROOT%runtime\python\Lib\site-packages"
SET "PATH=%APP_ROOT%runtime\python;%PATH%"

SET "TORCHINDUCTOR_CACHE_DIR=%APP_ROOT%.cache\torch_inductor"
SET "HF_HOME=%APP_ROOT%.cache\huggingface"
SET "TORCH_HOME=%APP_ROOT%.cache\torch"

echo ============================================================================
echo   Running Cardio-PDF-Tagger 1-Click Sample Verification Suite
echo   (Testing 5 clinical edge cases on 16GB RAM non-admin Windows target)
echo ============================================================================
echo.

"%PYTHON_BIN%" -m cardio_tagger.cli ^
    --input-dir "%APP_ROOT%sample_reports" ^
    --output-csv "%APP_ROOT%sample_results.csv" ^
    --output-jsonl "%APP_ROOT%sample_results.jsonl" ^
    --output-parquet "%APP_ROOT%sample_results.parquet" ^
    --workers 2

echo.
echo ----------------------------------------------------------------------------
echo SUMMARY RESULTS (from sample_results.csv):
echo ----------------------------------------------------------------------------
type "%APP_ROOT%sample_results.csv"
echo.
echo ============================================================================
echo Verification completed successfully!
echo Outputs generated in:
echo   - %APP_ROOT%sample_results.csv
echo   - %APP_ROOT%sample_results.parquet
echo   - %APP_ROOT%sample_results.jsonl
echo ============================================================================
echo.
pause
ENDLOCAL
