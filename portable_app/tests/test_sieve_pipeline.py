#!/usr/bin/env python3
"""
End-to-End Verification Suite for the 6-Tier Clinical Cardiology & Staged PCI Sieve.
Tests:
  1. Classic final-page Conclusion with newline delimiter + Staged PCI to LAD in 4 weeks
  2. Early-section (Page 1 of 3) Executive Summary Conclusion with inline colon delimiter
  3. Negated Staged PCI ("No indication for staged PCI to diagonal branch")
  4. Historical Staged PCI ("History of prior staged PCI to RCA 2 years ago")
  5. Conditional Staged PCI ("Consider staged PCI to LCx if outpatient MPI shows ischemia")
  6. Index-Admission Performed Staged PCI ("Successful staged PCI to mid-LAD performed today")
  7. OCR Typo Recovery ("Recommend stged PCl to OM1 in 2 to 4 weeks") + Multi-Concept (LVEF, IVUS, CABG, DAPT)
  8. DuckDB Checkpointing & State Persistence
"""
import sys
from pathlib import Path

# Add portable_app to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml
from cardio_tagger.sieve_engine import CascadingCardioSieve
from cardio_tagger.section_parser import ClinicalSectionParser
from cardio_tagger.cli import DuckDBCheckpointManager


def get_sieve() -> CascadingCardioSieve:
    ontology_path = Path(__file__).resolve().parents[1] / "cardio_tagger" / "ontology" / "cardio_concepts.yaml"
    ontology = yaml.safe_load(ontology_path.read_text(encoding="utf-8"))
    return CascadingCardioSieve(ontology=ontology)


def test_case1_final_page_newline():
    sieve = get_sieve()
    res = sieve.evaluate_document(
        "case1_final_page_newline.pdf",
        [
            "CLINICAL HISTORY: 64M with inferior STEMI.\nPROCEDURE: Primary PCI to culprit RCA.",
            "FINDINGS:\n1. RCA: 100% acute occlusion, successful DES.\n2. Mid-LAD: 85% calcified stenosis.\n\nCONCLUSION\n1. Successful primary PCI to culprit RCA with 3.5x28mm Xience DES.\n2. Severe residual mid-LAD stenosis; plan for staged PCI to mid-LAD in 4 weeks.\n3. Continue DAPT with aspirin and ticagrelor.\n\nElectronically signed by Dr. Tan",
        ],
    )
    assert res.conclusion_found is True
    assert res.conclusion_in_early_section is False
    assert res.staged_pci_detected is True
    assert res.staged_pci_status == "AFFIRMED_PLANNED"
    assert any("LAD" in v for v in res.staged_pci_vessels)
    assert res.staged_pci_timeframe == "in 4 weeks"


def test_case2_page1_early_conclusion():
    sieve = get_sieve()
    res = sieve.evaluate_document(
        "case2_page1_early_conclusion.pdf",
        [
            "CATHETERIZATION REPORT\nConclusion: Two-vessel coronary artery disease (LVEF 45%). Successful culprit PCI to LCx; scheduled for staged PCI to proximal RCA during index admission.\n\nPROCEDURE DETAILS:\nRight radial access obtained...",
            "HEMODYNAMICS:\nAO 128/74 mmHg, LVEDP 16 mmHg.\nIntravascular ultrasound (IVUS) performed.",
            "BILLING CODES: 92928",
        ],
        search_all_sections=True,
    )
    assert res.conclusion_found is True
    assert res.conclusion_in_early_section is True
    assert res.staged_pci_detected is True
    assert res.staged_pci_status == "AFFIRMED_PLANNED"
    assert any("RCA" in v for v in res.staged_pci_vessels)
    assert res.staged_pci_timeframe == "during index admission"

    concept_ids = {m.concept_id for m in res.all_concept_matches}
    assert "CARDIO_LVEF" in concept_ids
    assert "CARDIO_VESSEL_STENOSIS" in concept_ids
    assert "CARDIO_IVUS_OCT_FFR" in concept_ids


