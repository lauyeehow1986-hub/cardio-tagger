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
    assert "MID LAD: TOTAL OCCLUSION" in res.conclusion_lad_stenosis
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
    assert "MID LAD: 60%" in res.conclusion_lad_stenosis
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
    assert res.findings_lmca_stenosis == "LMCA: 0%"

    # Conclusion scope
    assert "SMALL LCX: 70-90%" in res.conclusion_lcx_stenosis
    assert res.conclusion_rca_stenosis == ""


def test_user_multiline_vessel_narrative_and_timi_exclusion():
    extractor = CoronaryStenosisExtractor()
    narrative = (
        "prox left anterior descending coronary artery 80% "
        "mid left anterior descending coronary artery has a moderate(50-70%) stenosis involving origin of first diagonal artery. "
        "Mid left anterior descending coronary artery has a moderate (approx 50% stenosis). "
        "Normal anterograde flow(timi 3). "
        "The first diagonal coronary artery has a non-flow limiting (less than 30% stenosis)."
    )
    res = extractor.extract(findings_text=narrative)
    expected_lad = (
        "PROXIMAL LAD: 80%; "
        "MID LAD: MODERATE (50-70%); "
        "MID LAD: MODERATE (APPROX 50%); "
        "D1: NON-FLOW LIMITING (<30%)"
    )
    assert res.findings_lad_stenosis == expected_lad
    assert res.findings_lmca_stenosis == ""
    assert res.findings_lcx_stenosis == ""
    assert res.findings_rca_stenosis == ""
    assert res.findings_graft_stenosis == ""


def test_similar_narratives_across_lcx_rca_lmca_graft():
    extractor = CoronaryStenosisExtractor()
    conclusion = (
        "CONCLUSION:\n"
        "1. Proximal circumflex coronary artery 70% stenosis. The first obtuse marginal coronary artery has a non-flow limiting (less than 30% stenosis). Second obtuse marginal branch has a severe (>70%) narrowing.\n"
        "2. Proximal right coronary artery 90% stenosis. Distal right coronary artery has a moderate (approx 50% stenosis). Posterior descending artery has a mild (20-30% stenosis). First posterolateral branch has a 50% lesion.\n"
        "3. Left main coronary artery has a mild (approx 20% stenosis).\n"
        "4. SVG to first obtuse marginal artery has a severe (80-90% stenosis). LIMA to left anterior descending artery is patent."
    )
    res = extractor.extract(conclusion_text=conclusion)

    assert "PROXIMAL LCX: 70%" in res.conclusion_lcx_stenosis
    assert "OM1: NON-FLOW LIMITING (<30%)" in res.conclusion_lcx_stenosis
    assert "OM2: SEVERE (>70%)" in res.conclusion_lcx_stenosis

    assert "PROXIMAL RCA: 90%" in res.conclusion_rca_stenosis
    assert "DISTAL RCA: MODERATE (APPROX 50%)" in res.conclusion_rca_stenosis
    assert "PDA: MILD (20-30%)" in res.conclusion_rca_stenosis
    assert "RPL1: 50%" in res.conclusion_rca_stenosis

    assert "LEFT MAIN: MILD (APPROX 20%)" in res.conclusion_lmca_stenosis

    assert "SVG TO OM1: SEVERE (80-90%)" in res.conclusion_graft_stenosis
    assert "LIMA TO LAD: PATENT" in res.conclusion_graft_stenosis


def test_zero_stenosis_normal_without_stenosis_free_of_restenosis():
    extractor = CoronaryStenosisExtractor()
    text = (
        "FINDINGS:\n"
        "LMCA is normal without stenosis. "
        "LAD has no significant stenosis. "
        "RCA without stenosis. "
        "Patent stent in proximal LCx, free of restenosis."
    )
    res = extractor.extract(findings_text=text)
    assert res.findings_lmca_stenosis == "LMCA: 0%"
    assert res.findings_lad_stenosis == "LAD: 0%"
    assert res.findings_rca_stenosis == "RCA: 0%"
    assert res.findings_lcx_stenosis == "PROXIMAL LCX: 0%"


def test_ostium_of_vessel_and_abbreviation_dot():
    extractor = CoronaryStenosisExtractor()
    text = (
        "CONCLUSION:\n"
        "the ostium of the proximal left anterior descending coronary artery has a moderate(approx. 50%) stenosis. "
        "Normal anterograde flow."
    )
    res = extractor.extract(conclusion_text=text)
    assert res.conclusion_lad_stenosis == "OSTIAL PROXIMAL LAD: MODERATE (APPROX 50%)"
    assert res.conclusion_rca_stenosis == ""
    assert res.conclusion_lcx_stenosis == ""


def test_section_parser_findings_and_conclusion_split():
    from cardio_tagger.section_parser import ClinicalSectionParser
    parser = ClinicalSectionParser()
    page1 = (
        "CARDIAC CATHETERIZATION REPORT\n"
        "INDICATIONS: 68M with stable angina.\n"
        "FINDINGS:\n"
        "LMCA: Normal.\n"
        "LAD: 70% mid stenosis.\n"
        "LCx: Small caliber with 80% lesion.\n"
        "RCA: 100% total occlusion.\n\n"
        "CONCLUSION:\n"
        "1. Two-vessel CAD.\n"
        "2. Successful PCI to LAD.\n"
        "3. Plan staged PCI to RCA."
    )
    doc = parser.parse_document("test.pdf", [page1])
    assert "70% mid stenosis" in doc.findings_text
    assert "Two-vessel CAD" in doc.conclusion_text
