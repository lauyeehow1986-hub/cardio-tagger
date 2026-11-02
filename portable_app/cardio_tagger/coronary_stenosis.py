"""
Coronary Vessel Stenosis and Lesion Severity Extractor.
Extracts fine-grained vessel stenosis percentages and qualitative lesion descriptors
across native coronary territories (LMCA, LAD, LCX, RCA) and bypass grafts,
structured independently for both Conclusion and Diagnostic Findings scopes.
"""
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Set


@dataclass
class CoronaryStenosisResult:
    conclusion_lmca_stenosis: str = ""
    conclusion_lad_stenosis: str = ""
    conclusion_lcx_stenosis: str = ""
    conclusion_rca_stenosis: str = ""
    conclusion_graft_stenosis: str = ""
    findings_lmca_stenosis: str = ""
    findings_lad_stenosis: str = ""
    findings_lcx_stenosis: str = ""
    findings_rca_stenosis: str = ""
    findings_graft_stenosis: str = ""


class CoronaryStenosisExtractor:
    """
    Deterministic, layout-aware clinical parser for coronary vessel stenosis
    and lesion descriptions in catheterization, angiogram, and intervention notes.
    """

    # Territory mappings: (Canonical territory, Regex pattern matching vessel/segment)
    TERRITORIES = [
        ("GRAFT", re.compile(r"(?i)\b(?:LIMA|RIMA|SVG|saphenous\s+vein\s+graft|internal\s+mammary|BIMA)\b")),
        ("LMCA", re.compile(r"(?i)\b(?:LMCA|left\s+main(?:\s+coronary(?:\s+artery)?)?|left\s+main\s+stem|LMS|LM)\b")),
        ("LAD", re.compile(r"(?i)\b(?:LAD|left\s+anterior\s+descending|D[1-3]?|diagonal(?:\s+[1-3])?|ramus(?:\s+intermedius)?|RI)\b")),
        ("LCX", re.compile(r"(?i)\b(?:LCx|LCX|left\s+circumflex|circumflex|circ\b|OM[1-3]?|obtuse\s+marginal(?:\s+[1-3])?|LPL[1-2]?|left\s+posterolateral)\b")),
        ("RCA", re.compile(r"(?i)\b(?:RCA|right\s+coronary(?:\s+artery)?|PDA|RPDA|posterior\s+descending(?:\s+artery)?|RPL[1-3]?|PLV|PLB|posterolateral(?:\s+branch)?|AM[1-2]?|acute\s+marginal)\b")),
    ]

    MODIFIER_PATTERN = r"(?:small|large|dominant|non[\-\s]?dominant|hypoplastic|ectatic|tortuous|proximal|prox|mid|distal|ostial|apical|shaft|bifurcation)"

    # Combined vessel pattern allowing preceding or trailing modifiers
    VESSEL_NAME_PATTERN = re.compile(
        r"(?i)\b(?P<vessel>"
        r"(?:" + MODIFIER_PATTERN + r"[\t \-]+)*"
        r"(?:"
        r"LIMA(?:\s+to\s+[a-z0-9\-]+)?|RIMA(?:\s+to\s+[a-z0-9\-]+)?|SVG(?:\s+to\s+[a-z0-9\-]+)?|"
        r"LMCA|left\s+main(?:\s+coronary(?:\s+artery)?)?|left\s+main\s+stem|LMS|LM|"
        r"LAD|left\s+anterior\s+descending|D[1-3]?|diagonal(?:\s+[1-3])?|ramus(?:\s+intermedius)?|RI|"
        r"LCx|LCX|left\s+circumflex|circumflex|OM[1-3]?|obtuse\s+marginal(?:\s+[1-3])?|LPL[1-2]?|"
        r"RCA|right\s+coronary(?:\s+artery)?|PDA|RPDA|posterior\s+descending(?:\s+artery)?|RPL[1-3]?|PLV|PLB|posterolateral(?:\s+branch)?|AM[1-2]?|acute\s+marginal"
        r")"
        r"(?:[\t \-]+" + MODIFIER_PATTERN + r")*"
        r")\b"
    )

    # Stenosis / Severity patterns
    PCT_PATTERN = r"(?:(?:~|approx(?:imately)?\s*|[><]=?\s*|up\s+to\s*)?[0-9]{1,3}\s*(?:-|to|\/)\s*[0-9]{1,3}\s*%|[0-9]{1,3}\s*%)"
    OCCL_PATTERN = r"(?:100%\s*(?:CTO|chronic\s+total\s+occlusion|total\s+occlusion|occlusion|occluded)|total(?:ly)?\s+occlu(?:ded|sion)|chronic\s+total\s+occlusion|CTO|subtotal(?:ly)?\s+occlu(?:ded|sion)|99%\s*(?:critical|stenosis)?)"
    STENT_PATTERN = r"(?:patent\s+stent|stent\s+is\s+patent|patent\s+des|patent|in[\-\s]?stent\s+restenosis|isr)"
    QUAL_PATTERN = r"(?:severe\s+(?:stenosis|disease|narrowing|lesion)|moderate\s+(?:stenosis|disease|narrowing|lesion)|mild\s+(?:stenosis|disease|narrowing|lesion|plaque)|normal|no\s+(?:significant\s+)?stenosis)"

    ALL_STENOSIS_PATTERN = re.compile(
        rf"(?i)(?P<stenosis>{OCCL_PATTERN}|{PCT_PATTERN}|{STENT_PATTERN}|{QUAL_PATTERN})"
    )

    def extract(self, conclusion_text: str = "", findings_text: str = "") -> CoronaryStenosisResult:
        """
        Extracts stenosis findings for both Conclusion and Diagnostic Findings scopes.
        """
        c_map = self._extract_scope(conclusion_text, is_conclusion=True)
        f_map = self._extract_scope(findings_text, is_conclusion=False)

        return CoronaryStenosisResult(
            conclusion_lmca_stenosis="; ".join(c_map["LMCA"]),
            conclusion_lad_stenosis="; ".join(c_map["LAD"]),
            conclusion_lcx_stenosis="; ".join(c_map["LCX"]),
            conclusion_rca_stenosis="; ".join(c_map["RCA"]),
            conclusion_graft_stenosis="; ".join(c_map["GRAFT"]),
            findings_lmca_stenosis="; ".join(f_map["LMCA"]),
            findings_lad_stenosis="; ".join(f_map["LAD"]),
            findings_lcx_stenosis="; ".join(f_map["LCX"]),
            findings_rca_stenosis="; ".join(f_map["RCA"]),
            findings_graft_stenosis="; ".join(f_map["GRAFT"]),
        )

    def _determine_territory(self, vessel_str: str) -> str:
        for territory, pat in self.TERRITORIES:
            if pat.search(vessel_str):
                return territory
        return "OTHER"

    def _normalize_stenosis_desc(self, stenosis_raw: str) -> str:
        s = stenosis_raw.strip().upper()
        s = re.sub(r"\s+", " ", s)
        if re.match(r"(?i)^severe(?:\s+disease|\s+narrowing|\s+lesion)?$", s):
            return "SEVERE STENOSIS"
        if re.match(r"(?i)^moderate(?:\s+disease|\s+narrowing|\s+lesion)?$", s):
            return "MODERATE STENOSIS"
        if re.match(r"(?i)^mild(?:\s+disease|\s+narrowing|\s+lesion|\s+plaque)?$", s):
            return "MILD STENOSIS"
        if re.search(r"(?i)total\s+occlusion|totally\s+occluded", s):
            if "100%" not in s and "SUBTOTAL" not in s:
                return "TOTAL OCCLUSION"
        return s

    def _extract_scope(self, text: str, is_conclusion: bool) -> Dict[str, List[str]]:
        results: Dict[str, List[str]] = {
            "LMCA": [],
            "LAD": [],
            "LCX": [],
            "RCA": [],
            "GRAFT": [],
        }
        if not text:
            return results

        lines = [l.strip() for l in re.split(r"[\r\n;]+", text) if l.strip()]
        seen_entries: Set[Tuple[str, str]] = set()

        for l in lines:
            l_clean = re.sub(r"^\s*[0-9]+[\.\)]\s*", "", l)
            sub_chunks = [sc.strip() for sc in re.split(r"\.\s+", l_clean) if sc.strip()]
            for chunk in sub_chunks:
                # 1. Header check: e.g. "LAD: 80% proximal stenosis, 50% mid lesion." or "LMCA: Normal."
                m_head = re.match(
                    r"(?i)^\s*(?P<vessel>LMCA|LEFT MAIN|LMS|LM|LAD|LEFT ANTERIOR DESCENDING|LCX|LEFT CIRCUMFLEX|CIRCUMFLEX|RCA|RIGHT CORONARY|SVG(?:\s+to\s+[a-z0-9\-]+)?|LIMA(?:\s+to\s+[a-z0-9\-]+)?)[\t ]*[:\-]\s*(?P<rest>.*)",
                    chunk,
                )
                if m_head:
                    base_v = m_head.group("vessel").strip().upper()
                    terr = self._determine_territory(base_v)
                    rest = m_head.group("rest")
                    clauses = [c.strip() for c in re.split(r"[,;]+", rest) if c.strip()]
                    for cl in clauses:
                        if re.search(r"(?i)\b(?:normal|no\s+(?:significant\s+)?stenosis)\b", cl):
                            entry = f"{base_v}: NORMAL"
                            if (terr, entry) not in seen_entries:
                                seen_entries.add((terr, entry))
                                results[terr].append(entry)
                            continue
                        m_st = self.ALL_STENOSIS_PATTERN.search(cl)
                        if m_st:
                            st_val = self._normalize_stenosis_desc(m_st.group("stenosis"))
                            m_mod = re.search(r"(?i)\b(" + self.MODIFIER_PATTERN + r")\b", cl)
                            mod_prefix = f"{m_mod.group(1).upper()} " if m_mod else ""
                            entry = f"{mod_prefix}{base_v}: {st_val}"
                            if (terr, entry) not in seen_entries:
                                seen_entries.add((terr, entry))
                                results[terr].append(entry)
                    continue

                # 2. Prose check
                has_success_pci = bool(re.search(r"(?i)\b(?:successful\s+(?:primary\s+)?pci|stent(?:ed)?\s+with|des\s+to)\b", chunk))
                is_residual = bool(re.search(r"(?i)\b(?:residual|staged|subsequent|pending|untreated)\b", chunk))

                # Pattern A: Vessel then Stenosis
                v_matches = list(self.VESSEL_NAME_PATTERN.finditer(chunk))
                for i, vm in enumerate(v_matches):
                    v_str = vm.group("vessel").strip().upper()
                    terr = self._determine_territory(v_str)
                    if terr == "OTHER":
                        continue
                    if is_conclusion and has_success_pci and not is_residual:
                        if re.search(r"(?i)\b(?:pci|stent|des)\s+(?:to|in|with)\s+.*?" + re.escape(v_str), chunk):
                            continue
                    start_tail = vm.end()
                    end_tail = v_matches[i + 1].start() if i + 1 < len(v_matches) else len(chunk)
                    tail = chunk[start_tail:end_tail]
                    m_st = self.ALL_STENOSIS_PATTERN.search(tail)
                    if m_st:
                        st_val = self._normalize_stenosis_desc(m_st.group("stenosis"))
                        entry = f"{v_str}: {st_val}"
                        if (terr, entry) not in seen_entries:
                            seen_entries.add((terr, entry))
                            results[terr].append(entry)

                # Pattern B: Stenosis then preposition (of/in/to/at/involving) then Vessel
                for st_m in self.ALL_STENOSIS_PATTERN.finditer(chunk):
                    st_val = self._normalize_stenosis_desc(st_m.group("stenosis"))
                    tail = chunk[st_m.end(): st_m.end() + 50]
                    m_prep = re.match(r"^\s*(?:of|in|to|at|involving)\s+(?P<after>.*)", tail, re.I)
                    if m_prep:
                        after_text = m_prep.group("after")
                        m_v = self.VESSEL_NAME_PATTERN.search(after_text)
                        if m_v:
                            v_str = m_v.group("vessel").strip().upper()
                            terr = self._determine_territory(v_str)
                            if terr != "OTHER":
                                entry = f"{v_str}: {st_val}"
                                if (terr, entry) not in seen_entries:
                                    seen_entries.add((terr, entry))
                                    results[terr].append(entry)

        return results
