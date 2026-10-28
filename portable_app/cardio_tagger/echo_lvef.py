"""
Hierarchical Echocardiography LVEF Extraction Engine.

Features:
  1. Strict Section Cascade:
     Conclusion / Impression / Summary (P1) -> Findings / Left Ventricle (P2) -> Measurements (P3)
  2. Method Preference (within active section):
     3D > 2D (Biplane Simpson / Auto-EF / Teichholz) > Unspecified > Visual (Eyeball / Estimated)
  3. Historical & Comparative Disambiguation:
     Excludes dated historical studies (e.g. "prior LVEF 40% in 2021").
     Resolves comparative sentences ("improved from 30% on prior to 55% currently" -> 55%).
  4. Range & Qualitative Value Parsing:
     Discrete numbers ("55%"), ranges ("50-55%" -> 52.5 midpoint), inequalities (">55%", "<35%"),
     and qualitative fallbacks ("Normal", "Moderately reduced") when no numbers exist.
"""
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .section_parser import ExtractedSection, ParsedDocument


@dataclass
class EchoLVEFCandidate:
    raw_text: str
    numeric_midpoint: Optional[float]
    method: str  # 3D, 2D_BIPLANE, 2D_TEICHHOLZ, 2D, VISUAL, UNSPECIFIED, QUALITATIVE
    method_rank: int  # 1: 3D, 2: 2D, 3: UNSPECIFIED, 4: VISUAL, 5: QUALITATIVE
    section_name: str
    is_historical: bool
    evidence_clause: str


@dataclass
class EchoLVEFResult:
    lvef_extracted: str = "NONE"
    lvef_numeric: Optional[float] = None
    lvef_method: str = "NONE"
    lvef_section: str = "NONE"
    evidence_text: str = ""


