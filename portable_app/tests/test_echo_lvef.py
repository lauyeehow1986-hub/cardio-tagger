#!/usr/bin/env python3
"""
Test Suite for Echocardiography Section Detection & LVEF Extraction.
Tests:
  1. Section header detection (Conclusion, Findings, Measurements)
  2. Case 1: Conclusion visual range ("50-55%" -> 52.5, VISUAL, CONCLUSION)
  3. Case 2: Method preference within Conclusion (3D > 2D Simpson's)
  4. Case 3: Findings fallback when Conclusion lacks LVEF
  5. Case 4: Measurements table fallback when Conclusion & Findings lack LVEF
  6. Case 5: Temporal comparative disambiguation ("improved from 30% in 2022 to 55% today")
  7. Case 6: Pure historical exclusion (prior dated LVEF excluded, yields NONE)
  8. Case 7: Qualitative fallback when no % values exist ("Normal" -> null numeric)
"""
import sys
from pathlib import Path

# Add portable_app to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from cardio_tagger.section_parser import ClinicalSectionParser
from cardio_tagger.echo_lvef import EchoLVEFExtractor, EchoLVEFResult


def test_echo_section_parsing():
    parser = ClinicalSectionParser()
    text = (
        "ECHOCARDIOGRAM REPORT\n\n"
        "FINDINGS:\n"
        "Left ventricle is normal in size and wall thickness.\n\n"
        "MEASUREMENTS:\n"
        "LVEF 3D: 58 %\n"
        "LVEDV: 110 ml\n"
        "LVESV: 47 ml\n\n"
        "SUMMARY:\n"
        "Visually estimated LVEF is 50-55%. Moderate mitral regurgitation."
    )
    doc = parser.parse_pages("echo_report.txt", [text])
    assert len(doc.conclusion_sections) > 0
    assert "findings" in doc.all_sections
    assert "measurements" in doc.all_sections
    assert any("58" in s.text for s in doc.all_sections["measurements"])
    assert any("50-55" in s.text for s in doc.conclusion_sections)


def test_case1_conclusion_visual_range():
    parser = ClinicalSectionParser()
    extractor = EchoLVEFExtractor()
    text = (
        "FINDINGS:\nLeft ventricular cavity is normal in size.\n\n"
        "CONCLUSION:\n1. Visually estimated LVEF is 50-55%.\n2. Mild aortic sclerosis."
    )
    doc = parser.parse_pages("case1.txt", [text])
    res = extractor.extract(doc)
    assert res.lvef_extracted == "50-55%"
    assert res.lvef_numeric == 52.5
    assert res.lvef_method == "VISUAL"
    assert res.lvef_section == "CONCLUSION"


def test_case2_conclusion_3d_over_2d():
    parser = ClinicalSectionParser()
    extractor = EchoLVEFExtractor()
    text = (
        "IMPRESSION:\n"
        "1. 3D LVEF is 58%.\n"
        "2. 2D Biplane Simpson's LVEF calculated at 54%.\n"
        "3. Eyeball estimated EF: 50-55%."
    )
    doc = parser.parse_pages("case2.txt", [text])
    res = extractor.extract(doc)
    assert res.lvef_extracted == "58%"
    assert res.lvef_numeric == 58.0
    assert res.lvef_method == "3D"
    assert res.lvef_section == "CONCLUSION"


def test_case3_findings_fallback():
    parser = ClinicalSectionParser()
    extractor = EchoLVEFExtractor()
    text = (
        "FINDINGS:\n"
        "Left Ventricle: 2D Biplane Simpson's LVEF is 45%. Mild basal inferolateral hypokinesis.\n\n"
        "MEASUREMENTS:\n"
        "LVEF (Teichholz): 48 %\n\n"
        "CONCLUSION:\n"
        "1. Moderate mitral regurgitation.\n"
        "2. No pericardial effusion."
    )
    doc = parser.parse_pages("case3.txt", [text])
    res = extractor.extract(doc)
    assert res.lvef_extracted == "45%"
    assert res.lvef_numeric == 45.0
    assert res.lvef_method == "2D_BIPLANE"
    assert res.lvef_section == "FINDINGS"


def test_case4_measurements_fallback():
    parser = ClinicalSectionParser()
    extractor = EchoLVEFExtractor()
    text = (
        "FINDINGS:\n"
        "Normal LV wall thickness and internal dimensions.\n\n"
        "MEASUREMENTS:\n"
        "LVEF (Biplane): 60 %\n"
        "LVEDV: 110 ml\n"
        "LVESV: 44 ml\n\n"
        "CONCLUSION:\n"
        "Normal echocardiographic examination."
    )
    doc = parser.parse_pages("case4.txt", [text])
    res = extractor.extract(doc)
    assert res.lvef_extracted == "60%"
    assert res.lvef_numeric == 60.0
    assert res.lvef_method == "2D_BIPLANE"
    assert res.lvef_section == "MEASUREMENTS"


