# Design Document: PCI Intervention Extraction Engine

**Date:** 2026-11-03  
**Status:** Validated  
**Module:** `cardio_tagger.pci_intervention`

---

## 1. Overview & Motivation
Cardiac catheterization reports frequently include a dedicated procedural section titled `PCI INTERVENTION` (or variations such as `PERCUTANEOUS CORONARY INTERVENTION`, `PCI PROCEDURE`, `INTERVENTION`, `ANGIOPLASTY DETAILS`). 

Within this section, reports document:
1. Target vessel locations (native coronary arteries, anatomical segments, side-branches, and bypass grafts, e.g., `SVG to RPDA`, `LMCA`, `Prox RCA`, `RPAV`, `RPDA`, `Proximal LAD`, `D1`).
2. Multiple lines of specific devices used on that vessel (guiding catheters, balloons with ATM inflation pressures, drug-eluting stents with dimensions, intravascular imaging, calcium modification, etc.).
3. Procedural success outcome (e.g. `Successful angioplasty`, `Successful stenting`, `Unsuccessful`, `Suboptimal`).
4. Post-procedure residual stenosis (e.g. `Residual stenosis 0%`, `<10%`, or unstated/blank).

### Strict Boundary Isolation Requirement
**Pre-PCI diagnostic stenosis** (from `FINDINGS` and `CONCLUSION`) and **post-PCI residual stenosis** (from `PCI INTERVENTION`) must remain strictly isolated:
- Diagnostic stenosis columns must never capture post-PCI residual stenosis (e.g., `Residual stenosis 0%` must not overwrite pre-PCI 80% stenosis).
- PCI residual stenosis columns must only reflect the post-PCI result.
- If residual stenosis is omitted or blank in the report, it must remain blank `""` (never assumed or defaulted).

---

## 2. Output Schema & Column Definitions

Eight new dedicated columns are added to `DocumentTagResult`, DuckDB schemas, CSV, and Parquet outputs:

| Column Name | Type | Description & Example |
|---|---|---|
| `pci_intervened_vessels` | `str` | Semicolon-delimited list of treated vessels: `SVG TO RPDA; PROX RCA; D1` |
| `pci_lmca_residual_stenosis` | `str` | LMCA territory residual stenosis: `LMCA: 0%` or blank `""` |
| `pci_lad_residual_stenosis` | `str` | LAD territory residual stenosis: `PROXIMAL LAD: 0%; D1: 0%` or blank `""` |
| `pci_lcx_residual_stenosis` | `str` | LCx territory residual stenosis: `OM1: 0%` or blank `""` |
| `pci_rca_residual_stenosis` | `str` | RCA territory residual stenosis: `PROX RCA: 0%; RPDA: 0%` or blank `""` |
| `pci_graft_residual_stenosis` | `str` | Graft territory residual stenosis: `SVG TO RPDA: 0%` or blank `""` |
| `pci_success_status` | `str` | Procedural success per vessel: `SVG TO RPDA: SUCCESSFUL ANGIOPLASTY; PROX RCA: SUCCESSFUL ANGIOPLASTY` |
| `pci_devices_used` | `str` | Categorized granular device lines per vessel: `SVG TO RPDA: [GUIDING CATHETER] 6Fr EBU 3.5 Launcher (Medtronic); [BALLOON] Sapphire NC 24 3.5 x 15 mm (Orbus), 22 atm; [DRUG-ELUTING STENT] Synergy Megatron (MR) 4 x 20 mm (Boston Scientific), 10 atm; [IVUS] OptiCross` |

---

## 3. Architecture & Components

```
                          PDF Clinical Report
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │  ClinicalSectionParser   │
                     └────────────┬─────────────┘
                                  │
      ┌───────────────────────────┼───────────────────────────┐
      │ (Findings & Conclusion)   │ (PCI Section)             │ (Page 1)
      ▼                           ▼                           ▼
┌──────────────┐           ┌──────────────┐           ┌──────────────┐
│  Coronary    │           │     PCI      │           │ Demographics │
│  Diagnostic  │           │ Intervention │           │  & Echo EF   │
│  Stenosis    │           │  Extractor   │           │  Extractors  │
└──────┬───────┘           └──────┬───────┘           └──────┬───────┘
       │                          │                          │
       │ Diagnostic Stenosis      │ Residual Stenosis,       │
       │ (LMCA, LAD, LCX,         │ Devices, Outcome,        │ Demographics,
       │  RCA, Graft)             │ Intervened Vessels       │ LVEF, Staged PCI
       └──────────────────────────┼──────────────────────────┘
                                  │
                                  ▼
                       ┌──────────────────────┐
                       │  DocumentTagResult   │
                       └──────────┬───────────┘
                                  │
                                  ▼
                   DuckDB / Parquet / CSV Exports
```

### Component Details:

