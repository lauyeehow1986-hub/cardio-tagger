# System Design: Indication STEMI, Indication AMI, PCI Done, and Primary PCI (PPCI) Tagging

**Date:** 2026-11-06  
**Status:** Approved  
**Target Version:** v1.6.0  

---

## 1. Overview & Clinical Objectives

This feature introduces automated clinical extraction for four core procedural and diagnostic indicators from cardiac catheterization and cardiology PDF reports:
1. **Indication: STEMI (`indication_stemi`)**: ST-segment elevation myocardial infarction as the acute clinical presentation or procedural indication.
2. **Indication: AMI (`indication_ami`)**: Acute myocardial infarction as a superset (includes STEMI, NSTEMI, and undifferentiated acute coronary syndrome).
3. **PCI Done (`pci_done`)**: Whether percutaneous coronary intervention (angioplasty, stenting, atherectomy, thrombectomy) was performed during the procedure.
4. **Primary PCI / PCI for STEMI Done (`ppci_done`)**: Whether emergent/primary PCI was performed for acute STEMI (either explicitly stated or synthesized from STEMI presentation + acute PCI intervention).

Each indicator outputs three synchronized fields:
* **Status**: `YES` (affirmed present), `NO` (absent / not performed), or `NEGATED` (explicitly ruled out or deferred).
* **Evidence**: The verbatim clinical phrase or sentence from the report providing unambiguous auditability.
* **Confidence**: Floating-point score (`0.00` to `1.00`) representing extraction certainty.

---

## 2. Scope & Section Rules

### 2.1 Indication STEMI & AMI Scope
* **Primary Scope**: `INDICATION`, `REASON FOR STUDY`, `DIAGNOSIS`, `PRE-PROCEDURE DIAGNOSIS`, `PROCEDURE TITLE`, and `CONCLUSION` sections.
* **Strict History Exclusion**: Mentions in past medical history sections (`PMHx`, `past medical history`, `history of coronary artery disease`, `prior MI in 20XX`) are strictly ignored.
* **Fallback Scope**: If no dedicated indication section exists, the procedure header, title, and conclusion sections are evaluated.

### 2.2 PCI Done & PPCI Done Scope
* **Primary Scope**: `PCI INTERVENTION` section, `PROCEDURE` / `PROCEDURE DETAILS` section, and `CONCLUSION` / `IMPRESSION` section.

---

## 3. Extraction & Classification Rules

### 3.1 STEMI vs. NSTEMI Differentiation
* **STEMI Patterns**:
  * Regex: `\b(?:STEMI|ST[\-\s]elevation\s+(?:myocardial\s+infarction|MI)|acute\s+STEMI|(?:anterior|inferior|lateral|posterior|anteroseptal|extensive)\s+STEMI)\b`
  * Strict negative lookahead/lookbehind: Must not match `NSTEMI`, `non-ST elevation`, or `non-STEMI`.
  * Negation handling: `"no STEMI"`, `"STEMI ruled out"` $\rightarrow$ `indication_stemi = NEGATED` (confidence `0.95`).
  * If affirmed: `indication_stemi = YES` (confidence `0.95`).
* **AMI (Superset)**:
  * Triggers `YES` if `indication_stemi = YES`.
  * Triggers `YES` if `NSTEMI` / `non-ST elevation MI` is present (`indication_stemi = NO`, `indication_ami = YES`).
  * Triggers `YES` if undifferentiated acute MI / ACS is present (`"Acute Myocardial Infarction"`, `"AMI"`, `"Troponin-positive ACS"`, `"Acute Coronary Syndrome"`).
  * Triggers `NO` (confidence `0.00`, evidence `""`) if no acute ischemic event is indicated.

### 3.2 PCI Done
* Evaluates `pci_intervened_vessels`, device deployments (stents, balloon angioplasty, atherectomy/IVL, thrombectomy), and procedural statements.
* **`YES`**: Intervened vessel detected, stent or balloon dilated, or narrative confirms angioplasty/stenting performed (confidence `0.95`–`1.00`).
* **`NEGATED`**: Explicitly documented non-intervention: `"PCI deferred"`, `"diagnostic coronary angiogram only"`, `"no intervention performed"`, `"conservative medical therapy"`, `"referred for CABG"` (confidence `0.95`).
* **`NO`**: Pure diagnostic procedure with no intervention keywords or devices.

### 3.3 PPCI Done (Primary PCI / PCI for STEMI)
* **`YES` (Explicit)**: Direct phrase match: `"Primary PCI"`, `"PPCI"`, `"Primary angioplasty"`, `"Primary PTCA"`, `"PCI for acute STEMI"`, `"Emergent PCI for STEMI"` (confidence `0.98`).
* **`YES` (Synthesized / Deduced)**: `pci_done == "YES"` **AND** `indication_stemi == "YES"` (confidence `0.92`).
  * Evidence: Combined indication evidence and PCI target vessel statement (e.g., `"Indication: Acute Anterior STEMI; Stented Proximal LAD"`).
* **`NO`**: Elective PCI, PCI without STEMI indication, or no PCI performed.

---

## 4. Architecture & Export Schema

### 4.1 Module: `indication_pci_classifier.py`
A lightweight, zero-dependency extractor exposing:
```python
@dataclass
class IndicationPCIResult:
    indication_stemi: str = "NO"
    indication_stemi_evidence: str = ""
    indication_stemi_confidence: float = 0.0
    indication_ami: str = "NO"
    indication_ami_evidence: str = ""
    indication_ami_confidence: float = 0.0
    pci_done: str = "NO"
    pci_done_evidence: str = ""
    pci_done_confidence: float = 0.0
    ppci_done: str = "NO"
    ppci_done_evidence: str = ""
    ppci_done_confidence: float = 0.0
```

### 4.2 Sieve Engine Integration (`sieve_engine.py`)
`DocumentTagResult` will include all 12 fields, populated after section parsing and PCI device extraction.

### 4.3 CLI and Export Layer (`cli.py`)
All 12 fields are added to `base_fields` in CSV exports, JSONL streaming, and DuckDB checkpoints.

---

## 5. Verification Plan

* **Unit Tests (`portable_app/tests/test_indication_pci.py`)**:
  1. `test_stemi_vs_nstemi_differentiation`: Confirm NSTEMI sets `indication_stemi = NO` and `indication_ami = YES`.
  2. `test_history_exclusion`: Confirm `"PMHx: STEMI in 2019"` results in `indication_stemi = NO`.
  3. `test_pure_diagnostic_cath`: Confirm diagnostic angiogram sets `pci_done = NO` and `ppci_done = NO`.
  4. `test_explicit_ppci`: Confirm `"Primary PCI to LAD"` sets `ppci_done = YES` with confidence 0.98.
  5. `test_synthesized_ppci`: Confirm STEMI indication + LAD stenting sets `ppci_done = YES` with confidence 0.92.
  6. `test_negated_pci`: Confirm `"PCI deferred"` sets `pci_done = NEGATED`.
* **Full Regression Suite**: Run all 57 existing test cases to ensure 100% backward compatibility.