def test_case5_comparative_disambiguation():
    parser = ClinicalSectionParser()
    extractor = EchoLVEFExtractor()
    text = (
        "SUMMARY:\n"
        "1. LVEF has significantly improved from 30% on prior study (10/2022) to 55% currently.\n"
        "2. Resolution of apical akinesis."
    )
    doc = parser.parse_pages("case5.txt", [text])
    res = extractor.extract(doc)
    assert res.lvef_extracted == "55%"
    assert res.lvef_numeric == 55.0
    assert res.lvef_section == "CONCLUSION"


def test_case6_pure_historical_exclusion():
    parser = ClinicalSectionParser()
    extractor = EchoLVEFExtractor()
    text = (
        "IMPRESSION:\n"
        "1. Prior echo from 04/2021 demonstrated LVEF 40%.\n"
        "2. Current study technically limited with uninterpretable LV endocardial borders."
    )
    doc = parser.parse_pages("case6.txt", [text])
    res = extractor.extract(doc)
    assert res.lvef_extracted == "NONE"
    assert res.lvef_numeric is None
    assert res.lvef_method == "NONE"
    assert res.lvef_section == "NONE"


def test_case7_qualitative_fallback():
    parser = ClinicalSectionParser()
    extractor = EchoLVEFExtractor()
    text = (
        "CONCLUSION:\n"
        "1. Normal LV systolic function and cavity size.\n"
        "2. No regional wall motion abnormalities."
    )
    doc = parser.parse_pages("case7.txt", [text])
    res = extractor.extract(doc)
    assert res.lvef_extracted == "Normal"
    assert res.lvef_numeric is None
    assert res.lvef_method == "QUALITATIVE"
    assert res.lvef_section == "CONCLUSION"


def test_visually_estimated_variations():
    parser = ClinicalSectionParser()
    extractor = EchoLVEFExtractor()
    variations = [
        "CONCLUSION: Visually estimated lvef 45-50%.",
        "CONCLUSION: Visually estimated lvef 45 to 50%.",
        "CONCLUSION: Visually estimated lvef 45% to 50%.",
        "CONCLUSION: Visually estimated lvef 45-50.",
        "CONCLUSION: Visually estimated lvef 45 to 50.",
        "CONCLUSION: Visually estimated lvef between 45 and 50%.",
        "CONCLUSION: Visually estimated LVEF is 45 to 50%.",
        "CONCLUSION: 2D echocardiogram. Visually estimated LVEF 45 to 50%.",
    ]
    for text in variations:
        doc = parser.parse_pages("var.txt", [text])
        res = extractor.extract(doc)
        assert res.lvef_extracted == "45-50%", f"Failed for {text}: got {res.lvef_extracted}"
        assert res.lvef_numeric == 47.5, f"Failed for {text}: got {res.lvef_numeric}"
        assert res.lvef_method == "VISUAL", f"Failed for {text}: got {res.lvef_method}"
        assert res.lvef_section == "CONCLUSION"


def test_method_priority_3d_over_2d_over_visual_over_unspecified():
    parser = ClinicalSectionParser()
    extractor = EchoLVEFExtractor()

    # Hierarchy: 3D (Rank 1) > 2D (Rank 2) > VISUAL (Rank 3) > UNSPECIFIED (Rank 4)

    # 1. 3D, 2D, Visual, Unspecified present -> 3D wins
    t1 = (
        "CONCLUSION:\n"
        "1. 3D LVEF: 55%.\n"
        "2. 2D Biplane Simpson's: 50%.\n"
        "3. Visually estimated LVEF: 45 to 50%.\n"
        "4. LVEF is 52%."
    )
    d1 = parser.parse_pages("t1.txt", [t1])
    r1 = extractor.extract(d1)
    assert r1.lvef_extracted == "55%"
    assert r1.lvef_method == "3D"

    # 2. 2D, Visual, Unspecified present -> 2D wins
    t2 = (
        "CONCLUSION:\n"
        "1. 2D Biplane Simpson's LVEF: 50%.\n"
        "2. Visually estimated LVEF 45 to 50%.\n"
        "3. LVEF 52%."
    )
    d2 = parser.parse_pages("t2.txt", [t2])
    r2 = extractor.extract(d2)
    assert r2.lvef_extracted == "50%"
    assert r2.lvef_method == "2D_BIPLANE"

    # 3. Visual and Unspecified present -> Visual wins over Unspecified
    t3 = (
        "CONCLUSION:\n"
        "1. Visually estimated LVEF 45 to 50%.\n"
        "2. Calculated LVEF 52%."
    )
    d3 = parser.parse_pages("t3.txt", [t3])
    r3 = extractor.extract(d3)
    assert r3.lvef_extracted == "45-50%"
    assert r3.lvef_numeric == 47.5
    assert r3.lvef_method == "VISUAL"

    # 4. Only Unspecified numeric present -> Unspecified wins
    t4 = "CONCLUSION:\nLVEF is 52%."
    d4 = parser.parse_pages("t4.txt", [t4])
    r4 = extractor.extract(d4)
    assert r4.lvef_extracted == "52%"
    assert r4.lvef_numeric == 52.0
    assert r4.lvef_method == "UNSPECIFIED"

