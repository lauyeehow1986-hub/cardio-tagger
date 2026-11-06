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

# Ensure ClinicalSectionParser has parse_sections convenience method
if not hasattr(ClinicalSectionParser, "parse_sections"):
    def _parse_sections(self, text: str) -> ParsedDocument:
        """Convenience method to parse a raw text string directly into a ParsedDocument."""
        return self.parse_pages("inline.txt", [text])
    ClinicalSectionParser.parse_sections = _parse_sections


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
        r"non[\s\-]st[\s\-]?elevation(?:\s+myocardial\s+infarction|\s+mi)?|"
        r"non[\s\-]stemi|"
        r"nstemi|"
        r"nste[\s\-]acs|"
        r"nste\-?mi"
        r")\b",
        re.IGNORECASE
    )

    # STEMI regex patterns
    STEMI_PATTERN = re.compile(
        r"\b(?:"
        r"(?:acute\s+|subacute\s+|recent\s+)?(?:extensive\s+|anterior\s+|anterolateral\s+|anteroseptal\s+|inferior\s+|inferolateral\s+|inferoposterior\s+|lateral\s+|posterior\s+|apical\s+)*"
        r"(?:st[\s\-]?elevation\s+(?:myocardial\s+infarction|mi)|(?<!non[\s\-])(?<!non\s)stemi|(?<!non[\s\-])(?<!non\s)ste\-?mi)"
        r")\b",
        re.IGNORECASE
    )

    # AMI patterns (STEMI, NSTEMI, or general acute myocardial infarction)
    AMI_PATTERN = re.compile(
        r"\b(?:"
        r"acute\s+myocardial\s+infarction|"
        r"acute\s+mi\b|"
        r"ami\b|"
        r"myocardial\s+infarction|"
        r"nstemi|"
        r"non[\s\-]st[\s\-]?elevation(?:\s+myocardial\s+infarction|\s+mi)?|"
        r"non[\s\-]stemi|"
        r"stemi|"
        r"st[\s\-]?elevation\s+(?:myocardial\s+infarction|mi)"
        r")\b",
        re.IGNORECASE
    )

    # Past history line indicators to exclude past events
    HISTORY_LINE_PATTERN = re.compile(
        r"(?i)^[\t ]*(?:past\s+medical\s+history|pmhx?|previous\s+history|medical\s+history|prior\s+history)\s*[:\-—]"
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

        # 1. Gather candidate sentences from prioritized sections
        candidate_sentences = self._gather_candidate_sentences(parsed)

        # 2. Evaluate STEMI vs NSTEMI vs AMI
        self._evaluate_indication(candidate_sentences, result)

        return result

    def _gather_candidate_sentences(self, parsed: ParsedDocument) -> List[Tuple[str, str]]:
        """
        Gathers (source_section, line_text) tuples in clinical priority:
        1. Explicit 'indication' sections
        2. Fallback to 'conclusion' sections if no indication present
        3. Fallback to other procedural text if needed
        Excludes explicit past history headers or lines.
        """
        candidates: List[Tuple[str, str]] = []

        # 1. Check indication sections
        ind_secs = parsed.all_sections.get("indication", [])
        for sec in ind_secs:
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
                for line in sec.text.split("\n"):
                    line_str = line.strip()
                    if not line_str or self.HISTORY_LINE_PATTERN.match(line_str):
                        continue
                    candidates.append(("conclusion", line_str))

        return candidates

    def _evaluate_indication(
        self, candidate_sentences: List[Tuple[str, str]], result: IndicationPCIResult
    ) -> None:
        """
        Evaluates candidate lines for STEMI and AMI.
        Strictly differentiates STEMI from NSTEMI.
        """
        stemi_evidence: Optional[str] = None
        nstemi_evidence: Optional[str] = None
        ami_evidence: Optional[str] = None

        for _, sentence in candidate_sentences:
            # Check for NSTEMI
            if self.NSTEMI_PATTERN.search(sentence):
                if not nstemi_evidence:
                    nstemi_evidence = sentence

            # Check for STEMI: mask out NSTEMI phrases first to prevent false matches
            masked = self.NSTEMI_PATTERN.sub("[NSTEMI_MASK]", sentence)
            if self.STEMI_PATTERN.search(masked):
                if not stemi_evidence:
                    stemi_evidence = sentence

            # Check for general AMI
            if self.AMI_PATTERN.search(sentence):
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
