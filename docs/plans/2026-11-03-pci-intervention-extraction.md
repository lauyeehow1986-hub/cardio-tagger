# PCI Intervention Extraction Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract intervened vessels, multi-line granular devices, procedural success outcomes, and post-PCI residual stenosis from `PCI INTERVENTION` sections into 8 dedicated columns while strictly preventing bleed-through into pre-PCI diagnostic stenosis.

**Architecture:** A pure Python `PCIInterventionExtractor` parses segmented `PCI INTERVENTION` sections into structured vessel blocks, classifies granular devices (`[GUIDING CATHETER]`, `[BALLOON]`, `[DRUG-ELUTING STENT]`, `[IVUS]`, `[OCT]`, `[FFR]`, `[ROTABLATOR]`, `[SHOCKWAVE (IVL)]`, `[CUTTING/SCORING BALLOON]`, `[ASPIRATION / THROMBECTOMY]`), records outcome success status, and maps post-PCI residual stenosis across the 5 standard territories (`LMCA`, `LAD`, `LCX`, `RCA`, `GRAFT`) with zero defaults for omitted values.

**Tech Stack:** Python 3.14+, Pytest, DuckDB, Parquet, PyMuPDF, pure standard library regex (`re`).

---

### Task 1: Add `pci_intervention` Section Parsing to `ClinicalSectionParser`

**Files:**
- Modify: `portable_app/cardio_tagger/section_parser.py`
- Test: `portable_app/tests/test_coronary_stenosis.py`

**Step 1: Write failing test in `portable_app/tests/test_coronary_stenosis.py`**
Test that `ClinicalSectionParser` recognizes `PCI INTERVENTION:` as its own section and populates `parsed.pci_text` without polluting `parsed.findings_text`.

```python
def test_pci_intervention_section_parsing_and_isolation():
    from cardio_tagger.section_parser import ClinicalSectionParser
    parser = ClinicalSectionParser()
    text = (
        "CARDIAC CATHETERIZATION REPORT\n"
        "FINDINGS:\n"
        "Left Anterior Descending Coronary Artery: 80% proximal LAD stenosis.\n"
        "PCI INTERVENTION:\n"
        "Proximal LAD:\n"
        "Guiding catheter: 6Fr EBU 3.5 Launcher\n"
        "Successful angioplasty. Residual stenosis 0%.\n"
        "CONCLUSION:\n"
        "CAD s/p PCI to LAD."
    )
    parsed = parser.parse_pages("test.pdf", [text])
    assert "80% proximal LAD stenosis" in parsed.findings_text
    assert "Residual stenosis 0%" not in parsed.findings_text
    assert "Residual stenosis 0%" in parsed.pci_text
    assert "CAD s/p PCI to LAD" in parsed.conclusion_text
```

**Step 2: Run test to verify it fails**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_coronary_stenosis.py -k test_pci_intervention_section_parsing_and_isolation -v`
Expected: FAIL (`AttributeError: 'ParsedDocument' object has no attribute 'pci_text'`)

**Step 3: Implement minimal changes in `portable_app/cardio_tagger/section_parser.py`**
- Add `pci_text` property on `ParsedDocument`:
  ```python
  @property
  def pci_text(self) -> str:
      pci_secs = self.all_sections.get("pci_intervention", [])
      if pci_secs:
          return "\n\n".join(s.text for s in pci_secs)
      return ""
  ```
- Add `"pci_intervention"` regex in `OTHER_SECTION_HEADERS`:
  ```python
  "pci_intervention": re.compile(
      r"(?im)(?:^|\n|[.;]\s+)[\t ]*(?:[0-9IVX]+[\.\)][\t ]*)?(?:"
      r"PCI[\t ]+INTERVENTIONS?|"
      r"PERCUTANEOUS[\t ]+CORONARY[\t ]+INTERVENTIONS?|"
      r"PCI[\t ]+PROCEDURES?|"
      r"ANGIOPLASTY[\t ]+DETAILS?|"
      r"CORONARY[\t ]+INTERVENTIONS?|"
      r"INTERVENTIONS?|"
      r"PCI[\t ]+DETAILS?"
      r")[\t ]*(?:[:\-—\n]|$)"
  ),
  ```

**Step 4: Run test to verify it passes**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_coronary_stenosis.py -k test_pci_intervention_section_parsing_and_isolation -v`
Expected: PASS

