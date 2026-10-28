# Echo LVEF Extraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a specialized Echocardiography LVEF extraction engine with strict section hierarchy (Conclusion > Findings > Measurements), method ranking (3D > 2D > Visual), historical/dated value exclusion, and range parsing.

**Architecture:** Extend `ClinicalSectionParser` to recognize echo measurement and finding boundaries. Create a dedicated `EchoLVEFExtractor` engine applying hierarchical multi-pass rule evaluation and temporal clause disambiguation. Integrate structured LVEF columns (`lvef_extracted`, `lvef_numeric`, `lvef_method`, `lvef_section`) into `sieve_engine.py`, `cli.py`, CSV/Parquet outputs, and the portable Windows bundle.

**Tech Stack:** Python 3.11/3.14, Regular Expressions, PyMuPDF, DuckDB, PyArrow, Pytest.

---

### Task 1: Echo Section Detection in `section_parser.py`

**Files:**
- Modify: `portable_app/cardio_tagger/section_parser.py`
- Test: `portable_app/tests/test_echo_lvef.py`

**Step 1: Write the failing test**
Create `portable_app/tests/test_echo_lvef.py` with test for echo sections:
```python
def test_echo_section_parsing():
    from cardio_tagger.section_parser import ClinicalSectionParser
    parser = ClinicalSectionParser()
    text = (
        "ECHOCARDIOGRAM REPORT\n"
        "FINDINGS:\nLeft ventricle is normal in size.\n\n"
        "MEASUREMENTS:\nLVEF 3D: 58 %\nLVEDV: 110 ml\n\n"
        "SUMMARY:\nVisually estimated LVEF is 50-55%."
    )
    doc = parser.parse_pages("echo_report.txt", [text])
    assert len(doc.conclusion_sections) > 0
    assert "findings" in doc.all_sections
    assert "measurements" in doc.all_sections
```

**Step 2: Run test to verify it fails**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_echo_lvef.py::test_echo_section_parsing -p no:cacheprovider -v`
Expected: FAIL ("measurements" not in `doc.all_sections`).

**Step 3: Implement echo section headers**
In `portable_app/cardio_tagger/section_parser.py`, add `measurements` and expand `findings` and `conclusion` patterns to capture echocardiographic section headers.

**Step 4: Run test to verify it passes**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_echo_lvef.py::test_echo_section_parsing -p no:cacheprovider -v`
Expected: PASS.

**Step 5: Commit**
```bash
git add portable_app/cardio_tagger/section_parser.py portable_app/tests/test_echo_lvef.py
git commit -m "feat(parser): add echocardiography findings and measurements section detection"
```

---

### Task 2: Dedicated Echo LVEF Extractor (`echo_lvef.py`)

**Files:**
- Create: `portable_app/cardio_tagger/echo_lvef.py`
- Test: `portable_app/tests/test_echo_lvef.py`

**Step 1: Write tests for all 7 clinical edge cases**
In `portable_app/tests/test_echo_lvef.py`, implement:
- `test_case1_conclusion_visual_range()`: `"Conclusion: Visually estimated LVEF 50-55%"` $\rightarrow$ `50-55%`, `52.5`, `VISUAL`, `CONCLUSION`.
- `test_case2_conclusion_3d_over_2d()`: Conclusion with both 3D 58% and 2D Simpson 54% $\rightarrow$ `58%`, `58.0`, `3D`, `CONCLUSION`.
- `test_case3_findings_fallback()`: No LVEF in Conclusion; Findings has 2D Biplane 45% $\rightarrow$ `45%`, `45.0`, `2D_BIPLANE`, `FINDINGS`.
- `test_case4_measurements_fallback()`: No LVEF in Conclusion/Findings; Measurements has `EF (Biplane): 60%` $\rightarrow$ `60%`, `60.0`, `2D_BIPLANE`, `MEASUREMENTS`.
- `test_case5_comparative_disambiguation()`: `"LVEF improved from 30% in 2022 to 55% today"` $\rightarrow$ `55%`, `55.0`, not 30%.
- `test_case6_pure_historical_exclusion()`: `"Prior study in 2021 showed LVEF 40%. Current study image quality inadequate."` $\rightarrow$ `lvef_extracted == "NONE"`.
- `test_case7_qualitative_fallback()`: `"Normal LV systolic function, no wall motion abnormalities"` $\rightarrow$ `"Normal"`, `None`, `QUALITATIVE`, `CONCLUSION`.

