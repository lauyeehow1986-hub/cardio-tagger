import sys
from pathlib import Path

# Add portable_app to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from cardio_tagger.patient_demographics import PatientDemographicsExtractor, PatientDemographicsResult


def test_standard_singapore_nric_and_demographics():
    extractor = PatientDemographicsExtractor()
    text = (
        "NATIONAL HEART CENTRE SINGAPORE\n"
        "2D TRANSTHORACIC ECHOCARDIOGRAM REPORT\n\n"
        "Patient Name: TAN AH KOW, MR          NRIC: S1234567A\n"
        "MRN / Patient ID: 10029381            DOB: 12/03/1960    Sex: M\n"
        "Procedure Date: 28/10/2026            Report Date: 29/10/2026\n"
        "Referring Doctor: Dr. Smith, MD\n\n"
        "INDICATION: Shortness of breath.\n"
    )
    res = extractor.extract(text)
    assert res.patient_name == "TAN AH KOW"
    assert res.nric == "S1234567A"
    assert res.patient_id == "10029381"
    assert res.procedure_date == "2026-10-28"
    assert res.report_date == "2026-10-29"
    assert res.procedure_type == "TTE"
    assert "TRANSTHORACIC ECHOCARDIOGRAM" in res.procedure_title.upper()


def test_temporary_nric_x_and_y_up_to_13_chars():
    extractor = PatientDemographicsExtractor()

    # 9-char X NRIC
    t1 = (
        "Name: JOHN DOE\n"
        "NRIC/FIN: X1234567A\n"
        "Case No: C88192\n"
        "Date of Exam: 15-Mar-2026\n"
        "CARDIAC CATHETERIZATION REPORT"
    )
    r1 = extractor.extract(t1)
    assert r1.nric == "X1234567A"
    assert r1.procedure_type == "CATH_PCI"
    assert r1.procedure_date == "2026-03-15"

    # 13-char X temporary NRIC ending with alphabet (e.g. x01234567891a)
    t2 = (
        "Patient: JANE SMITH MDM\n"
        "Identity No: x01234567891a\n"
        "MRN: 994821\n"
        "Study Date: 2026-05-20\n"
        "TRANSESOPHAGEAL ECHOCARDIOGRAM"
    )
    r2 = extractor.extract(t2)
    assert r2.nric == "X01234567891A"
    assert r2.procedure_type == "TEE"
    assert r2.procedure_date == "2026-05-20"


def test_masked_nric():
    extractor = PatientDemographicsExtractor()
    t = (
        "Patient Name: LEE KENG HUAT\n"
        "NRIC: S****567A\n"
        "Hosp ID: H55432\n"
        "Exam Date: 04.11.2026\n"
        "DOBUTAMINE STRESS ECHOCARDIOGRAM"
    )
    r = extractor.extract(t)
    assert r.patient_name == "LEE KENG HUAT"
    assert r.nric == "S****567A"
    assert r.patient_id == "H55432"
    assert r.procedure_date == "2026-11-04"
    assert r.procedure_type == "STRESS_ECHO"