def test_case3_negated():
    sieve = get_sieve()
    res = sieve.evaluate_document(
        "case3_negated.pdf",
        [
            "CONCLUSION:\n1. Successful PCI to LAD.\n2. Mild 40% RCA disease; no indication for staged PCI to RCA. Medical therapy optimized."
        ],
    )
    assert res.staged_pci_detected is False
    assert res.staged_pci_status == "NEGATED"


def test_case4_conditional():
    sieve = get_sieve()
    res = sieve.evaluate_document(
        "case4_conditional.pdf",
        [
            "IMPRESSION AND PLAN:\n1. Culprit RCA stenting completed.\n2. Moderate 65% LCx lesion; consider staged PCI to LCx if outpatient stress test positive for lateral ischemia."
        ],
    )
    assert res.staged_pci_detected is True
    assert res.staged_pci_status == "CONDITIONAL"
    assert res.peak_tier_used == "Tier5_Ollama"


def test_case5_ocr_typo():
    sieve = get_sieve()
    res = sieve.evaluate_document(
        "case5_ocr_typo.pdf",
        [
            "CONCLUSIONS - \n1. Multivessel CAD.\n2. Recommend stged PCl to OM1 in 2 to 4 weeks."
        ],
    )
    assert res.staged_pci_detected is True
    assert res.staged_pci_status == "AFFIRMED_PLANNED"
    assert any("OM1" in v for v in res.staged_pci_vessels)


def test_case6_performed_index():
    sieve = get_sieve()
    res = sieve.evaluate_document(
        "case6_performed.pdf",
        [
            "CONCLUSION:\n1. Successful staged PCI to mid-LAD performed today with 3.0x20mm drug-eluting stent.\n2. Excellent final angiographic result with TIMI 3 flow."
        ],
    )
    assert res.staged_pci_detected is True
    assert res.staged_pci_status == "AFFIRMED_PERFORMED_INDEX"
    assert any("LAD" in v for v in res.staged_pci_vessels)


def test_duckdb_checkpointing(tmp_path):
    db_file = str(tmp_path / "test_checkpoint.duckdb")
    mgr = DuckDBCheckpointManager(db_file)
    mgr.save_checkpoint(
        {
            "pdf_path": "report_001.pdf",
            "file_size": 1024,
            "mtime_ns": 123456789,
            "total_pages": 2,
            "conclusion_found": True,
            "conclusion_in_early_section": False,
            "staged_pci_detected": True,
            "staged_pci_status": "AFFIRMED_PLANNED",
            "staged_pci_vessels": ["LAD"],
            "staged_pci_timeframe": "in 4 weeks",
            "staged_pci_confidence": 0.98,
            "all_concept_matches": [],
            "peak_tier_used": "Tier1_Lexical",
            "processing_ms": 1.2,
            "used_ocr_fallback": False,
        }
    )
    keys = mgr.get_completed_keys()
    assert ("report_001.pdf", 1024, 123456789) in keys
    mgr.close()


def test_multi_cardiac_conditions():
    sieve = get_sieve()
    from cardio_tagger.cli import _format_concept_fields

    ontology_path = Path(__file__).resolve().parents[1] / "cardio_tagger" / "ontology" / "cardio_concepts.yaml"
    ontology = yaml.safe_load(ontology_path.read_text(encoding="utf-8"))
    concepts = ontology.get("concepts", {})

    # Clinical note for HF, AFib, and AMI without staged PCI
    text = (
        "IMPRESSION:\n"
        "1. Acute anterior STEMI (acute myocardial infarction) s/p primary PCI to proximal LAD.\n"
        "2. Decompensated heart failure with reduced ejection fraction (HFrEF, LVEF 30%).\n"
        "3. Paroxysmal atrial fibrillation on apixaban.\n"
        "4. No indication for staged PCI. Medical optimization."
    )
    res = sieve.evaluate_document("multi_cardio.pdf", [text], search_all_sections=True)
    assert res.staged_pci_detected is False
    assert res.staged_pci_status == "NEGATED"

    formatted = _format_concept_fields({"all_concept_matches": res.all_concept_matches}, concepts)
    assert formatted["has_acute_myocardial_infarction"] is True
    assert formatted["has_heart_failure_syndrome"] is True
    assert formatted["has_atrial_fibrillation_arrhythmia"] is True
    assert formatted["has_lvef_systolic_function"] is True
    assert "CARDIO_AMI" in formatted["detected_cardio_concepts"]
    assert "CARDIO_HEART_FAILURE" in formatted["detected_cardio_concepts"]
    assert "CARDIO_AFIB" in formatted["detected_cardio_concepts"]


