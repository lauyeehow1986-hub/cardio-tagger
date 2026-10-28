"""
Multi-Pass Layout-Aware & Multi-Delimiter Clinical PDF Section Parser.
Specifically engineered to locate CONCLUSION / IMPRESSION / SUMMARY / PLAN sections
whether they appear at the end of the PDF or on Page 1 (Executive Summary layout),
and across diverse delimiters (newlines, colons, em-dashes, numbered headings, tables).
Includes automatic RapidOCR fallback for scanned pages with raster images (< 40 chars native text).
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ExtractedSection:
    section_type: str
    header_matched: str
    text: str
    page_number: int
    total_pages: int
    char_start: int
    char_end: int
    is_early_section: bool
    extraction_method: str


@dataclass
class ParsedDocument:
    pdf_path: str
    total_pages: int
    full_text: str
    conclusion_sections: List[ExtractedSection] = field(default_factory=list)
    all_sections: Dict[str, List[ExtractedSection]] = field(default_factory=dict)
    used_ocr_fallback: bool = False


class ClinicalSectionParser:
    """
    Isolates target clinical sections (primarily CONCLUSION, extensible to any section)
    with resilience to:
      1. Newline delimiters (`CONCLUSION\n1. Staged PCI...`)
      2. Inline colon/dash delimiters (`Conclusion: Recommend staged PCI...`)
      3. Multi-column or box/table boundaries
      4. Conclusion appearing on Page 1 / top-of-report vs final page
      5. Scanned/raster image pages via RapidOCR fallback (<40 native chars)
    """

    CONCLUSION_HEADER_PATTERNS = [
        re.compile(
            r"(?im)^[\t ]*(?:(?:[0-9IVX]+[\.\)]|\*|\#+)[\t ]*)?"
            r"(?P<header>(?:FINAL[\t ]+|CATHETERIZATION[\t ]+|ANGIOGRAPHIC[\t ]+|CLINICAL[\t ]+|PROCEDURE[\t ]+|DISCHARGE[\t ]+|ECHOCARDIOGRAPHIC[\t ]+|OVERALL[\t ]+)?"
            r"(?:CONCLUSIONS?\s*(?:AND|&|/)\s*RECOMMENDATIONS?|CONCLUSIONS?\s*(?:AND|&|/)\s*PLAN|"
            r"IMPRESSIONS?\s*(?:AND|&|/)\s*PLAN|SUMMARY\s*(?:AND|&|/)\s*RECOMMENDATIONS?|"
            r"CONCLUSIONS?|IMPRESSIONS?|FINAL[\t ]+SUMMARY|RECOMMENDATIONS?\s*(?:AND|&|/)\s*PLAN|"
            r"ASSESSMENT\s*(?:AND|&|/)\s*PLAN|OVERALL[\t ]+IMPRESSION|FINAL[\t ]+IMPRESSION|SUMMARY))"
            r"[\t ]*(?:[:\-—\n]|\s*$)"
        ),
        re.compile(
            r"(?im)(?:^|\n|[.;]\s+)[\t ]*(?P<header>CONCLUSIONS?|IMPRESSIONS?|RECOMMENDATIONS?|SUMMARY)[\t ]*[:\-—][\t ]*(?:\n|\S|$)"
        ),
        re.compile(
            r"(?im)^\s*\|[\t ]*(?P<header>CONCLUSIONS?|IMPRESSIONS?|SUMMARY)[\t ]*\|"
        ),
    ]

    OTHER_SECTION_HEADERS = {
        "indication": re.compile(
            r"(?im)(?:^|\n|[.;]\s+)[\t ]*(?:[0-9IVX]+[\.\)][\t ]*)?(?:INDICATIONS?|HISTORY|CLINICAL[\t ]+HISTORY)[\t ]*(?:[:\-—\n]|$)"
        ),
        "procedure": re.compile(
            r"(?im)(?:^|\n|[.;]\s+)[\t ]*(?:[0-9IVX]+[\.\)][\t ]*)?(?:PROCEDURES?[\t ]+PERFORMED|PROCEDURE[\t ]+DETAILS?|TECHNIQUE|INTERVENTION)[\t ]*(?:[:\-—\n]|$)"
        ),
        "hemodynamics": re.compile(
            r"(?im)(?:^|\n|[.;]\s+)[\t ]*(?:[0-9IVX]+[\.\)][\t ]*)?(?:HEMODYNAMICS?|VENTRICULOGRAPHY|LEFT[\t ]+VENTRICULOGRAM)[\t ]*(?:[:\-—\n]|$)"
        ),
        "findings": re.compile(
            r"(?im)(?:^|\n|[.;]\s+)[\t ]*(?:[0-9IVX]+[\.\)][\t ]*)?(?:"
            r"CORONARY[\t ]+ANGIOGRAPHY|ANGIOGRAPHIC[\t ]+FINDINGS?|FINDINGS?|CORONARY[\t ]+ANATOMY|"
            r"LEFT[\t ]+VENTRICLE|LV[\t ]+SYSTOLIC[\t ]+FUNCTION|VENTRICULAR[\t ]+FUNCTION|"
            r"WALL[\t ]+MOTION[\t ]+FINDINGS?|CHAMBERS?|ECHOCARDIOGRAPHIC[\t ]+FINDINGS?|2D[\t ]+FINDINGS?"
            r")[\t ]*(?:[:\-—\n]|$)"
        ),
        "measurements": re.compile(
            r"(?im)(?:^|\n|[.;]\s+)[\t ]*(?:[0-9IVX]+[\.\)][\t ]*)?(?:"
            r"QUANTITATIVE[\t ]+MEASUREMENTS?|ECHO(?:CARDIOGRAPHIC)?[\t ]+MEASUREMENTS?|"
            r"MEASUREMENTS?|2D[\t ]+MEASUREMENTS?|M[\-\s]MODE[\t ]+(?:&|AND[\t ]+)?2D[\t ]+MEASUREMENTS?|"
            r"HEMODYNAMICS?[\t ]+(?:&|AND[\t ]+)?MEASUREMENTS?|MEASUREMENTS?[\t ]+(?:&|AND[\t ]+)?CALCULATIONS?|"
            r"DOPPLER[\t ]+MEASUREMENTS?|DIMENSIONS?|QUANTITATIVE[\t ]+DATA"
            r")[\t ]*(?:[:\-—\n]|$)"
        ),
        "complications": re.compile(
            r"(?im)(?:^|\n|[.;]\s+)[\t ]*(?:[0-9IVX]+[\.\)][\t ]*)?(?:COMPLICATIONS?|ESTIMATED[\t ]+BLOOD[\t ]+LOSS)[\t ]*(?:[:\-—\n]|$)"
        ),
        "plan": re.compile(
            r"(?im)(?:^|\n|[.;]\s+)[\t ]*(?:[0-9IVX]+[\.\)][\t ]*)?(?:PLAN|DISPOSITION|FOLLOW[\t \-]UP[\t ]+PLAN|POST[\t \-]PROCEDURE[\t ]+PLAN|RECOMMENDATIONS?)[\t ]*(?:[:\-—\n]|$)"
        ),
    }

    STOP_BOUNDARY_PATTERN = re.compile(
        r"(?im)^[\t ]*(?:(?:[0-9IVX]+[\.\)][\t ]*)?(?:"
        r"ELECTRONICALLY[\t ]+SIGNED[\t ]+BY|SIGNED[\t ]+BY|ATTENDING[\t ]+CARDIOLOGIST|"
        r"ATTENDING[\t ]+PHYSICIAN|DICTATED[\t ]+BY|TRANSCRIBED[\t ]+BY|"
        r"CC:|DISTRIBUTION[\t ]+LIST|BILLING[\t ]+SUMMARY|BILLING[\t ]+CODES|CPT[\t ]+CODES|"
        r"RADIATION[\t ]+DOSE[\t ]+REPORT|RADIATION[\t ]+DOSE|CONTRAST[\t ]+LOG|NURSING[\t ]+FLOWSHEET|"
        r"PAGE[\t ]+[0-9]+[\t ]+OF[\t ]+[0-9]+"
        r"))\b"
    )

    def __init__(self, enable_ocr: bool = True):
        self.enable_ocr = enable_ocr
        self._ocr_engine = None

    def _get_ocr_engine(self):
        if self._ocr_engine is None and self.enable_ocr:
            try:
                from rapidocr_onnxruntime import RapidOCR
                self._ocr_engine = RapidOCR()
            except Exception:
                self._ocr_engine = False
        return self._ocr_engine if self._ocr_engine else None

    def parse_pdf(self, pdf_path: str) -> ParsedDocument:
        """
        Parses a PDF directly from disk using PyMuPDF (~1.5ms native text),
        falling back to RapidOCR only on pages where native text < 40 chars
        and raster images exist.
        """
        path = Path(pdf_path)
        if path.suffix.lower() in (".txt", ".md"):
            raw = path.read_text(encoding="utf-8", errors="ignore")
            pages = raw.split("\f") if "\f" in raw else [raw]
            return self.parse_pages(str(pdf_path), pages, used_ocr=False)

        used_ocr = False
        page_texts: List[str] = []

        try:
            import pymupdf as fitz
        except ImportError:
            try:
                import fitz
            except ImportError:
                fitz = None

        if fitz is not None:
            doc = fitz.open(str(pdf_path))
            for page in doc:
                text = page.get_text("text")
                # Scanned page check: < 40 characters and has images
                if len(text.strip()) < 40 and len(page.get_images()) > 0:
                    ocr = self._get_ocr_engine()
                    if ocr:
                        pix = page.get_pixmap()
                        img_bytes = pix.tobytes("png")
                        ocr_result, _ = ocr(img_bytes)
                        if ocr_result:
                            ocr_text = "\n".join([line[1] for line in ocr_result])
                            if len(ocr_text.strip()) > len(text.strip()):
                                text = ocr_text
                                used_ocr = True
                page_texts.append(text)
            doc.close()
        else:
            try:
                import pypdf
                reader = pypdf.PdfReader(str(pdf_path))
                page_texts = [p.extract_text() or "" for p in reader.pages]
            except Exception as exc:
                page_texts = [f"[ERROR_READING_PDF: {exc}]"]

        return self.parse_pages(str(pdf_path), page_texts, used_ocr=used_ocr)

    def parse_pages(self, pdf_path: str, page_texts: List[str], used_ocr: bool = False) -> ParsedDocument:
        total_pages = len(page_texts)
        full_text = "\n\f\n".join(page_texts)
        doc = ParsedDocument(
            pdf_path=pdf_path,
            total_pages=total_pages,
            full_text=full_text,
            used_ocr_fallback=used_ocr,
        )

        total_doc_len = len(full_text)

        # Inspect ALL pages because Conclusion may appear on Page 1 or final page
        for idx, page_raw in enumerate(page_texts):
            page_num = idx + 1
            normalized = self._normalize_delimiters(page_raw)
            sections_on_page = self._extract_sections_from_text(
                normalized, page_num=page_num, total_pages=total_pages, total_doc_len=total_doc_len
            )
            for sec in sections_on_page:
                doc.all_sections.setdefault(sec.section_type, []).append(sec)
                if sec.section_type in ("conclusion", "plan"):
                    doc.conclusion_sections.append(sec)

        # Fallback: if a document has no explicit header (e.g. short 1-page cath note, CSV note, or
        # broken OCR header), extract the text as a synthetic conclusion window.
        # For single-page or notes < 2500 chars, capture the entire text so clinical intent is never lost.
        if not doc.conclusion_sections and page_texts:
            last_page = self._normalize_delimiters(page_texts[-1])
            tail_start = 0 if (total_pages == 1 or len(last_page) < 2500) else max(0, int(len(last_page) * 0.60))
            tail_text = last_page[tail_start:].strip()
            if tail_text:
                fallback_sec = ExtractedSection(
                    section_type="conclusion_tail_fallback",
                    header_matched="[TAIL_WINDOW_FALLBACK]",
                    text=tail_text,
                    page_number=total_pages,
                    total_pages=total_pages,
                    char_start=tail_start,
                    char_end=len(last_page),
                    is_early_section=False,
                    extraction_method="tail_heuristic_window",
                )
                doc.conclusion_sections.append(fallback_sec)
                doc.all_sections.setdefault("conclusion_tail_fallback", []).append(fallback_sec)

        return doc

    @staticmethod
    def _normalize_delimiters(text: str) -> str:
        # Normalize non-breaking spaces, CRLF, form feeds, box characters, and table pipe borders
        cleaned = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"[│┃┆┇┊┋|]{1,2}", " \n ", cleaned)
        return cleaned

    def _extract_sections_from_text(
        self, text: str, page_num: int, total_pages: int, total_doc_len: int = 0
    ) -> List[ExtractedSection]:
        boundaries: List[Tuple[int, int, str, str]] = []

        # 1. Find conclusion headers
        for pat in self.CONCLUSION_HEADER_PATTERNS:
            for m in pat.finditer(text):
                boundaries.append((m.start(), m.end(), "conclusion", m.group("header").strip()))

        # 2. Find other standard cardiology headers
        for sec_name, pat in self.OTHER_SECTION_HEADERS.items():
            for m in pat.finditer(text):
                if not any(abs(m.start() - b[0]) < 8 for b in boundaries):
                    boundaries.append((m.start(), m.end(), sec_name, m.group(0).strip()))

        # 3. Find stop boundaries (signatures, footers, billing)
        for m in self.STOP_BOUNDARY_PATTERN.finditer(text):
            boundaries.append((m.start(), m.end(), "_stop_", m.group(0).strip()))

        boundaries.sort(key=lambda x: x[0])
        extracted: List[ExtractedSection] = []

        for i, (start_idx, content_start, sec_type, header_str) in enumerate(boundaries):
            if sec_type == "_stop_":
                continue
            # End index is next major section header, stop boundary, or end of page
            end_idx = len(text)
            for j in range(i + 1, len(boundaries)):
                next_start, _, next_type, _ = boundaries[j]
                # Merge: If current section is 'conclusion' and following header is 'plan' or 'recommendations',
                # include both blocks so staged PCI timing/vessel instructions in Plan are never truncated!
                if sec_type == "conclusion" and next_type in ("plan", "recommendations"):
                    continue
                end_idx = next_start
                break

            body = text[content_start:end_idx].strip(" :-\n\t")
            if not body:
                continue

            # Flag early section: appears on Page 1 of multi-page doc, or has substantive sections after it
            is_early = (
                (page_num == 1 and total_pages > 1)
                or (page_num < total_pages)
                or any(b[2] not in ("_stop_", "plan", "conclusion") for b in boundaries[i + 1 :])
            )

            extracted.append(
                ExtractedSection(
                    section_type=sec_type,
                    header_matched=header_str,
                    text=body,
                    page_number=page_num,
                    total_pages=total_pages,
                    char_start=start_idx,
                    char_end=end_idx,
                    is_early_section=is_early,
                    extraction_method="regex_header_boundary",
                )
            )

        return extracted
