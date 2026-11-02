import sys
from pathlib import Path

# Add portable_app to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from cardio_tagger.coronary_stenosis import CoronaryStenosisExtractor, CoronaryStenosisResult


def test_user_edge_cases_lcx_lad_rpl1():
    extractor = CoronaryStenosisExtractor()
    conclusion_text = (
        "CONCLUSION:\n"
        "1. Two-vessel CAD with small lcx 70-90% and mid lad 50%.\n"
        "2. RPL1 70% stenosis; plan for medical optimization."
    )
    res = extractor.extract(conclusion_text=conclusion_text, findings_text="")

    assert "SMALL LCX: 70-90%" in res.conclusion_lcx_stenosis
    assert "MID LAD: 50%" in res.conclusion_lad_stenosis
    assert "RPL1: 70%" in res.conclusion_rca_stenosis
    assert res.conclusion_lmca_stenosis == ""
    assert res.conclusion_graft_stenosis == ""


def test_occlusions_and_qualitative_states():
    extractor = CoronaryStenosisExtractor()
    text = (
        "IMPRESSION:\n"
        "1. 100% CTO of proximal RCA.\n"
        "2. Total occlusion of mid-LAD.\n"
        "3. Subtotal occlusion of ostial LCx.\n"
        "4. Patent stent in distal LAD.\n"
        "5. Severe disease in OM1."
    )
    res = extractor.extract(conclusion_text=text, findings_text="")

    assert "PROXIMAL RCA: 100% CTO" in res.conclusion_rca_stenosis
    assert "MID-LAD: TOTAL OCCLUSION" in res.conclusion_lad_stenosis
    assert "DISTAL LAD: PATENT STENT" in res.conclusion_lad_stenosis
    assert "OSTIAL LCX: SUBTOTAL OCCLUSION" in res.conclusion_lcx_stenosis
    assert "OM1: SEVERE STENOSIS" in res.conclusion_lcx_stenosis


def test_multi_lesion_concatenation_in_territory():
    extractor = CoronaryStenosisExtractor()
    text = (
        "CONCLUSION:\n"
        "Proximal LAD 70% stenosis. Mid LAD 50% disease. D1 80% lesion."
    )
    res = extractor.extract(conclusion_text=text, findings_text="")

    expected = "PROXIMAL LAD: 70%; MID LAD: 50%; D1: 80%"
    assert res.conclusion_lad_stenosis == expected


def test_all_territories_and_grafts():
    extractor = CoronaryStenosisExtractor()
    conclusion = (
        "SUMMARY:\n"
        "1. Left Main: 40% distal bifurcation plaque.\n"
        "2. Mid-LAD: 60% stenosis.\n"
        "3. OM1: 75% tubular lesion.\n"
        "4. PDA: 70% focal stenosis.\n"
        "5. LIMA to LAD: patent; SVG to OM1: 80% stenosis."
    )
    res = extractor.extract(conclusion_text=conclusion, findings_text="")

    assert "LEFT MAIN: 40%" in res.conclusion_lmca_stenosis
    assert "MID-LAD: 60%" in res.conclusion_lad_stenosis
    assert "OM1: 75%" in res.conclusion_lcx_stenosis
    assert "PDA: 70%" in res.conclusion_rca_stenosis
    assert "LIMA TO LAD: PATENT" in res.conclusion_graft_stenosis
    assert "SVG TO OM1: 80%" in res.conclusion_graft_stenosis


def test_dual_scopes_conclusion_vs_findings():
    extractor = CoronaryStenosisExtractor()
    findings = (
        "CORONARY ANGIOGRAPHY FINDINGS:\n"
        "LAD: 80% proximal stenosis, 50% mid lesion.\n"
        "LCx: 70-90% small caliber vessel.\n"
        "RCA: 100% total occlusion.\n"
        "LMCA: Normal."
    )
    conclusion = (
        "CONCLUSION:\n"
        "1. Successful PCI with 3.5x28mm DES to proximal LAD.\n"
        "2. Residual small LCx 70-90%."
    )
    res = extractor.extract(conclusion_text=conclusion, findings_text=findings)

    # Findings scope
    assert "PROXIMAL LAD: 80%" in res.findings_lad_stenosis
    assert "MID LAD: 50%" in res.findings_lad_stenosis
    assert "SMALL LCX: 70-90%" in res.findings_lcx_stenosis
    assert "RCA: 100% TOTAL OCCLUSION" in res.findings_rca_stenosis
    assert res.findings_lmca_stenosis == "LMCA: NORMAL"

    # Conclusion scope
    assert "SMALL LCX: 70-90%" in res.conclusion_lcx_stenosis
    # Proximal LAD in conclusion was successful PCI, so residual is LCx
    assert res.conclusion_rca_stenosis == ""
