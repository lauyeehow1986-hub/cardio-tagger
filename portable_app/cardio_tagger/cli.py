#!/usr/bin/env python3
"""
Portable Windows CLI Entrypoint for Cardio-PDF-Tagger.
Optimized for 1,000 to 1,000,000+ PDFs within a strict 16 GB RAM CPU limit on non-admin Windows.
Features:
  - Bounded multiprocessing.Pool with worker recycling (maxtasksperchild=500)
  - Embedded DuckDB streaming checkpoints & instant resumption (--resume)
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
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

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


class DuckDBCheckpointManager:
    """
    Manages DuckDB checkpointing and state persistence to support
    instant resumption across 1,000,000+ PDF processing runs.
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
        self.conn.execute(
            """
            INSERT OR REPLACE INTO checkpoints (pdf_path, file_size, mtime_ns, result_json)
            VALUES (?, ?, ?, ?)
            """,
            (item["pdf_path"], item["file_size"], item["mtime_ns"], json.dumps(item)),
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
        description="1M-PDF Clinical Cardiology & Staged PCI Portable Tagger (16GB RAM Non-Admin Windows)",
    )
    parser.add_argument("--input-dir", required=True, help="Directory of PDFs (or recursive glob)")
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
        help="Optional subset of concept keys. Default: all.",
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

    ontology_path = Path(args.ontology)
    ontology = yaml.safe_load(ontology_path.read_text(encoding="utf-8"))

    in_dir = Path(args.input_dir)
    all_files = sorted(
        [p for p in in_dir.rglob("*") if p.suffix.lower() in (".pdf", ".txt", ".md")]
    )

    print(f"[Cardio-Tagger] Discovered {len(all_files)} documents in {in_dir}")

    checkpoint_mgr = DuckDBCheckpointManager(args.checkpoint_db)
    completed_keys = set()
    if args.resume:
        completed_keys = checkpoint_mgr.get_completed_keys()
        print(f"[Cardio-Tagger] Resuming: {len(completed_keys)} documents already verified in checkpoint.duckdb")

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
    t_start = time.perf_counter()

    csv_fields = [
        "pdf_path",
        "total_pages",
        "conclusion_found",
        "conclusion_in_early_section",
        "staged_pci_detected",
        "staged_pci_status",
        "staged_pci_vessels",
        "staged_pci_timeframe",
        "staged_pci_confidence",
        "matched_concepts_count",
        "peak_tier_used",
        "processing_ms",
        "used_ocr_fallback",
    ]

    all_results: List[Dict[str, Any]] = []

    # Write headers if starting fresh
    mode = "a" if args.resume and os.path.exists(args.output_csv) else "w"
    with open(args.output_csv, mode, newline="", encoding="utf-8") as f_csv, open(
        args.output_jsonl, mode, encoding="utf-8"
    ) as f_jsonl:
        writer = csv.DictWriter(f_csv, fieldnames=csv_fields)
        if mode == "w":
            writer.writeheader()

        if tasks:
            # Bounded pool recycling workers every 500 tasks to prevent memory fragmentation
            with mp.Pool(
                processes=args.workers,
                initializer=_init_worker,
                initargs=(ontology, True, args.enable_ollama),
                maxtasksperchild=500,
            ) as pool:
                for idx, res_dict in enumerate(pool.imap_unordered(_process_single_doc, tasks, chunksize=16), 1):
                    all_results.append(res_dict)
                    checkpoint_mgr.save_checkpoint(res_dict)

                    writer.writerow(
                        {
                            "pdf_path": res_dict["pdf_path"],
                            "total_pages": res_dict["total_pages"],
                            "conclusion_found": res_dict["conclusion_found"],
                            "conclusion_in_early_section": res_dict["conclusion_in_early_section"],
                            "staged_pci_detected": res_dict["staged_pci_detected"],
                            "staged_pci_status": res_dict["staged_pci_status"],
                            "staged_pci_vessels": ";".join(res_dict["staged_pci_vessels"]),
                            "staged_pci_timeframe": res_dict["staged_pci_timeframe"] or "",
                            "staged_pci_confidence": res_dict["staged_pci_confidence"],
                            "matched_concepts_count": len(res_dict["all_concept_matches"]),
                            "peak_tier_used": res_dict["peak_tier_used"],
                            "processing_ms": res_dict["processing_ms"],
                            "used_ocr_fallback": res_dict.get("used_ocr_fallback", False),
                        }
                    )
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
    print(
        f"[Cardio-Tagger] Finished processing {len(tasks)} documents in {elapsed}s "
        f"({round((len(tasks) / max(elapsed, 0.001)), 1)} docs/sec) -> {args.output_csv}"
    )


if __name__ == "__main__":
    main()
