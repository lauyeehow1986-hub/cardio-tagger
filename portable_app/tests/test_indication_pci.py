import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from cardio_tagger.indication_pci_classifier import IndicationPCIClassifier, IndicationPCIResult
from cardio_tagger.section_parser import ClinicalSectionParser
from cardio_tagger.pci_intervention import PCIInterventionResult


def test_stemi_vs_nstemi_differentiation():
    classifier = IndicationPCIClassifier()
    parser = ClinicalSectionParser()
    
    # 1. Pure STEMI case
    stemi_text = "INDICATION: Acute extensive anterior STEMI.\nPROCEDURE: Coronary angiogram."
    parsed = parser.parse_sections(stemi_text)
    res = classifier.classify(parsed=parsed, pci_result=PCIInterventionResult())
    assert res.indication_stemi == "YES"
    assert "STEMI" in res.indication_stemi_evidence
    assert res.indication_stemi_confidence >= 0.90
    assert res.indication_ami == "YES"
    
    # 2. Pure NSTEMI case
    nstemi_text = "INDICATION: Acute coronary syndrome, NSTEMI with elevated troponin.\nPROCEDURE: Coronary angiogram."
    parsed_nstemi = parser.parse_sections(nstemi_text)
    res_nstemi = classifier.classify(parsed=parsed_nstemi, pci_result=PCIInterventionResult())
    assert res_nstemi.indication_stemi == "NO"
    assert res_nstemi.indication_ami == "YES"
    assert "NSTEMI" in res_nstemi.indication_ami_evidence

def test_history_exclusion_and_scope_priority():
    classifier = IndicationPCIClassifier()
    parser = ClinicalSectionParser()

    # Test 1 (History ignored):
    t1 = (
        "PAST MEDICAL HISTORY: STEMI in 2017, hypertension, diabetes.\n"
        "INDICATION: Elective diagnostic catheterization for stable angina.\n"
        "CONCLUSION: Moderate LAD CAD."
    )
    parsed1 = parser.parse_sections(t1)
    res1 = classifier.classify(parsed1)
    assert res1.indication_stemi == "NO"
    assert res1.indication_ami == "NO"

    # Test 2 (Conclusion fallback):
    t2 = (
        "PROCEDURE: Coronary angiogram.\n"
        "CONCLUSION: Acute inferior STEMI. Recommended medical therapy."
    )
    parsed2 = parser.parse_sections(t2)
    res2 = classifier.classify(parsed2)
    assert res2.indication_stemi == "YES"
    assert res2.indication_ami == "YES"
    assert "STEMI" in res2.indication_stemi_evidence

    # Test 3 (ST-segment elevation phrase):
    t3 = (
        "INDICATION: Acute ST-segment elevation myocardial infarction.\n"
        "PROCEDURE: Angiogram."
    )
    parsed3 = parser.parse_sections(t3)
    res3 = classifier.classify(parsed3)
    assert res3.indication_stemi == "YES"
    assert res3.indication_ami == "YES"


def test_expanded_regex_variants():
    classifier = IndicationPCIClassifier()
    parser = ClinicalSectionParser()

    # nonstemi
    res_nonstemi = classifier.classify(parser.parse_sections("INDICATION: nonstemi with chest pain."))
    assert res_nonstemi.indication_stemi == "NO"
    assert res_nonstemi.indication_ami == "YES"

    # nsteacs
    res_nsteacs = classifier.classify(parser.parse_sections("INDICATION: nsteacs presentation."))
    assert res_nsteacs.indication_stemi == "NO"
    assert res_nsteacs.indication_ami == "YES"

    # ST segment elevation (unhyphenated)
    res_unhyphenated = classifier.classify(parser.parse_sections("INDICATION: Acute ST segment elevation myocardial infarction."))
    assert res_unhyphenated.indication_stemi == "YES"
    assert res_unhyphenated.indication_ami == "YES"

    # PMH line inside indication section ignored
    t_inline_pmh = (
        "INDICATION:\n"
        "PMH: STEMI in 2015\n"
        "Elective evaluation for atypical chest pain."
    )
    res_pmh = classifier.classify(parser.parse_sections(t_inline_pmh))
    assert res_pmh.indication_stemi == "NO"
    assert res_pmh.indication_ami == "NO"

