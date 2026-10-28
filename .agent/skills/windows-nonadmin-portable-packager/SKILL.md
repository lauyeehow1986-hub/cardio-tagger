---
name: windows-nonadmin-portable-packager
description: Package Python clinical NLP pipelines, ONNX Runtime models, DuckDB, and Portable Ollama into a zero-admin-rights xcopy-deployable Windows directory constrained to 16 GB CPU RAM. Use when building, auditing, or troubleshooting the portable Windows distribution.
---
# Windows Non-Admin Portable Packager (16 GB RAM CPU Target)

Build a self-contained folder (`dist/cardio-tagger-portable/`) on the Windows Development Workstation that runs via `xcopy` / USB / network share on any locked-down Windows 10/11 PC with zero administrator privileges.

## Critical Non-Admin Windows Packaging Rules

1. **Prefer Embeddable Python Folder (`--onedir` style) Over Single-File `.exe` (`--onefile`)**:
   - Single-file PyInstaller executables unpack 1-3 GB of DLLs and model weights into `%TEMP%\ _MEIxxxxxx` on every invocation, which triggers corporate Endpoint Detection & Response (EDR) / AppLocker blocks and fills locked-down user temp quotas.
   - Instead, use the official **Python Windows Embeddable Package** (`python-3.11.9-embed-amd64.zip`) inside `runtime/python/` with `python311._pth` modified to include `Lib/site-packages` and `../../app`.
2. **Bundle User-Local MSVC Runtime DLLs**:
   - Locked-down hospital/enterprise PCs may lack the latest Visual C++ Redistributable (`vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140.dll`), which `onnxruntime` and `fitz` require.
   - Copy `vcruntime140.dll`, `vcruntime140_1.dll`, and `msvcp140.dll` from the dev workstation's `C:\Windows\System32` directly into `dist/cardio-tagger-portable/runtime/python/`. Windows DLL search order loads them from the executable directory without admin rights or registry entries.
3. **16 GB RAM Memory Budget Enforcement**:
   - Windows 10/11 OS + background enterprise agents consume `~3.5-4.0 GB` RAM, leaving `12.0 GB` usable budget:
     - Orchestrator + DuckDB Streaming State: `~350 MB`
     - 4 Worker Processes x (PyMuPDF + Aho-Corasick + MedSpaCy + INT8 GLiNER-BioMed ONNX): `4 x ~650 MB = ~2.6 GB`
     - Optional Portable Ollama (`Qwen2.5-3B-Instruct-Q4_K_M` with `OLLAMA_NUM_PARALLEL=1`, `num_ctx=2048`): `~2.3 GB`
     - Total Peak RAM: `~5.25 GB` (well below the 16 GB hardware limit, zero pagefile thrashing).
   - Recycling Workers: Set `max_tasks_per_child=500` in `ProcessPoolExecutor` / `multiprocessing.Pool` and explicitly call `doc.close()` on every PyMuPDF document so C-heap fragmentation never accumulates across 1,000,000 PDFs.
4. **Zero PowerShell Dependency on Target Workstations**:
   - Locked-down enterprise/hospital laptops frequently block `powershell.exe` and `.ps1` execution via AppLocker, ConstrainedLanguageMode, or Group Policy.
   - The portable distribution must be 100% executable using native Windows Command Prompt (`cmd.exe`) batch files (`run_cardio_tagger.bat`, `run_sample_verification.bat`) that invoke `%~dp0runtime\python\python.exe` directly, with zero reliance on PowerShell.
   - When writing `python311._pth`, avoid UTF-8 BOM (`\ufeff`) headers (which PowerShell 5.1 injects by default and causes Python's C-level import bootstrap to fail on `\ufeffpython311.zip`).