### 3.1 Section Parser (`section_parser.py`)
- Add `pci_intervention` to `OTHER_SECTION_HEADERS`:
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
  )
  ```
- Expose `parsed.pci_text` property returning the concatenated text of `pci_intervention` sections.
- Exclude `pci_intervention` text from `parsed.findings_text` to prevent bleed-through into diagnostic evaluation.

### 3.2 Diagnostic Stenosis Isolation (`coronary_stenosis.py`)
- Explicitly block residual patterns in diagnostic extraction:
  `\b(?:residual\s+stenosis|residual\s*[:\-\s]|post[\-\s]?pci|post[\-\s]?stent|post[\-\s]?angioplasty)\b`
  to guarantee that diagnostic stenosis only captures pre-PCI disease.

### 3.3 PCI Intervention Extractor (`pci_intervention.py`)
A dedicated pure Python extractor `PCIInterventionExtractor`:
1. **Block Segmentation**:
   - Detects vessel headings (e.g. `SVG to RPDA:`, `LMCA:`, `Prox RCA:`, `RPAV:`, `RPDA:`, `Proximal LAD:`, `D1:`, etc.).
   - Gathers all subsequent device, outcome, and residual stenosis lines under that vessel until the next vessel or section end.
2. **Comprehensive Vessel Recognition**:
   - Grafts: `SVG to <target>`, `LIMA to <target>`, `RIMA to <target>`, `BIMA`
   - RCA territory: `RPAV`, `RPDA`, `RPL1-3`, `AM1-2`, `Prox RCA`, `Mid RCA`, `Distal RCA`, `RCA`
   - LAD territory: `D1-D3`, `Diagonal`, `Proximal LAD`, `Mid LAD`, `Distal LAD`, `Ostial LAD`, `LAD`
   - LCX territory: `OM1-OM3`, `Obtuse Marginal`, `Proximal LCX`, `Mid LCX`, `Distal LCX`, `LCX`, `Ramus Intermedius`, `RI`
   - LMCA territory: `LMCA`, `LMS`, `Left Main`, `Ostial LMCA`
3. **Granular Device Classification**:
   - `[GUIDING CATHETER]`: Guiding catheters, ebu, jr, al, jl, launcher, guide catheter, etc.
   - `[BALLOON]`: Semi-compliant, NC balloon, Sapphire, Trek, Quantum, etc., with dimensions and ATM.
   - `[DRUG-ELUTING STENT]`: DES, Synergy Megatron, Onyx, Xience, Ultimaster, etc., with dimensions and ATM.
   - `[STENT]`: BMS or generic stents.
   - `[IVUS]`: Intravascular ultrasound, OptiCross, Eagle Eye, etc.
   - `[OCT]`: Optical coherence tomography, Dragonfly, OFDI, etc.
   - `[FFR]`: Fractional flow reserve, iFR, pressure wire, etc.
   - `[ROTABLATOR]`: Rotational atherectomy, rotablation burr, etc.
   - `[SHOCKWAVE (IVL)]`: Intravascular lithotripsy, IVL shockwave balloon, etc.
   - `[CUTTING/SCORING BALLOON]`: Wolverine, Flextome, scoring balloon, AngioSculpt, etc.
   - `[ASPIRATION / THROMBECTOMY]`: Export catheter, Pronto, aspiration, thrombectomy, etc.
4. **Procedural Outcome Recognition**:
   - `SUCCESSFUL ANGIOPLASTY`, `SUCCESSFUL STENTING`, `SUCCESSFUL PCI`, `UNSUCCESSFUL`, `SUBOPTIMAL RESULT`, `ABORTED`.
5. **Residual Stenosis Recognition**:
   - Matches: `Residual stenosis\s*[:\-\s]*([<>]?\s*[0-9]{1,3}(?:\s*-\s*[0-9]{1,3})?\s*%)`
   - Maps to standard territory dictionary: `LMCA`, `LAD`, `LCX`, `RCA`, `GRAFT`.
   - Leaves value strictly blank `""` if not present.

---

## 4. Verification & Testing Strategy
1. **Unit Tests (`test_pci_intervention.py`)**:
   - Test user exact clinical snippet:
     ```text
     PCI INTERVENTION:
     SVG to RPDA:
     Guiding catheter: 6fr ebu3.5 launcher(medtronic)
     Balloon: sapphire nc 24 3.5 x 15 mm (orbus). 22 atm
     Drug-eluting stent: synergy Megatron(mr) 4mm x 20mm (boston scientific). 10 atm.
     Successful angioplasty. Residual stenosis 0%.
     ```
   - Test multi-vessel intervention (`SVG to RPDA`, `LMCA`, `PROX RCA`, `RPAV`, `RPDA`, `PROXIMAL LAD`, `D1`).
   - Test specific granular device tags (`[IVUS]`, `[OCT]`, `[FFR]`, `[ROTABLATOR]`, `[SHOCKWAVE (IVL)]`, `[CUTTING/SCORING BALLOON]`, `[ASPIRATION / THROMBECTOMY]`).
   - Test blank residual stenosis behavior (verifying it remains empty string when unmentioned).
   - Test negative/unsuccessful outcomes (`Suboptimal result`, `Unsuccessful`).
2. **Two-Way Isolation Test**:
   - Verify report with both `FINDINGS: 80% proximal LAD stenosis` and `PCI INTERVENTION: Proximal LAD ... Residual stenosis 0%` keeps pre-PCI `findings_lad_stenosis = 'PROXIMAL LAD: 80%'` and `pci_lad_residual_stenosis = 'PROXIMAL LAD: 0%'`.
3. **Full Pipeline & Sample Verification**:
   - Run full 48+ test suite.
   - Run `run_sample_verification.bat` on the portable Windows distribution bundle.
