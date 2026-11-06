"""
Clinical Indication, Acute Myocardial Infarction (AMI), STEMI,
PCI Execution, and Primary PCI (PPCI) Classifier.

Extracts indication STEMI and AMI status with strict NSTEMI differentiation,
evaluates procedural execution and hardware for PCI execution,
and synthesizes Primary PCI (PPCI) status with verbatim evidence and confidence scores.
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Union, Tuple
import re

from cardio_tagger.section_parser import ParsedDocument, ClinicalSectionParser
from cardio_tagger.pci_intervention import PCIInterventionResult


@dataclass
class IndicationPCIResult:
    indication_stemi: str = "NO"
    indication_stemi_evidence: str = ""
    indication_stemi_confidence: float = 0.0
    indication_ami: str = "NO"
    indication_ami_evidence: str = ""
    indication_ami_confidence: float = 0.0
    pci_done: str = "NO"
    pci_done_evidence: str = ""
    pci_done_confidence: float = 0.0
    ppci_done: str = "NO"
    ppci_done_evidence: str = ""
    ppci_done_confidence: float = 0.0


class IndicationPCIClassifier:
    """
    Evaluates clinical documents to classify:
    1. Indication STEMI (strictly excluding NSTEMI and non-STEMI)
    2. Indication AMI (STEMI, NSTEMI, or unspecified acute myocardial infarction)
    3. PCI Done status (evaluating interventions, hardware, or explicit procedural negation)
    4. PPCI Done status (Primary PCI explicit matching or synthesis with STEMI indication)
    """

    # NSTEMI regex patterns (must be strictly differentiated from STEMI)
    NSTEMI_PATTERN = re.compile(
        r"\b(?:"
        r"non[\s\-]st[\s\-]?(?:segment\s+|seg\s+)?elevation(?:\s+myocardial\s+infarction|\s+mi)?|"
        r"non[\s\-]?stemi|"
        r"nstemi|"
        r"nste[\s\-]?acs|"
        r"nste\-?mi"
        r")\b",
        re.IGNORECASE,
    )

    # STEMI regex patterns
    STEMI_PATTERN = re.compile(
        r"\b(?:"
        r"(?:acute\s+|subacute\s+|recent\s+)?(?:extensive\s+|anterior\s+|anterolateral\s+|anteroseptal\s+|inferior\s+|inferolateral\s+|inferoposterior\s+|lateral\s+|posterior\s+|apical\s+)*"
        r"(?:st[\s\-]?(?:segment\s+|seg\s+)?elevation\s+(?:myocardial\s+infarction|mi)|(?<!non[\s\-])(?<!non\s)stemi|(?<!non[\s\-])(?<!non\s)ste\-?mi)"
        r")\b",
        re.IGNORECASE,
    )

    # AMI patterns (STEMI, NSTEMI, or general acute myocardial infarction)
    AMI_PATTERN = re.compile(
        r"\b(?:"
        r"acute\s+myocardial\s+infarction|"
        r"acute\s+mi\b|"
        r"ami\b|"
        r"myocardial\s+infarction|"
        r"nstemi|"
        r"non[\s\-]st[\s\-]?(?:segment\s+|seg\s+)?elevation(?:\s+myocardial\s+infarction|\s+mi)?|"
        r"non[\s\-]?stemi|"
        r"nste[\s\-]?acs|"
        r"nste\-?mi|"
        r"stemi|"
        r"st[\s\-]?(?:segment\s+|seg\s+)?elevation\s+(?:myocardial\s+infarction|mi)"
        r")\b",
        re.IGNORECASE,
    )

    # Past history section types to strictly exclude
    HISTORY_SECTION_TYPES = {
        "history",
        "pmh",
        "pmhx",
        "past_medical_history",
        "medical_history",
        "prior_history",
    }

    # Past history line indicators to exclude past events (allowing leading bullets/numbers)
    HISTORY_LINE_PATTERN = re.compile(
        r"(?i)^[\t ]*(?:[\*\-\•\u2022]|(?:[0-9IVX]+[\.\)]))?[\t ]*(?:"
        r"past\s+(?:medical\s+)?history(?:\s*[:\-—]|\s+|$)|"
        r"pmhx?(?:\s*[:\-—]|\s+|$)|"
        r"previous(?:\s+history)?\s*[:\-—]|"
        r"history\s+of\s*[:\-—]|"
        r"prior\s+(?:medical\s+)?history(?:\s*[:\-—]|\s+|$)|"
        r"medical\s+history(?:\s*[:\-—]|\s+|$)"
        r")"
    )

    # Past event pattern to mask inline historical qualifiers in sentences before checking STEMI/AMI
    PAST_EVENT_PATTERN = re.compile(
        r"\b(?:"
        r"(?:history\s+of|h/o|prior|previous|past|old|remote|status[\s\-]post|s/p|hx\s+of|family\s+history\s+of|fhx\s+of)\s+"
        r"(?:(?!now|presenting|presents|acute)[^.;\n])*?\b(?:stemi|nstemi|ami|myocardial\s+infarction|mi)\b|"
        r"\b(?:stemi|nstemi|ami|myocardial\s+infarction|mi)\b\s*"
        r"(?:in\s+[12][90]\d{2}|\([12][90]\d{2}\)|[12][90]\d{2}|\d+\s+(?:years?|yrs?|months?|mths?)\s+ago)\b"
        r")",
        re.IGNORECASE,
    )

    # Past procedure pattern to mask inline historical stents/PCI in sentences
    PAST_PROC_PATTERN = re.compile(
        r"\b(?:"
        r"(?:history\s+of|h/o|prior|previous|past|old|remote|status[\s\-]post|s/p|hx\s+of|patent)\s+"
        r"[^.;\n]*?\b(?:pci|stent(?:s|ing)?|ptca|angioplasty|cabg|revascularization)\b|"
        r"\b(?:pci|stent(?:s|ing)?|ptca|angioplasty|cabg)\b\s*"
        r"(?:in\s+[12][90]\d{2}|\([12][90]\d{2}\)|[12][90]\d{2}|\d+\s+(?:years?|yrs?|months?|mths?)\s+ago)\b"
        r")",
        re.IGNORECASE,
    )

    # Explicit Primary PCI (PPCI) patterns
    PPCI_EXPLICIT_PATTERN = re.compile(
        r"\b(?:"
        r"primary\s+(?:percutaneous\s+coronary\s+intervention|pci)\b|"
        r"ppci\b|"
        r"primary\s+(?:balloon\s+)?angioplasty\b|"
        r"primary\s+ptca\b|"
        r"(?:emergent|emergency|urgent)\s+pci(?:\s+for\s+stemi)?\b|"
        r"pci\s+for\s+stemi\b|"
        r"(?:angioplasty|stenting)\s+for\s+stemi\b"
        r")\b",
        re.IGNORECASE,
    )

    # Affirmative PCI terms in text
    PCI_AFFIRMATIVE_PATTERN = re.compile(
        r"\b(?:"
        r"(?:successful|unsuccessful|aborted)?\s*(?:percutaneous\s+coronary\s+intervention|pci)\s+to\b|"
        r"successful\s+(?:percutaneous\s+coronary\s+intervention|pci)\b|"
        r"(?:percutaneous\s+coronary\s+intervention|pci)\s+(?:performed|done|completed|attempted)\b|"
        r"primary\s+pci\b|"
        r"ppci\b|"
        r"(?:angioplasty\s+and\s+stenting|angioplasty\s+&\s+stenting)\b|"
        r"(?:balloon\s+angioplasty|plain\s+old\s+balloon\s+angioplasty|poba)\b|"
        r"primary\s+(?:balloon\s+)?angioplasty\b|"
        r"ptca\b|"
        r"stent(?:s)?\s+deployed\b|"
        r"stent(?:s)?\s+implanted\b|"
        r"stenting\s+of\b|"
        r"stented\b|"
        r"(?:des|bms)\s+(?:deployed|implanted|to)\b|"
        r"drug[\s\-]eluting\s+stent(?:\s+deployed|\s+implanted)?\b|"
        r"bare[\s\-]metal\s+stent(?:\s+deployed|\s+implanted)?\b|"
        r"aspiration\s+thrombectomy\b|"
        r"(?:intravascular\s+lithotripsy|ivl|shockwave)\b|"
        r"(?:rotational\s+atherectomy|rotablation|rotablator)\b|"
        r"(?:orbital\s+atherectomy|laser\s+atherectomy)\b|"
        r"direct\s+stenting\b|"
        r"culprit\s+vessel\s+pci\b|"
        r"successful\s+(?:stenting|angioplasty|procedure)\b"
        r")\b",
        re.IGNORECASE,
    )

    # Negation patterns for PCI
    PCI_NEGATION_PATTERN = re.compile(
        r"\b(?:"
        r"pci\s+(?:to\s+[a-z0-9\-\s/]+\s+)?deferred\b|"
        r"intervention\s+(?:to\s+[a-z0-9\-\s/]+\s+)?deferred\b|"
        r"stenting\s+(?:to\s+[a-z0-9\-\s/]+\s+)?deferred\b|"
        r"no\s+(?:new\s+|further\s+)?intervention(?:s)?(?:\s+performed|\s+done)?\b|"
        r"no\s+pci(?:\s+performed|\s+done)?\b|"
        r"no\s+stent(?:s)?\s+(?:deployed|implanted|placed)?\b|"
        r"no\s+angioplasty(?:\s+performed|\s+done)?\b|"
        r"diagnostic\s+(?:coronary\s+)?(?:angiogram|angiography|cath|catheterization)?\s*only\b|"
        r"diagnostic\s+only\b|"
        r"conservative\s+medical\s+(?:therapy|management)\b|"
        r"medical\s+management\s+only\b|"
        r"referred\s+for\s+(?:urgent\s+|emergent\s+|elective\s+)?cabg\b|"
        r"recommend(?:ed)?\s+(?:for\s+)?(?:urgent\s+|emergent\s+|elective\s+)?cabg\b|"
        r"plan\s+(?:for\s+)?(?:urgent\s+|emergent\s+|elective\s+)?cabg\b|"
        r"for\s+(?:urgent\s+|emergent\s+|elective\s+)?cabg\b|"
        r"referred\s+for\s+surgical\s+(?:revascularization|cabg)\b"
        r")\b",
        re.IGNORECASE,
    )

    def classify(
        self,
        parsed: Union[ParsedDocument, str],
        pci_result: Optional[PCIInterventionResult] = None,
    ) -> IndicationPCIResult:
        """
        Classifies clinical presentation (STEMI, AMI) and intervention status (PCI Done, PPCI Done).
        """
        if isinstance(parsed, str):
            parser = ClinicalSectionParser()
            parsed = parser.parse_sections(parsed)

        result = IndicationPCIResult()

        # 1. Gather candidate sentences from prioritized sections for indication
        candidate_sentences = self._gather_candidate_sentences(parsed)

        # 2. Evaluate STEMI vs NSTEMI vs AMI
        self._evaluate_indication(candidate_sentences, result)

        # 3. Evaluate PCI Done and PPCI Done
        self._evaluate_pci_and_ppci(parsed, pci_result, result)

        return result

    def _gather_candidate_sentences(self, parsed: ParsedDocument) -> List[Tuple[str, str]]:
        """
        Gathers (source_section, line_text) tuples in clinical priority:
        1. Explicit 'indication' sections
        2. Fallback to 'conclusion' sections if no indication present
        3. Fallback to procedure sections/headers if needed
        Strictly excludes any section or line representing past medical history.
        """
        candidates: List[Tuple[str, str]] = []

        # 1. Check indication sections
        ind_secs = parsed.all_sections.get("indication", [])
        for sec in ind_secs:
            if sec.section_type in self.HISTORY_SECTION_TYPES:
                continue
            if re.search(r"\b(?:past|pmh|previous|prior)\b", sec.header_matched, re.I):
                continue
            for line in sec.text.split("\n"):
                line_str = line.strip()
                if not line_str or self.HISTORY_LINE_PATTERN.match(line_str):
                    continue
                candidates.append(("indication", line_str))

        # 2. If no indication candidate lines found, fall back to conclusion sections
        if not candidates:
            conc_secs = parsed.conclusion_sections or parsed.all_sections.get("conclusion", [])
            for sec in conc_secs:
                if sec.section_type in self.HISTORY_SECTION_TYPES:
                    continue
                if re.search(r"\b(?:past|pmh|previous|prior)\b", sec.header_matched, re.I):
                    continue
                for line in sec.text.split("\n"):
                    line_str = line.strip()
                    if not line_str or self.HISTORY_LINE_PATTERN.match(line_str):
                        continue
                    candidates.append(("conclusion", line_str))

        # 3. Fallback to procedure sections if no indication or conclusion lines
        if not candidates:
            proc_secs = parsed.all_sections.get("procedure", [])
            for sec in proc_secs:
                if sec.section_type in self.HISTORY_SECTION_TYPES:
                    continue
                if re.search(r"\b(?:past|pmh|previous|prior)\b", sec.header_matched, re.I):
                    continue
                if sec.header_matched and not self.HISTORY_LINE_PATTERN.match(sec.header_matched):
                    candidates.append(("procedure_header", sec.header_matched))
                for line in sec.text.split("\n"):
                    line_str = line.strip()
                    if not line_str or self.HISTORY_LINE_PATTERN.match(line_str):
                        continue
                    candidates.append(("procedure", line_str))

        return candidates

    def _evaluate_indication(
        self, candidate_sentences: List[Tuple[str, str]], result: IndicationPCIResult
    ) -> None:
        """
        Evaluates candidate lines for STEMI and AMI.
        Strictly differentiates STEMI from NSTEMI.
        Masks inline history qualifiers before matching acute events.
        """
        stemi_evidence: Optional[str] = None
        nstemi_evidence: Optional[str] = None
        ami_evidence: Optional[str] = None

        for _, sentence in candidate_sentences:
            # Mask inline history qualifiers (e.g. "history of STEMI in 2018", "prior STEMI")
            sentence_active = self.PAST_EVENT_PATTERN.sub("[HISTORY_MASK]", sentence)

            # Check for NSTEMI
            if self.NSTEMI_PATTERN.search(sentence_active):
                if not nstemi_evidence:
                    nstemi_evidence = sentence

            # Check for STEMI: mask out NSTEMI phrases first to prevent false matches
            masked = self.NSTEMI_PATTERN.sub("[NSTEMI_MASK]", sentence_active)
            if self.STEMI_PATTERN.search(masked):
                if not stemi_evidence:
                    stemi_evidence = sentence

            # Check for general AMI
            if self.AMI_PATTERN.search(sentence_active):
                if not ami_evidence:
                    ami_evidence = sentence

        # 1. STEMI adjudication
        if stemi_evidence:
            result.indication_stemi = "YES"
            result.indication_stemi_evidence = stemi_evidence
            result.indication_stemi_confidence = 0.95
            # STEMI is inherently an AMI
            result.indication_ami = "YES"
            result.indication_ami_evidence = stemi_evidence
            result.indication_ami_confidence = 0.95
        else:
            result.indication_stemi = "NO"
            result.indication_stemi_evidence = ""
            result.indication_stemi_confidence = 0.0

            # 2. AMI adjudication (when not STEMI)
            if nstemi_evidence:
                result.indication_ami = "YES"
                result.indication_ami_evidence = nstemi_evidence
                result.indication_ami_confidence = 0.95
            elif ami_evidence:
                result.indication_ami = "YES"
                result.indication_ami_evidence = ami_evidence
                result.indication_ami_confidence = 0.95
            else:
                result.indication_ami = "NO"
                result.indication_ami_evidence = ""
                result.indication_ami_confidence = 0.0

    def _gather_procedural_sentences(self, parsed: ParsedDocument) -> List[Tuple[str, str]]:
        """
        Gathers candidate lines across non-history clinical sections to evaluate
        PCI execution, explicit PPCI, and procedural negation.
        """
        candidates: List[Tuple[str, str]] = []
        priority_keys = ["procedure", "intervention", "conclusion", "findings", "plan", "indication", "summary"]
        other_keys = [k for k in parsed.all_sections if k not in priority_keys and k not in self.HISTORY_SECTION_TYPES]

        for sec_key in priority_keys + other_keys:
            for sec in parsed.all_sections.get(sec_key, []):
                if sec.section_type in self.HISTORY_SECTION_TYPES:
                    continue
                if re.search(r"\b(?:past|pmh|previous|prior)\b", sec.header_matched, re.I):
                    continue
                if sec.header_matched and not self.HISTORY_LINE_PATTERN.match(sec.header_matched):
                    candidates.append((f"{sec_key}_header", sec.header_matched))
                for line in sec.text.split("\n"):
                    line_str = line.strip()
                    if not line_str or self.HISTORY_LINE_PATTERN.match(line_str):
                        continue
                    candidates.append((sec_key, line_str))

        if not candidates and parsed.full_text:
            for line in parsed.full_text.split("\n"):
                line_str = line.strip()
                if not line_str or self.HISTORY_LINE_PATTERN.match(line_str):
                    continue
                candidates.append(("full_text", line_str))

        return candidates

    def _evaluate_pci_and_ppci(
        self,
        parsed: ParsedDocument,
        pci_result: Optional[PCIInterventionResult],
        result: IndicationPCIResult,
    ) -> None:
        """
        Evaluates procedural evidence to classify PCI Done and PPCI Done.
        """
        # 1. Check if pci_result from PCIInterventionExtractor provides direct evidence
        has_vessels = bool(pci_result and pci_result.intervened_vessels and pci_result.intervened_vessels.strip())
        has_devices = bool(pci_result and pci_result.devices_used and pci_result.devices_used.strip())

        if has_vessels or has_devices:
            result.pci_done = "YES"
            result.pci_done_confidence = 1.0 if (has_vessels and has_devices) else 0.95
            evidence_parts = []
            if has_vessels:
                evidence_parts.append(f"Intervened: {pci_result.intervened_vessels}")
            if has_devices:
                evidence_parts.append(f"Devices: {pci_result.devices_used}")
            result.pci_done_evidence = "; ".join(evidence_parts)

        # 2. Gather procedural sentences from non-history sections
        proc_sentences = self._gather_procedural_sentences(parsed)

        explicit_ppci_evidence: Optional[str] = None
        affirmative_pci_evidence: Optional[str] = None
        negated_pci_evidence: Optional[str] = None

        for _, sentence in proc_sentences:
            # Mask inline history (e.g., "prior stent", "s/p PCI in 2016")
            masked_proc = self.PAST_PROC_PATTERN.sub("[HISTORY_MASK]", sentence)

            # Check for explicit PPCI in this sentence
            if not explicit_ppci_evidence and self.PPCI_EXPLICIT_PATTERN.search(masked_proc):
                if not self.PCI_NEGATION_PATTERN.search(sentence):
                    explicit_ppci_evidence = sentence

            # Check for negation patterns
            if not negated_pci_evidence and self.PCI_NEGATION_PATTERN.search(sentence):
                negated_pci_evidence = sentence

            # Mask negation patterns to avoid matching "pci" in "pci deferred"
            masked_neg = self.PCI_NEGATION_PATTERN.sub("[NEG_MASK]", masked_proc)

            # Check affirmative PCI patterns
            if not affirmative_pci_evidence and self.PCI_AFFIRMATIVE_PATTERN.search(masked_neg):
                affirmative_pci_evidence = sentence

        # 3. Adjudicate pci_done if not already set from pci_result
        if result.pci_done != "YES":
            if explicit_ppci_evidence:
                result.pci_done = "YES"
                result.pci_done_confidence = 0.98
                result.pci_done_evidence = explicit_ppci_evidence
            elif affirmative_pci_evidence:
                result.pci_done = "YES"
                result.pci_done_confidence = 0.95
                result.pci_done_evidence = affirmative_pci_evidence
            elif negated_pci_evidence:
                result.pci_done = "NEGATED"
                result.pci_done_confidence = 0.95
                result.pci_done_evidence = negated_pci_evidence
            else:
                result.pci_done = "NO"
                result.pci_done_confidence = 0.0
                result.pci_done_evidence = ""

        # 4. Adjudicate ppci_done
        if explicit_ppci_evidence:
            result.ppci_done = "YES"
            result.ppci_done_confidence = 0.98
            result.ppci_done_evidence = explicit_ppci_evidence
        elif result.pci_done == "YES" and result.indication_stemi == "YES":
            result.ppci_done = "YES"
            result.ppci_done_confidence = 0.92
            result.ppci_done_evidence = (
                f"Indication: {result.indication_stemi_evidence}; PCI: {result.pci_done_evidence}"
            )
        elif result.pci_done == "NEGATED":
            result.ppci_done = "NO"
            result.ppci_done_confidence = 0.95
            result.ppci_done_evidence = result.pci_done_evidence
        else:
            result.ppci_done = "NO"
            result.ppci_done_confidence = 0.0
            result.ppci_done_evidence = ""
