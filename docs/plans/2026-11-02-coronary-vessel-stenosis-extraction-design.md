# Design Document: Coronary Vessel Stenosis Extraction Engine

**Date:** 2026-11-02  
**Status:** Approved  
**Author:** Antigravity  

---

## 1. Executive Summary
This design adds automated extraction of fine-grained coronary artery stenosis and lesion severity from both the **Conclusion** (Impression / Plan / Summary) and **Diagnostic Information** (Findings / Angiographic Details) sections of cardiology reports (Cath/PCI, angiograms, consultation notes).

The engine parses anatomical qualifiers (e.g. `small`, `mid`, `proximal`, `ostial`, `distal`), main vessels, and branching vessels (e.g. `LAD`, `D1`, `LCx`, `OM1`, `RCA`, `PDA`, `RPL1`, `LMCA`, `LIMA`, `SVG`) along with their quantitative percentages (e.g. `50%`, `70-90%`, `~80%`) and qualitative lesion states (e.g. `100% CTO`, `total occlusion`, `patent stent`, `severe disease`).

Results are structured into 10 dedicated export columns across native coronary territories (`LMCA`, `LAD`, `LCx`, `RCA`) and bypass grafts (`Graft`).

---

## 2. Anatomical Territory Mapping & Taxonomy

Coronary lesions are mapped into 5 territories, each populated independently for both Conclusion and Diagnostic Findings scopes:

| Territory | Conclusion Column | Findings / Diagnostic Column | Covered Segments & Branches |
| :--- | :--- | :--- | :--- |
| **LMCA** | `conclusion_lmca_stenosis` | `findings_lmca_stenosis` | Left Main, LMCA, LM, LMS (ostial, mid/shaft, distal, bifurcation) |
| **LAD** | `conclusion_lad_stenosis` | `findings_lad_stenosis` | LAD (ostial, prox, mid, distal, apical), Diagonals (`D1`, `D2`, `D3`, diagonal branch), Ramus Intermedius (`RI`) |
| **LCX** | `conclusion_lcx_stenosis` | `findings_lcx_stenosis` | LCx, Circumflex (ostial, prox, mid, distal), Obtuse Marginals (`OM1`, `OM2`, `OM3`), Left Posterolateral (`LPL`, `LPL1`, `LPL2`) |
| **RCA** | `conclusion_rca_stenosis` | `findings_rca_stenosis` | RCA (ostial, prox, mid, distal), Posterior Descending (`PDA`, `RPDA`), Posterolateral (`RPL`, `RPL1`, `RPL2`, `RPL3`, `PLV`, `PLB`), Acute Marginal (`AM`) |
| **Graft** | `conclusion_graft_stenosis` | `findings_graft_stenosis` | Bypass grafts: `LIMA`, `RIMA`, `SVG` (SVG-LAD, SVG-OM, SVG-RCA, etc.) |

### Anatomical Modifiers & Caliber Prefixes
The extractor captures clinical prefixes preceding vessels or segments:
- **Caliber & dominance**: `small`, `large`, `dominant`, `nondominant` / `non-dominant`, `hypoplastic`, `ectatic`, `tortuous`
- **Segments**: `ostial`, `proximal` (or `prox`), `mid`, `distal`, `apical`
- **Examples**:
  - `small lcx 70-90%` $\rightarrow$ LCX territory: `SMALL LCX: 70-90%`
  - `mid lad 50%` $\rightarrow$ LAD territory: `MID LAD: 50%`
  - `rpl1 70%` $\rightarrow$ RCA territory: `RPL1: 70%`

---

## 3. Stenosis Grammar & Qualitative States

The grammar captures:
1. **Percentages**:
   - Single percentage: `50%`, `70%`, `99%`
   - Percentage range: `70-90%`, `70 to 90%`, `70% - 90%`, `50-60%`
   - Approximations / thresholds: `~70%`, `approx 80%`, `>70%`, `<50%`, `up to 90%`
2. **Qualitative & Occlusion Descriptors**:
   - `100% CTO` / `chronic total occlusion`
   - `total occlusion` / `100% occluded` / `acutely occluded`
   - `subtotal occlusion` / `99% critical stenosis`
   - `severe stenosis`, `moderate disease`, `mild plaque`, `minimal disease`, `irregularities`
   - `patent stent` / `in-stent restenosis (ISR)` / `instent restenosis`

---

## 4. Multi-Lesion Formatting & Representation

When multiple lesions belong to the same territory within a section, they are normalized and joined with semicolons:
- **LAD Example**: `"Mid LAD 50% stenosis. Distal D1 has 70-90% disease."`  
  $\rightarrow$ `conclusion_lad_stenosis`: `MID LAD: 50%; D1: 70-90%`
- **RCA Example**: `"Proximal RCA: 100% total occlusion. RPL1: 70%."`  
  $\rightarrow$ `findings_rca_stenosis`: `PROXIMAL RCA: 100% TOTAL OCCLUSION; RPL1: 70%`
- If explicitly normal (e.g. `"LCx: Normal"`), it records `LCX: NORMAL`. If no mention exists, the field remains empty `""`.

---

## 5. Architectural Components

1. **`portable_app/cardio_tagger/coronary_stenosis.py`**:
   - `CoronaryStenosisExtractor`: Pure Python, zero-external-dependency, regex-based segment parser.
   - `CoronaryStenosisResult`: Dataclass containing the 10 fields.
2. **`portable_app/cardio_tagger/section_parser.py`**:
   - Extract and expose both `conclusion_text` and `findings_text` (from `FINDINGS:`, `ANGIOGRAPHIC DETAILS:`, `CORONARY ARTERIES:`, etc.).
3. **`portable_app/cardio_tagger/sieve_engine.py`**:
   - Incorporate the 10 fields into `DocumentTagResult`.
   - Invoke `CoronaryStenosisExtractor` during document evaluation.
4. **`portable_app/cardio_tagger/cli.py`**:
   - Add the 10 fields to CSV outputs, Parquet schema, JSONL export, and DuckDB checkpoint persistence.

---

## 6. Verification Plan
- Unit test suite in `portable_app/tests/test_coronary_stenosis.py` covering:
  - User edge cases (`small lcx 70-90%`, `mid lad 50%`, `rpl1 70%`)
  - Occlusions and qualitative states (`100% CTO`, `total occlusion`, `patent stent`)
  - Multi-lesion concatenation in a territory
  - Graft extraction (`LIMA to LAD patent`, `SVG to RCA 90%`)
  - Dual-scope isolation (Conclusion vs Findings)
- Full regression testing with `pytest`.
- 1-click batch verification with `run_sample_verification.bat`.
