# Indication STEMI, Indication AMI, PCI Done, and PPCI Tagging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement automated clinical extraction and 12-column synchronized export for STEMI indication, AMI superset, PCI done status, and Primary PCI (PPCI) with evidence excerpts and confidence scores.

**Architecture:** A modular extractor `IndicationPCIClassifier` parses indication and conclusion sections while rejecting past medical history, accurately differentiates STEMI from NSTEMI, evaluates procedural text and hardware for PCI execution, and synthesizes PPCI status. This is wired directly into `sieve_engine.py` and exported through `cli.py`.

**Tech Stack:** Python 3.10+ (standard library `re`, `dataclasses`), `pytest`, existing `section_parser.py` and `pci_intervention.py`.

---

### Task 1: Core Classifier Module (`indication_pci_classifier.py`)

**Files:**
- Create: `portable_app/cardio_tagger/indication_pci_classifier.py`
- Create: `portable_app/tests/test_indication_pci.py`

**Step 1: Write the failing test**

In `portable_app/tests/test_indication_pci.py`:
```python
import pytest
from cardio_tagger.indication_pci_classifier import IndicationPCIClassifier, IndicationPCIResult
from cardio_tagger.section_parser import ClinicalSectionParser
from cardio_tagger.pci_intervention import PCIInterventionResult

def test_stemi_vs_nstemi_differentiation():
    classifier = IndicationPCIClassifier()
    parser = ClinicalSectionParser()
    
    # 1. Pure STEMI case
    stemi_text = "INDICATION: Acute extensive anterior STEMI.\nPROCEDURE: Coronary angiogram."
    parsed = parser.parse_sections(stemi_text)
    res = classifier.classify(parsed=parsed, pci_result=PCIInterventionResult())
    assert res.indication_stemi == "YES"
    assert "STEMI" in res.indication_stemi_evidence
    assert res.indication_stemi_confidence >= 0.90
    assert res.indication_ami == "YES"
    
    # 2. Pure NSTEMI case
    nstemi_text = "INDICATION: Acute coronary syndrome, NSTEMI with elevated troponin.\nPROCEDURE: Coronary angiogram."
    parsed_nstemi = parser.parse_sections(nstemi_text)
    res_nstemi = classifier.classify(parsed=parsed_nstemi, pci_result=PCIInterventionResult())
    assert res_nstemi.indication_stemi == "NO"
    assert res_nstemi.indication_ami == "YES"
    assert "NSTEMI" in res_nstemi.indication_ami_evidence
```

**Step 2: Run test to verify it fails**

Run: `pytest portable_app/tests/test_indication_pci.py::test_stemi_vs_nstemi_differentiation -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'cardio_tagger.indication_pci_classifier'`

**Step 3: Write minimal implementation**

Create `portable_app/cardio_tagger/indication_pci_classifier.py` defining:
* `IndicationPCIResult` dataclass with the 12 fields.
* `IndicationPCIClassifier` with STEMI and AMI regex patterns, strictly rejecting NSTEMI and extracting verbatim evidence sentences.

**Step 4: Run test to verify it passes**

Run: `pytest portable_app/tests/test_indication_pci.py::test_stemi_vs_nstemi_differentiation -v`  
Expected: PASS

**Step 5: Commit**

```bash
git add portable_app/cardio_tagger/indication_pci_classifier.py portable_app/tests/test_indication_pci.py
git commit -m "feat: implement IndicationPCIClassifier with STEMI and NSTEMI differentiation"
```

---

### Task 2: Past History Exclusion & Scoped Text Resolution

**Files:**
- Modify: `portable_app/cardio_tagger/indication_pci_classifier.py`
- Modify: `portable_app/tests/test_indication_pci.py`

**Step 1: Write the failing test**