def test_csv_input_processing(tmp_path):
    import csv
    import subprocess

    input_csv = tmp_path / "clinical_cohort.csv"
    output_csv = tmp_path / "tagged_cohort.csv"
    output_jsonl = tmp_path / "tagged_cohort.jsonl"
    checkpoint_db = tmp_path / "cohort_checkpoint.duckdb"

    # Write a multi-row cohort CSV
    rows = [
        {
            "patient_id": "PT_101",
            "age": "67",
            "note_text": "CONCLUSION: Two-vessel CAD. Successful culprit PCI to RCA today; plan for staged PCI to proximal LAD in 4 weeks.",
        },
        {
            "patient_id": "PT_102",
            "age": "74",
            "note_text": "SUMMARY: Congestive heart failure exacerbation (HFrEF) and persistent atrial fibrillation. No coronary intervention planned.",
        },
        {
            "patient_id": "PT_103",
            "age": "55",
            "note_text": "IMPRESSION: Severe dilated cardiomyopathy with NYHA class III symptoms. No indication for staged PCI.",
        },
    ]

    with open(input_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["patient_id", "age", "note_text"])
        writer.writeheader()
        writer.writerows(rows)

    # Run the CLI via Python
    cli_script = Path(__file__).resolve().parents[1] / "cardio_tagger" / "cli.py"
    cmd = [
        sys.executable,
        str(cli_script),
        "--input-csv",
        str(input_csv),
        "--output-csv",
        str(output_csv),
        "--output-jsonl",
        str(output_jsonl),
        "--checkpoint-db",
        str(checkpoint_db),
        "--workers",
        "2",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"CLI exited with error:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"

    assert output_csv.exists()
    with open(output_csv, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 3

        # Row 1 (PT_101): Has Staged PCI
        assert reader[0]["patient_id"] == "PT_101"
        assert reader[0]["age"] == "67"
        assert reader[0]["staged_pci_detected"] == "True"
        assert reader[0]["staged_pci_status"] == "AFFIRMED_PLANNED"
        assert "LAD" in reader[0]["staged_pci_vessels"]

        # Row 2 (PT_102): Heart Failure + AFib, No Staged PCI
        assert reader[1]["patient_id"] == "PT_102"
        assert reader[1]["staged_pci_detected"] == "False"
        assert reader[1]["has_heart_failure_syndrome"] == "True"
        assert reader[1]["has_atrial_fibrillation_arrhythmia"] == "True"

        # Row 3 (PT_103): Cardiomyopathy, Negated Staged PCI
        assert reader[2]["patient_id"] == "PT_103"
        assert reader[2]["staged_pci_detected"] == "False"
        assert reader[2]["staged_pci_status"] == "NEGATED"
        assert reader[2]["has_cardiomyopathy_myocarditis"] == "True"


def test_echo_lvef_sieve_integration():
    sieve = get_sieve()
    text = (
        "ECHOCARDIOGRAM REPORT\n"
        "FINDINGS:\n"
        "Left ventricle: normal wall thickness. 2D Biplane Simpson's LVEF 52%.\n\n"
        "CONCLUSION:\n"
        "1. Normal LV systolic function; visually estimated LVEF is 50-55%.\n"
        "2. No regional wall motion abnormalities."
    )
    res = sieve.evaluate_document("echo_test.pdf", [text])
    assert res.lvef_extracted == "50-55%"
    assert res.lvef_numeric == 52.5
    assert res.lvef_method == "VISUAL"
    assert res.lvef_section == "CONCLUSION"



if __name__ == "__main__":
    test_case1_final_page_newline()
    test_case2_page1_early_conclusion()
    test_case3_negated()
    test_case4_conditional()
    test_case5_ocr_typo()
    test_case6_performed_index()
    print("ALL 6 CLINICAL VERIFICATION SUITES PASSED 100%!")
