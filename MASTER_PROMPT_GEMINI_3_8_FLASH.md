# Antigravity IDE Master Prompt (Gemini 3.8 Flash): 1M-PDF Portable Clinical Cardiology & Staged PCI Tagger

Use the copy-paste Master Prompt below in **Antigravity IDE** with **Gemini 3.8 Flash** (`gemini-3.8-flash`) selected. It is paired with the three workspace skills (`.agent/skills/`) and the custom **Cardio-Tagger MCP Server** (`mcp_servers/cardio_tagger_mcp/server.py`) bundled in `cardio_pdf_tagger_antigravity_kit.zip`.

## System Architecture & 16 GB RAM Budget Summary

| Pipeline Tier | Engine / Library | Target Scope | Avg Latency / Doc | RAM Footprint (4 Workers) | Purpose in Cardiology Sieve |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 0: Ingestion & Section Sieve** | [PyMuPDF](https://github.com/pymupdf/PyMuPDF) + [RapidOCR](https://github.com/RapidAI/RapidOCR) + [DuckDB](https://github.com/duckdb/duckdb-python) | Native PDF text (OCR fallback if scanned) + Multi-Pass Section Parser | `1.5 ms` (`~180 ms` if OCR) | `~350 MB` (Orchestrator + DuckDB) | Isolates `CONCLUSION` / `IMPRESSION` / `SUMMARY` / `PLAN` whether on the last page or Page 1, handling newlines, colons, tables, and tail fallbacks |
| **Tier 1: Lexical & Regex Gate** | [pyahocorasick](https://github.com/WojciechMula/pyahocorasick) + Pre-compiled Regex | Candidate `Conclusion` (or `All` sections) | `<0.2 ms` | `<60 MB` | Filters out 85–92% of non-matching PDFs instantaneously using C-trie seeds & boundary regexes |
| **Tier 2: Clinical ConText Engine** | [medSpaCy](https://github.com/medspacy/medspacy) (`ConText` modifier window) | Sentences passing Tier 1 | `1.8 ms` | `~180 MB` | Distinguishes `AFFIRMED_PLANNED` (*"plan for staged PCI in 4 wks"*) vs `AFFIRMED_PERFORMED_INDEX` vs `NEGATED` (*"no indication for staged PCI"*) vs `HISTORICAL` vs `CONDITIONAL` |
| **Tier 3: Zero-Shot Biomedical NER** | [GLiNER-BioMed](https://github.com/ds4dh/GLiNER-biomed) (`Ihor/gliner-biomed-bi-small-v1.0`) via [ONNX Runtime](https://github.com/microsoft/onnxruntime) INT8 | Sentences passing Tier 1 & Tier 2 (`~8–15%` of corpus) | `14.0 ms` | `4 × ~380 MB = ~1.52 GB` | Extracts zero-shot spans: target vessels (`LAD`, `RCA`, `LCx`, `OM1`, `LMCA`), timeframe (`in 4 weeks`, `index admission`), stent types, `LVEF %`, `FFR/IVUS` |
| **Tier 4: OCR Fuzzy & Semantic Matcher** | `RapidFuzz` + Static Clinical Embeddings (`Model2Vec` / `BioLord-INT8` ONNX) | Unmatched / OCR-noisy sentences | `2.5 ms` | `~160 MB` | Recovers OCR degradation (*"stged PCl"*, *"percutanous interv."*) and maps paraphrased cardiology concepts to SNOMED-CT / UMLS CUIs |
| **Tier 5: Local LLM Arbitrator** | Portable [Ollama Windows ZIP](https://docs.ollama.com/windows) (`Qwen2.5-3B-Instruct-Q4_K_M`) | Ambiguous / conditional sentences only (`<1.5%` of corpus) | `420 ms` (only on `<1.5%`) | `~2.25 GB` (shared single instance) | Resolves complex conditional clinical logic (*"If outpatient stress MPI shows anterior ischemia, proceed with staged PCI to mid-LAD; otherwise medical therapy"*) |

## Copy-Paste Master Prompt for Antigravity IDE (`Gemini 3.8 Flash`)

```markdown
# ROLE & OBJECTIVE
You are the Lead Clinical NLP Systems Architect and Windows Portable Packaging Engineer operating inside Antigravity IDE on Gemini 3.8 Flash (`gemini-3.8-flash`).

Your objective is to build, test, verify, and package `cardio-tagger` — a high-throughput, fault-tolerant, zero-admin-rights Windows x64 Portable CLI Application that loops through 1,000 to 1,000,000+ clinical cardiology PDF reports to detect, classify, and extract **Staged PCI (Percutaneous Coronary Intervention)** primarily from the **Conclusion** section (which normally resides at the end of the report but may appear on Page 1 or earlier sections, separated by newlines, colons, dashes, numbered headers, or table cells), while being 100% extensible via a declarative YAML ontology (`cardio_concepts.yaml`) to **all cardiology concepts across all report sections**.

## HARDWARE & DEPLOYMENT CONSTRAINTS
1. **Target Machine (Locked-Down Production Workstation)**:
   - OS: Windows 10 / 11 x64 with **NO Administrator Rights** (cannot install MSI packages, cannot write to `C:\Program Files` or `HKLM`, cannot install system-wide VC++ redistributables or Windows services).
   - Memory: **16 GB CPU-only RAM** (no discrete GPU assumed). Total peak application RAM across all worker processes and local model servers MUST stay strictly `<= 11.5 GB` (leaving `>= 4.5 GB` for Windows OS and background enterprise agents).
   - Network: **100% Offline / Air-Gapped Execution** (all Python wheels, ONNX weights, tokenizers, and GGUF models must live inside the portable folder).
2. **Development Machine (Build Workstation)**:
   - OS: Windows 10 / 11 x64 with full internet access and unrestricted tooling to download dependencies, quantize models to INT8 ONNX, and assemble the portable distribution folder `dist/cardio-tagger-portable/`.

## REQUIRED WORKSPACE SKILLS & MCP TOOLS
Before writing or modifying code, load and follow these installed Antigravity skills:
- `.agent/skills/cardio-section-sieve-architect/SKILL.md`
- `.agent/skills/gliner-biomed-onnx-quantizer/SKILL.md`
- `.agent/skills/windows-nonadmin-portable-packager/SKILL.md`

Use the registered `cardio-tagger-mcp` MCP Server tools (`inspect_pdf_sections`, `test_sieve_tiers_on_text`, `validate_cardio_ontology`, `benchmark_16gb_ram_budget`) at every milestone to verify your implementation deterministically.

## ARCHITECTURAL SPECIFICATION TO IMPLEMENT & VERIFY

### 1. Multi-Pass Layout-Aware PDF Section Segmenter (`cardio_tagger/section_parser.py`)
- **Primary Engine**: Use `PyMuPDF` (`fitz`) to extract text page-by-page in `~1.5 ms/PDF`.
- **Scanned PDF Fallback**: If a page yields `< 40` characters of native text and contains embedded raster images, invoke `rapidocr-onnxruntime` (CPU INT8 PaddleOCR via ONNX Runtime) on that page only.
- **Conclusion Position Agnostic**: Scan all pages for conclusion headers (`CONCLUSION`, `CONCLUSIONS`, `IMPRESSION`, `IMPRESSION AND PLAN`, `SUMMARY AND RECOMMENDATIONS`, `CONCLUSIONS / PLAN`, `FINAL SUMMARY`). Record `is_early_section = True` whenever the conclusion appears on Page 1 of a multi-page report or in the top 45% of the document.
- **Multi-Delimiter Normalization**: Handle headers followed by `
` (newline), `:` (colon), `-` / `—` (hyphen/em-dash), Markdown/numbered lists (`1.`, `IV.`), or pipe/table cells.
- **Section Merging & Stop Boundaries**: If `CONCLUSION` is immediately followed by `PLAN` or `RECOMMENDATIONS`, merge them so staged PCI timing/vessel instructions in `Plan:` are never truncated. Terminate section extraction cleanly at signature/footer stop boundaries (`Electronically signed by`, `Attending Cardiologist`, `Dictated by`, `CC:`, `Billing/CPT Codes`, `Radiation Dose`).
- **Headerless Fallback**: If a PDF has zero recognizable section headers, extract the bottom 40% of the final page as `conclusion_tail_fallback` so no short cath report is silently skipped.

### 2. Extensible Cardiology Ontology (`cardio_tagger/ontology/cardio_concepts.yaml`)
- Maintain a hot-reloadable YAML ontology where `staged_pci` is the primary target and 10+ additional cardiology concepts (`primary_or_culprit_pci`, `cabg_evaluation`, `lvef_systolic_function`, `coronary_vessel_stenosis`, `intracoronary_physiology_imaging`, `calcium_modification_athrectomy`, `structural_valvular_intervention`, `mechanical_circulatory_support`, `dapt_antithrombotic_regimen`) are pre-configured across `conclusion` or `all` sections.
- Each concept defines:
  - `id`, `display_name`, `snomed_ct`, `umls_cui`
  - `target_sections` (e.g. `["conclusion", "impression", "plan"]` or `["all"]`)
  - `allow_all_sections_fallback` (boolean)
  - `aho_corasick_seeds` (fast case-insensitive substring/trie triggers)
  - `regex_patterns` (boundary-aware clinical regular expressions)
  - `gliner_labels` (natural-language entity prompts for zero-shot `GLiNER-BioMed`)

### 3. The 6-Tier Cascading Clinical NLP Sieve (`cardio_tagger/sieve_engine.py`)
- **Tier 0 (Streaming & Checkpointing)**: Stream PDF paths through a bounded `multiprocessing.Pool(processes=4, maxtasksperchild=500)` (recycling workers every 500 PDFs to guarantee zero C-heap memory leaks across 1,000,000 files). Persist state in an embedded `DuckDB` database (`checkpoint.duckdb`) keyed by `(pdf_path, file_size, mtime_ns)` so interrupted 1M-PDF runs resume instantly with `--resume`.
- **Tier 1 (Sub-Millisecond Lexical & Regex Sieve)**: Run `pyahocorasick` automaton + compiled regexes on the target section(s). Immediately mark documents with zero seed/regex/fuzzy hits as negative in `<0.2 ms`.
- **Tier 2 (Clinical ConText & Assertion Classifier)**: Apply `medSpaCy` ConText directional modifier windows (`pre_window=8`, `post_window=6`) to classify every match into one of 5 mutually exclusive clinical assertion states:
  1. `AFFIRMED_PLANNED`: Future/scheduled staged PCI (*"Plan for staged PCI to mid-LAD in 4 weeks"*, *"Stage II PCI to RCA during index admission"*).
  2. `AFFIRMED_PERFORMED_INDEX`: Staged PCI completed during the current catheterization (*"Successful staged PCI to OM1 performed today"*).
  3. `CONDITIONAL`: Contingent on ischemia/viability testing (*"Consider staged PCI to LCx if outpatient stress MPI is positive"*).
  4. `HISTORICAL`: Prior completed staged PCI in medical history (*"History of staged PCI to RCA in 2023"*).
  5. `NEGATED`: Explicitly ruled out or deferred (*"No indication for staged PCI"*, *"Patient declined staged PCI"*).
- **Tier 3 (Zero-Shot Biomedical NER via INT8 GLiNER-BioMed ONNX)**: On candidate sentences passing Tier 1, run `Ihor/gliner-biomed-bi-small-v1.0` quantized to INT8 on `onnxruntime` (`CPUExecutionProvider`, `intra_op_num_threads=2`) to extract:
  - `target_vessels` (`LAD`, `Proximal LAD`, `Mid-LAD`, `RCA`, `LCx`, `LMCA`, `OM1`, `D1`, `Ramus`, `PDA`, `LIMA`, `SVG`)
  - `planned_timeframe` (`in 4 weeks`, `during index admission`, `prior to discharge`, `in 3-5 days`)
  - Concept-specific values (`LVEF %`, `FFR/iFR value`, `Stent dimensions/drug`, `Stenosis %`)
- **Tier 4 (Fuzzy OCR Typo Recovery & Static Clinical Embeddings)**: Use `RapidFuzz` partial token ratio + ONNX static clinical sentence embeddings to catch OCR corruptions (*"stged PCl"*, *"stgd percutanous intervention"*) and non-standard phrasing.
- **Tier 5 (Ambiguity Arbitrator via Portable Local Ollama / GGUF)**: Invoked **only** when Tier 2 flags `CONDITIONAL` or conflicting modifiers (`<1.5%` of documents). Query the local portable Ollama server (`127.0.0.1:11435`, running `Qwen2.5-3B-Instruct-Q4_K_M` with `temperature=0.0` and strict JSON schema) to adjudicate the exact clinical status.

### 4. Non-Admin Windows Portable Packaging (`scripts/build_portable_bundle.ps1` & `run_cardio_tagger.bat`)
- Assemble `dist/cardio-tagger-portable/` using:
  - `runtime/python/`: Official Python 3.11 Windows Embeddable x64 ZIP with `python311._pth` configured for local `Lib/site-packages` and user-local copies of `vcruntime140.dll`, `vcruntime140_1.dll`, and `msvcp140.dll`.
  - `runtime/ollama/`: Standalone `ollama-windows-amd64.zip` extracted with `OLLAMA_MODELS` pointed to `%~dp0models\ollama`.
  - `models/gliner_biomed_int8/`: Offline INT8 ONNX export of `Ihor/gliner-biomed-bi-small-v1.0`.
  - `run_cardio_tagger.bat`: Sets `HF_HUB_OFFLINE=1`, `ORT_INTRA_OP_NUM_THREADS=2`, `OMP_NUM_THREADS=2`, and launches `cardio_tagger.cli` with zero registry or `%APPDATA%` writes.

## EXECUTION CHECKLIST
1. Call `validate_cardio_ontology` and `benchmark_16gb_ram_budget` via the `cardio-tagger-mcp` MCP server.
2. Verify and enhance `cardio_tagger/section_parser.py`, `cardio_tagger/sieve_engine.py`, and `cardio_tagger/cli.py` (including DuckDB checkpointing and Parquet/CSV/JSONL export).
3. Run `pytest portable_app/tests/test_sieve_pipeline.py` and `test_sieve_tiers_on_text` across all 5 clinical edge cases (final-page newline conclusion, Page-1 inline conclusion, negated staged PCI, conditional staged PCI, and OCR typo recovery).
4. Execute `scripts/build_portable_bundle.ps1` to generate the ready-to-copy Windows folder `dist/cardio-tagger-portable/`.
```