In `portable_app/tests/test_indication_pci.py`:
```python
def test_history_exclusion_and_scope_priority():
    classifier = IndicationPCIClassifier()
    parser = ClinicalSectionParser()
    
    # History must be ignored
    history_text = (
        "PAST MEDICAL HISTORY: STEMI in 2017, hypertension, diabetes.\n"
        "INDICATION: Elective diagnostic catheterization for stable angina.\n"
        "CONCLUSION: Moderate LAD CAD."
    )
    parsed = parser.parse_sections(history_text)
    res = classifier.classify(parsed=parsed, pci_result=PCIInterventionResult())
    assert res.indication_stemi == "NO"
    assert res.indication_ami == "NO"
    
    # Conclusion fallback if no indication section
    conclusion_text = (
        "PROCEDURE: Coronary angiogram.\n"
        "CONCLUSION: Acute inferior STEMI. Recommended medical therapy."
    )
    parsed_conc = parser.parse_sections(conclusion_text)
    res_conc = classifier.classify(parsed=parsed_conc, pci_result=PCIInterventionResult())
    assert res_conc.indication_stemi == "YES"
    assert res_conc.indication_ami == "YES"
```

**Step 2: Run test to verify it fails**

Run: `pytest portable_app/tests/test_indication_pci.py::test_history_exclusion_and_scope_priority -v`  
Expected: FAIL (history text leaking into STEMI indication)

**Step 3: Write minimal implementation**

In `IndicationPCIClassifier`:
* Prioritize sections tagged as `indication` or `conclusion`.
* Explicitly exclude text from sections classified under `history` / `pmhx` or lines preceded by `PAST MEDICAL HISTORY`, `PMH:`, `PREVIOUS:`.
* If no indication section exists, safely fall back to procedure header / conclusion without touching history.

**Step 4: Run test to verify it passes**

Run: `pytest portable_app/tests/test_indication_pci.py::test_history_exclusion_and_scope_priority -v`  
Expected: PASS

**Step 5: Commit**

```bash
git add portable_app/cardio_tagger/indication_pci_classifier.py portable_app/tests/test_indication_pci.py
git commit -m "feat: enforce past history exclusion and conclusion fallback for indication tags"
```

---

### Task 3: PCI Done & Primary PCI (PPCI) Detection Logic

**Files:**
- Modify: `portable_app/cardio_tagger/indication_pci_classifier.py`
- Modify: `portable_app/tests/test_indication_pci.py`

**Step 1: Write the failing test**

In `portable_app/tests/test_indication_pci.py`:
```python
def test_pci_done_and_ppci_detection():
    classifier = IndicationPCIClassifier()
    parser = ClinicalSectionParser()
    
    # 1. Pure diagnostic catheterization
    diag_text = (
        "INDICATION: Stable angina.\n"
        "PROCEDURE: Diagnostic coronary angiography.\n"
        "FINDINGS: Normal coronaries. No PCI performed.\n"
        "CONCLUSION: Normal angiogram."
    )
    parsed_diag = parser.parse_sections(diag_text)
    res_diag = classifier.classify(parsed=parsed_diag, pci_result=PCIInterventionResult())
    assert res_diag.pci_done == "NO"
    assert res_diag.ppci_done == "NO"
    
    # 2. Explicit PPCI
    ppci_text = (
        "INDICATION: Chest pain.\n"
        "PROCEDURE: Primary PCI to Proximal LAD with 3.5x20mm DES.\n"
        "CONCLUSION: Successful primary angioplasty."
    )
    parsed_ppci = parser.parse_sections(ppci_text)
    pci_res = PCIInterventionResult(
        intervened_vessels="PROXIMAL LAD",
        devices_used="PROXIMAL LAD: [DRUG-ELUTING STENT] 3.5x20mm DES",
        success_status="PROXIMAL LAD: SUCCESSFUL ANGIOPLASTY"
    )
    res_ppci = classifier.classify(parsed=parsed_ppci, pci_result=pci_res)
    assert res_ppci.pci_done == "YES"
    assert res_ppci.ppci_done == "YES"
    assert res_ppci.ppci_done_confidence >= 0.95
    
    # 3. Synthesized PPCI (STEMI indication + PCI performed without the word 'primary')
    synth_text = (
        "INDICATION: Acute anterior STEMI.\n"
        "PROCEDURE: Angioplasty and stenting of culprit LAD.\n"
        "CONCLUSION: Successful stenting of LAD."
    )
    parsed_synth = parser.parse_sections(synth_text)
    res_synth = classifier.classify(parsed=parsed_synth, pci_result=pci_res)
    assert res_synth.indication_stemi == "YES"
    assert res_synth.pci_done == "YES"
    assert res_synth.ppci_done == "YES"
    assert res_synth.ppci_done_confidence >= 0.90
    
    # 4. Negated PCI
    neg_text = (
        "INDICATION: Severe 3-vessel CAD.\n"
        "PROCEDURE: Diagnostic angiogram. PCI deferred in view of surgical CABG.\n"
        "CONCLUSION: Plan CABG."
    )
    parsed_neg = parser.parse_sections(neg_text)
    res_neg = classifier.classify(parsed=parsed_neg, pci_result=PCIInterventionResult())
    assert res_neg.pci_done == "NEGATED"
    assert "deferred" in res_neg.pci_done_evidence.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest portable_app/tests/test_indication_pci.py::test_pci_done_and_ppci_detection -v`  
