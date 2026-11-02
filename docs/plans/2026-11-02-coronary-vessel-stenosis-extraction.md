# Coronary Vessel Stenosis Extraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract fine-grained coronary artery stenosis and lesion severity (e.g. `small lcx 70-90%`, `mid lad 50%`, `rpl1 70%`, `100% CTO`) across native vessels (LMCA, LAD, LCX, RCA) and bypass grafts into 10 structured columns across both Conclusion and Diagnostic Findings scopes.

**Architecture:** A lightweight, pure-Python deterministic segment parser (`CoronaryStenosisExtractor`) parses anatomical qualifiers, vessel segments, branching vessels, and stenosis percentages or qualitative states. `ClinicalSectionParser` extracts both `conclusion_text` and `findings_text`, which are independently evaluated by `CascadingCardioSieve` and exported to CSV, Parquet, JSONL, and DuckDB checkpoints.

**Tech Stack:** Python 3.11+, PyMuPDF, DuckDB, PyArrow / Parquet, Pytest.

---

### Task 1: Core `CoronaryStenosisExtractor` and Unit Tests

**Files:**
- Create: `portable_app/cardio_tagger/coronary_stenosis.py`
- Create: `portable_app/tests/test_coronary_stenosis.py`

**Step 1: Write failing unit tests for vessel and stenosis extraction**
In `portable_app/tests/test_coronary_stenosis.py`:
- Test single and range percentages (`small lcx 70-90%`, `mid lad 50%`, `rpl1 70%`).
- Test occlusion and qualitative states (`100% CTO`, `total occlusion`, `patent stent`, `severe disease`).
- Test multi-lesion concatenation in the same territory (`PROX LAD: 70%; MID LAD: 50%`).
- Test territory routing:
  - LMCA: `Left Main: 30%` -> `conclusion_lmca_stenosis`
  - LAD: `Mid LAD 50%, D1 80%` -> `conclusion_lad_stenosis`
  - LCX: `Small LCX 70-90%, OM1 60%` -> `conclusion_lcx_stenosis`
  - RCA: `Prox RCA 100% CTO, RPL1 70%` -> `conclusion_rca_stenosis`
  - Graft: `LIMA to LAD patent, SVG to RCA 90%` -> `conclusion_graft_stenosis`

**Step 2: Run test to verify it fails**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_coronary_stenosis.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cardio_tagger.coronary_stenosis'`

**Step 3: Implement `CoronaryStenosisExtractor` in `portable_app/cardio_tagger/coronary_stenosis.py`**
- Define `CoronaryStenosisResult` dataclass with 10 fields:
  `conclusion_lmca_stenosis`, `conclusion_lad_stenosis`, `conclusion_lcx_stenosis`, `conclusion_rca_stenosis`, `conclusion_graft_stenosis`,
  `findings_lmca_stenosis`, `findings_lad_stenosis`, `findings_lcx_stenosis`, `findings_rca_stenosis`, `findings_graft_stenosis`.
- Implement regex patterns for:
  - Territories & branches: LMCA, LAD (D1-D3, Ramus), LCx (OM1-OM3, LPL), RCA (PDA, RPL1-3, PLV, AM), Grafts (LIMA, RIMA, SVG).
  - Anatomical modifiers: `small`, `large`, `dominant`, `non-dominant`, `proximal` (`prox`), `mid`, `distal`, `ostial`, `apical`.
  - Stenosis values: `XX%`, `XX-YY%`, `XX to YY%`, `~XX%`, `>XX%`, `<XX%`, `up to YY%`, `100% CTO`, `total occlusion`, `subtotal occlusion`, `patent stent`, `in-stent restenosis`, `severe`, `moderate`, `mild`.
- Implement `extract(conclusion_text: str, findings_text: str) -> CoronaryStenosisResult`.

**Step 4: Run test to verify it passes**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_coronary_stenosis.py -v`
Expected: PASS (all tests pass)

**Step 5: Commit**
```bash
git add portable_app/cardio_tagger/coronary_stenosis.py portable_app/tests/test_coronary_stenosis.py
git commit -m "feat(stenosis): implement CoronaryStenosisExtractor for vessel territories and severity"
```

---

### Task 2: Section Parser Findings Extraction

**Files:**
- Modify: `portable_app/cardio_tagger/section_parser.py`
- Test: `portable_app/tests/test_coronary_stenosis.py`

**Step 1: Write test verifying `extract_sections` returns both `conclusion_text` and `findings_text`**
In `test_coronary_stenosis.py`:
- Add test `test_section_parser_findings_and_conclusion_split` with a multi-page cath report containing explicit `FINDINGS:` and `CONCLUSION:`.

**Step 2: Run test to verify failure**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_coronary_stenosis.py -k test_section_parser_findings -v`
Expected: FAIL (missing `findings_text` attribute or method).

