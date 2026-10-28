@echo off
REM ============================================================================
REM Pure cmd.exe Portable Bundler for Cardio-PDF-Tagger
REM Zero PowerShell Required on Build Machine
REM ============================================================================
SETLOCAL EnableDelayedExpansion

SET "REPO_ROOT=%~dp0..\.."
SET "DIST_ROOT=%REPO_ROOT%\dist\cardio-tagger-portable"

echo [1/5] Creating directory layout at %DIST_ROOT%...
if not exist "%DIST_ROOT%\runtime\python\Lib\site-packages" mkdir "%DIST_ROOT%\runtime\python\Lib\site-packages"
if not exist "%DIST_ROOT%\runtime\ollama" mkdir "%DIST_ROOT%\runtime\ollama"
if not exist "%DIST_ROOT%\models\gliner_biomed_int8" mkdir "%DIST_ROOT%\models\gliner_biomed_int8"
if not exist "%DIST_ROOT%\models\ollama" mkdir "%DIST_ROOT%\models\ollama"
if not exist "%DIST_ROOT%\app" mkdir "%DIST_ROOT%\app"

echo [2/5] Extracting Python 3.11 Embeddable Runtime...
if exist "%REPO_ROOT%\python-3.11.9-embed-amd64.zip" (
    tar -xf "%REPO_ROOT%\python-3.11.9-embed-amd64.zip" -C "%DIST_ROOT%\runtime\python"
) else (
    echo Note: python-3.11.9-embed-amd64.zip not found in root.
)

echo [3/5] Bundling MSVC runtime DLLs...
copy /Y "%windir%\System32\vcruntime140.dll" "%DIST_ROOT%\runtime\python\" >nul 2>&1
copy /Y "%windir%\System32\vcruntime140_1.dll" "%DIST_ROOT%\runtime\python\" >nul 2>&1
copy /Y "%windir%\System32\msvcp140.dll" "%DIST_ROOT%\runtime\python\" >nul 2>&1

echo [4/5] Syncing application code and launchers...
xcopy /E /I /Y "%REPO_ROOT%\portable_app\cardio_tagger" "%DIST_ROOT%\app\cardio_tagger" >nul
copy /Y "%REPO_ROOT%\portable_app\scripts\run_cardio_tagger.bat" "%DIST_ROOT%\run_cardio_tagger.bat" >nul
if exist "%REPO_ROOT%\synthetic_pdfs" (
    xcopy /E /I /Y "%REPO_ROOT%\synthetic_pdfs" "%DIST_ROOT%\sample_reports" >nul
)

echo [5/5] Bundle layout ready at: %DIST_ROOT%
ENDLOCAL