Expected: FAIL

**Step 3: Write minimal implementation**

In `IndicationPCIClassifier`:
* Evaluate `pci_result`: if `intervened_vessels` or `devices_used` is populated $\rightarrow$ `pci_done = YES`.
* Check negation patterns: `"PCI deferred"`, `"no intervention"`, `"diagnostic only"` $\rightarrow$ `pci_done = NEGATED`.
* Check explicit PPCI patterns: `"primary pci"`, `"ppci"`, `"primary angioplasty"`, `"pci for stemi"`.
* If explicit match $\rightarrow$ `ppci_done = YES` (conf `0.98`).
* If `pci_done == "YES"` and `indication_stemi == "YES"` $\rightarrow$ `ppci_done = YES` (conf `0.92`).
* Otherwise $\rightarrow$ `ppci_done = NO`.

**Step 4: Run test to verify it passes**

Run: `pytest portable_app/tests/test_indication_pci.py::test_pci_done_and_ppci_detection -v`  
Expected: PASS

**Step 5: Commit**

```bash
git add portable_app/cardio_tagger/indication_pci_classifier.py portable_app/tests/test_indication_pci.py
git commit -m "feat: implement pci_done and ppci_done explicit and synthesized detection"
```

---

### Task 4: Sieve Engine Integration (`sieve_engine.py`)

**Files:**
- Modify: `portable_app/cardio_tagger/sieve_engine.py`
- Modify: `portable_app/tests/test_sieve_pipeline.py`

**Step 1: Write the failing test**

In `portable_app/tests/test_sieve_pipeline.py`:
```python
def test_pipeline_indication_pci_fields():
    # Verify DocumentTagResult contains all 12 fields
    from cardio_tagger.sieve_engine import CascadingCardioSieve
    import yaml
    from pathlib import Path
    ont_path = Path(__file__).resolve().parents[1] / "cardio_tagger" / "ontology" / "cardio_concepts.yaml"
    ont = yaml.safe_load(ont_path.read_text(encoding="utf-8"))
    sieve = CascadingCardioSieve(ontology=ont, enable_gliner=False)
    
    text = (
        "INDICATION: Inferior STEMI.\n"
        "PCI INTERVENTION:\n"
        "RCA:\n"
        "Drug-eluting stent: 3.5 x 24 mm Onyx. 14 atm.\n"
        "Successful angioplasty. Residual stenosis 0%.\n"
        "CONCLUSION: Successful primary angioplasty to RCA."
    )
    res = sieve.evaluate_document("stemi_ppci.pdf", [text])
    assert res.indication_stemi == "YES"
    assert res.indication_ami == "YES"
    assert res.pci_done == "YES"
    assert res.ppci_done == "YES"
    assert res.ppci_done_confidence >= 0.90
    assert "RCA" in res.pci_intervened_vessels
```

