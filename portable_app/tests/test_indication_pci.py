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

    # Bulleted / numbered PMH line inside indication section
    t_bulleted_pmh = (
        "INDICATION:\n"
        "* Past Medical History: STEMI in 2019\n"
        "1. Medical History: Acute MI 5 years ago\n"
        "Elective evaluation for atypical chest pain."
    )
    res_bulleted = classifier.classify(parser.parse_sections(t_bulleted_pmh))
    assert res_bulleted.indication_stemi == "NO"
    assert res_bulleted.indication_ami == "NO"


def test_pci_done_and_ppci_detection():
    classifier = IndicationPCIClassifier()
    parser = ClinicalSectionParser()

    # 1. Pure diagnostic catheterization: pci_done in ("NO", "NEGATED"), ppci_done == "NO"
    diag_text = (
        "INDICATION: Stable angina.\n"
        "PROCEDURE: Diagnostic coronary angiography.\n"
        "FINDINGS: Normal coronaries. No PCI performed.\n"
        "CONCLUSION: Normal angiogram."
    )
    parsed_diag = parser.parse_sections(diag_text)
    res_diag = classifier.classify(parsed=parsed_diag, pci_result=PCIInterventionResult())
    assert res_diag.pci_done in ("NO", "NEGATED")
    assert res_diag.ppci_done == "NO"

    # 2. Explicit PPCI: ppci_done == "YES", confidence >= 0.95
    ppci_text = (
        "INDICATION: Chest pain.\n"
        "PROCEDURE: Primary PCI to Proximal LAD with 3.5x20mm DES.\n"
        "CONCLUSION: Successful primary angioplasty."
    )
    parsed_ppci = parser.parse_sections(ppci_text)
    pci_res = PCIInterventionResult(
        intervened_vessels="PROXIMAL LAD",
        devices_used="PROXIMAL LAD: [DRUG-ELUTING STENT] 3.5x20mm DES",
        success_status="PROXIMAL LAD: SUCCESSFUL ANGIOPLASTY",
    )
    res_ppci = classifier.classify(parsed=parsed_ppci, pci_result=pci_res)
    assert res_ppci.pci_done == "YES"
    assert res_ppci.ppci_done == "YES"
    assert res_ppci.ppci_done_confidence >= 0.95
    assert "primary" in res_ppci.ppci_done_evidence.lower() or "ppci" in res_ppci.ppci_done_evidence.lower()

    # 3. Synthesized PPCI (STEMI indication + PCI performed): indication_stemi == "YES", pci_done == "YES", ppci_done == "YES", confidence >= 0.90
    synth_text = (
        "INDICATION: Acute anterior STEMI.\n"
        "PROCEDURE: Angioplasty and stenting of culprit LAD.\n"
        "CONCLUSION: Successful stenting of LAD."
    )
    parsed_synth = parser.parse_sections(synth_text)
    res_synth = classifier.classify(parsed=parsed_synth, pci_result=pci_res)
    assert res_synth.indication_stemi == "YES"
    assert res_synth.pci_done == "YES"
    assert res_synth.ppci_done == "YES"
    assert res_synth.ppci_done_confidence >= 0.90
    assert len(res_synth.ppci_done_evidence) > 0

    # 4. Negated PCI: "PCI deferred" -> pci_done == "NEGATED"
    neg_text = (
        "INDICATION: Severe 3-vessel CAD.\n"
        "PROCEDURE: Diagnostic angiogram. PCI deferred in view of surgical CABG.\n"
        "CONCLUSION: Plan CABG."
    )
    parsed_neg = parser.parse_sections(neg_text)
    res_neg = classifier.classify(parsed=parsed_neg, pci_result=PCIInterventionResult())
    assert res_neg.pci_done == "NEGATED"
    assert "deferred" in res_neg.pci_done_evidence.lower()
    assert res_neg.ppci_done in ("NO", "NEGATED")

    # 5. Inline history immunity: "INDICATION: History of STEMI in 2018. Elective diagnostic catheterization." -> indication_stemi == "NO", ppci_done == "NO"
    inline_hist_text = (
        "INDICATION: History of STEMI in 2018. Elective diagnostic catheterization.\n"
        "PROCEDURE: Diagnostic coronary angiography.\n"
        "CONCLUSION: Patent prior stent. No new intervention."
    )
    parsed_inline = parser.parse_sections(inline_hist_text)
    res_inline = classifier.classify(parsed=parsed_inline, pci_result=PCIInterventionResult())
    assert res_inline.indication_stemi == "NO"
    assert res_inline.indication_ami == "NO"
    assert res_inline.pci_done in ("NO", "NEGATED")
    assert res_inline.ppci_done == "NO"


def test_pci_edge_cases_and_inline_acute_presentation():
    classifier = IndicationPCIClassifier()
    parser = ClinicalSectionParser()

    # 1. Pure diagnostic catheterization with NO negation phrase
    pure_diag = (
        "INDICATION: Stable angina.\n"
        "PROCEDURE: Diagnostic coronary angiography.\n"
        "FINDINGS: 50% mid LAD stenosis.\n"
        "CONCLUSION: Moderate CAD."
    )
    res_pure = classifier.classify(parsed=parser.parse_sections(pure_diag))
    assert res_pure.pci_done == "NO"
    assert res_pure.pci_done_confidence == 0.0
    assert res_pure.ppci_done == "NO"
    assert res_pure.ppci_done_confidence == 0.0

    # 2. Text-only affirmative PCI (no pci_result provided)
    text_pci = (
        "INDICATION: Unstable angina.\n"
        "PROCEDURE: Angioplasty and stenting of culprit LAD with DES.\n"
        "CONCLUSION: Successful stenting of LAD."
    )
    res_text_pci = classifier.classify(parsed=parser.parse_sections(text_pci))
    assert res_text_pci.pci_done == "YES"
    assert res_text_pci.pci_done_confidence >= 0.95
    assert "stenting" in res_text_pci.pci_done_evidence.lower()

    # 3. Inline history alongside acute presentation
    inline_acute = (
        "INDICATION: CAD s/p CABG in 2015, now presenting with acute anterior STEMI.\n"
        "PROCEDURE: Emergency angiogram and PCI to SVG.\n"
        "CONCLUSION: Successful revascularization."
    )
    res_inline_acute = classifier.classify(parsed=parser.parse_sections(inline_acute))
    assert res_inline_acute.indication_stemi == "YES"
    assert res_inline_acute.indication_ami == "YES"
    assert res_inline_acute.pci_done == "YES"
    assert res_inline_acute.ppci_done == "YES"

    # 4. Deferred intervention with vessel
    vessel_deferred = (
        "INDICATION: Multivessel CAD.\n"
        "PROCEDURE: Coronary angiography. PCI to RCA deferred.\n"
        "CONCLUSION: Conservative medical management."
    )
    res_vessel_deferred = classifier.classify(parsed=parser.parse_sections(vessel_deferred))
    assert res_vessel_deferred.pci_done == "NEGATED"
    assert "deferred" in res_vessel_deferred.pci_done_evidence.lower() or "conservative" in res_vessel_deferred.pci_done_evidence.lower()
    assert res_vessel_deferred.ppci_done in ("NO", "NEGATED")
