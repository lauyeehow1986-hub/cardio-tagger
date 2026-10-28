# Cardio-Tagger: 1M-PDF Clinical Cardiology & Staged PCI Portable Tagger

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Windows x64](https://img.shields.io/badge/Platform-Windows%20x64%20(Zero--Admin)-brightgreen.svg)]()
[![RAM Budget: 16 GB CPU](https://img.shields.io/badge/RAM%20Budget-16%20GB%20CPU-orange.svg)]()
[![PowerShell: None Required](https://img.shields.io/badge/PowerShell-Zero%20Dependency-blueviolet.svg)]()

A high-throughput, fault-tolerant, **zero-admin-rights** Windows x64 application engineered to stream through **1,000 to 1,000,000+ clinical cardiology PDF reports**. It accurately detects, classifies, and extracts **Staged Percutaneous Coronary Intervention (Staged PCI)** and 10+ core cardiology concepts primarily from the **Conclusion / Impression / Plan** section (whether on Page 1 or the final page), while supporting full extensibility via a declarative YAML ontology (`cardio_concepts.yaml`).

Designed specifically for **locked-down hospital/enterprise workstations** with **no administrator rights**, **no PowerShell availability**, and a strict **16 GB CPU-only RAM ceiling**.

---

## Architecture: The 6-Tier Cascading Clinical Sieve

To process up to 1,000,000 PDFs without out-of-memory errors or C-heap fragmentation, `cardio-tagger` employs a cascading sieve where each tier only receives documents/sentences that passed the previous gate:

| Pipeline Tier | Engine / Library | Scope | Latency / Doc | RAM (4 Workers) | Purpose in Cardiology Sieve |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 0: Streamer & Parser** | PyMuPDF (`fitz`) + RapidOCR + DuckDB | Native PDF text (OCR fallback if scanned) | `~1.5 ms` (`~180 ms` if OCR) | `~350 MB` | Isolates `CONCLUSION` / `IMPRESSION` / `PLAN` whether on Page 1 or last page; merges Plan; stops at signatures. |
| **Tier 1: Lexical Gate** | `pyahocorasick` C-trie + Regex | Target Conclusion / Plan sections | `<0.2 ms` | `<60 MB` | Filters out 85–92% of non-matching reports in sub-millisecond time. |
| **Tier 2: ConText Assertion** | `medSpaCy` ConText Modifier Windows | Sentences passing Tier 1 | `1.8 ms` | `~180 MB` | Classifies matches into 5 clinical states: `AFFIRMED_PLANNED`, `AFFIRMED_PERFORMED_INDEX`, `CONDITIONAL`, `HISTORICAL`, `NEGATED`. |
| **Tier 3: Biomedical NER** | `GLiNER-BioMed` (`Ihor/gliner-biomed-bi-small-v1.0`) INT8 ONNX | Sentences passing Tier 1 & 2 (~8–15%) | `14.0 ms` | `~1.52 GB` | Extracts zero-shot spans: target vessels (`LAD`, `RCA`, `LCx`, `OM1`, `LMCA`), timeframe (`in 4 weeks`), stent dimensions, `LVEF %`, `FFR/iFR`. |
| **Tier 4: OCR Typo Recovery** | `RapidFuzz` Token Ratio | Unmatched / noisy text | `2.5 ms` | `~160 MB` | Recovers degraded OCR text (*"stged PCl"*, *"stgd percutanous"*) and typo variations. |
| **Tier 5: LLM Arbitrator** | Portable Ollama (`Qwen2.5-3B-Instruct-Q4_K_M`) | Ambiguous / conditional cases only (<1.5%) | `420 ms` | `~2.25 GB` (shared single instance) | Adjudicates complex conditional logic (*"consider staged PCI if outpatient stress test positive"*). |

Peak memory consumption across 4 workers + DuckDB + OS overhead remains strictly **<= 8.6 GB**, leaving **>= 7.4 GB safe headroom** on a 16 GB workstation.

---

## Quickstart Guide

### Option 1: Standalone Portable Bundle (No Installation, No PowerShell, No Admin)

1. Download [`cardio-tagger-portable-v1.0.0-windows-x64.zip`](https://github.com/lauyeehow1986-hub/cardio-tagger/releases) from the Releases page.
2. Extract the ZIP anywhere on your target Windows PC (e.g. `C:\Users\%USERNAME%\Desktop\cardio-tagger-portable` or a USB drive).
3. **Run 1-Click Verification**: Double-click `run_sample_verification.bat` in Windows File Explorer. It executes 5 bundled clinical edge-case reports through `cmd.exe` and displays summary results.
4. **Interactive Processing**: Double-click `run_cardio_tagger.bat` to launch the interactive directory prompt. Drag and drop your folder of PDFs into the window and press Enter.

### Option 2: Command Prompt CLI Usage

Open standard Windows Command Prompt (`cmd.exe`) in the extracted portable folder:

```cmd
cd cardio-tagger-portable

REM 1. Run over a directory of PDFs (outputs exact PDF paths and True/False Staged PCI indicators)
run_cardio_tagger.bat --input-dir "C:\ClinicalData\CathReports"

REM 2. Run over a clinical notes CSV table (preserves original columns, appends tags)
run_cardio_tagger.bat --input-csv "C:\ClinicalData\patient_cohort.csv" --text-column clinical_note --output-csv tagged_cohort.csv

REM 3. Run on specific cardiac conditions (e.g. Heart Failure, AFib, and Staged PCI)
run_cardio_tagger.bat --input-dir "C:\ClinicalData\CathReports" --concepts staged_pci heart_failure_syndrome atrial_fibrillation_arrhythmia

REM 4. Full production run with 4 workers, Parquet export, and DuckDB checkpoint resume
run_cardio_tagger.bat --input-dir "C:\ClinicalData\CathReports" --output-csv results.csv --output-parquet results.parquet --output-jsonl detailed.jsonl --resume --workers 4
```

---

## CLI Reference & Flags

```text
usage: cardio-tagger [-h] (--input-dir INPUT_DIR | --input-csv INPUT_CSV)
                     [--text-column TEXT_COLUMN] [--id-column ID_COLUMN]
                     [--output-csv OUTPUT_CSV] [--output-jsonl OUTPUT_JSONL]
                     [--output-parquet OUTPUT_PARQUET]
                     [--checkpoint-db CHECKPOINT_DB] [--resume] [--workers WORKERS]
                     [--ontology ONTOLOGY] [--concepts [CONCEPTS ...]]
                     [--all-sections] [--enable-ollama]
```

### Argument Details

| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--input-dir` | Path | *Optional* | Path to folder containing clinical PDFs, scanned PDFs, or text notes (`.pdf`, `.txt`, `.md`). Recursively scanned. |
| `--input-csv` | File | *Optional* | Path to input tabular CSV file containing clinical notes/reports (e.g. EHR extraction tables). |
| `--text-column` | String | *Auto-detected* | Name of column in input CSV containing report text (e.g. `report_text`, `clinical_note`, `impression`). |
| `--id-column` | String | *Auto-detected* | Name of column in input CSV containing row ID (e.g. `patient_id`, `mrn`, `row_id`). |
| `--output-csv` | File | `staged_pci_results.csv` | Summary CSV file containing document-level classification, condition flags, vessels, timeframe, confidence, and page metadata. |
| `--output-parquet` | File | `staged_pci_results.parquet` | High-performance columnar Parquet file containing all structured features for analytics in DuckDB, Polars, or Python. |
| `--output-jsonl` | File | `staged_pci_detailed.jsonl` | Line-delimited JSON with full span-level evidence, sentence matches, and multi-concept tags. |
| `--checkpoint-db` | File | `checkpoint.duckdb` | Path to embedded DuckDB database persisting processed files and mtime hashes. |
| `--resume` | Flag | `False` | Resumes an interrupted run. Reads `checkpoint.duckdb` and skips files matching `(pdf_path, file_size, mtime_ns)`. |
| `--workers` | Int | `4` | Number of worker processes. Uses `maxtasksperchild=500` to guarantee zero memory leaks across 1M docs. |
| `--ontology` | File | `cardio_concepts.yaml` | Path to declarative cardiology ontology YAML. |
| `--concepts` | List | `None` (All) | Optional subset of concept IDs to extract (e.g. `--concepts staged_pci heart_failure_syndrome atrial_fibrillation_arrhythmia`). |
| `--all-sections` | Flag | `False` | Extends search beyond Conclusion / Impression / Plan to include History, Procedure, Hemodynamics, and Anatomy. |
| `--enable-ollama`| Flag | `False` | Enables local Ollama CPU arbitrator on `127.0.0.1:11435` for ambiguous conditional statements. |

---

## Output Data Structure

The generated CSV and Parquet files contain the following clinical schema:

### Core Document & Staged PCI Columns
| Column | Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `pdf_path` | String | `reports/cath_10492.pdf` | Source file path or CSV document ID (`patient_id`) |
| `staged_pci_detected` | Boolean | **`True`** / **`False`** | **Explicit indicator: `True` if Staged PCI is present (Planned, Performed Index, or Conditional); `False` otherwise** |
| `staged_pci_status` | Enum | `AFFIRMED_PLANNED` | Granular clinical status: `AFFIRMED_PLANNED`, `AFFIRMED_PERFORMED_INDEX`, `CONDITIONAL`, `HISTORICAL`, `NEGATED`, `NONE` |
| `staged_pci_vessels` | String | `MID-LAD;RCA` | Extracted target coronary branches |
| `staged_pci_timeframe` | String | `in 4 weeks` | Extracted staging timeframe |
| `staged_pci_confidence`| Float | `0.99` | Sieve confidence score (0.0 to 1.0) |
| `detected_cardio_concepts`| String | `CARDIO_AMI;CARDIO_STAGED_PCI` | Semicolon-delimited list of all affirmed cardiology concepts |
| `conclusion_found` | Boolean | `True` | Whether a conclusion section was detected |
| `total_pages` | Integer | `3` | Total pages in PDF (or 1 for CSV note) |
| `peak_tier_used` | String | `Tier3_GLiNER_BioMed` | Highest sieve tier invoked for this report |
| `processing_ms` | Float | `2.84` | Wall-clock processing time in milliseconds |

### Multi-Cardiology Condition Columns (for Every Concept in Ontology)
For each active condition, the output includes two dedicated columns:
- `has_<concept_name>`: Boolean (`True` / `False`) indicating presence of that condition
- `<concept_name>_status`: Clinical assertion status (`AFFIRMED`, `AFFIRMED_PLANNED`, `CONDITIONAL`, `HISTORICAL`, `NEGATED`, `NONE`)

Examples:
- `has_heart_failure_syndrome` & `heart_failure_syndrome_status`
- `has_atrial_fibrillation_arrhythmia` & `atrial_fibrillation_arrhythmia_status`
- `has_acute_myocardial_infarction` & `acute_myocardial_infarction_status`
- `has_cabg_evaluation` & `cabg_evaluation_status`
- `has_lvef_systolic_function` & `lvef_systolic_function_status`
- `has_coronary_vessel_stenosis` & `coronary_vessel_stenosis_status`
- `has_cardiomyopathy_myocarditis` & `cardiomyopathy_myocarditis_status`
- `has_structural_valvular_intervention` & `structural_valvular_intervention_status`

When `--input-csv` is used, all original columns from your input CSV (e.g. `patient_id`, `mrn`, `age`, `encounter_date`) are **100% preserved**, and these clinical tagger columns are appended directly.

---

## Extensible Cardiology Ontology (`cardio_concepts.yaml`)

Concepts are defined declaratively in `portable_app/cardio_tagger/ontology/cardio_concepts.yaml`. Pre-configured concepts include:
- `staged_pci` (SNOMED-CT: 415070008, UMLS: C1532338)
- `primary_or_culprit_pci`
- `cabg_evaluation`
- `lvef_systolic_function`
- `coronary_vessel_stenosis`
- `intracoronary_physiology_imaging` (IVUS, OCT, FFR, iFR)
- `calcium_modification_athrectomy` (Rotablator, Shockwave IVL)
- `structural_valvular_intervention` (TAVR, MitraClip)
- `mechanical_circulatory_support` (Impella, IABP, ECMO)
- `dapt_antithrombotic_regimen`
- `heart_failure_syndrome` (HFrEF, HFpEF, CHF, NYHA class)
- `atrial_fibrillation_arrhythmia` (AFib, Atrial Flutter, PVI ablation)
- `acute_myocardial_infarction` (STEMI, NSTEMI, Unstable Angina, ACS)
- `cardiomyopathy_myocarditis` (HCM/HOCM, DCM, Amyloidosis, Myocarditis)

---

## Model Context Protocol (MCP) Server for Antigravity IDE

A custom FastMCP server is included in `mcp_servers/cardio_tagger_mcp/server.py` to allow AI coding agents in Antigravity IDE to inspect documents and run benchmarks:

```json
{
  "mcpServers": {
    "cardio-tagger-mcp": {
      "command": "python",
      "args": ["mcp_servers/cardio_tagger_mcp/server.py"],
      "env": {
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

---

## Development & Building

To run tests on the development workstation:
```bash
python -m pytest portable_app/tests/test_sieve_pipeline.py -p no:cacheprovider -v
```

To assemble a fresh portable Windows bundle:
- Via Command Prompt: `portable_app\scripts\build_portable_bundle.bat`
- Via PowerShell: `portable_app\scripts\build_portable_bundle.ps1`

---

## Security & Privacy Notice

- **Clean Room Reimplementation**: Built purely from clinical concept specifications.
- **Zero Real Patient Data**: Only synthetic and de-identified catheterization reports are included.
- **Zero Network Ingestion**: The portable runtime runs 100% offline with zero outbound network calls, zero telemetry, and zero writes to system directories or `%APPDATA%`.
- **Educational / Research Use**: Not intended for automated diagnosis or unsupervised clinical decision-making.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