class EchoLVEFExtractor:
    """
    Precision extractor for Left Ventricular Ejection Fraction (LVEF) from
    echocardiography reports, enforcing clinical section priority and method hierarchy.
    """

    # Primary numerical LVEF pattern: captures 55%, 50-55%, 50 to 55%, >55%, <35%
    LVEF_NUMERIC_PATTERN = re.compile(
        r"(?i)(?P<prefix>>|<|>=|<=|~|approx\.?|approximately)?\s*"
        r"(?P<low>[0-9]{2})\s*"
        r"(?:(?:[\-–—]|(?:\s+to\s+))\s*(?P<high>[0-9]{2}))?\s*%"
    )

    # Comparative sentence pattern: "improved from 30% in 2022 to 55% today"
    COMPARATIVE_PATTERN = re.compile(
        r"(?i)(?:improved|increased|decreased|reduced|worsened|changed)\s+"
        r"(?:from\s+)?(?P<prior>[0-9]{2}(?:\s*[\-–—]\s*[0-9]{2})?\s*%)\s*"
        r"[^.;\n]*?\s+(?:to\s+)(?P<current>[0-9]{2}(?:\s*[\-–—]\s*[0-9]{2})?\s*%)"
    )

    HISTORICAL_TERMS = [
        re.compile(r"(?i)\b(?:prior|previous|baseline|historical|formerly?|remote|earlier|old)\b"),
        re.compile(r"\b(?:in\s+20[0-2][0-9]|on\s+[0-9]{1,2}/[0-9]{1,2}/(?:20)?[0-9]{2}|from\s+[0-9]{1,2}/[0-9]{4}|[0-9]{1,2}/(?:20)?[0-9]{2})\b"),
        re.compile(r"(?i)\b(?:compared\s+to|comparison\s+with|s/p\s+prior)\b"),
    ]

    QUALITATIVE_PATTERNS = [
        (re.compile(r"(?i)\b(?:normal|preserved)\s+(?:lv\s+systolic\s+function|lvef|ef|systolic\s+function)\b"), "Normal"),
        (re.compile(r"(?i)\b(?:lv\s+systolic\s+function|lvef|ef)\s+(?:is\s+)?(?:normal|preserved)\b"), "Normal"),
        (re.compile(r"(?i)\b(?:hyperdynamic)\s+(?:lv\s+systolic\s+function|lvef|ef)\b"), "Hyperdynamic"),
        (re.compile(r"(?i)\bmildly\s+reduced\s+(?:lv\s+systolic\s+function|lvef|ef)\b"), "Mildly reduced"),
        (re.compile(r"(?i)\bmoderately\s+reduced\s+(?:lv\s+systolic\s+function|lvef|ef)\b"), "Moderately reduced"),
        (re.compile(r"(?i)\bseverely\s+reduced\s+(?:lv\s+systolic\s+function|lvef|ef)\b"), "Severely reduced"),
    ]

    def extract(self, parsed_doc: ParsedDocument) -> EchoLVEFResult:
        """
        Extracts LVEF according to strict section priority:
        Conclusion -> Findings -> Measurements
        """
        # Section Priority 1: Conclusion / Impression / Summary / Plan
        conclusion_sections = list(parsed_doc.conclusion_sections)
        res = self._extract_from_section_group("CONCLUSION", conclusion_sections)
        if res and res.lvef_extracted != "NONE":
            return res

        # Section Priority 2: Findings / Left Ventricle / Chambers
        findings_sections = parsed_doc.all_sections.get("findings", [])
        res = self._extract_from_section_group("FINDINGS", findings_sections)
        if res and res.lvef_extracted != "NONE":
            return res

        # Section Priority 3: Measurements table
        measurements_sections = parsed_doc.all_sections.get("measurements", [])
        res = self._extract_from_section_group("MEASUREMENTS", measurements_sections)
        if res and res.lvef_extracted != "NONE":
            return res

        # If no numeric candidate found in any section, check for qualitative descriptors
        qual_res = self._extract_qualitative_fallback(parsed_doc)
        if qual_res:
            return qual_res

        return EchoLVEFResult()

    def _extract_from_section_group(
        self, section_name: str, sections: List[ExtractedSection]
    ) -> Optional[EchoLVEFResult]:
        if not sections:
            return None

        candidates: List[EchoLVEFCandidate] = []
        for sec in sections:
            sec_candidates = self._extract_candidates_from_text(sec.text, section_name)
            candidates.extend(sec_candidates)

        # Filter out historical values
        current_candidates = [c for c in candidates if not c.is_historical]
        if not current_candidates:
            return None

        # Sort by method hierarchy (3D=1, 2D=2, UNSPECIFIED=3, VISUAL=4)
        current_candidates.sort(key=lambda c: (c.method_rank, -(c.numeric_midpoint or 0)))
        best = current_candidates[0]

        return EchoLVEFResult(
            lvef_extracted=best.raw_text,
            lvef_numeric=best.numeric_midpoint,
            lvef_method=best.method,
            lvef_section=section_name,
            evidence_text=best.evidence_clause,
        )

    def _extract_candidates_from_text(
        self, text: str, section_name: str
    ) -> List[EchoLVEFCandidate]:
        candidates: List[EchoLVEFCandidate] = []

        # Split text into sentences / table lines
        lines_or_sentences = [
            s.strip()
            for s in re.split(r"(?:\n+|\r+|(?<=[.!?])\s+(?=[A-Z0-9\-•*]))", text)
            if s.strip()
        ]

        for stmt in lines_or_sentences:
            stmt_lower = stmt.lower()

            # Check if line has LVEF / EF / Ejection Fraction context
            if not self._is_lvef_context(stmt_lower):
                continue

            # Check for comparative sentence: "improved from 30% in 2022 to 55% today"
            comp_match = self.COMPARATIVE_PATTERN.search(stmt)
            if comp_match:
                prior_val = comp_match.group("prior")
                curr_val = comp_match.group("current")

                # The prior value is historical
                parsed_prior, mid_prior = self._parse_lvef_value(prior_val)
                candidates.append(
                    EchoLVEFCandidate(
                        raw_text=parsed_prior,
                        numeric_midpoint=mid_prior,
                        method="UNSPECIFIED",
                        method_rank=3,
                        section_name=section_name,
                        is_historical=True,
                        evidence_clause=stmt,
                    )
                )

                # The current value is current
                parsed_curr, mid_curr = self._parse_lvef_value(curr_val)
                method, rank = self._determine_method(stmt_lower, curr_val)
                candidates.append(
                    EchoLVEFCandidate(
                        raw_text=parsed_curr,
                        numeric_midpoint=mid_curr,
                        method=method,
                        method_rank=rank,
                        section_name=section_name,
                        is_historical=False,
                        evidence_clause=stmt,
                    )
                )
                continue

            # Standard numeric scan in statement
            for m in self.LVEF_NUMERIC_PATTERN.finditer(stmt):
                raw_match = m.group(0).strip()
                prefix = m.group("prefix")
                low_str = m.group("low")
                high_str = m.group("high")

                low_val = float(low_str)
                # Plausibility check: LVEF is clinically between 5% and 95%
                if not (5 <= low_val <= 95):
                    continue

                if high_str:
                    high_val = float(high_str)
                    midpoint = round((low_val + high_val) / 2.0, 1)
                    raw_formatted = f"{int(low_val)}-{int(high_val)}%"
                else:
                    midpoint = low_val
                    raw_formatted = f"{prefix or ''}{int(low_val)}%"

                # Context around this specific match
                start_idx = max(0, m.start() - 40)
                end_idx = min(len(stmt), m.end() + 40)
                local_window = stmt[start_idx:end_idx]

                is_hist = self._is_historical(stmt, local_window)
                method, rank = self._determine_method(stmt_lower, raw_match)

                candidates.append(
                    EchoLVEFCandidate(
                        raw_text=raw_formatted,
                        numeric_midpoint=midpoint,
                        method=method,
                        method_rank=rank,
                        section_name=section_name,
                        is_historical=is_hist,
                        evidence_clause=stmt,
                    )
                )

        return candidates

    def _determine_method(self, text_lower: str, val_match_str: str) -> Tuple[str, int]:
        """
        Determines the acquisition method and assigns strict priority rank:
        1: 3D
        2: 2D (Biplane, Simpson, Teichholz, Auto-EF)
        3: UNSPECIFIED (Numeric without visual marker)
        4: VISUAL (Eyeball, Estimated, Range without 2D/3D tag)
        """
        # Rank 1: 3D
        if re.search(r"(?i)\b(?:3[\-\s]?d|tri[\-\s]?plane|3[\-\s]?d\s+(?:auto|simpson|volume))\b", text_lower):
            return "3D", 1

        # Rank 2: 2D Biplane / Simpson / Auto-EF / Teichholz
        if re.search(r"(?i)\b(?:biplane|simpson(?:'s)?|modified\s+simpson|method\s+of\s+discs|auto[\-\s]?ef)\b", text_lower):
            return "2D_BIPLANE", 2

        if re.search(r"(?i)\b(?:teich(?:holz)?|m[\-\s]?mode)\b", text_lower):
            return "2D_TEICHHOLZ", 2

        if re.search(r"(?i)\b(?:2[\-\s]?d(?:\s+echo)?|quantitative)\b", text_lower):
            return "2D", 2

        # Rank 4: Visual Estimate / Eyeball
        if re.search(r"(?i)\b(?:visual(?:ly)?|eyeball|estimated?|semi[\-\s]?quantitative)\b", text_lower):
            return "VISUAL", 4

        # If it's a range (e.g. 50-55%) without explicit 2D/3D tag, clinically it's an estimated visual range
        if re.search(r"[0-9]{2}\s*(?:[\-–—]|(?:\s+to\s+))\s*[0-9]{2}", val_match_str):
            return "VISUAL", 4

        # Rank 3: Unspecified
        return "UNSPECIFIED", 3

    def _is_historical(self, full_stmt: str, local_window: str) -> bool:
        """
        Returns True if the candidate is attributed to a prior historical examination.
        """
        target = f"{full_stmt} {local_window}"
        for pat in self.HISTORICAL_TERMS:
            if pat.search(target):
                return True
        return False

    def _is_lvef_context(self, text_lower: str) -> bool:
        return bool(
            re.search(r"(?i)\b(?:lvef|ef|ejection\s+fraction|systolic\s+function|lv\s+function)\b", text_lower)
            or "biplane" in text_lower
            or "simpson" in text_lower
            or "teich" in text_lower
            or "3d" in text_lower
        )

    def _parse_lvef_value(self, raw_str: str) -> Tuple[str, Optional[float]]:
        m = self.LVEF_NUMERIC_PATTERN.search(raw_str)
        if not m:
            return raw_str.strip(), None
        low = float(m.group("low"))
        if m.group("high"):
            high = float(m.group("high"))
            return f"{int(low)}-{int(high)}%", round((low + high) / 2.0, 1)
        prefix = m.group("prefix") or ""
        return f"{prefix}{int(low)}%", low

    def _extract_qualitative_fallback(self, parsed_doc: ParsedDocument) -> Optional[EchoLVEFResult]:
        for sec in parsed_doc.conclusion_sections:
            for pat, label in self.QUALITATIVE_PATTERNS:
                if pat.search(sec.text):
                    return EchoLVEFResult(
                        lvef_extracted=label,
                        lvef_numeric=None,
                        lvef_method="QUALITATIVE",
                        lvef_section="CONCLUSION",
                        evidence_text=sec.text.strip(),
                    )

        for sec in parsed_doc.all_sections.get("findings", []):
            for pat, label in self.QUALITATIVE_PATTERNS:
                if pat.search(sec.text):
                    return EchoLVEFResult(
                        lvef_extracted=label,
                        lvef_numeric=None,
                        lvef_method="QUALITATIVE",
                        lvef_section="FINDINGS",
                        evidence_text=sec.text.strip(),
                    )

        return None
