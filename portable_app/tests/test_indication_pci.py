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
