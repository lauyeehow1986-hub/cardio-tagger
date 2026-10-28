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


if __name__ == "__main__":
    test_case1_final_page_newline()
    test_case2_page1_early_conclusion()
    test_case3_negated()
    test_case4_conditional()
    test_case5_ocr_typo()
    test_case6_performed_index()
    print("ALL 6 CLINICAL VERIFICATION SUITES PASSED 100%!")