**Step 2: Run tests to verify they fail**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_echo_lvef.py -p no:cacheprovider -v`
Expected: FAIL (`echo_lvef` module not found).

**Step 3: Implement `EchoLVEFExtractor` in `portable_app/cardio_tagger/echo_lvef.py`**
Implement dataclass `EchoLVEFResult` and class `EchoLVEFExtractor` with:
1. `extract(parsed_doc: ParsedDocument) -> EchoLVEFResult`
2. Priority search: Conclusion $\rightarrow$ Findings $\rightarrow$ Measurements
3. Method ranking: 3D (Rank 1) > 2D (Rank 2) > Unspecified (Rank 3) > Visual (Rank 4)
4. Temporal disambiguation clause splitter to isolate historical values.
5. Range/midpoint calculator (`parse_lvef_value`).

**Step 4: Run tests to verify they pass**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_echo_lvef.py -p no:cacheprovider -v`
Expected: All 8 tests PASS.

**Step 5: Commit**
```bash
git add portable_app/cardio_tagger/echo_lvef.py portable_app/tests/test_echo_lvef.py
git commit -m "feat(echo): implement EchoLVEFExtractor with hierarchical section and method ranking"
```

---

### Task 3: Integration into Sieve Engine & CLI Outputs

**Files:**
- Modify: `portable_app/cardio_tagger/sieve_engine.py`
- Modify: `portable_app/cardio_tagger/cli.py`
- Test: `portable_app/tests/test_sieve_pipeline.py`

**Step 1: Write integration tests**
In `portable_app/tests/test_sieve_pipeline.py`, add:
- `test_echo_lvef_sieve_integration()`: Verifies `res.echo_lvef` populated in `evaluate_document`.
- `test_echo_lvef_csv_columns()`: Verifies CLI output contains `lvef_extracted`, `lvef_numeric`, `lvef_method`, and `lvef_section`.

**Step 2: Run tests to verify they fail**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_sieve_pipeline.py::test_echo_lvef_sieve_integration -p no:cacheprovider -v`
Expected: FAIL (`DocumentTagResult` has no `echo_lvef`).

**Step 3: Integrate into `sieve_engine.py` and `cli.py`**
1. Add `echo_lvef: Optional[Dict[str, Any]] = None` to `DocumentTagResult`.
2. In `CascadingCardioSieve.evaluate_document`, invoke `EchoLVEFExtractor().extract(parsed)`.
3. In `cli.py`, add `lvef_extracted`, `lvef_numeric`, `lvef_method`, `lvef_section` to `base_fields` and `tagger_fields`.

**Step 4: Run full test suite**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/ -p no:cacheprovider -v`
Expected: All tests PASS.

**Step 5: Commit**
```bash
git add portable_app/cardio_tagger/sieve_engine.py portable_app/cardio_tagger/cli.py portable_app/tests/test_sieve_pipeline.py
git commit -m "feat(cli): integrate structured Echo LVEF columns into pipeline and output formats"
```

---

### Task 4: Sync to Portable Bundle, End-to-End Verification, and Release

**Files:**
- Sync: `portable_app/` $\rightarrow$ `dist/cardio-tagger-portable/`
- Run: `cmd.exe /c run_sample_verification.bat`
- Run: `cmd.exe /c run_cardio_tagger.bat --input-csv sample_cohort.csv`
- Compress: `dist/cardio-tagger-portable-v1.2.0-windows-x64.zip`
- Publish: GitHub Release `v1.2.0`

**Step 1: Sync files into `dist/cardio-tagger-portable/app/cardio_tagger/`**
**Step 2: Run batch verification in cmd.exe**
**Step 3: Create v1.2.0 ZIP package**
**Step 4: Push git commit and create GitHub Release v1.2.0**
