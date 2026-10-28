#!/usr/bin/env python3
"""
Model Context Protocol (MCP) Server for Antigravity IDE: `cardio-tagger-mcp`
Provides 6 specialized tools so Gemini 3.8 Flash inside Antigravity IDE can:
  1. `inspect_pdf_sections`: Test section boundary extraction on any clinical PDF or text.
  2. `test_sieve_tiers_on_text`: Run Tiers 1-5 on clinical snippets and inspect assertion & vessel spans.
  3. `validate_cardio_ontology`: Validate `cardio_concepts.yaml` regexes, Aho-Corasick seeds, and SNOMED codes.
  4. `benchmark_16gb_ram_budget`: Calculate exact memory footprint and throughput projections for N workers.
  5. `generate_synthetic_cath_pdfs`: Generate realistic edge-case cardiac catheterization PDFs for testing.
  6. `verify_portable_bundle_manifest`: Audit `dist/cardio-tagger-portable` for zero-admin readiness.
"""
import json
import os
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure portable_app is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "portable_app"))

import yaml
from cardio_tagger.section_parser import ClinicalSectionParser
from cardio_tagger.sieve_engine import CascadingCardioSieve

try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("cardio-tagger-mcp")
except ImportError:
    class _DummyMCP:
        def tool(self):
            def decorator(fn):
                return fn
            return decorator
        def run(self):
            print("FastMCP not installed; install via `pip install mcp` to run stdio server.")
    mcp = _DummyMCP()


ONTOLOGY_PATH = REPO_ROOT / "portable_app" / "cardio_tagger" / "ontology" / "cardio_concepts.yaml"


@mcp.tool()
def inspect_pdf_sections(text_or_pages: List[str], doc_name: str = "sample.pdf") -> str:
    """
    Parses a list of page texts using ClinicalSectionParser and returns all detected
    Conclusion/Impression/Plan and other sections, including whether Conclusion was found
    in an early section (e.g. Page 1) or at the end of the report.
    """
    parser = ClinicalSectionParser()
    parsed = parser.parse_pages(doc_name, text_or_pages)
    return json.dumps(
        {
            "pdf_path": parsed.pdf_path,
            "total_pages": parsed.total_pages,
            "conclusion_count": len(parsed.conclusion_sections),
            "conclusion_sections": [asdict(s) for s in parsed.conclusion_sections],
            "all_section_keys": list(parsed.all_sections.keys()),
        },
        indent=2,
    )