**Step 5: Commit**
`git add portable_app/cardio_tagger/section_parser.py portable_app/tests/test_coronary_stenosis.py`
`git commit -m "feat: add pci_intervention section parsing and pci_text property"`

---

### Task 2: Build `PCIInterventionExtractor` with TDD

**Files:**
- Create: `portable_app/cardio_tagger/pci_intervention.py`
- Create: `portable_app/tests/test_pci_intervention.py`

**Step 1: Write failing test in `portable_app/tests/test_pci_intervention.py`**
Test vessel segmentation, granular device tagging, outcome parsing, and territory mapping:

```python
import pytest
from cardio_tagger.pci_intervention import PCIInterventionExtractor

def test_pci_intervention_extraction_user_case():
    extractor = PCIInterventionExtractor()
    text = (
        "PCI INTERVENTION:\n"
        "SVG to RPDA:\n"
        "guiding catheter: 6fr ebu3.5 launcher(medtronic)\n"
        "Balloon: sapphire nc 24 3.5 x 15 mm (orbus). 22 atm\n"
        "Drug-eluting stent: synergy Megatron(mr) 4mm x 20mm (boston scientific). 10 atm.\n"
        "Successful angioplasty. Residual stenosis 0%."
    )
    res = extractor.extract(text)
    assert res.intervened_vessels == "SVG TO RPDA"
    assert res.graft_residual_stenosis == "SVG TO RPDA: 0%"
    assert res.rca_residual_stenosis == ""
    assert "SVG TO RPDA: SUCCESSFUL ANGIOPLASTY" in res.success_status
    assert "[GUIDING CATHETER] 6Fr EBU 3.5 Launcher (Medtronic)" in res.devices_used
    assert "[BALLOON] Sapphire NC 24 3.5 x 15 mm (Orbus), 22 atm" in res.devices_used
    assert "[DRUG-ELUTING STENT] Synergy Megatron (MR) 4mm x 20mm (Boston Scientific), 10 atm" in res.devices_used

def test_pci_intervention_granular_devices_and_blank_residual():
    extractor = PCIInterventionExtractor()
    text = (
        "PCI INTERVENTION:\n"
        "Prox RCA:\n"
        "Guiding catheter: 6Fr JR4\n"
        "Shockwave (IVL): 3.5 x 12 mm balloon, 80 pulses\n"
        "Rotablator: 1.5 mm burr at 160,000 RPM\n"
        "Cutting balloon: 3.0 x 10 mm Wolverine\n"
        "IVUS: OptiCross pre and post stenting\n"
        "FFR: 0.76 pre-PCI, 0.92 post-PCI\n"
        "Drug-eluting stent: Onyx 3.5 x 24 mm\n"
        "Successful angioplasty.\n\n"
        "D1:\n"
        "Balloon: 2.0 x 12 mm Sapphire\n"
        "Aspiration / Thrombectomy: Export catheter\n"
        "Suboptimal result. Residual stenosis 30%."
    )
    res = extractor.extract(text)
    assert "PROX RCA" in res.intervened_vessels
    assert "D1" in res.intervened_vessels
    # Blank residual stenosis for Prox RCA because no percentage was given!
    assert res.rca_residual_stenosis == ""
    # D1 residual stenosis
    assert res.lad_residual_stenosis == "D1: 30%"
    # Outcomes
    assert "PROX RCA: SUCCESSFUL ANGIOPLASTY" in res.success_status
    assert "D1: SUBOPTIMAL RESULT" in res.success_status
    # Granular device tags
    assert "[SHOCKWAVE (IVL)]" in res.devices_used
    assert "[ROTABLATOR]" in res.devices_used
    assert "[CUTTING/SCORING BALLOON]" in res.devices_used
    assert "[IVUS]" in res.devices_used
    assert "[FFR]" in res.devices_used
    assert "[ASPIRATION / THROMBECTOMY]" in res.devices_used
```

