"""
Hierarchical Echocardiography LVEF Extraction Engine.

Features:
  1. Strict Section Cascade:
     Conclusion / Impression / Summary (P1) -> Findings / Left Ventricle (P2) -> Measurements (P3)
  2. Method Preference (within active section):
     3D > 2D (Biplane Simpson / Auto-EF / Teichholz) > Visual (Eyeball / Estimated) > Unspecified
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
    method_rank: int  # 1: 3D, 2: 2D, 3: VISUAL, 4: UNSPECIFIED, 5: QUALITATIVE
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

    # Primary numerical LVEF pattern: captures 55%, 50-55%, 50 to 55%, 50% to 55%, 50-55, 50 to 50, >55%, <35%
    # Uses negative lookaround to prevent matching decimals (e.g. 0.94 cm2/m2) as integer percentages
    LVEF_NUMERIC_PATTERN = re.compile(
        r"(?i)(?:between\s+)?(?P<prefix>>|<|>=|<=|~|approx\.?|approximately|greater\s+than|less\s+than)?\s*"
        r"(?<![\.\d])(?P<low>[0-9]{2})(?!\.[0-9])\s*(?:%|percent)?\s*"
        r"(?:(?:[\-–—]|(?:\s*(?:to|and)\s*))\s*(?<![\.\d])(?P<high>[0-9]{2})(?!\.[0-9])\s*(?:%|percent)?)?"
        r"(?:\s*%)?"
    )

    REJECTED_UNITS_PATTERN = re.compile(
        r"^\s*(?:cm(?:2|²|3|³)?(?:\s*/\s*m(?:2|²))?|mm(?:2|²|3|³)?|m(?:2|²)|"
        r"ml(?:\s*/\s*m(?:2|²))?|l\s*/\s*min|m/s(?:ec)?|cm/s(?:ec)?|"
        r"mmhg|bpm|kg|ms|sec|seconds?|years?|yo|yr|g/m(?:2|²)?|kpa)\b",
        re.IGNORECASE,
    )

    REFERENCE_RANGE_PREFIX = re.compile(
        r"(?i)(?:\[|\(|\b)(?:N|NL|Normal|Ref|Reference|Norm)\s*(?:range)?\s*[:=\s]\s*$"
    )

    REFERENCE_RANGE_BRACKETS = re.compile(
        r"(?i)(?:\[|\()\s*(?:N|NL|Normal|Ref|Reference|Norm)\s*(?:range)?\s*[:=\s]\s*"
        r"[0-9]{2}(?:\s*(?:[\-–—]|to|and)\s*[0-9]{2})?\s*%?\s*(?:\]|\))"
    )

    # Comparative sentence pattern: "improved from 30% in 2022 to 55% today"
    COMPARATIVE_PATTERN = re.compile(
        r"(?i)(?:improved|increased|decreased|reduced|worsened|changed)\s+"
        r"(?:from\s+)?(?P<prior>[0-9]{2}(?:\s*(?:[\-–—]|to|and)\s*[0-9]{2})?\s*%?)\s*"
        r"[^.;\n]*?\s+(?:to\s+)(?P<current>[0-9]{2}(?:\s*(?:[\-–—]|to|and)\s*[0-9]{2})?\s*%?)"
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

    FIELD_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_\-\s/()]{2,25}:(?!\s*$)")
    LIST_ITEM_PATTERN = re.compile(r"^(?:[0-9]{1,2}[\.\)]|[•\-\*■]|\([a-z0-9]\))\s+", re.IGNORECASE)
    METHOD_MODIFIER_PATTERN = re.compile(
        r"^(?:\(?\s*(?:visual(?:ly)?(?:\s+estimate[ds]?)?|eyeball(?:\s+estimate[ds]?)?|estimated?|"
        r"biplane|simpson(?:'s)?|teichholz|m[\-\s]?mode|auto[\-\s]?ef)\b\s*\)?[\.\;]?)",
        re.IGNORECASE,
    )

    @classmethod
    def _unwrap_and_split_statements(cls, text: str) -> List[str]:
        """
        Unwraps soft line breaks within sentences, clinical lists, and method qualifiers,
        while preserving boundaries between distinct list items, paragraphs, and table fields.
        """
        raw_lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
        if not raw_lines:
            return []

        merged_lines: List[str] = []
        for line in raw_lines:
            if not merged_lines:
                merged_lines.append(line)
                continue

            prev = merged_lines[-1]
            prev_ends_punct = bool(re.search(r"[.!?]\s*$", prev))
            is_prev_colon = prev.endswith(":") or prev.endswith("=")
            is_prev_connector = bool(
                re.search(
                    r"(?i)\b(?:is|was|are|with|of|between|from|to|at|and|or|estimated|approx\.?|approximately)\s*$",
                    prev,
                )
            )
            is_prev_lvef = bool(
                re.search(
                    r"(?i)\b(?:lvef|ef)(?=[0-9><=:~]|\b)|(?:ejection\s+fraction|lv\s+systolic\s+function|visually\s+estimated)\b",
                    prev,
                )
            )

            is_next_list_item = bool(cls.LIST_ITEM_PATTERN.match(line))
            is_next_field_label = bool(cls.FIELD_LABEL_PATTERN.match(line))
            is_next_method_modifier = bool(cls.METHOD_MODIFIER_PATTERN.match(line))
            is_next_paren = line.startswith("(") or line.startswith("[")
            is_next_numeric = bool(re.match(r"^[><~]?\s*[0-9]{2}\b", line))
            is_next_lowercase = line[0].islower() if line else False
            is_next_connector = bool(
                re.match(r"(?i)^(?:to|and|with|of|between|from|or|percent|%)\b", line)
            )

            # Determine whether 'line' is a wrapped continuation that should merge onto 'prev'
            should_merge = False

            if is_next_method_modifier or is_next_paren:
                # E.g. prev="LVEF 40%", line="(visual estimate)." or line="Visual estimate."
                should_merge = True
            elif is_prev_colon and not is_next_list_item:
                # E.g. prev="Visually estimated LVEF:", line="45-50%"
                should_merge = True
            elif is_prev_connector or is_next_connector or is_next_lowercase:
                # Syntactic continuation across line wrap
                should_merge = True
            elif is_prev_lvef and is_next_numeric and not is_next_list_item:
                # E.g. prev="Visually estimated LVEF", line="45-50%"
                should_merge = True
            elif not prev_ends_punct and not is_next_list_item and not is_next_field_label:
                # Soft line-wrapping without terminal punctuation
                should_merge = True

            if should_merge:
                merged_lines[-1] = f"{prev} {line}"
            else:
                merged_lines.append(line)

        # Split any merged lines that contain multiple sentences into individual statements
        statements: List[str] = []
        for m_line in merged_lines:
            sub_stmts = [
                s.strip()
                for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\-•*])", m_line)
                if s.strip()
            ]
            statements.extend(sub_stmts)

        return statements

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

        # Sort by method hierarchy (3D=1, 2D=2, VISUAL=3, UNSPECIFIED=4)
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

        # Split text into statements, unwrapping soft line breaks
        lines_or_sentences = self._unwrap_and_split_statements(text)

        for stmt in lines_or_sentences:
            stmt_lower = stmt.lower()

            # Check if line has LVEF / EF / Ejection Fraction context
            if not self._is_lvef_context(stmt_lower):
                continue

            # Strip reference / normal ranges (e.g. [N:53-75], (Normal: 53-75%))
            # so machine template values are never confused with patient measurements
            stmt_cleaned = self.REFERENCE_RANGE_BRACKETS.sub("", stmt)

            # Check for comparative sentence: "improved from 30% in 2022 to 55% today"
            comp_match = self.COMPARATIVE_PATTERN.search(stmt_cleaned)
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
                        method_rank=4,
                        section_name=section_name,
                        is_historical=True,
                        evidence_clause=stmt,
                    )
                )

                # The current value is current
                parsed_curr, mid_curr = self._parse_lvef_value(curr_val)
                method, rank = self._determine_method(
                    local_window=stmt_lower,
                    before_match=stmt_lower,
                    after_match="",
                    val_match_str=curr_val,
                    has_high="-" in curr_val or "to" in curr_val,
                )
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
            for m in self.LVEF_NUMERIC_PATTERN.finditer(stmt_cleaned):
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
                    if not (5 <= high_val <= 95):
                        continue
                    midpoint = round((low_val + high_val) / 2.0, 1)
                    raw_formatted = f"{int(low_val)}-{int(high_val)}%"
                else:
                    midpoint = low_val
                    raw_formatted = f"{prefix or ''}{int(low_val)}%"

                # Context around this specific match
                start_idx = max(0, m.start() - 50)
                end_idx = min(len(stmt_cleaned), m.end() + 50)
                local_window = stmt_cleaned[start_idx:end_idx]
                before_match = stmt_cleaned[start_idx:m.start()].lower()
                after_match = stmt_cleaned[m.end():end_idx].lower()

                # Discard match if preceded by normal / reference range tag (e.g. N: 53-75)
                if self.REFERENCE_RANGE_PREFIX.search(before_match):
                    continue

                # Discard match if followed by non-LVEF clinical units (cm2, mmhg, ml, etc.)
                if self.REJECTED_UNITS_PATTERN.match(after_match):
                    continue

                is_hist = self._is_historical(stmt, local_window, before_match, after_match)
                method, rank = self._determine_method(
                    local_window=local_window.lower(),
                    before_match=before_match,
                    after_match=after_match,
                    val_match_str=raw_match,
                    has_high=bool(high_str),
                )

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

    def _determine_method(
        self,
        local_window: str,
        before_match: str,
        after_match: str,
        val_match_str: str,
        has_high: bool,
    ) -> Tuple[str, int]:
        """
        Determines the acquisition method and assigns strict priority rank:
        1: 3D
        2: 2D (Biplane, Simpson, Teichholz, Auto-EF, 2D Quantitative)
        3: VISUAL (Eyeball, Estimated, Range without 2D/3D tag)
        4: UNSPECIFIED (Numeric without visual marker)
        """
        nearby = f"{before_match} {after_match}"

        # 1. Explicit 3D (Rank 1)
        if re.search(r"(?i)\b(?:3[\-\s]?d|tri[\-\s]?plane|3[\-\s]?d\s+(?:auto|simpson|volume|full))\b", nearby):
            return "3D", 1

        # 2. Explicit Visual / Eyeball / Estimated (Rank 3)
        # If explicitly marked as visual/estimated (e.g. "visually estimated lvef 45 to 50%"),
        # visual classification takes precedence even if the broader sentence mentioned 2D Echo.
        if re.search(r"(?i)\b(?:visual(?:ly)?|eyeball|estimated?|semi[\-\s]?quantitative)\b", nearby):
            return "VISUAL", 3

        # 3. Explicit 2D Biplane / Simpson / Auto-EF (Rank 2)
        if re.search(r"(?i)\b(?:biplane|simpson(?:'s)?|modified\s+simpson|method\s+of\s+discs|auto[\-\s]?ef)\b", nearby):
            return "2D_BIPLANE", 2

        # 4. Explicit 2D Teichholz / M-mode (Rank 2)
        if re.search(r"(?i)\b(?:teich(?:holz)?|m[\-\s]?mode)\b", nearby):
            return "2D_TEICHHOLZ", 2

        # 5. Explicit 2D Quantitative directly preceding LVEF (Rank 2)
        if re.search(r"(?i)\b(?:2[\-\s]?d(?:\s*lvef|\s*ef)?|quantitative)\b", before_match):
            return "2D", 2

        # 6. Any range without 2D/3D tag is clinically an estimated visual range (Rank 3)
        if has_high or re.search(r"[0-9]{2}\s*(?:[\-–—]|(?:\s*(?:to|and)\s*))\s*[0-9]{2}", val_match_str):
            return "VISUAL", 3

        # 7. Unspecified numeric value (Rank 4)
        return "UNSPECIFIED", 4

    def _is_historical(
        self, full_stmt: str, local_window: str, before_match: str = "", after_match: str = ""
    ) -> bool:
        """
        Returns True if the candidate is attributed to a prior historical examination.
        """
        nearby = f"{before_match} {after_match}" if before_match or after_match else local_window
        for pat in self.HISTORICAL_TERMS:
            if pat.search(nearby):
                return True
        return False

    def _is_lvef_context(self, text_lower: str) -> bool:
        # Exclude explicit non-ventricular valve area statements that don't mention EF
        if re.search(r"(?i)\b(?:ava|mva|tva|pva|aortic\s+valve\s+area|mitral\s+valve\s+area|planimetry)\b", text_lower):
            if not re.search(r"(?i)\b(?:lvef|ef)(?=[0-9><=:~]|\b)|(?:ejection\s+fraction|systolic\s+function)\b", text_lower):
                return False

        return bool(
            re.search(r"(?i)\b(?:lvef|ef)(?=[0-9><=:~]|\b)|(?:ejection\s+fraction|systolic\s+function|lv\s+function)\b", text_lower)
            or "biplane" in text_lower
            or "simpson" in text_lower
            or "teich" in text_lower
            or re.search(r"(?i)\b3[\-\s]?d\s+(?:lvef|ef|ejection|volume|volumes|auto|full|quantification)\b", text_lower)
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