**Step 2: Run test to verify it fails**

Run: `pytest portable_app/tests/test_sieve_pipeline.py::test_pipeline_indication_pci_fields -v`  
Expected: FAIL (`AttributeError: 'DocumentTagResult' object has no attribute 'indication_stemi'`)

**Step 3: Write minimal implementation**

In `sieve_engine.py`:
* Import `IndicationPCIClassifier`.
* Instantiate `self.indication_pci_classifier = IndicationPCIClassifier()` in `__init__`.
* Add 12 fields to `DocumentTagResult` dataclass.
* In `evaluate_document()`, invoke `self.indication_pci_classifier.classify(parsed=parsed, pci_result=pci_res)` and pass the 12 fields into `DocumentTagResult`.

**Step 4: Run test to verify it passes**

Run: `pytest portable_app/tests/test_sieve_pipeline.py::test_pipeline_indication_pci_fields -v`  
Expected: PASS

**Step 5: Commit**

```bash
git add portable_app/cardio_tagger/sieve_engine.py portable_app/tests/test_sieve_pipeline.py
git commit -m "feat: wire IndicationPCIClassifier into CascadingCardioSieve engine"
```

---

### Task 5: CLI & Export Layer Integration (`cli.py`)

**Files:**
- Modify: `portable_app/cardio_tagger/cli.py`
- Modify: `portable_app/tests/test_sieve_pipeline.py`

**Step 1: Write the failing test**

In `portable_app/tests/test_sieve_pipeline.py`:
```python
def test_cli_base_fields_include_indication_and_pci():
    from cardio_tagger.sieve_engine import DocumentTagResult
    import dataclasses
    field_names = [f.name for f in dataclasses.fields(DocumentTagResult)]
    for expected in [
        "indication_stemi", "indication_stemi_evidence", "indication_stemi_confidence",
        "indication_ami", "indication_ami_evidence", "indication_ami_confidence",
        "pci_done", "pci_done_evidence", "pci_done_confidence",
        "ppci_done", "ppci_done_evidence", "ppci_done_confidence"
    ]:
        assert expected in field_names
```

**Step 2: Run test to verify it fails**

Run: `pytest portable_app/tests/test_sieve_pipeline.py::test_cli_base_fields_include_indication_and_pci -v`  
Expected: PASS or FAIL depending on Task 4 state.

**Step 3: Write minimal implementation**

In `cli.py`:
* Add the 12 new fields to `base_fields` in both CSV writer setups (lines ~465 and ~615).
* Ensure row mapping dictionaries forward `res_dict[f]` into the output dictionary for each document.

**Step 4: Run full test suite**

Run: `pytest portable_app/tests -v`  
Expected: All 60+ tests PASS.

**Step 5: Commit**

```bash
git add portable_app/cardio_tagger/cli.py portable_app/tests/test_sieve_pipeline.py
git commit -m "feat: add indication and pci fields to CLI base fields and CSV exports"
```

---

### Task 6: Full Regression Verification & Distribution Sync

**Files:**
- Modify: `portable_app/cardio_tagger/__init__.py` (bump version to `1.6.0`)
- Sync: `dist/cardio-tagger-portable/app/cardio_tagger/`

**Step 1: Run all automated tests**
Run: `pytest portable_app/tests`  
Expected: 100% tests passing.

**Step 2: Sync to portable bundle**
Copy `indication_pci_classifier.py`, `sieve_engine.py`, `cli.py`, and `__init__.py` to `dist/cardio-tagger-portable/app/cardio_tagger/`.

**Step 3: Run sample verification batch**
Run: `dist/cardio-tagger-portable/run_sample_verification.bat` inside standard sandbox.

**Step 4: Commit and package**
```bash
git add portable_app/ dist/
git commit -m "chore: release v1.6.0 with STEMI, AMI, PCI Done, and PPCI tagging"
```