**Step 3: Implement `findings_text` extraction in `ClinicalSectionParser`**
In `portable_app/cardio_tagger/section_parser.py`:
- Add `FINDINGS_HEADERS` pattern (`FINDINGS:`, `ANGIOGRAPHIC FINDINGS:`, `PROCEDURE DETAILS:`, `CORONARY ARTERIES:`, `VESSEL DETAILS:`).
- Store `findings_text: str` in `SectionParseResult`.
- Extract narrative text starting from `FINDINGS` up until `CONCLUSION` or stop headers.

**Step 4: Run test to verify pass**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_coronary_stenosis.py -k test_section_parser_findings -v`
Expected: PASS

**Step 5: Commit**
```bash
git add portable_app/cardio_tagger/section_parser.py portable_app/tests/test_coronary_stenosis.py
git commit -m "feat(parser): add diagnostic findings section extraction to ClinicalSectionParser"
```

---

### Task 3: Pipeline Integration in `sieve_engine.py`

**Files:**
- Modify: `portable_app/cardio_tagger/sieve_engine.py`
- Modify: `portable_app/tests/test_sieve_pipeline.py`

**Step 1: Write integration test in `test_sieve_pipeline.py`**
- Add `test_coronary_stenosis_sieve_integration` verifying that `sieve.evaluate_document()` returns populated `conclusion_*_stenosis` and `findings_*_stenosis` fields.

**Step 2: Run test to verify failure**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_sieve_pipeline.py -k test_coronary_stenosis_sieve_integration -v`
Expected: FAIL (attributes not found on `DocumentTagResult`).

**Step 3: Update `sieve_engine.py`**
- Add 10 fields to `DocumentTagResult`:
  `conclusion_lmca_stenosis`, `conclusion_lad_stenosis`, `conclusion_lcx_stenosis`, `conclusion_rca_stenosis`, `conclusion_graft_stenosis`,
  `findings_lmca_stenosis`, `findings_lad_stenosis`, `findings_lcx_stenosis`, `findings_rca_stenosis`, `findings_graft_stenosis`.
- In `CascadingCardioSieve.__init__`:
  Instantiate `self.stenosis_extractor = CoronaryStenosisExtractor()`.
- In `evaluate_document()`:
  Call `self.stenosis_extractor.extract(conclusion_window, findings_window)`.
  Populate result fields.

**Step 4: Run test to verify pass**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_sieve_pipeline.py -k test_coronary_stenosis_sieve_integration -v`
Expected: PASS

**Step 5: Commit**
```bash
git add portable_app/cardio_tagger/sieve_engine.py portable_app/tests/test_sieve_pipeline.py
git commit -m "feat(sieve): integrate coronary vessel stenosis extraction into CascadingCardioSieve"
```

---

### Task 4: CLI, CSV/Parquet Export & DuckDB Checkpoint Integration

**Files:**
- Modify: `portable_app/cardio_tagger/cli.py`
- Modify: `portable_app/tests/test_sieve_pipeline.py`

**Step 1: Update CLI integration tests**
In `portable_app/tests/test_sieve_pipeline.py`:
- Update `test_csv_input_processing` to verify `conclusion_lad_stenosis`, `findings_lad_stenosis`, etc., are present in output CSV and DuckDB checkpoints.

**Step 2: Run test to verify failure**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_sieve_pipeline.py -k test_csv_input_processing -v`
Expected: FAIL

**Step 3: Update `cli.py`**
- Add the 10 fields to `tagger_fields` (CSV mode), `base_fields` (PDF mode), and output row dictionaries.
- Update `DuckDBCheckpointManager` schema to include the 10 columns with `TEXT` data type.

**Step 4: Run test to verify pass**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_sieve_pipeline.py -k test_csv_input_processing -v`
Expected: PASS

**Step 5: Commit**
```bash
git add portable_app/cardio_tagger/cli.py portable_app/tests/test_sieve_pipeline.py
git commit -m "feat(cli): export 10 coronary vessel stenosis columns to CSV, Parquet, and DuckDB"
```

---

### Task 5: Portable Bundle Sync, cmd.exe Verification & Release v1.4.0

**Files:**
- Sync: `dist/cardio-tagger-portable/app/cardio_tagger/`
- Test: `dist/cardio-tagger-portable/run_sample_verification.bat`
- Build: `dist/cardio-tagger-portable-v1.4.0-windows-x64.zip`

**Step 1: Sync modified python files to portable distribution**
Copy `coronary_stenosis.py`, `section_parser.py`, `sieve_engine.py`, `cli.py` to `dist/cardio-tagger-portable/app/cardio_tagger/`.

**Step 2: Run sample verification in pure cmd.exe**
Run: `cmd.exe /c "cd /d dist\cardio-tagger-portable && run_sample_verification.bat < nul"`
Verify output columns in `sample_results.csv` and `sample_results.parquet`.

**Step 3: Clean temporary test outputs and compress zip**
Compress `dist/cardio-tagger-portable-v1.4.0-windows-x64.zip`.

**Step 4: Git commit & push**
Push `main` to GitHub.

**Step 5: Publish GitHub Release v1.4.0**
Execute `gh release create v1.4.0`.
