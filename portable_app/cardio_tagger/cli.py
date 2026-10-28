#!/usr/bin/env python3
"""
Portable Windows CLI Entrypoint for Cardio-PDF-Tagger.
Optimized for 1,000 to 1,000,000+ PDFs or CSV clinical notes within a strict 16 GB RAM CPU limit on non-admin Windows.

Features:
  - Supports both PDF folder directories (--input-dir) and tabular CSV files (--input-csv)
  - Auto-detection of text and ID columns for clinical note tables
  - Bounded multiprocessing.Pool with worker recycling (maxtasksperchild=500)
  - Embedded DuckDB streaming checkpoints & instant resumption (--resume)
  - Full-spectrum cardiology ontology support (14+ conditions) with dynamic concept columns
  - Multi-format export: CSV, JSONL, and columnar Parquet
  - Automatic RapidOCR fallback for scanned catheterization PDFs
"""
import argparse
import csv
import json
import multiprocessing as mp
import os
import sys
import time
import zlib
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from cardio_tagger.section_parser import ClinicalSectionParser, ParsedDocument
    from cardio_tagger.sieve_engine import CascadingCardioSieve, DocumentTagResult
else:
    from .section_parser import ClinicalSectionParser, ParsedDocument
    from .sieve_engine import CascadingCardioSieve, DocumentTagResult

try:
    import duckdb
except ImportError:
    duckdb = None

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = None
    pq = None


TEXT_CANDIDATE_NAMES = [
    "text",
    "report_text",
    "note_text",
    "clinical_note",
    "clinical_text",
    "impression",
    "conclusion",
    "narrative",
    "content",
    "note",
    "body",
    "report",
    "findings",
]

ID_CANDIDATE_NAMES = [
    "id",
    "doc_id",
    "row_id",
    "report_id",
    "note_id",
    "patient_id",
    "mrn",
    "accession_number",
    "study_id",
    "encounter_id",
]

PRIORITY_ORDER = [
    "AFFIRMED_PLANNED",
    "AFFIRMED_PERFORMED_INDEX",
    "AFFIRMED",
    "CONDITIONAL",
    "HISTORICAL",
    "NEGATED",
]


def _init_worker(ontology_dict: Dict[str, Any], enable_gliner: bool, enable_ollama: bool):
    global _worker_sieve, _worker_parser
    _worker_parser = ClinicalSectionParser(enable_ocr=True)
    _worker_sieve = CascadingCardioSieve(
        ontology=ontology_dict,
        enable_gliner=enable_gliner,
        enable_ollama=enable_ollama,
    )


def _extract_raw_pages(pdf_path_str: str) -> Tuple[List[str], bool]:
    path = Path(pdf_path_str)
    if path.suffix.lower() in (".txt", ".md"):
        raw = path.read_text(encoding="utf-8", errors="ignore")
        pages = raw.split("\f") if "\f" in raw else [raw]
        return pages, False

    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            fitz = None

    if fitz is not None:
        doc = fitz.open(pdf_path_str)
        pages = []
        used_ocr = False
        for page in doc:
            text = page.get_text("text")
            if len(text.strip()) < 40 and len(page.get_images()) > 0:
                ocr = _worker_parser._get_ocr_engine()
                if ocr:
                    pix = page.get_pixmap()
                    img_bytes = pix.tobytes("png")
                    ocr_res, _ = ocr(img_bytes)
                    if ocr_res:
                        ocr_text = "\n".join([line[1] for line in ocr_res])
                        if len(ocr_text.strip()) > len(text.strip()):
                            text = ocr_text
                            used_ocr = True
            pages.append(text)
        doc.close()
        return pages, used_ocr

    try:
        import pypdf
        reader = pypdf.PdfReader(pdf_path_str)
        return [p.extract_text() or "" for p in reader.pages], False
    except Exception as exc:
        return [f"[ERROR_READING_PDF: {exc}]"], False