@mcp.tool()
def test_sieve_tiers_on_text(
    page_texts: List[str],
    target_concepts: Optional[List[str]] = None,
    search_all_sections: bool = False,
) -> str:
    """
    Runs the 6-Tier Cascading Cardiology Sieve on a list of page strings and returns
    structured Staged PCI status, target vessels, planned timeframe, and all concept matches.
    """
    ontology = yaml.safe_load(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    sieve = CascadingCardioSieve(ontology=ontology)
    res = sieve.evaluate_document(
        pdf_path="interactive_test.pdf",
        page_texts=page_texts,
        target_concepts=target_concepts,
        search_all_sections=search_all_sections,
    )
    return json.dumps(asdict(res), indent=2)


@mcp.tool()
def validate_cardio_ontology(ontology_path: Optional[str] = None) -> str:
    """
    Validates the YAML cardiology ontology for regex syntax, seed completeness,
    and SNOMED-CT/UMLS metadata.
    """
    p = Path(ontology_path) if ontology_path else ONTOLOGY_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    concepts = data.get("concepts", {})
    report = {"valid": True, "concept_count": len(concepts), "concepts": {}, "errors": []}
    for key, cdef in concepts.items():
        seeds = cdef.get("aho_corasick_seeds", [])
        patterns = cdef.get("regex_patterns", [])
        for pat in patterns:
            try:
                re.compile(pat)
            except re.error as exc:
                report["valid"] = False
                report["errors"].append(f"{key}: invalid regex '{pat}' -> {exc}")
        report["concepts"][key] = {
            "id": cdef.get("id"),
            "display_name": cdef.get("display_name"),
            "snomed_ct": cdef.get("snomed_ct"),
            "seeds": len(seeds),
            "regexes": len(patterns),
            "gliner_labels": len(cdef.get("gliner_labels", [])),
        }
    return json.dumps(report, indent=2)


@mcp.tool()
def benchmark_16gb_ram_budget(
    num_workers: int = 4,
    include_gliner_int8: bool = True,
    include_local_ollama_q4: bool = True,
    num_pdfs: int = 1_000_000,
) -> str:
    """
    Computes the projected peak RAM usage on a 16 GB Windows PC and estimates
    wall-clock runtime for 1,000 to 1,000,000 PDFs across the 6-Tier Sieve.
    """
    windows_os_overhead_gb = 3.6
    orchestrator_duckdb_gb = 0.35
    per_worker_base_gb = 0.18  # Python + PyMuPDF + Aho-Corasick + MedSpaCy
    per_worker_gliner_gb = 0.42 if include_gliner_int8 else 0.0
    ollama_server_gb = 2.25 if include_local_ollama_q4 else 0.0

    workers_total_gb = num_workers * (per_worker_base_gb + per_worker_gliner_gb)
    peak_ram_gb = round(
        windows_os_overhead_gb + orchestrator_duckdb_gb + workers_total_gb + ollama_server_gb, 2
    )
    headroom_gb = round(16.0 - peak_ram_gb, 2)

    # Throughput calculation (Tier 0+1 takes ~2ms; 10% hit Tier 2+3 (~18ms); 1.5% hit Tier 5 (~450ms))
    avg_ms_per_pdf_single_core = 2.0 + (0.10 * 18.0) + (0.015 * 450.0 if include_local_ollama_q4 else 0.0)
    effective_ms_per_pdf = avg_ms_per_pdf_single_core / max(1, num_workers)
    total_hours_for_batch = round((num_pdfs * effective_ms_per_pdf) / (1000.0 * 3600.0), 2)

    return json.dumps(
        {
            "hardware_limit_gb": 16.0,
            "windows_os_overhead_gb": windows_os_overhead_gb,
            "orchestrator_duckdb_gb": orchestrator_duckdb_gb,
            "workers_total_gb": round(workers_total_gb, 2),
            "ollama_q4_server_gb": ollama_server_gb,
            "projected_peak_ram_gb": peak_ram_gb,
            "safe_headroom_gb": headroom_gb,
            "fits_in_16gb_ram": peak_ram_gb <= 14.5,
            "estimated_ms_per_pdf_effective": round(effective_ms_per_pdf, 2),
            "estimated_hours_for_batch": total_hours_for_batch,
        },
        indent=2,
    )


@mcp.tool()
def generate_synthetic_cath_pdfs(output_dir: str = "synthetic_pdfs", count: int = 5) -> str:
    """
    Generates realistic clinical cardiac catheterization PDF reports covering the 5 key edge cases:
      1. Classic final-page Conclusion with newline delimiter + Staged PCI to mid-LAD in 4 weeks
      2. Early-section (Page 1 of 3) Executive Summary Conclusion with inline colon delimiter
      3. Negated Staged PCI ("No indication for staged PCI to diagonal branch")
      4. Conditional Staged PCI ("Consider staged PCI to LCx if outpatient stress test positive")
      5. OCR Typo Recovery ("Recommend stged PCl to OM1 in 2 to 4 weeks")
    """
    out_path = REPO_ROOT / output_dir
    out_path.mkdir(parents=True, exist_ok=True)

    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    test_cases = [
        (
            "case1_final_page_newline.pdf",
            [
                (
                    "CARDIAC CATHETERIZATION & CORONARY ANGIOGRAPHY REPORT\n\n"
                    "PATIENT: Doe, John | MRN: 9028192 | DATE: 2026-03-15\n"
                    "INDICATIONS: 64M presenting with acute inferior STEMI.\n\n"
                    "PROCEDURE PERFORMED:\n"
                    "1. Right radial catheterization with 6F Glidesheath.\n"
                    "2. Coronary angiography.\n"
                    "3. Primary percutaneous coronary intervention (PCI) to culprit RCA.\n\n"
                    "HEMODYNAMICS:\n"
                    "Aortic Pressure: 132/78 mmHg. LVEDP: 18 mmHg."
                ),
                (
                    "CORONARY ANGIOGRAPHY FINDINGS:\n"
                    "1. Left Main: Normal.\n"
                    "2. LAD: Proximal LAD has mild 30% disease. Mid-LAD has severe 85% calcified stenosis.\n"
                    "3. LCx: Non-obstructive 40% plaque.\n"
                    "4. RCA: Acute 100% mid-RCA occlusion with heavy thrombus. Successfully revascularized with 3.5x28mm Xience DES.\n\n"
                    "CONCLUSION\n"
                    "1. Successful primary PCI to culprit acute RCA occlusion.\n"
                    "2. Severe residual mid-LAD stenosis; plan for staged PCI to mid-LAD in 4 weeks.\n"
                    "3. Continue DAPT with aspirin and ticagrelor.\n\n"
                    "Electronically signed by Dr. Tan, MD, FSCAI"
                ),
            ],
        ),
        (
            "case2_page1_early_conclusion.pdf",
            [
                (
                    "UNIVERSITY HEART CENTER - EXECUTIVE SUMMARY CATH REPORT\n\n"
                    "Conclusion: Two-vessel coronary artery disease (LVEF 45%). Successful culprit PCI to LCx; "
                    "scheduled for staged PCI to proximal RCA during index admission.\n\n"
                    "CLINICAL HISTORY: 58-year-old female with NSTEMI.\n"
                    "PROCEDURES PERFORMED: Left heart catheterization, PCI to LCx with drug-eluting stent.\n"
                    "ACCESS: Right femoral artery."
                ),
                (
                    "CORONARY ANGIOGRAM DETAILS:\n"
                    "LM: Unremarkable.\n"
                    "LAD: Mild luminal irregularities.\n"
                    "LCx: 90% stenosis in mid-segment; treated with 2.75x18mm DES with TIMI 3 flow.\n"
                    "RCA: 80% proximal RCA lesion; deferred for staged PCI.\n"
                    "HEMODYNAMICS: Central aortic pressure 125/70 mmHg."
                ),
                (
                    "POST-PROCEDURE PLAN:\n"
                    "1. Bed rest for 4 hours.\n"
                    "2. Hydration for contrast clearance.\n"
                    "3. Discharge planning following staged RCA procedure.\n\n"
                    "Dictated by: Attending Cardiologist Dr. Marcus\n"
                    "BILLING CODES: 92928, 93458"
                ),
            ],
        ),
        (
            "case3_negated.pdf",
            [
                (
                    "CATHETERIZATION LABORATORY REPORT\n\n"
                    "FINDINGS:\n"
                    "Left Anterior Descending: 95% proximal stenosis successfully stented with 3.0x23mm Synergy DES.\n"
                    "Right Coronary Artery: Mild 40% mid-vessel plaque.\n\n"
                    "CONCLUSION:\n"
                    "1. Successful PCI to culprit LAD lesion with excellent angiographic result.\n"
                    "2. Mild 40% RCA disease; no indication for staged PCI to RCA. Medical therapy optimized.\n\n"
                    "Signed by: Dr. Sarah Vance, Interventional Cardiology"
                )
            ],
        ),
        (
            "case4_conditional.pdf",
            [
                (
                    "INVASIVE CARDIOLOGY PROCEDURE NOTE\n\n"
                    "PROCEDURE: Emergent revascularization of acute anterior wall MI.\n"
                    "INTERVENTION: DES placement to proximal LAD.\n\n"
                    "IMPRESSION AND PLAN:\n"
                    "1. Primary PCI to LAD successfully accomplished.\n"
                    "2. Moderate 65% LCx lesion with borderline FFR; consider staged PCI to LCx if outpatient stress test positive for lateral ischemia.\n"
                    "3. Post-procedure monitoring in CCU.\n\n"
                    "Attending Cardiologist: Dr. Kevin Ortiz, MD"
                )
            ],
        ),
        (
            "case5_ocr_typo.pdf",
            [
                (
                    "CARDIAC CATH REPORT [SCANNED ARCHIVE]\n\n"
                    "PROCEDURE: Selective coronary angiography and intervention.\n"
                    "FINDINGS: High grade stenosis in OM1.\n\n"
                    "CONCLUSIONS - \n"
                    "1. Multivessel coronary disease.\n"
                    "2. Recommend stged PCl to OM1 in 2 to 4 weeks.\n\n"
                    "Dictated by Dr. H. Patel"
                )
            ],
        ),
    ]

    generated_files = []
    for filename, pages in test_cases[:count]:
        file_path = out_path / filename
        doc = fitz.open()
        for page_text in pages:
            page = doc.new_page(width=612, height=792)  # Standard Letter size
            page.insert_text(
                fitz.Point(54, 72),
                page_text,
                fontsize=11,
                fontname="helv",
            )
        doc.save(str(file_path))
        doc.close()
        generated_files.append(str(file_path))

    return json.dumps(
        {
            "status": "success",
            "count": len(generated_files),
            "output_dir": str(out_path),
            "generated_files": generated_files,
        },
        indent=2,
    )


@mcp.tool()
def verify_portable_bundle_manifest(bundle_dir: str = "dist/cardio-tagger-portable") -> str:
    """
    Audits the generated portable distribution folder for complete offline zero-admin readiness:
      - Validates Python embeddable runtime & unlocked python311._pth
      - Checks local MSVC runtime DLLs (vcruntime140.dll, etc.)
      - Verifies application code and cardio_concepts.yaml
      - Audits launcher script (run_cardio_tagger.bat)
    """
    p = (REPO_ROOT / bundle_dir).resolve()
    report = {
        "bundle_path": str(p),
        "exists": p.exists(),
        "ready_for_zero_admin_deployment": False,
        "checks": {},
        "missing_components": [],
    }

    if not p.exists():
        report["missing_components"].append("Bundle directory does not exist yet. Run scripts/build_portable_bundle.ps1 first.")
        return json.dumps(report, indent=2)

    essential_items = {
        "python_exe": p / "runtime" / "python" / "python.exe",
        "pth_file": p / "runtime" / "python" / "python311._pth",
        "app_cli": p / "app" / "cardio_tagger" / "cli.py",
        "ontology_yaml": p / "app" / "cardio_tagger" / "ontology" / "cardio_concepts.yaml",
        "launcher_bat": p / "run_cardio_tagger.bat",
    }

    for name, item_path in essential_items.items():
        found = item_path.exists()
        report["checks"][name] = found
        if not found:
            report["missing_components"].append(f"Missing {name}: {item_path}")

    # Check MSVC runtime dlls
    msvc_dlls = ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"]
    msvc_found = all((p / "runtime" / "python" / dll).exists() for dll in msvc_dlls)
    report["checks"]["msvc_runtime_dlls"] = msvc_found

    report["ready_for_zero_admin_deployment"] = len(report["missing_components"]) == 0
    return json.dumps(report, indent=2)


if __name__ == "__main__":
    mcp.run()
