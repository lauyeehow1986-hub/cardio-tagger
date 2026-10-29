# Design Document: Patient Demographics, Dates & Procedure Type Extraction

**Date**: 2026-10-29  
**Target Module**: `portable_app/cardio_tagger/patient_demographics.py`  
**Integration Points**: `sieve_engine.py`, `section_parser.py`, `cli.py`  

---

## 1. Executive Summary

This feature extends the Cardio-Tagger pipeline to automatically extract essential clinical administrative metadata from the header / demographics section on Page 1 of medical reports (Cath/PCI, TTE, TEE, Stress Echo):
1. **`patient_name`**: Patient full name with titles stripped (`MR`, `MDM`, `MS`, `DR`, etc.).
2. **`nric`**: Singapore National Registration Identity Card / FIN / Temporary IDs:
   - Standard NRIC/FIN: `S1234567A`, `T0123456B`, `F1234567M`, `G1234567A`, `M1234567A`.
   - Masked NRIC/FIN: `S****567A`, `T****123B`, etc.
   - Temporary Hospital NRIC: Starting with `X` or `Y`, up to 13 characters total, ending with an alphabet (e.g., `X1234567A`, `X01234567891A`, `Y1234567890A`, `X****567A`).
3. **`patient_id`**: Hospital Registration Number, MRN, or Case Number.
4. **`procedure_date`**: Date the procedure/study was performed, normalized to ISO `YYYY-MM-DD`.
5. **`report_date`**: Date the report was created/verified, normalized to ISO `YYYY-MM-DD`.
6. **`procedure_type`**: Normalized code (`TTE`, `TEE`, `STRESS_ECHO`, `CATH_PCI`, `RHC`, `OTHER`).
7. **`procedure_title`**: Raw title string from report header (e.g. `2D TRANSTHORACIC ECHOCARDIOGRAM REPORT`).

---

## 2. Extraction Logic & Component Design

### 2.1 Demographics Region Isolation
The extractor analyzes the first 2,500 characters of Page 1 or all text prior to clinical narrative section headers (`INDICATION:`, `CLINICAL HISTORY:`, `FINDINGS:`, `PROCEDURE DETAILS:`).

### 2.2 Field Extraction Rules

#### A. NRIC / FIN Extraction
- **Standard & Masked NRIC**:
  `r"(?i)\b(?P<nric>[STFGM](?:[0-9]{7}|[\*X]{4}[0-9]{3})[A-Z])\b"`
- **Temporary X/Y NRIC (up to 13 chars, ending with alphabet)**:
  `r"(?i)\b(?P<nric_temp>[XY][0-9A-Z\*]{6,11}[A-Z])\b"`
- **Contextual Label Match**:
  Under `NRIC:`, `FIN:`, `Identity No:`, `ID No:`, `NRIC/FIN:`, `National ID:`.

#### B. Patient Name Extraction
- Matches `Patient Name:`, `Name:`, `Pt Name:`, `Patient:` while avoiding clinician labels (`Doctor:`, `Physician:`, `Sonographer:`, `Reported By:`).
- Cleans prefixes: `MR`, `MRS`, `MDM`, `MS`, `DR`, `MISS`, `A/PROF`, `PROF`.
- Strips trailing punctuation, commas, or adjacent metadata tags.

#### C. Patient ID / MRN Extraction
- Matches `MRN:`, `Patient ID:`, `Hosp ID:`, `Registration No:`, `Reg No:`, `Case No:`, `Account No:`.
- Extracts alphanumeric identifier.

#### D. Procedure & Report Dates
- Labeled patterns for Procedure Date: `Procedure Date:`, `Date of Study:`, `Study Date:`, `Exam Date:`, `Date of Procedure:`, `Date Performed:`.
- Labeled patterns for Report Date: `Report Date:`, `Date of Report:`, `Dictated Date:`, `Verified Date:`, `Transcribed Date:`.
- Robust parser converting `DD/MM/YYYY`, `DD-Mon-YYYY`, `YYYY-MM-DD`, `DD.MM.YYYY`, `Month DD, YYYY` to standard `YYYY-MM-DD`.
- Fallback: If only one date is present in the demographics header, `procedure_date` takes it.

#### E. Procedure Type & Title
- **Normalized Code**:
  - `TTE`: `Transthoracic Echocardiogram`, `TTE`, `2D Echo`, `Transthoracic Echo`, `Echocardiogram Report`.
  - `TEE`: `Transesophageal Echocardiogram`, `TEE`, `Trans-esophageal Echo`.
  - `STRESS_ECHO`: `Stress Echocardiogram`, `Dobutamine Stress Echo`, `Exercise Stress Echo`.
  - `CATH_PCI`: `Coronary Angiogram`, `Cardiac Catheterization`, `PCI Report`, `Angiography Report`, `Coronary Intervention`.
  - `RHC`: `Right Heart Catheterization`, `Swan-Ganz`, `Hemodynamics`.
  - `OTHER`: Default when no specific modality is matched.
- **Raw Title**:
  - Captured from the first 3 lines of Page 1 or the matched title line.

---

## 3. Data Flow & Output Schema

### 3.1 Updated `DocumentTagResult` Dataclass
```python
@dataclass
class DocumentTagResult:
    pdf_path: str
    total_pages: int
    conclusion_found: bool
    conclusion_in_early_section: bool
    staged_pci_detected: bool
    staged_pci_status: str
    staged_pci_vessels: List[str]
    staged_pci_timeframe: Optional[str]
    staged_pci_confidence: float
    all_concept_matches: List[ConceptMatch]
    processing_ms: float
    peak_tier_used: str
    used_ocr_fallback: bool = False
    lvef_extracted: str = "NONE"
    lvef_numeric: Optional[float] = None
    lvef_method: str = "NONE"
    lvef_section: str = "NONE"
    # New demographics & procedure fields:
    patient_name: str = ""
    nric: str = ""
    patient_id: str = ""
    procedure_date: str = ""
    report_date: str = ""
    procedure_type: str = "OTHER"
    procedure_title: str = ""
```

### 3.2 Output CSV / Parquet Columns
The generated CSV and Parquet files will include:
`patient_name, nric, patient_id, procedure_date, report_date, procedure_type, procedure_title, staged_pci_detected, ...`

---

## 4. Test & Verification Plan
1. **Unit Tests in `test_patient_demographics.py`**:
   - Singapore standard NRIC (`S1234567A`, `T0123456B`).
   - Temporary NRIC (`X1234567A`, `Y1234567890A` up to 12 chars ending in alphabet).
   - Masked NRIC (`S****567A`, `X****567A`).
   - Patient name cleaning (stripping titles, handling Asian and Western names).
   - Procedure and Report date parsing & ISO normalization.
   - Procedure type identification (`TTE`, `TEE`, `CATH_PCI`, `STRESS_ECHO`).
2. **Integration Verification**:
   - Verify `evaluate_document` output with all new fields.
   - Verify CLI runs on PDFs and CSVs in pure `cmd.exe` batch mode.
   - Regression test across all existing 26 unit tests.