def _process_single_doc(
    item: Tuple[str, Optional[List[str]], bool]
) -> Dict[str, Any]:
    file_path_str, target_concepts, search_all = item
    path = Path(file_path_str)
    try:
        stat = path.stat()
        file_size = stat.st_size
        mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))
    except Exception:
        file_size = 0
        mtime_ns = 0

    pages, used_ocr = _extract_raw_pages(file_path_str)

    res = _worker_sieve.evaluate_document(
        pdf_path=file_path_str,
        page_texts=pages,
        target_concepts=target_concepts,
        search_all_sections=search_all,
        used_ocr=used_ocr,
    )

    data = asdict(res)
    data["file_size"] = file_size
    data["mtime_ns"] = mtime_ns
    return data


def _process_single_csv_row(
    item: Tuple[str, str, Optional[List[str]], bool, Dict[str, Any], int, int]
) -> Dict[str, Any]:
    doc_id, text, target_concepts, search_all, orig_row, file_size, mtime_ns = item
    pages = [text] if text else [""]

    res = _worker_sieve.evaluate_document(
        pdf_path=doc_id,
        page_texts=pages,
        target_concepts=target_concepts,
        search_all_sections=search_all,
        used_ocr=False,
    )

    data = asdict(res)
    data["file_size"] = file_size
    data["mtime_ns"] = mtime_ns
    data["_orig_row"] = orig_row
    return data


def _format_concept_fields(
    res_dict: Dict[str, Any], ontology_concepts: Dict[str, Any]
) -> Dict[str, Any]:
    matches_by_id: Dict[str, List[Any]] = {}
    for m in res_dict.get("all_concept_matches", []):
        cid = m.get("concept_id") if isinstance(m, dict) else getattr(m, "concept_id", None)
        if cid:
            matches_by_id.setdefault(cid, []).append(m)

    out: Dict[str, Any] = {}
    detected_ids = set()

    for ckey, cdef in ontology_concepts.items():
        cid = cdef.get("id", ckey)
        matches = matches_by_id.get(cid, [])
        if matches:
            def _sort_key(item):
                st = item.get("assertion_status") if isinstance(item, dict) else getattr(item, "assertion_status", "NONE")
                idx = PRIORITY_ORDER.index(st) if st in PRIORITY_ORDER else 99
                conf = item.get("confidence", 0.0) if isinstance(item, dict) else getattr(item, "confidence", 0.0)
                return (idx, -conf)

            matches.sort(key=_sort_key)
            best_m = matches[0]
            status = best_m.get("assertion_status") if isinstance(best_m, dict) else getattr(best_m, "assertion_status", "AFFIRMED")
            is_detected = status in ("AFFIRMED_PLANNED", "AFFIRMED_PERFORMED_INDEX", "AFFIRMED", "CONDITIONAL")
            if is_detected:
                detected_ids.add(cid)
            out[f"has_{ckey}"] = is_detected
            out[f"{ckey}_status"] = status
        else:
            out[f"has_{ckey}"] = False
            out[f"{ckey}_status"] = "NONE"

    out["detected_cardio_concepts"] = ";".join(sorted(detected_ids))
    return out


def _detect_column(fieldnames: List[str], requested: Optional[str], candidates: List[str]) -> Optional[str]:
    if requested:
        for col in fieldnames:
            if col.strip().lower() == requested.strip().lower():
                return col
        return requested
    lower_map = {col.strip().lower(): col for col in fieldnames}
    for cand in candidates:
        if cand in lower_map:
            return lower_map[cand]
    return None