**Step 2: Run test to verify it fails**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_pci_intervention.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'cardio_tagger.pci_intervention'`)

**Step 3: Implement `portable_app/cardio_tagger/pci_intervention.py`**
Implement `PCIInterventionResult` dataclass and `PCIInterventionExtractor` with:
- `VESSEL_HEADER_REGEX` matching `SVG TO <TARGET>`, `LMCA`, `PROX RCA`, `RPAV`, `RPDA`, `PROXIMAL LAD`, `D1`, `OM1`, etc.
- Standardizer mapping vessels to territories (`LMCA`, `LAD`, `LCX`, `RCA`, `GRAFT`).
- Line-by-line device regex parser classifying:
  - `[GUIDING CATHETER]`
  - `[BALLOON]`
  - `[DRUG-ELUTING STENT]` / `[STENT]`
  - `[IVUS]`
  - `[OCT]`
  - `[FFR]`
  - `[ROTABLATOR]`
  - `[SHOCKWAVE (IVL)]`
  - `[CUTTING/SCORING BALLOON]`
  - `[ASPIRATION / THROMBECTOMY]`
- Outcome extractor (`SUCCESSFUL ANGIOPLASTY`, `SUCCESSFUL STENTING`, `UNSUCCESSFUL`, `SUBOPTIMAL RESULT`, etc.).
- Residual stenosis extractor: only extracts explicit percentages (e.g. `Residual stenosis 0%`, `Residual 10%`, `<10%`), leaves strictly blank `""` if unstated.

**Step 4: Run test to verify it passes**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_pci_intervention.py -v`
Expected: PASS

**Step 5: Commit**
`git add portable_app/cardio_tagger/pci_intervention.py portable_app/tests/test_pci_intervention.py`
`git commit -m "feat: implement PCIInterventionExtractor with granular devices and territory routing"`

---

### Task 3: Block Residual Stenosis in `coronary_stenosis.py`

**Files:**
- Modify: `portable_app/cardio_tagger/coronary_stenosis.py`
- Test: `portable_app/tests/test_coronary_stenosis.py`

**Step 1: Write failing test in `portable_app/tests/test_coronary_stenosis.py`**
Test that `Residual stenosis 0%` or `residual 20%` is ignored by `CoronaryStenosisExtractor` so it never contaminates diagnostic findings or conclusions.

```python
def test_residual_stenosis_ignored_in_diagnostic_scope():
    extractor = CoronaryStenosisExtractor()
    text = (
        "FINDINGS:\n"
        "Left Anterior Descending Coronary Artery: 80% proximal LAD stenosis.\n"
        "Residual stenosis 0% post stent."
    )
    res = extractor.extract(findings_text=text)
    assert res.findings_lad_stenosis == "PROXIMAL LAD: 80%"
```

**Step 2: Run test to verify it fails**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_coronary_stenosis.py -k test_residual_stenosis_ignored_in_diagnostic_scope -v`

**Step 3: Implement filter in `coronary_stenosis.py`**
In `_extract_scope`, skip clauses or sub-chunks matching:
`re.search(r"(?i)\b(?:residual\s+stenosis|residual\s*[:\-\s]|post[\-\s]?pci|post[\-\s]?stent)\b", cl)`

**Step 4: Run test to verify it passes**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_coronary_stenosis.py -k test_residual_stenosis_ignored_in_diagnostic_scope -v`
Expected: PASS

**Step 5: Commit**
`git add portable_app/cardio_tagger/coronary_stenosis.py portable_app/tests/test_coronary_stenosis.py`
`git commit -m "fix: block residual stenosis from diagnostic findings and conclusion extraction"`

---

### Task 4: Integrate PCI Intervention into `CascadingCardioSieve` & `DocumentTagResult`

**Files:**
- Modify: `portable_app/cardio_tagger/sieve_engine.py`
- Modify: `portable_app/cardio_tagger/batch_runner.py`
- Test: `portable_app/tests/test_sieve_pipeline.py`

**Step 1: Write failing test in `portable_app/tests/test_sieve_pipeline.py`**
Test end-to-end extraction through `CascadingCardioSieve.evaluate_document`:

