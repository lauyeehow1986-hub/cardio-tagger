# Patient Demographics, Dates & Procedure Type Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract patient name, NRIC (including standard S/T/F/G/M and temporary X/Y up to 12 chars), patient ID/MRN, procedure date, report date, procedure type code, and raw procedure title from Page 1 demographics headers of clinical cardiology PDFs and notes.

**Architecture:** A lightweight, deterministic header extractor (`PatientDemographicsExtractor`) parses the top demographics region of Page 1. Extracted metadata flows through `DocumentTagResult` in `sieve_engine.py` and is exported to CSV, Parquet, and JSONL via `cli.py`.

**Tech Stack:** Python 3.10+, regex, dataclasses, pytest.

---

### Task 1: Demographics & Procedure Extractor (`patient_demographics.py`)

**Files:**
- Create: `portable_app/cardio_tagger/patient_demographics.py`
- Test: `portable_app/tests/test_patient_demographics.py`

**Step 1: Write the failing tests**

```python
# portable_app/tests/test_patient_demographics.py
import pytest
from cardio_tagger.patient_demographics import PatientDemographicsExtractor, PatientDemographicsResult


def test_standard_singapore_nric_and_demographics():
    extractor = PatientDemographicsExtractor()
    text = (
        "NATIONAL HEART CENTRE SINGAPORE\n"
        "2D TRANSTHORACIC ECHOCARDIOGRAM REPORT\n\n"
        "Patient Name: TAN AH KOW, MR          NRIC: S1234567A\n"
        "MRN / Patient ID: 10029381            DOB: 12/03/1960    Sex: M\n"
        "Procedure Date: 28/10/2026            Report Date: 29/10/2026\n"
        "Referring Doctor: Dr. Smith, MD\n\n"
        "INDICATION: Shortness of breath.\n"
    )
    res = extractor.extract(text)
    assert res.patient_name == "TAN AH KOW"
    assert res.nric == "S1234567A"
    assert res.patient_id == "10029381"
    assert res.procedure_date == "2026-10-28"
    assert res.report_date == "2026-10-29"
    assert res.procedure_type == "TTE"
    assert "TRANSTHORACIC ECHOCARDIOGRAM" in res.procedure_title.upper()


def test_temporary_nric_x_and_y_up_to_13_chars():
    extractor = PatientDemographicsExtractor()
    
    # 9-char X NRIC
    t1 = "Name: JOHN DOE\nNRIC/FIN: X1234567A\nCase No: C88192\nDate of Exam: 15-Mar-2026\nCARDIAC CATHETERIZATION REPORT"
    r1 = extractor.extract(t1)
    assert r1.nric == "X1234567A"
    assert r1.procedure_type == "CATH_PCI"
    assert r1.procedure_date == "2026-03-15"

    # 13-char X temporary NRIC ending with alphabet (e.g. x01234567891a)
    t2 = "Patient: JANE SMITH MDM\nIdentity No: x01234567891a\nMRN: 994821\nStudy Date: 2026-05-20\nTRANSESOPHAGEAL ECHOCARDIOGRAM"
    r2 = extractor.extract(t2)
    assert r2.nric == "X01234567891A"
    assert r2.procedure_type == "TEE"
    assert r2.procedure_date == "2026-05-20"


def test_masked_nric():
    extractor = PatientDemographicsExtractor()
    t = "Patient Name: LEE KENG HUAT\nNRIC: S****567A\nHosp ID: H55432\nExam Date: 04.11.2026\nDOBUTAMINE STRESS ECHOCARDIOGRAM"
    r = extractor.extract(t)
    assert r.patient_name == "LEE KENG HUAT"
    assert r.nric == "S****567A"
    assert r.patient_id == "H55432"
    assert r.procedure_date == "2026-11-04"
    assert r.procedure_type == "STRESS_ECHO"
```

**Step 2: Run test to verify it fails**

Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_patient_demographics.py -p no:cacheprovider -v`  
Expected: `ModuleNotFoundError: No module named 'cardio_tagger.patient_demographics'`

**Step 3: Implement `PatientDemographicsExtractor`**

Create `portable_app/cardio_tagger/patient_demographics.py`:
- Demographics block extraction scoped to the top header on Page 1.
- `NRIC_STANDARD_PATTERN`: `[STFGM](?:[0-9]{7}|[\*X]{4}[0-9]{3})[A-Z]`
- `NRIC_TEMP_PATTERN`: `[XY][0-9A-Z\*]{5,10}[A-Z]` (allowing up to 12 characters, ending with an alphabet).
- Name extraction stripping `MR`, `MDM`, `MS`, `DR`, `MRS`, `PROF`.
- Date parser converting `DD/MM/YYYY`, `DD-Mon-YYYY`, `YYYY-MM-DD`, `DD.MM.YYYY`, `Month DD, YYYY` to ISO `YYYY-MM-DD`.
- Modality mapping: `TTE`, `TEE`, `STRESS_ECHO`, `CATH_PCI`, `RHC`, `OTHER`.

**Step 4: Run test to verify it passes**

Run: `C:\Python314\python.exe -m pytest portable_app/tests/test_patient_demographics.py -p no:cacheprovider -v`  
Expected: 3 passed.

---

### Task 2: Integrate into `DocumentTagResult` and `CascadingCardioSieve`

**Files:**
- Modify: `portable_app/cardio_tagger/sieve_engine.py`
- Test: `portable_app/tests/test_sieve_pipeline.py`

**Step 1: Write integration test**

Verify `evaluate_document` populates:
- `res.patient_name`
- `res.nric`
- `res.patient_id`
- `res.procedure_date`
- `res.report_date`
- `res.procedure_type`
- `res.procedure_title`

**Step 2: Update `sieve_engine.py`**

- Add fields to `DocumentTagResult`.
- Instantiate `PatientDemographicsExtractor` in `CascadingCardioSieve.__init__`.
- Call `extractor.extract(parsed.full_text[:3000])` in `evaluate_document`.

**Step 3: Run pytest to verify all pipeline tests pass**

Run: `C:\Python314\python.exe -m pytest portable_app/tests/ -p no:cacheprovider -v`

---

### Task 3: CLI & Export Updates (`cli.py`)

**Files:**
- Modify: `portable_app/cardio_tagger/cli.py`

**Step 1: Update CSV & Parquet Schema**

- Ensure `patient_name`, `nric`, `patient_id`, `procedure_date`, `report_date`, `procedure_type`, `procedure_title` are serialized to output CSV columns.
- Ensure DuckDB checkpointing persists these new fields.

**Step 2: Verification with Native `cmd.exe` Batch Files**

- Sync updated files to `dist/cardio-tagger-portable/app/cardio_tagger/`.
- Run `cmd.exe /c "cd /d dist\cardio-tagger-portable && run_sample_verification.bat < nul"`.
- Verify new demographics and procedure columns appear in `sample_results.csv`.

---

### Task 4: Packaging & Release `v1.3.0`

**Files:**
- Bundle: `dist/cardio-tagger-portable-v1.3.0-windows-x64.zip`
- Git commit & push.
- GitHub Release `v1.3.0`.