class DuckDBCheckpointManager:
    """
    Manages DuckDB checkpointing and state persistence to support
    instant resumption across 1,000,000+ PDF or CSV processing runs.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.enabled = duckdb is not None
        if self.enabled:
            self.conn = duckdb.connect(self.db_path)
            self._init_tables()

    def _init_tables(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                pdf_path VARCHAR,
                file_size BIGINT,
                mtime_ns BIGINT,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                result_json VARCHAR,
                PRIMARY KEY (pdf_path, file_size, mtime_ns)
            )
            """
        )

    def get_completed_keys(self) -> set:
        if not self.enabled:
            return set()
        rows = self.conn.execute(
            "SELECT pdf_path, file_size, mtime_ns FROM checkpoints"
        ).fetchall()
        return {(r[0], r[1], r[2]) for r in rows}

    def save_checkpoint(self, item: Dict[str, Any]):
        if not self.enabled:
            return
        doc_key = item.get("pdf_path") or item.get("doc_id", "unknown")
        self.conn.execute(
            """
            INSERT OR REPLACE INTO checkpoints (pdf_path, file_size, mtime_ns, result_json)
            VALUES (?, ?, ?, ?)
            """,
            (doc_key, item["file_size"], item["mtime_ns"], json.dumps(item)),
        )

    def export_parquet(self, output_parquet_path: str, jsonl_path: Optional[str] = None):
        if not self.enabled:
            return
        if os.path.exists(output_parquet_path):
            try:
                os.remove(output_parquet_path)
            except Exception:
                pass
        abs_parquet = os.path.abspath(output_parquet_path).replace("\\", "/")
        if jsonl_path and os.path.exists(jsonl_path) and os.path.getsize(jsonl_path) > 0:
            abs_jsonl = os.path.abspath(jsonl_path).replace("\\", "/")
            self.conn.execute(
                f"COPY (SELECT * FROM read_json_auto('{abs_jsonl}')) TO '{abs_parquet}' (FORMAT PARQUET)"
            )
        else:
            self.conn.execute(
                f"COPY (SELECT pdf_path, file_size, mtime_ns, processed_at, result_json FROM checkpoints) TO '{abs_parquet}' (FORMAT PARQUET)"
            )

    def close(self):
        if self.enabled:
            self.conn.close()