```python
def test_pci_intervention_end_to_end_sieve():
    from cardio_tagger.sieve_engine import CascadingCardioSieve
    import yaml
    from pathlib import Path
    ont_path = Path(__file__).resolve().parents[1] / "cardio_tagger" / "ontology" / "cardio_concepts.yaml"
    ont = yaml.safe_load(ont_path.read_text(encoding="utf-8"))
    sieve = CascadingCardioSieve(ontology=ont, enable_gliner=False)

    text = (
        "CARDIAC CATHETERIZATION REPORT\n"
        "PATIENT: WONG AH TECK\n"
        "NRIC: S1234567A\n\n"
        "CORONARY ANGIOGRAM:\n"
        "LAD: 90% proximal stenosis.\n"
        "RCA: Normal.\n\n"
        "PCI INTERVENTION:\n"
        "Proximal LAD:\n"
        "Guiding catheter: 6Fr EBU 3.5 Launcher (Medtronic)\n"
        "Balloon: Sapphire NC 3.5 x 15 mm. 18 atm\n"
        "Drug-eluting stent: Synergy Megatron 4 x 20 mm. 14 atm\n"
        "Successful angioplasty. Residual stenosis 0%.\n\n"
        "CONCLUSION:\n"
        "Successful PCI to proximal LAD."
    )
    res = sieve.evaluate_document("pci_test.pdf", [text])
    # Diagnostic findings preserved
    assert "PROXIMAL LAD: 90%" in res.findings_lad_stenosis
    assert "RCA: 0%" in res.findings_rca_stenosis
    # PCI residual stenosis strictly separated
    assert res.pci_lad_residual_stenosis == "PROXIMAL LAD: 0%"
    assert res.pci_rca_residual_stenosis == ""
    assert res.pci_intervened_vessels == "PROXIMAL LAD"
    assert "PROXIMAL LAD: SUCCESSFUL ANGIOPLASTY" in res.pci_success_status
    assert "[GUIDING CATHETER]" in res.pci_devices_used
    assert "[BALLOON]" in res.pci_devices_used
    assert "[DRUG-ELUTING STENT]" in res.pci_devices_used
```

**Step 2: Run test to verify it fails**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_sieve_pipeline.py -k test_pci_intervention_end_to_end_sieve -v`

**Step 3: Implement fields and sieve call**
- In `DocumentTagResult`, add:
  ```python
  pci_intervened_vessels: str = ""
  pci_lmca_residual_stenosis: str = ""
  pci_lad_residual_stenosis: str = ""
  pci_lcx_residual_stenosis: str = ""
  pci_rca_residual_stenosis: str = ""
  pci_graft_residual_stenosis: str = ""
  pci_success_status: str = ""
  pci_devices_used: str = ""
  ```
- In `CascadingCardioSieve.__init__`, initialize `self.pci_extractor = PCIInterventionExtractor()`.
- In `evaluate_document`, invoke `self.pci_extractor.extract(parsed.pci_text)`.
- In `batch_runner.py`, update DuckDB table schema and CSV/Parquet export dict to include the 8 new columns.

**Step 4: Run test to verify it passes**
Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_sieve_pipeline.py -k test_pci_intervention_end_to_end_sieve -v`
Expected: PASS

**Step 5: Commit**
`git add portable_app/cardio_tagger/sieve_engine.py portable_app/cardio_tagger/batch_runner.py portable_app/tests/test_sieve_pipeline.py`
`git commit -m "feat: integrate PCI intervention extraction into sieve pipeline and DuckDB/Parquet exporters"`

---

### Task 5: Sync to Dist Bundle, Run Full Test Suite, and Verify Sample Reports

**Files:**
- Modify: `portable_app/cardio_tagger/__init__.py` (bump version to 1.5.0)
- Sync: `dist/cardio-tagger-portable/app/cardio_tagger/*`

**Step 1: Run full test suite**
Run: `C:\Python314\python.exe -m pytest portable_app/tests -v`
Expected: All 50+ tests PASS 100%.

**Step 2: Sync updated files to dist bundle**
Copy `__init__.py`, `pci_intervention.py`, `section_parser.py`, `coronary_stenosis.py`, `sieve_engine.py`, `batch_runner.py` into `dist/cardio-tagger-portable/app/cardio_tagger/`.

**Step 3: Run sample verification**
Run: `cmd.exe /c "cd /d dist\cardio-tagger-portable && run_sample_verification.bat < nul"`
Verify that `sample_results.csv` includes the 8 new columns cleanly populated without regressions.
Clean up temporary sample outputs.

**Step 4: Package and Release v1.5.0**
- Build `dist/cardio-tagger-portable-v1.5.0-windows-x64.zip`.
- Commit changes and tag `v1.5.0`.
- Push to origin and create GitHub Release v1.5.0.
