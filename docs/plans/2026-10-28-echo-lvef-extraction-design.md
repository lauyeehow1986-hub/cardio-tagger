# Echo LVEF Extraction Engine Design Document

**Date**: 2026-10-28  
**Status**: Approved / In Progress  
**Objective**: Build a high-precision, hierarchical Left Ventricular Ejection Fraction (LVEF) extraction engine for Echocardiography reports (PDF and CSV) with strict section priority, method preference (3D > 2D > Visual), historical/dated value exclusion, and range parsing.

---

## 1. Clinical Context & Requirements

Echocardiography reports contain LVEF measurements across multiple sections and modalities:
- Modalities: 3D echocardiography volume calculations, 2D Biplane Simpson's method of discs, Teichholz M-mode formulas, and eyeball visual estimates.
- Sections: Executive Summary/Conclusion, Anatomical Findings/Left Ventricle descriptions, and Quantitative Measurement tables.
- Temporal artifacts: Frequent citations of prior/baseline historical echocardiograms (e.g. *"prior LVEF was 40% in 2021"*).

### Core Requirements
1. **Section Priority Cascade**:
   $$\text{Conclusion} \longrightarrow \text{Findings} \longrightarrow \text{Measurements}$$
   - Search Conclusion first; if a valid non-historical LVEF is found, stop and select it.
   - If not in Conclusion, search Findings.
   - If not in Findings, search Measurements.
2. **Method Ranking (Within Active Section)**:
   $$\mathbf{3D} \;>\; \mathbf{2D} \;(\text{Biplane / Simpson's / Auto-EF}) \;>\; \mathbf{UNSPECIFIED} \;>\; \mathbf{VISUAL} \;(\text{Eyeball / Estimated})$$
3. **Historical Value Exclusion**:
   - Exclude historical/prior dated values.
   - Disambiguate comparative sentences (e.g., *"improved from 35% on 11/2023 to 55% currently"* $\rightarrow$ select `55%`, discard `35%`).
4. **Range & Numeric Parsing**:
   - Discrete numbers (e.g., `55%`) $\rightarrow$ string: `"55%"`, numeric: `55.0`.
   - Ranges (e.g., `50-55%`, `50 to 55%`) $\rightarrow$ string: `"50-55%"`, numeric: `52.5` (midpoint).
   - Inequalities (e.g., `>55%`, `<35%`) $\rightarrow$ string: `">55%"`, numeric: `55.0`.
   - Qualitative terms (if no numbers anywhere in study): e.g., `"Normal"` $\rightarrow$ string: `"Normal"`, numeric: `null`.

---

## 2. Architectural Components

### 2.1 Section Parser Enhancements (`section_parser.py`)
Add explicit support for Echocardiography section headers:
- `conclusion`: `CONCLUSION`, `IMPRESSION`, `SUMMARY`, `FINAL IMPRESSION`, `OVERALL ASSESSMENT`.
- `findings`: `FINDINGS`, `LEFT VENTRICLE`, `LV SYSTOLIC FUNCTION`, `CHAMBERS`, `2D/DOPPLER FINDINGS`, `WALL MOTION ASSESSMENT`.
- `measurements`: `MEASUREMENTS`, `QUANTITATIVE MEASUREMENTS`, `ECHO MEASUREMENTS`, `M-MODE & 2D MEASUREMENTS`, `HEMODYNAMICS & MEASUREMENTS`.

### 2.2 Echo LVEF Extractor Module (`echo_lvef.py` & `sieve_engine.py`)
A dedicated clinical entity parser that evaluates text blocks:
1. Candidate pattern matching (regex + token trie) capturing:
   - Target percentages & ranges: `([0-9]{2}(?:\s*(?:-|to|–)\s*[0-9]{2})?\s*%)` or `([><]\s*[0-9]{2}\s*%)`
   - Associated method keywords within a 12-token context window
   - Associated temporal/historical markers (dates, `prior`, `previous`, `baseline`, `improved from`, `decreased from`)
2. Temporal Disambiguation:
   - Clause splitter separating comparative statements into historical vs current clauses.
3. Candidate scoring and selection:
   - Group non-historical candidates by section.
   - Within the highest-priority section having non-historical candidates, select the candidate with highest method rank.

### 2.3 CLI & Schema Integration (`cli.py`)
Add four dedicated columns to all output CSVs and Parquet files:
- `lvef_extracted` (VARCHAR)
- `lvef_numeric` (FLOAT)
- `lvef_method` (VARCHAR)
- `lvef_section` (VARCHAR)

---

## 3. Test & Verification Plan
1. **Case 1**: Conclusion with Visually Estimated 50-55% $\rightarrow$ Output `50-55%`, `52.5`, `VISUAL`, `CONCLUSION`.
2. **Case 2**: Conclusion with both 3D 58% and 2D Simpson 54% $\rightarrow$ Output `58%`, `58.0`, `3D`, `CONCLUSION`.
3. **Case 3**: Conclusion has NO LVEF; Findings has 2D Biplane 45% $\rightarrow$ Output `45%`, `45.0`, `2D_BIPLANE`, `FINDINGS`.
4. **Case 4**: Conclusion & Findings have NO LVEF; Measurements table has `LVEF (Biplane): 60%` $\rightarrow$ Output `60%`, `60.0`, `2D_BIPLANE`, `MEASUREMENTS`.
5. **Case 5**: Comparative sentence: *"LVEF has improved from 30% in 2022 to 55% today"* $\rightarrow$ Output `55%`, `55.0`, not 30%.
6. **Case 6**: Pure historical: *"Prior study in 2021 showed LVEF 40%. Current study image quality inadequate."* $\rightarrow$ Output `NONE`, `null`, `NONE`, `NONE`.
7. **Case 7**: Qualitative only: *"Normal LV systolic function, no regional wall motion abnormalities"* $\rightarrow$ Output `"Normal"`, `null`, `QUALITATIVE`, `CONCLUSION`.
