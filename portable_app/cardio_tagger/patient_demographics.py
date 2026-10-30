"""
Patient Demographics, Study Dates, and Procedure Type Extractor.
Extracts patient name, NRIC/FIN (including temporary X/Y formats), MRN/Patient ID,
Procedure Date, Report Date, and Procedure Type from Page 1 clinical report headers.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PatientDemographicsResult:
    patient_name: str = ""
    nric: str = ""
    patient_id: str = ""
    procedure_date: str = ""
    report_date: str = ""
    procedure_type: str = "OTHER"
    procedure_title: str = ""


class PatientDemographicsExtractor:
    """
    Layout-aware extractor for Page 1 medical report headers and demographics blocks.
    Deterministic, <0.1ms per document, zero external runtime dependencies.
    """

    # Standard Singapore NRIC / FIN: S, T, F, G, M followed by 7 digits or masked 4 stars/X + 3 digits, ending in letter
    NRIC_STANDARD_PATTERN = re.compile(
        r"(?i)\b(?P<nric>[STFGM](?:[0-9]{7}|[\*X]{4}[0-9]{3})[A-Z])\b"
    )

    # Temporary Hospital IDs: X or Y, up to 13 chars total, ending in letter (e.g. X1234567A, X01234567891A, Y1234567890A)
    NRIC_TEMP_PATTERN = re.compile(
        r"(?i)\b(?P<nric>[XY][0-9A-Z\*]{6,11}[A-Z])\b"
    )

    NRIC_LABEL_PATTERN = re.compile(
        r"(?im)\b(?:NRIC(?:[\t ]*/[\t ]*FIN)?|FIN|IDENTITY[\t ]+(?:NO|NUMBER)|ID[\t ]+NO|NATIONAL[\t ]+ID)[\t ]*[:=\-]?[\t ]*(?P<val>[A-Z0-9\*]{7,15})",
    )

    PATIENT_ID_PATTERN = re.compile(
        r"(?im)\b(?:MRN(?:[\t ]*/[\t ]*PATIENT[\t ]+ID)?|PATIENT[\t ]+ID|HOSP(?:ITAL)?[\t ]+ID|REG(?:ISTRATION)?[\t ]+NO|CASE[\t ]+NO|ACCOUNT[\t ]+NO)[\t ]*[:=\-]?[\t ]*(?P<val>[A-Z0-9\-]{3,20})"
    )

    NAME_LABEL_PATTERN = re.compile(
        r"(?im)\b(?P<label>PATIENT[\t ]+NAME|PT[\t ]+NAME|NAME[\t ]+OF[\t ]+PATIENT|PATIENT(?:[\t ]*/[\t ]*(?:NRIC|FIN|IC|MRN|ID))?|PT|NAME)[\t ]*[:=\-][\t ]*(?P<val>[A-Za-z\s,.\x27\-/@()]{2,60})|"
        r"\b(?P<label2>PATIENT[\t ]+NAME|PT[\t ]+NAME|NAME[\t ]+OF[\t ]+PATIENT)[\t ]+(?P<val2>[A-Za-z\s,.\x27\-/@()]{2,60})"
    )

    NAME_LINE_ONLY_LABEL = re.compile(
        r"(?i)^\s*(?:PATIENT[\t ]+NAME|PT[\t ]+NAME|NAME[\t ]+OF[\t ]+PATIENT|PATIENT|PT|NAME)\s*[:=\-]?\s*$"
    )

    NAME_DELIMITER_SPLIT = re.compile(
        r"(?i)(?:"
        r"\t+|"
        r"\s{2,}(?:[A-Z][a-z0-9\-]*\s*[:=\-])|"
        r"\s{3,}|"
        r"\s*[|;]\s*|"
        r"\s*[,|\-]?\s*(?:NRIC|FIN|IC|MRN|DOB|SEX|GENDER|AGE|HOSP|DATE|ID|REF|BED|WARD|CASE|RN|ACCT|ROOM|LOC)\b|"
        r"\s*/\s*(?:[STFGM][0-9*]|[XY][0-9A-Z*]|MRN|\d)"
        r")"
    )

    EXCLUDE_NAME_WORDS = re.compile(
        r"(?i)\b(?:DOCTOR|PHYSICIAN|ATTENDING|SONOGRAPHER|CARDIOLOGIST|REFERRING|FELLOW|REGISTRAR|CLINICIAN|"
        r"HOSPITAL|CENTRE|DEPARTMENT|REPORT|DATE|NRIC|MRN|SEX|AGE|DOB|GENDER|"
        r"TYPE|CLASS|CATEGORY|LOCATION|WARD|BED|STATUS|INFORMATION|PARTICULARS|DEMOGRAPHICS|PROFILE|DETAILS|SUMMARY)\b"
    )

    PROC_DATE_LABEL_PATTERN = re.compile(
        r"(?im)\b(?:PROCEDURE[\t ]+DATE|DATE[\t ]+OF[\t ]+PROCEDURE|DATE[\t ]+OF[\t ]+EXAM(?:INATION)?|EXAM[\t ]+DATE|STUDY[\t ]+DATE|DATE[\t ]+OF[\t ]+STUDY|DATE[\t ]+PERFORMED|DOA|ADM[\t ]+DATE)[\t ]*[:=\-]?[\t ]*(?P<val>[A-Z0-9\s,\-/.]{6,25})"
    )

    REPORT_DATE_LABEL_PATTERN = re.compile(
        r"(?im)\b(?:REPORT[\t ]+DATE|DATE[\t ]+OF[\t ]+REPORT|DICTATED[\t ]+DATE|DATE[\t ]+DICTATED|TRANSCRIPTION[\t ]+DATE|VERIFIED[\t ]+DATE|ORDER[\t ]+DATE)[\t ]*[:=\-]?[\t ]*(?P<val>[A-Z0-9\s,\-/.]{6,25})"
    )

    DATE_PATTERN = re.compile(
        r"\b(?:"
        r"[0-3]?[0-9][/\-.][0-1]?[0-9][/\-.](?:20)?[0-9]{2}|"
        r"(?:20)?[0-9]{2}[/\-.][0-1]?[0-9][/\-.][0-3]?[0-9]|"
        r"[0-3]?[0-9][\-\s]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\-\s]+(?:20)?[0-9]{2}|"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s]+[0-3]?[0-9],?[\s]+(?:20)?[0-9]{2}"
        r")\b",
        re.IGNORECASE,
    )

    PROCEDURE_MODALITY_PATTERNS = [
        ("TEE", re.compile(r"(?i)\b(?:trans[\-\s]?esophageal\s+echo(?:cardiogram)?|transesophageal\s+echo|tee)\b")),
        ("STRESS_ECHO", re.compile(r"(?i)\b(?:stress\s+echo(?:cardiogram)?|dobutamine\s+stress\s+echo|exercise\s+stress\s+echo|treadmill\s+echo)\b")),
        ("TTE", re.compile(r"(?i)\b(?:trans[\-\s]?thoracic\s+echo(?:cardiogram)?|transthoracic\s+echo|2d\s+echo(?:cardiogram)?|echocardiogram\s+report|echocardiography\s+report|tte)\b")),
        ("CATH_PCI", re.compile(r"(?i)\b(?:coronary\s+angiogra(?:m|phy)|cardiac\s+catheterization|pci\s+report|percutaneous\s+coronary\s+intervention|angiography\s+report|coronary\s+intervention)\b")),
        ("RHC", re.compile(r"(?i)\b(?:right\s+heart\s+cath(?:eterization)?|rhc|swan[\-\s]?ganz|hemodynamic\s+study)\b")),
    ]

    PROCEDURE_TITLE_SEARCH = re.compile(
        r"(?im)^[\t ]*(?:[0-9]+\.\s*)?(?P<title>(?:(?:2D|3D|DOPPLER|COLOR|TRANS[\-\s]?THORACIC|TRANS[\-\s]?ESOPHAGEAL|DOBUTAMINE|EXERCISE|STRESS|CARDIAC|CORONARY)[\t \-/]+)*"
        r"(?:ECHOCARDIOGRAM|ECHOCARDIOGRAPHY|CATHETERIZATION|ANGIOGRAM|ANGIOGRAPHY|INTERVENTION|STUDY)[\t ]*(?:REPORT)?)"
    )

    def extract(self, page1_text: str) -> PatientDemographicsResult:
        """
        Extracts patient demographics, dates, and procedure type from Page 1 text.
        """
        if not page1_text:
            return PatientDemographicsResult()

        # Isolate top header / demographics region (first 2500 characters or before clinical narrative)
        header_text = self._isolate_demographics_region(page1_text)

        # 1. Extract NRIC
        nric = self._extract_nric(header_text)

        # 2. Extract Patient ID / MRN
        patient_id = self._extract_patient_id(header_text, exclude_val=nric)

        # 3. Extract Patient Name
        patient_name = self._extract_patient_name(header_text)

        # 4. Extract Procedure & Report Dates
        proc_date, rep_date = self._extract_dates(header_text)

        # 5. Extract Procedure Modality & Title
        proc_type, proc_title = self._extract_procedure_info(page1_text[:2000])

        return PatientDemographicsResult(
            patient_name=patient_name,
            nric=nric,
            patient_id=patient_id,
            procedure_date=proc_date,
            report_date=rep_date,
            procedure_type=proc_type,
            procedure_title=proc_title,
        )

    def _isolate_demographics_region(self, text: str) -> str:
        # Cut off at first major clinical narrative section header
        m = re.search(
            r"(?im)^(?:INDICATION|CLINICAL[\t ]+HISTORY|HISTORY|PROCEDURE[\t ]+DETAILS|FINDINGS|TECHNIQUE|HEMODYNAMICS)[\t ]*[:\-—\n]",
            text,
        )
        if m:
            return text[: m.start()]
        return text[:2500]

    def _extract_nric(self, text: str) -> str:
        # Check explicit label first
        m_label = self.NRIC_LABEL_PATTERN.search(text)
        if m_label:
            cand = m_label.group("val").strip().upper()
            if self.NRIC_STANDARD_PATTERN.match(cand) or self.NRIC_TEMP_PATTERN.match(cand):
                return cand

        # Scan text for standard NRIC/FIN
        m_std = self.NRIC_STANDARD_PATTERN.search(text)
        if m_std:
            return m_std.group("nric").strip().upper()

        # Scan text for temporary X/Y NRIC
        m_temp = self.NRIC_TEMP_PATTERN.search(text)
        if m_temp:
            return m_temp.group("nric").strip().upper()

        return ""

    def _extract_patient_id(self, text: str, exclude_val: str = "") -> str:
        for m in self.PATIENT_ID_PATTERN.finditer(text):
            val = m.group("val").strip().upper()
            if val and val != exclude_val:
                return val
        return ""

    def _clean_patient_name(self, raw_val: str) -> str:
        # Cut at column delimiters or next field labels
        cleaned = self.NAME_DELIMITER_SPLIT.split(raw_val)[0].strip()
        # Clean clinical titles and honorifics
        cleaned = re.sub(
            r"(?i)\b(?:MR|MRS|MDM|MS|MISS|DR|PROF|A/PROF|ASSOC[\t ]+PROF|MD)\b[\.,]?",
            "",
            cleaned,
        )
        # Clean leftover empty parentheses from removed titles e.g. (MR) -> ()
        cleaned = re.sub(r"\(\s*\)", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")

        # Validate plausibility
        if len(cleaned) >= 2 and re.search(r"[A-Za-z]", cleaned):
            if not self.EXCLUDE_NAME_WORDS.search(cleaned):
                return cleaned.upper()
        return ""

    def _extract_patient_name(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for i, line in enumerate(lines):
            # 1. Inline match (e.g. "Patient: Tan Ah Kow", "Patient Name: Tan Ah Kow")
            m = self.NAME_LABEL_PATTERN.search(line)
            if m:
                raw_val = m.group("val") or m.group("val2")
                cand = self._clean_patient_name(raw_val)
                if cand:
                    return cand

            # 2. Next-line match when label is on its own line (e.g. "Patient:\nTan Ah Kow")
            if self.NAME_LINE_ONLY_LABEL.match(line):
                for next_idx in range(i + 1, min(i + 3, len(lines))):
                    next_line = lines[next_idx]
                    # Ensure next line is not another section header or label
                    if not re.search(
                        r"(?i)^\s*(?:NRIC|FIN|IC|MRN|DOB|SEX|GENDER|AGE|HOSP|DATE|ID|REF|INDICATION|CLINICAL|PROCEDURE|FINDINGS|REPORT)\b",
                        next_line,
                    ):
                        cand = self._clean_patient_name(next_line)
                        if cand:
                            return cand
        return ""

    def _extract_dates(self, text: str) -> Tuple[str, str]:
        proc_date = ""
        rep_date = ""

        # Check explicit procedure date label
        m_proc = self.PROC_DATE_LABEL_PATTERN.search(text)
        if m_proc:
            raw_p = m_proc.group("val")
            m_date = self.DATE_PATTERN.search(raw_p)
            if m_date:
                proc_date = self._normalize_date(m_date.group(0))

        # Check explicit report date label
        m_rep = self.REPORT_DATE_LABEL_PATTERN.search(text)
        if m_rep:
            raw_r = m_rep.group("val")
            m_date = self.DATE_PATTERN.search(raw_r)
            if m_date:
                rep_date = self._normalize_date(m_date.group(0))

        # Fallback: if only one date is present in the demographics block
        if not proc_date and not rep_date:
            all_dates = self.DATE_PATTERN.findall(text)
            if all_dates:
                proc_date = self._normalize_date(all_dates[0])

        return proc_date, rep_date

    def _normalize_date(self, raw_date_str: str) -> str:
        s = raw_date_str.strip(" ,.-")
        # Try known standard date formats
        formats = [
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%d.%m.%Y",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d-%b-%Y",
            "%d %b %Y",
            "%d-%B-%Y",
            "%d %B %Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d/%m/%y",
            "%d-%m-%y",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(s, fmt)
                # Plausibility check: between 1990 and 2040
                if 1990 <= dt.year <= 2040:
                    return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return s

    def _extract_procedure_info(self, text: str) -> Tuple[str, str]:
        proc_type = "OTHER"
        for code, pat in self.PROCEDURE_MODALITY_PATTERNS:
            if pat.search(text):
                proc_type = code
                break

        proc_title = ""
        m_title = self.PROCEDURE_TITLE_SEARCH.search(text)
        if m_title:
            proc_title = m_title.group("title").strip()
        else:
            # Fallback: check first 3 lines for title
            for line in text.splitlines()[:4]:
                line_s = line.strip()
                if any(k in line_s.upper() for k in ("ECHOCARDIOGRAM", "CATHETERIZATION", "ANGIOGRAM", "PCI", "REPORT")):
                    proc_title = line_s
                    break

        return proc_type, proc_title
