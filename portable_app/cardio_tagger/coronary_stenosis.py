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
    Standardizes spelled-out vessel names and ordinals to clean clinical acronyms
    (e.g., PROXIMAL LAD, MID LAD, D1, OM1, RPL1, PDA, LMCA) and normalizes qualitative
    and comparison percentage modifiers.
    """

    ORDINAL_MAP = {
        "FIRST": "1",
        "1ST": "1",
        "SECOND": "2",
        "2ND": "2",
        "THIRD": "3",
        "3RD": "3",
        "FOURTH": "4",
        "4TH": "4",
    }

    MODIFIERS = r"(?:small|large|dominant|non[\-\s]?dominant|hypoplastic|ectatic|tortuous|proximal|prox|mid|distal|ostial|apical|shaft|bifurcation)"

    GRAFT_TARGET = (
        r"(?:"
        r"(?:(?:first|1st|second|2nd|third|3rd)\s+)?(?:diagonal(?:\s+[1-3])?|D[1-3]|obtuse\s+marginal(?:\s+[1-3])?|OM[1-3]?|posterolateral(?:\s+branch)?|rpl[1-3]?|lpl[1-2]?|plb[1-2]?|plv|acute\s+marginal(?:\s+[1-2])?|am[1-2]?|posterior\s+descending|pda|rpda|ramus(?:\s+intermedius)?|ri|left\s+anterior\s+descending|lad|left\s+circumflex|circumflex|circ\b|lcx|right\s+coronary|rca)"
        r"(?:\s+coronary)?(?:\s+(?:artery|branch|vessel))?"
        r")"
    )

    VESSEL_CORE = (
        r"(?:"
        rf"(?:LIMA|RIMA|SVG|saphenous\s+vein(?:\s+graft)?|left\s+internal\s+mammary(?:\s+artery)?|right\s+internal\s+mammary(?:\s+artery)?|BIMA)(?:\s+to\s+{GRAFT_TARGET})?|"
        r"(?:(?:first|1st|second|2nd|third|3rd)\s+)?(?:diagonal(?:\s+[1-3])?|D[1-3])(?:\s+coronary)?(?:\s+(?:artery|branch|vessel))?|"
        r"(?:(?:first|1st|second|2nd|third|3rd)\s+)?(?:obtuse\s+marginal(?:\s+[1-3])?|OM[1-3]?)(?:\s+coronary)?(?:\s+(?:artery|branch|vessel))?|"
        r"(?:(?:first|1st|second|2nd)\s+)?(?:posterolateral(?:\s+branch)?|rpl[1-3]?|lpl[1-2]?|plb[1-2]?|plv)(?:\s+coronary)?(?:\s+(?:artery|branch|vessel))?|"
        r"(?:(?:first|1st)\s+)?(?:acute\s+marginal(?:\s+[1-2])?|am[1-2]?)(?:\s+(?:artery|branch))?|"
        r"(?:posterior\s+descending|pda|rpda)(?:\s+coronary)?(?:\s+(?:artery|branch))?|"
        r"(?:ramus(?:\s+intermedius)?|ri)(?:\s+coronary)?(?:\s+(?:artery|branch))?|"
        r"(?:left\s+anterior\s+descending|lad)(?:\s+coronary)?(?:\s+(?:artery|branch))?|"
        r"(?:left\s+circumflex|circumflex|circ\b|lcx)(?:\s+coronary)?(?:\s+(?:artery|branch))?|"
        r"(?:right\s+coronary|rca)(?:\s+coronary)?(?:\s+(?:artery|branch))?|"
        r"(?:left\s+main(?:\s+coronary)?(?:\s+artery|\s+stem)?|lmca|lms|lm)"
        r")"
    )

    VESSEL_NAME_PATTERN = re.compile(
        rf"(?i)\b(?P<vessel>(?:the\s+)?(?:(?:ostium|origin)\s+of\s+(?:the\s+)?)?(?:{MODIFIERS}[\s\-]+)*(?:{VESSEL_CORE})(?:[\s\-]+{MODIFIERS})*)\b"
    )

    QUAL_PREFIX = r"(?:non[\-\s]flow[\-\s]limiting|non[\-\s]significant|mild(?:[\-\s]to[\-\s]moderate)?|moderate(?:[\-\s]to[\-\s]severe)?|severe|critical)"
    PCT_BODY = r"(?:(?:less\s+than\s*|greater\s+than\s*|[<>~]=?\s*|approx(?:imately)?\.?\s*|up\s+to\s*)?[0-9]{1,3}(?:\s*(?:-|to|\/)\s*[0-9]{1,3})?\s*%)"
    OCCL_PATTERN = r"(?:100%\s*(?:CTO|chronic\s+total\s+occlusion|total\s+occlusion|occlusion|occluded)|total(?:ly)?\s+occlu(?:ded|sion)|chronic\s+total\s+occlusion|CTO|subtotal(?:ly)?\s+occlu(?:ded|sion)|99%\s*(?:critical|stenosis)?)"
    STENT_PATTERN = r"(?:patent\s+stent|stent\s+is\s+patent|patent\s+des|patent|in[\-\s]?stent\s+restenosis|isr)"
    STANDALONE_QUAL = r"(?:severe\s+(?:stenosis|disease|narrowing|lesion)|moderate\s+(?:stenosis|disease|narrowing|lesion)|mild\s+(?:stenosis|disease|narrowing|lesion|plaque))"
    ZERO_STENOSIS_PATTERN = (
        r"(?:(?:angiographically\s+)?normal(?!\s+(?:anterograde\s+)?flow)(?:\s+coronar(?:y|ies))?|"
        r"without\s+(?:significant\s+)?(?:stenosis|disease|narrowing|lesion)|"
        r"no\s+(?:significant\s+)?(?:stenosis|disease|narrowing|lesion)|"
        r"free\s+of\s+(?:(?:in[\-\s]?stent\s+)?restenosis|disease|stenosis)|"
        r"no\s+(?:in[\-\s]?stent\s+)?restenosis|"
        r"without\s+(?:in[\-\s]?stent\s+)?restenosis)"
    )

    ALL_STENOSIS_PATTERN = re.compile(
        rf"(?i)(?P<stenosis>"
        rf"{OCCL_PATTERN}|"
        rf"{STENT_PATTERN}|"
        rf"(?:{QUAL_PREFIX}\s*(?:\(\s*{PCT_BODY}(?:\s+stenosis)?\s*\)|\s+{PCT_BODY}))|"
        rf"(?:\(\s*{PCT_BODY}(?:\s+stenosis)?\s*\))|"
        rf"{PCT_BODY}|"
        rf"{STANDALONE_QUAL}|"
        rf"{ZERO_STENOSIS_PATTERN}"
        rf")"
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

    def _normalize_pct_str(self, p: str) -> str:
        p = p.strip()
        p = re.sub(r"(?i)\bless\s+than\s*", "<", p)
        p = re.sub(r"(?i)\bgreater\s+than\s*", ">", p)
        p = re.sub(r"(?i)\bapprox(?:imately)?\.?\s*", "APPROX ", p)
        p = re.sub(r"\s+", " ", p)
        p = re.sub(r"<\s+", "<", p)
        p = re.sub(r">\s+", ">", p)
        p = re.sub(r"\s*%\s*", "%", p)
        return p.upper()

    def _normalize_stenosis_desc(self, s_raw: str) -> str:
        s = s_raw.strip().upper()
        s = re.sub(r"\s+", " ", s)
        if re.search(rf"(?i)\b{self.ZERO_STENOSIS_PATTERN}\b", s):
            return "0%"
        if re.search(r"(?i)total\s+occlusion|totally\s+occluded", s):
            if "100%" not in s and "SUBTOTAL" not in s:
                return "TOTAL OCCLUSION"
        if re.search(r"(?i)\bpatent\b", s):
            if "STENT" in s or "DES" in s:
                return "PATENT STENT"
            return "PATENT"
        if re.match(r"(?i)^severe(?:\s+disease|\s+narrowing|\s+lesion)?$", s):
            return "SEVERE STENOSIS"
        if re.match(r"(?i)^moderate(?:\s+disease|\s+narrowing|\s+lesion)?$", s):
            return "MODERATE STENOSIS"
        if re.match(r"(?i)^mild(?:\s+disease|\s+narrowing|\s+lesion|\s+plaque)?$", s):
            return "MILD STENOSIS"

        m_complex = re.match(
            rf"(?i)^(?P<qual>{self.QUAL_PREFIX})\s*(?:\(\s*(?P<in_paren>{self.PCT_BODY})(?:\s+stenosis)?\s*\)|\s*(?P<plain_pct>{self.PCT_BODY}))(?:\s+stenosis)?$",
            s,
        )
        if m_complex:
            qual = m_complex.group("qual").upper()
            qual = re.sub(r"\s+", " ", qual)
            pct = m_complex.group("in_paren") or m_complex.group("plain_pct")
            norm_pct = self._normalize_pct_str(pct)
            return f"{qual} ({norm_pct})"

        m_paren = re.match(rf"(?i)^\(\s*(?P<in_paren>{self.PCT_BODY})(?:\s+stenosis)?\s*\)$", s)
        if m_paren:
            return self._normalize_pct_str(m_paren.group("in_paren"))

        m_pct = re.match(rf"(?i)^(?P<pct>{self.PCT_BODY})$", s)
        if m_pct:
            return self._normalize_pct_str(m_pct.group("pct"))

        return s

    def standardize_vessel(self, raw_v: str) -> Tuple[str, str]:
        """
        Normalizes any spelled-out vessel name, ordinal, or segment to a clean
        clinical standard representation: (Territory, Standardized Acronym).
        """
        v = raw_v.strip().upper()
        v = re.sub(r"^(?:THE|A|AN)\s+", "", v)
        v = re.sub(r"\s+(?:CORONARY\s+)?(?:ARTERY|BRANCH|VESSEL)$", "", v)
        v = re.sub(r"\s*-\s*", " ", v)
        v = re.sub(r"^(?:THE\s+)?(?:OSTIUM|ORIGIN)\s+OF\s+(?:THE\s+)?", "OSTIAL ", v)

        # Grafts
        m_graft = re.match(
            r"^(?P<graft_type>LIMA|RIMA|SVG|BIMA|SAPHENOUS\s+VEIN(?:\s+GRAFT)?|LEFT\s+INTERNAL\s+MAMMARY(?:\s+ARTERY)?|RIGHT\s+INTERNAL\s+MAMMARY(?:\s+ARTERY)?)(?:\s+TO\s+(?P<target>.*))?$",
            v,
        )
        if m_graft:
            g_type = m_graft.group("graft_type")
            if "SAPHENOUS" in g_type:
                g_type = "SVG"
            elif "LEFT INTERNAL" in g_type:
                g_type = "LIMA"
            elif "RIGHT INTERNAL" in g_type:
                g_type = "RIMA"
            target = m_graft.group("target")
            if target:
                _, target_std = self.standardize_vessel(target)
                return "GRAFT", f"{g_type} TO {target_std}"
            return "GRAFT", g_type

        # Extract leading modifiers
        mods = []
        mod_reg = r"^(?:(PROXIMAL|PROX|MID|DISTAL|OSTIAL|APICAL|SMALL|LARGE|DOMINANT|NON[\s\-]?DOMINANT|ECTATIC|TORTUOUS)\s+)"
        while True:
            m_mod = re.match(mod_reg, v)
            if m_mod:
                m_val = m_mod.group(1).upper()
                if m_val == "PROX":
                    m_val = "PROXIMAL"
                elif m_val.startswith("NON"):
                    m_val = "NON-DOMINANT"
                mods.append(m_val)
                v = v[m_mod.end():].strip()
            else:
                break

        prefix = " ".join(mods) + (" " if mods else "")

        # Specific branches
        m_diag = re.search(r"\b(?:(FIRST|1ST|SECOND|2ND|THIRD|3RD)\s+)?DIAGONAL(?:\s*([1-3]))?\b|\bD([1-3])\b", v)
        if m_diag:
            num = m_diag.group(2) or m_diag.group(3)
            if not num and m_diag.group(1):
                num = self.ORDINAL_MAP.get(m_diag.group(1), "1")
            num_str = num if num else "1"
            return "LAD", f"{prefix}D{num_str}".strip()

        m_om = re.search(r"\b(?:(FIRST|1ST|SECOND|2ND|THIRD|3RD)\s+)?(?:OBTUSE\s+MARGINAL|OM)(?:\s*([1-3]))?\b|\bOM([1-3])\b", v)
        if m_om:
            num = m_om.group(2) or m_om.group(3)
            if not num and m_om.group(1):
                num = self.ORDINAL_MAP.get(m_om.group(1), "1")
            num_str = num if num else "1"
            return "LCX", f"{prefix}OM{num_str}".strip()

        m_pl = re.search(r"\b(?:(FIRST|1ST|SECOND|2ND)\s+)?(?:POSTEROLATERAL|PLB|PLV|RPL)(?:\s*([1-3]))?\b|\bRPL([1-3])\b", v)
        if m_pl:
            num = m_pl.group(2) or m_pl.group(3)
            if not num and m_pl.group(1):
                num = self.ORDINAL_MAP.get(m_pl.group(1), "1")
            num_str = num if num else "1"
            return "RCA", f"{prefix}RPL{num_str}".strip()

        if re.search(r"\b(?:PDA|RPDA|POSTERIOR\s+DESCENDING)\b", v):
            return "RCA", f"{prefix}PDA".strip()

        if re.search(r"\b(?:LAD|LEFT\s+ANTERIOR\s+DESCENDING)\b", v):
            return "LAD", f"{prefix}LAD".strip()

        if re.search(r"\b(?:LCX|LEFT\s+CIRCUMFLEX|CIRCUMFLEX|CIRC)\b", v):
            return "LCX", f"{prefix}LCX".strip()

        if re.search(r"\b(?:RCA|RIGHT(?:\s+CORONARY)?)\b", v):
            return "RCA", f"{prefix}RCA".strip()

        if re.search(r"\b(?:LMCA|LEFT\s+MAIN|LMS|LM)\b", v):
            base_lm = "LMCA" if "LMCA" in v or "LMS" in v else "LEFT MAIN"
            return "LMCA", f"{prefix}{base_lm}".strip()

        return "OTHER", f"{prefix}{v}".strip()

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
            sub_chunks = [
                sc.strip()
                for sc in re.split(r"(?<!\bapprox)(?<!\best)(?<!\bdr)(?<!\bmr)\.\s+", l_clean, flags=re.I)
                if sc.strip()
            ]
            for chunk in sub_chunks:
                # 1. Header check: e.g. "LAD: 80% proximal stenosis, 50% mid lesion." or "LMCA: Normal."
                m_head = re.match(
                    r"(?i)^\s*(?P<vessel>LMCA|LEFT MAIN|LMS|LM|LAD|LEFT ANTERIOR DESCENDING|LCX|LEFT CIRCUMFLEX|CIRCUMFLEX|RCA|RIGHT CORONARY|SVG(?:\s+to\s+[a-z0-9\-\s]+)?|LIMA(?:\s+to\s+[a-z0-9\-\s]+)?)[\t ]*[:\-]\s*(?P<rest>.*)",
                    chunk,
                )
                if m_head:
                    raw_v = m_head.group("vessel").strip()
                    terr, base_v = self.standardize_vessel(raw_v)
                    rest = m_head.group("rest")
                    clauses = [c.strip() for c in re.split(r"[,;]+", rest) if c.strip()]
                    for cl in clauses:
                        if re.search(rf"(?i)\b{self.ZERO_STENOSIS_PATTERN}\b", cl):
                            if not re.search(r"(?i)\b(?:flow|timi)\b", cl):
                                entry = f"{base_v}: 0%"
                                if (terr, entry) not in seen_entries:
                                    seen_entries.add((terr, entry))
                                    results[terr].append(entry)
                            continue
                        m_st = self.ALL_STENOSIS_PATTERN.search(cl)
                        if m_st:
                            st_val = self._normalize_stenosis_desc(m_st.group("stenosis"))
                            m_mod = re.search(r"(?i)\b(" + self.MODIFIERS + r")\b", cl)
                            mod_prefix = f"{m_mod.group(1).upper()} " if m_mod else ""
                            if mod_prefix == "PROX ":
                                mod_prefix = "PROXIMAL "
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
                claimed_stenoses = set()
                for i, vm in enumerate(v_matches):
                    raw_v = vm.group("vessel").strip()
                    terr, v_std = self.standardize_vessel(raw_v)
                    if terr == "OTHER":
                        continue
                    if is_conclusion and has_success_pci and not is_residual:
                        if re.search(r"(?i)\b(?:pci|stent|des)\s+(?:to|in|with)\s+.*?" + re.escape(raw_v), chunk):
                            continue
                    start_tail = vm.end()
                    end_tail = v_matches[i + 1].start() if i + 1 < len(v_matches) else len(chunk)
                    tail = chunk[start_tail:end_tail]

                    m_st = self.ALL_STENOSIS_PATTERN.search(tail)
                    if m_st:
                        claimed_stenoses.add(start_tail + m_st.start())
                        st_val = self._normalize_stenosis_desc(m_st.group("stenosis"))
                        entry = f"{v_std}: {st_val}"
                        if (terr, entry) not in seen_entries:
                            seen_entries.add((terr, entry))
                            results[terr].append(entry)

                # Pattern B: Stenosis then preposition (of/in/to/at) then Vessel
                for st_m in self.ALL_STENOSIS_PATTERN.finditer(chunk):
                    if st_m.start() in claimed_stenoses:
                        continue
                    st_val = self._normalize_stenosis_desc(st_m.group("stenosis"))
                    tail = chunk[st_m.end(): st_m.end() + 60]
                    m_prep = re.match(r"^\s*(?:(?:of|in|to|at)\s+)?(?P<after>.*)", tail, re.I)
                    if m_prep:
                        after_text = m_prep.group("after")
                        m_v = self.VESSEL_NAME_PATTERN.search(after_text)
                        if m_v:
                            raw_v = m_v.group("vessel").strip()
                            terr, v_std = self.standardize_vessel(raw_v)
                            if terr != "OTHER":
                                entry = f"{v_std}: {st_val}"
                                if (terr, entry) not in seen_entries:
                                    seen_entries.add((terr, entry))
                                    results[terr].append(entry)

        # Clean redundant patent entries if explicit percentage or 0% exists for that vessel
        cleaned_results: Dict[str, List[str]] = {}
        for terr, entries in results.items():
            pct_vessels = {e.split(": ", 1)[0] for e in entries if ": " in e and "%" in e.split(": ", 1)[1]}
            cleaned_results[terr] = [
                e for e in entries
                if not (": " in e and e.split(": ", 1)[1] in ("PATENT", "PATENT STENT") and e.split(": ", 1)[0] in pct_vessels)
            ]
        return cleaned_results