def main():
    parser = argparse.ArgumentParser(
        prog="cardio-tagger",
        description="1M-PDF & CSV Clinical Cardiology & Staged PCI Portable Tagger (16GB RAM Non-Admin Windows)",
    )
    parser.add_argument("--input-dir", default=None, help="Directory of PDFs (or recursive glob)")
    parser.add_argument("--input-csv", default=None, help="Input CSV file with clinical reports/notes")
    parser.add_argument("--text-column", default=None, help="Column name in CSV containing report text")
    parser.add_argument("--id-column", default=None, help="Column name in CSV containing row/document ID")
    parser.add_argument("--output-csv", default="staged_pci_results.csv", help="Output CSV summary path")
    parser.add_argument("--output-jsonl", default="staged_pci_detailed.jsonl", help="Detailed JSONL path")
    parser.add_argument("--output-parquet", default="staged_pci_results.parquet", help="Columnar Parquet path")
    parser.add_argument(
        "--checkpoint-db",
        default="checkpoint.duckdb",
        help="Embedded DuckDB checkpoint database path",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from DuckDB checkpoint, skipping already processed documents",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel worker processes (default: 4, bounded for 16GB RAM)",
    )
    parser.add_argument(
        "--ontology",
        default=str(Path(__file__).parent / "ontology" / "cardio_concepts.yaml"),
        help="Path to extensible cardiology ontology YAML",
    )
    parser.add_argument(
        "--concepts",
        nargs="*",
        default=None,
        help="Optional subset of concept keys. Default: all available concepts.",
    )
    parser.add_argument(
        "--all-sections",
        action="store_true",
        help="Scan all clinical sections in addition to Conclusion/Impression/Plan",
    )
    parser.add_argument(
        "--enable-ollama",
        action="store_true",
        help="Enable local Ollama arbitrator for ambiguous conditional sentences",
    )
    args = parser.parse_args()

    if not args.input_dir and not args.input_csv:
        parser.error("Either --input-dir <DIR> or --input-csv <FILE> must be provided.")

    ontology_path = Path(args.ontology)
    ontology = yaml.safe_load(ontology_path.read_text(encoding="utf-8"))
    all_ontology_concepts = ontology.get("concepts", {})

    if args.concepts:
        selected_concepts = {k: v for k, v in all_ontology_concepts.items() if k in args.concepts}
        if not selected_concepts:
            print(f"[Cardio-Tagger WARNING] None of {args.concepts} found in ontology. Falling back to all.")
            selected_concepts = all_ontology_concepts
    else:
        selected_concepts = all_ontology_concepts

    print(f"[Cardio-Tagger] Active Ontology Concepts ({len(selected_concepts)}): {', '.join(selected_concepts.keys())}")

    checkpoint_mgr = DuckDBCheckpointManager(args.checkpoint_db)
    completed_keys = set()
    if args.resume:
        completed_keys = checkpoint_mgr.get_completed_keys()
        print(f"[Cardio-Tagger] Resuming: {len(completed_keys)} records already verified in checkpoint.duckdb")

    t_start = time.perf_counter()

    # Mode 1: Tabular CSV Input Mode
    if args.input_csv:
        csv_in_path = Path(args.input_csv)
        if not csv_in_path.exists():
            sys.exit(f"[Cardio-Tagger ERROR] CSV input file not found: {csv_in_path}")

        # Detect encoding
        raw_head = csv_in_path.read_bytes()[:4096]
        enc = "utf-8-sig" if raw_head.startswith(b"\xef\xbb\xbf") else "utf-8"

        with open(csv_in_path, "r", encoding=enc, errors="ignore") as f_in:
            reader = csv.DictReader(f_in)
            if not reader.fieldnames:
                sys.exit(f"[Cardio-Tagger ERROR] Empty or invalid CSV file: {csv_in_path}")

            text_col = _detect_column(reader.fieldnames, args.text_column, TEXT_CANDIDATE_NAMES)
            if not text_col:
                sys.exit(
                    f"[Cardio-Tagger ERROR] Could not auto-detect text column in CSV.\n"
                    f"Found columns: {reader.fieldnames}\n"
                    f"Please specify --text-column <col_name>."
                )

            id_col = _detect_column(reader.fieldnames, args.id_column, ID_CANDIDATE_NAMES)
            print(f"[Cardio-Tagger] CSV Text Column: '{text_col}' | ID Column: '{id_col or '[row_index]'}'")

            tasks = []
            skipped_count = 0
            for idx, row in enumerate(reader, 1):
                doc_id = row.get(id_col) if id_col else None
                if not doc_id:
                    doc_id = f"row_{idx}"
                text = row.get(text_col, "") or ""
                file_size = len(text)
                mtime_ns = zlib.crc32(text.encode("utf-8", errors="ignore"))

                key = (doc_id, file_size, mtime_ns)
                if args.resume and key in completed_keys:
                    skipped_count += 1
                    continue

                tasks.append((doc_id, text, args.concepts, args.all_sections, row, file_size, mtime_ns))

        if skipped_count > 0:
            print(f"[Cardio-Tagger] Skipped {skipped_count} previously processed rows via DuckDB checkpoint.")

        print(f"[Cardio-Tagger] Processing {len(tasks)} CSV rows with {args.workers} workers (maxtasksperchild=500)...")

        tagger_fields = [
            "staged_pci_detected",
            "staged_pci_status",
            "staged_pci_vessels",
            "staged_pci_timeframe",
            "staged_pci_confidence",
            "lvef_extracted",
            "lvef_numeric",
            "lvef_method",
            "lvef_section",
            "detected_cardio_concepts",
            "conclusion_found",
            "peak_tier_used",
            "processing_ms",
        ]
        concept_fields = []
        for ckey in selected_concepts.keys():
            concept_fields.extend([f"has_{ckey}", f"{ckey}_status"])

        extra_fields = [f for f in tagger_fields + concept_fields if f not in reader.fieldnames]
        out_fields = list(reader.fieldnames) + extra_fields

        mode = "a" if args.resume and os.path.exists(args.output_csv) else "w"
        with open(args.output_csv, mode, newline="", encoding="utf-8") as f_csv, open(
            args.output_jsonl, mode, encoding="utf-8"
        ) as f_jsonl:
            writer = csv.DictWriter(f_csv, fieldnames=out_fields)
            if mode == "w":
                writer.writeheader()

            if tasks:
                with mp.Pool(
                    processes=args.workers,
                    initializer=_init_worker,
                    initargs=(ontology, True, args.enable_ollama),
                    maxtasksperchild=500,
                ) as pool:
                    for idx, res_dict in enumerate(
                        pool.imap_unordered(_process_single_csv_row, tasks, chunksize=32), 1
                    ):
                        checkpoint_mgr.save_checkpoint(res_dict)
                        orig = res_dict.get("_orig_row", {})
                        concept_dict = _format_concept_fields(res_dict, selected_concepts)

                        row_out = dict(orig)
                        row_out["staged_pci_detected"] = res_dict["staged_pci_detected"]
                        row_out["staged_pci_status"] = res_dict["staged_pci_status"]
                        row_out["staged_pci_vessels"] = ";".join(res_dict["staged_pci_vessels"])
                        row_out["staged_pci_timeframe"] = res_dict["staged_pci_timeframe"] or ""
                        row_out["staged_pci_confidence"] = res_dict["staged_pci_confidence"]
                        row_out["lvef_extracted"] = res_dict.get("lvef_extracted", "NONE")
                        row_out["lvef_numeric"] = res_dict.get("lvef_numeric")
                        row_out["lvef_method"] = res_dict.get("lvef_method", "NONE")
                        row_out["lvef_section"] = res_dict.get("lvef_section", "NONE")
                        row_out["detected_cardio_concepts"] = concept_dict["detected_cardio_concepts"]
                        row_out["conclusion_found"] = res_dict["conclusion_found"]
                        row_out["peak_tier_used"] = res_dict["peak_tier_used"]
                        row_out["processing_ms"] = res_dict["processing_ms"]
                        row_out.update(concept_dict)

                        writer.writerow(row_out)
                        res_copy = dict(res_dict)
                        res_copy.pop("_orig_row", None)
                        f_jsonl.write(json.dumps(res_copy) + "\n")

                        if idx % 500 == 0 or idx == len(tasks):
                            f_csv.flush()
                            f_jsonl.flush()
                            pct = round((idx / len(tasks)) * 100, 1)
                            print(f"[Cardio-Tagger] Progress: {idx}/{len(tasks)} ({pct}%) completed...")

    # Mode 2: Directory of PDFs Mode
    else:
        in_dir = Path(args.input_dir)
        all_files = sorted(
            [p for p in in_dir.rglob("*") if p.suffix.lower() in (".pdf", ".txt", ".md")]
        )
        print(f"[Cardio-Tagger] Discovered {len(all_files)} documents in {in_dir}")

        tasks = []
        skipped_count = 0
        for p in all_files:
            try:
                stat = p.stat()
                key = (str(p), stat.st_size, getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)))
            except Exception:
                key = (str(p), 0, 0)

            if args.resume and key in completed_keys:
                skipped_count += 1
                continue
            tasks.append((str(p), args.concepts, args.all_sections))

        if skipped_count > 0:
            print(f"[Cardio-Tagger] Skipped {skipped_count} previously processed documents via DuckDB checkpoint.")

        print(f"[Cardio-Tagger] Processing {len(tasks)} documents with {args.workers} workers (maxtasksperchild=500)...")

        base_fields = [
            "pdf_path",
            "total_pages",
            "conclusion_found",
            "conclusion_in_early_section",
            "staged_pci_detected",
            "staged_pci_status",
            "staged_pci_vessels",
            "staged_pci_timeframe",
            "staged_pci_confidence",
            "lvef_extracted",
            "lvef_numeric",
            "lvef_method",
            "lvef_section",
            "detected_cardio_concepts",
            "matched_concepts_count",
            "peak_tier_used",
            "processing_ms",
            "used_ocr_fallback",
        ]
        concept_fields = []
        for ckey in selected_concepts.keys():
            concept_fields.extend([f"has_{ckey}", f"{ckey}_status"])
        csv_fields = base_fields + concept_fields

        mode = "a" if args.resume and os.path.exists(args.output_csv) else "w"
        with open(args.output_csv, mode, newline="", encoding="utf-8") as f_csv, open(
            args.output_jsonl, mode, encoding="utf-8"
        ) as f_jsonl:
            writer = csv.DictWriter(f_csv, fieldnames=csv_fields)
            if mode == "w":
                writer.writeheader()

            if tasks:
                with mp.Pool(
                    processes=args.workers,
                    initializer=_init_worker,
                    initargs=(ontology, True, args.enable_ollama),
                    maxtasksperchild=500,
                ) as pool:
                    for idx, res_dict in enumerate(pool.imap_unordered(_process_single_doc, tasks, chunksize=16), 1):
                        checkpoint_mgr.save_checkpoint(res_dict)
                        concept_dict = _format_concept_fields(res_dict, selected_concepts)

                        row_data = {
                            "pdf_path": res_dict["pdf_path"],
                            "total_pages": res_dict["total_pages"],
                            "conclusion_found": res_dict["conclusion_found"],
                            "conclusion_in_early_section": res_dict["conclusion_in_early_section"],
                            "staged_pci_detected": res_dict["staged_pci_detected"],
                            "staged_pci_status": res_dict["staged_pci_status"],
                            "staged_pci_vessels": ";".join(res_dict["staged_pci_vessels"]),
                            "staged_pci_timeframe": res_dict["staged_pci_timeframe"] or "",
                            "staged_pci_confidence": res_dict["staged_pci_confidence"],
                            "lvef_extracted": res_dict.get("lvef_extracted", "NONE"),
                            "lvef_numeric": res_dict.get("lvef_numeric"),
                            "lvef_method": res_dict.get("lvef_method", "NONE"),
                            "lvef_section": res_dict.get("lvef_section", "NONE"),
                            "detected_cardio_concepts": concept_dict["detected_cardio_concepts"],
                            "matched_concepts_count": len(res_dict["all_concept_matches"]),
                            "peak_tier_used": res_dict["peak_tier_used"],
                            "processing_ms": res_dict["processing_ms"],
                            "used_ocr_fallback": res_dict.get("used_ocr_fallback", False),
                        }
                        row_data.update(concept_dict)
                        writer.writerow(row_data)
                        f_jsonl.write(json.dumps(res_dict) + "\n")

                        if idx % 500 == 0 or idx == len(tasks):
                            f_csv.flush()
                            f_jsonl.flush()
                            pct = round((idx / len(tasks)) * 100, 1)
                            print(f"[Cardio-Tagger] Progress: {idx}/{len(tasks)} ({pct}%) completed...")

    # Parquet export
    if args.output_parquet and checkpoint_mgr.enabled:
        try:
            checkpoint_mgr.export_parquet(args.output_parquet, jsonl_path=args.output_jsonl)
            print(f"[Cardio-Tagger] Exported Parquet to {args.output_parquet}")
        except Exception as exc:
            print(f"[Cardio-Tagger] Note: Parquet export via DuckDB encountered: {exc}")

    checkpoint_mgr.close()
    elapsed = round(time.perf_counter() - t_start, 3)
    num_processed = len(tasks)
    print(
        f"[Cardio-Tagger] Finished processing {num_processed} records in {elapsed}s "
        f"({round((num_processed / max(elapsed, 0.001)), 1)} records/sec) -> {args.output_csv}"
    )


if __name__ == "__main__":
    main()
