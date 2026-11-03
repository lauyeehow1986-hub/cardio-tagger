"""
High-Precision PCI Intervention & Device Extractor.
Extracts target vessel interventions, granular device categories, procedural success,
and post-PCI residual stenosis with strict boundary isolation from pre-PCI diagnostic findings.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class PCIInterventionResult:
    intervened_vessels: str = ""
    lmca_residual_stenosis: str = ""
    lad_residual_stenosis: str = ""
    lcx_residual_stenosis: str = ""
    rca_residual_stenosis: str = ""
    graft_residual_stenosis: str = ""
    success_status: str = ""
    devices_used: str = ""


class PCIInterventionExtractor:
    """
    Parses PCI INTERVENTION clinical sections.
    Standardizes vessels across 5 territories, extracts granular devices with full specs,
    records procedural outcomes, and isolates residual stenosis percentages without defaulting.
    """

    ORDINAL_MAP = {
        "FIRST": "1",
        "1ST": "1",
        "SECOND": "2",
        "2ND": "2",
        "THIRD": "3",
        "3RD": "3",
    }

    # Vessel header regex matching vessels on their own line or before a colon
    VESSEL_HEADER_PATTERN = re.compile(
        r"(?i)^\s*(?:[0-9]+[\.\)]\s*)?(?:(?:target\s+vessel|vessel|lesion)[\s:=]+)?"
        r"(?P<vessel>"
        r"(?:SVG|LIMA|RIMA|BIMA|SAPHENOUS\s+VEIN(?:\s+GRAFT)?)\s+TO\s+[A-Z0-9\-\s/]+|"
        r"(?:PROXIMAL|PROX|MID|DISTAL|OSTIAL)?[\t \-]*"
        r"(?:LMCA|LEFT\s+MAIN(?:\s+STEM)?|LMS|LM|"
        r"LAD|LEFT\s+ANTERIOR\s+DESCENDING|"
        r"LCX|LEFT\s+CIRCUMFLEX|CIRCUMFLEX|CIRC\b|"
        r"RCA|RIGHT\s+CORONARY(?:\s+ARTERY)?|"
        r"RPAV|RPDA|PDA|RPDA|PLV|PLB|RPL[1-3]?|LPL[1-2]?|AM[1-2]?|"
        r"(?:FIRST|1ST|SECOND|2ND|THIRD|3RD)?\s*(?:DIAGONAL(?:\s+[1-3])?|D[1-3])|"
        r"(?:FIRST|1ST|SECOND|2ND|THIRD|3RD)?\s*(?:OBTUSE\s+MARGINAL(?:\s+[1-3])?|OM[1-3])|"
        r"RAMUS(?:\s+INTERMEDIUS)?|RI\b)"
        r")"
        r"[\t ]*(?:[:\-—]|$)",
        flags=re.M,
    )

    RESIDUAL_PATTERN = re.compile(
        r"(?i)\bresidual(?:\s+stenosis)?\s*[:\-\s]*"
        r"(?P<val>[<>]?\s*[0-9]{1,3}(?:\s*(?:-|to)\s*[0-9]{1,3})?\s*%)"
    )

    OUTCOME_PATTERNS = [
        (re.compile(r"(?i)\bsuccessful\s+(?:angioplasty|stenting|pci|procedure|revascularization)\b"), "SUCCESSFUL ANGIOPLASTY"),
        (re.compile(r"(?i)\bsuboptimal\s+(?:result|angioplasty|stenting|outcome)\b"), "SUBOPTIMAL RESULT"),
        (re.compile(r"(?i)\bunsuccessful(?:\s+angioplasty|\s+stenting|\s+pci)?\b"), "UNSUCCESSFUL"),
        (re.compile(r"(?i)\b(?:aborted|procedure\s+aborted)\b"), "ABORTED"),
        (re.compile(r"(?i)\b(?:coronary\s+)?perforation\b"), "COMPLICATION: PERFORATION"),
        (re.compile(r"(?i)\b(?:coronary\s+)?dissection\b"), "COMPLICATION: DISSECTION"),
        (re.compile(r"(?i)\bfailure\s+to\s+(?:cross|dilate|deliver)\b"), "UNSUCCESSFUL: FAILURE TO CROSS"),
    ]

    DEVICE_TAGS = [
        # 1. Granular Physiology & Imaging
        (re.compile(r"(?i)\b(?:IVUS|intravascular\s+ultrasound|opticross|eagle\s+eye|polaris)\b"), "IVUS"),
        (re.compile(r"(?i)\b(?:OCT|optical\s+coherence(?:\s+tomography)?|dragonfly|ofdi)\b"), "OCT"),
        (re.compile(r"(?i)\b(?:FFR|iFR|RFR|dPR|fractional\s+flow|pressure\s+wire|coroventis)\b"), "FFR"),

        # 2. Granular Calcium Modification & Atherectomy
        (re.compile(r"(?i)\b(?:shockwave|ivl\b|intravascular\s+lithotripsy)\b"), "SHOCKWAVE (IVL)"),
        (re.compile(r"(?i)\b(?:rotablator|rotational\s+atherectomy|rotablation|burr\b)\b"), "ROTABLATOR"),
        (re.compile(r"(?i)\b(?:cutting\s+balloon|scoring\s+balloon|wolverine|flextome|angiosculpt|scoreflex)\b"), "CUTTING/SCORING BALLOON"),

        # 3. Thrombus Removal
        (re.compile(r"(?i)\b(?:aspiration(?:\s+catheter)?|thrombectomy|export(?:\s+catheter)?|pronto|thrombuster)\b"), "ASPIRATION / THROMBECTOMY"),

        # 4. Core Interventional Hardware
        (re.compile(r"(?i)\b(?:guiding\s+catheter|guide\s+catheter|launcher|ebu|jr[0-9]|al[0-9]|jl[0-9]|sheathless)\b"), "GUIDING CATHETER"),
        (re.compile(r"(?i)\b(?:drug[\-\s]eluting\s+stent|des\b|synergy|megatron|onyx|resolute|xience|sierra|ultimaster|promus|biomatrix|orsiro)\b"), "DRUG-ELUTING STENT"),
        (re.compile(r"(?i)\b(?:balloon|sapphire|nc\b|trek|quantum|semi[\-\s]?compliant|non[\-\s]?compliant|predilatation|postdilatation|dcb|deb|drug[\-\s]coated\s+balloon)\b"), "BALLOON"),
        (re.compile(r"(?i)\b(?:bare[\-\s]metal\s+stent|bms\b|scaffold|brs\b|stent)\b"), "STENT"),
        (re.compile(r"(?i)\b(?:microcatheter|guidewire|corsair|finecross|caravel|sion|runthrough|miracle|gaia)\b"), "MICROCATHETER / WIRE"),
    ]

    def standardize_vessel(self, raw_v: str) -> Tuple[str, str]:
        """
        Maps vessel string to standard territory and clean acronym.
        Returns: (territory, clean_vessel_name)
        """
        v = raw_v.strip().upper()
        v = re.sub(r"^(?:THE|A|AN)\s+", "", v)
        v = re.sub(r"\s+(?:CORONARY\s+)?(?:ARTERY|BRANCH|VESSEL)$", "", v)
        v = re.sub(r"\s*-\s*", " ", v)
        v = re.sub(r"^(?:THE\s+)?(?:OSTIUM|ORIGIN)\s+OF\s+(?:THE\s+)?", "OSTIAL ", v)

        # Grafts
        m_graft = re.match(
            r"^(?P<graft_type>LIMA|RIMA|SVG|BIMA|SAPHENOUS\s+VEIN(?:\s+GRAFT)?)\s+TO\s+(?P<target>.*)$",
            v,
        )
        if m_graft:
            g_type = m_graft.group("graft_type")
            if "SAPHENOUS" in g_type:
                g_type = "SVG"
            raw_tgt = m_graft.group("target").strip()
            _, tgt_std = self.standardize_vessel(raw_tgt)
            return "GRAFT", f"{g_type} TO {tgt_std}"

        # Segment modifiers
        mods = []
        mod_reg = r"^(?:(PROXIMAL|PROX|MID|DISTAL|OSTIAL|APICAL)\s+)"
        while True:
            m_mod = re.match(mod_reg, v)
            if m_mod:
                m_val = m_mod.group(1).upper()
                if m_val == "PROX":
                    m_val = "PROXIMAL"
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

        if re.search(r"\bRPAV\b", v):
            return "RCA", f"{prefix}RPAV".strip()

        if re.search(r"\b(?:RPDA|PDA|POSTERIOR\s+DESCENDING)\b", v):
            return "RCA", f"{prefix}RPDA".strip()

        m_pl = re.search(r"\b(?:(FIRST|1ST|SECOND|2ND)\s+)?(?:POSTEROLATERAL|PLB|PLV|RPL)(?:\s*([1-3]))?\b|\bRPL([1-3])\b", v)
        if m_pl:
            num = m_pl.group(2) or m_pl.group(3)
            if not num and m_pl.group(1):
                num = self.ORDINAL_MAP.get(m_pl.group(1), "1")
            num_str = num if num else "1"
            return "RCA", f"{prefix}RPL{num_str}".strip()

        if re.search(r"\b(?:LAD|LEFT\s+ANTERIOR\s+DESCENDING)\b", v):
            return "LAD", f"{prefix}LAD".strip()

        if re.search(r"\b(?:LCX|LEFT\s+CIRCUMFLEX|CIRCUMFLEX|CIRC)\b", v):
            return "LCX", f"{prefix}LCX".strip()

        if re.search(r"\b(?:RCA|RIGHT(?:\s+CORONARY)?)\b", v):
            return "RCA", f"{prefix}RCA".strip()

        if re.search(r"\b(?:LMCA|LEFT\s+MAIN|LMS|LM)\b", v):
            return "LMCA", f"{prefix}LMCA".strip()

        return "OTHER", f"{prefix}{v}".strip()

    def _clean_device_spec(self, line: str) -> str:
        """Cleans up leading label and trailing artifacts for device spec."""
        cleaned = re.sub(r"^[0-9]+[\.\)]\s*", "", line).strip()
        cleaned = re.sub(
            r"^(?:guiding\s+catheter|guide\s+catheter|balloon|drug[\-\s]eluting\s+stent|stent|ivus|oct|ffr|rotablator|shockwave(?:\s*\(ivl\))?|cutting\s+balloon|scoring\s+balloon|aspiration(?:\s*/\s*thrombectomy)?|thrombectomy)\s*[:\-]\s*",
            "",
            cleaned,
            flags=re.I,
        ).strip()
        cleaned = re.sub(r"[\r\n]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.rstrip(".;")

    def extract(self, pci_text: str = "") -> PCIInterventionResult:
        if not pci_text or not pci_text.strip():
            return PCIInterventionResult()

        text = pci_text.strip()
        # Remove top section header if present
        text = re.sub(r"(?im)^\s*(?:PCI[\t ]+INTERVENTIONS?|PERCUTANEOUS[\t ]+CORONARY[\t ]+INTERVENTIONS?|PCI[\t ]+PROCEDURES?|ANGIOPLASTY[\t ]+DETAILS?|CORONARY[\t ]+INTERVENTIONS?|PCI[\t ]+DETAILS?|INTERVENTIONS?)\s*[:\-]?\s*", "", text)

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        blocks: List[Tuple[str, str, List[str]]] = []  # List of (territory, vessel_name, [lines])

        current_vessel: Optional[Tuple[str, str]] = None
        current_lines: List[str] = []

        for line in lines:
            m_vh = self.VESSEL_HEADER_PATTERN.match(line)
            # Only treat as vessel header if line does NOT start with a known device or outcome word
            if m_vh and not re.match(r"(?i)^(?:guiding|balloon|drug|stent|ivus|oct|ffr|rotablator|shockwave|cutting|aspiration|successful|suboptimal|unsuccessful|residual)\b", line):
                if current_vessel:
                    blocks.append((current_vessel[0], current_vessel[1], current_lines))
                raw_v = m_vh.group("vessel").strip()
                terr, v_name = self.standardize_vessel(raw_v)
                current_vessel = (terr, v_name)
                current_lines = []
            else:
                if current_vessel:
                    current_lines.append(line)
                else:
                    # If lines appear before any explicit vessel header, create a generic block
                    current_vessel = ("OTHER", "UNSPECIFIED")
                    current_lines.append(line)

        if current_vessel:
            blocks.append((current_vessel[0], current_vessel[1], current_lines))

        intervened_vessels_list: List[str] = []
        residual_by_terr: Dict[str, List[str]] = {
            "LMCA": [],
            "LAD": [],
            "LCX": [],
            "RCA": [],
            "GRAFT": [],
        }
        success_status_list: List[str] = []
        devices_used_list: List[str] = []

        seen_vessels: Set[str] = set()

        for terr, v_name, blk_lines in blocks:
            if v_name != "UNSPECIFIED" and v_name not in seen_vessels:
                seen_vessels.add(v_name)
                intervened_vessels_list.append(v_name)

            vessel_devices: List[str] = []
            vessel_outcome: Optional[str] = None
            vessel_residual: Optional[str] = None

            for bl in blk_lines:
                # 1. Residual Stenosis
                m_res = self.RESIDUAL_PATTERN.search(bl)
                if m_res:
                    res_val = m_res.group("val").strip().upper()
                    res_val = re.sub(r"\s+", " ", res_val)
                    vessel_residual = res_val

                # 2. Outcome
                for pat, out_tag in self.OUTCOME_PATTERNS:
                    if pat.search(bl):
                        vessel_outcome = out_tag
                        break

                # 3. Device Tagging
                matched_device_tag = None
                for d_pat, d_tag in self.DEVICE_TAGS:
                    if d_pat.search(bl):
                        matched_device_tag = d_tag
                        break

                if matched_device_tag:
                    cleaned_spec = self._clean_device_spec(bl)
                    if cleaned_spec:
                        vessel_devices.append(f"[{matched_device_tag}] {cleaned_spec}")
                    else:
                        vessel_devices.append(f"[{matched_device_tag}]")

            # Route residual stenosis to territory column
            if vessel_residual:
                entry = f"{v_name}: {vessel_residual}" if v_name != "UNSPECIFIED" else vessel_residual
                if terr in residual_by_terr and entry not in residual_by_terr[terr]:
                    residual_by_terr[terr].append(entry)

            # Route outcome
            if vessel_outcome:
                out_str = f"{v_name}: {vessel_outcome}" if v_name != "UNSPECIFIED" else vessel_outcome
                if out_str not in success_status_list:
                    success_status_list.append(out_str)

            # Route devices
            if vessel_devices:
                dev_joined = "; ".join(vessel_devices)
                dev_entry = f"{v_name}: {dev_joined}" if v_name != "UNSPECIFIED" else dev_joined
                devices_used_list.append(dev_entry)

        return PCIInterventionResult(
            intervened_vessels="; ".join(intervened_vessels_list),
            lmca_residual_stenosis="; ".join(residual_by_terr["LMCA"]),
            lad_residual_stenosis="; ".join(residual_by_terr["LAD"]),
            lcx_residual_stenosis="; ".join(residual_by_terr["LCX"]),
            rca_residual_stenosis="; ".join(residual_by_terr["RCA"]),
            graft_residual_stenosis="; ".join(residual_by_terr["GRAFT"]),
            success_status="; ".join(success_status_list),
            devices_used=" | ".join(devices_used_list),
        )
