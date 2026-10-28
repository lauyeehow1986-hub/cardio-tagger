---
name: cardio-section-sieve-architect
description: Architect and tune the multi-pass clinical PDF section parser and 6-tier cascading NLP sieve for Staged PCI and extensible cardiology concepts. Use whenever building or refining PDF section segmentation (Conclusion at end or earlier pages, multi-delimiter headers), Aho-Corasick lexical gates, MedSpaCy ConText assertion rules, or DuckDB 1M-PDF streaming checkpoints.
---
# Cardio Section & 6-Tier Sieve Architect

Build and verify the clinical PDF section segmenter and 6-tier cascading NLP extraction pipeline for 1,000 to 1,000,000+ cardiology reports within a 16 GB CPU RAM budget.

## Core Architecture Rules

1. **Multi-Pass Section Isolation (`section_parser.py`)**:
   - Never assume `CONCLUSION` is exclusively on the final page. Executive-summary catheterization templates (e.g., Epic Cupid, Philips Xper, GE Mac-Lab) frequently place `CONCLUSION` or `IMPRESSION / PLAN` on Page 1 above `PROCEDURAL DETAILS` and `HEMODYNAMICS`.
   - Normalize all delimiter variants before boundary matching:
     - Newline-delimited headers (`CONCLUSION
1. Two-vessel CAD...`)
     - Inline colon/dash headers (`Conclusion: Successful PCI to RCA; staged PCI to LAD in 4 weeks.`)
     - Numbered or Roman-numeral headers (`IV. CONCLUSION AND RECOMMENDATIONS:`)
     - Boxed or pipe-table headers (`| CONCLUSION | Plan for staged PCI to LCx |`)
   - When `CONCLUSION` is immediately followed by `PLAN` or `RECOMMENDATIONS`, merge both blocks into the active conclusion window so staged PCI timing/vessel instructions in `Plan:` are never cut off.
   - If a report has no explicit section header (e.g., short 1-page note or OCR-degraded header), extract a synthetic tail window covering the final 40% of the last page (`conclusion_tail_fallback`).

2. **6-Tier Cascading Sieve (`sieve_engine.py`)**:
   - **Tier 0 (PyMuPDF + DuckDB Checkpoint State)**: Extract native PDF text via `fitz` (`~1.5 ms/doc`). Trigger `rapidocr-onnxruntime` only on pages where `len(page.get_text().strip()) < 40` and images exist. Log every processed `pdf_path` and SHA-256 hash into DuckDB so 1M-PDF runs resume cleanly after interruption.
   - **Tier 1 (Aho-Corasick + Boundary Regex)**: Use `pyahocorasick` + compiled regexes from `cardio_concepts.yaml` to filter out negative sections in `<0.2 ms/doc`.
   - **Tier 2 (Clinical ConText Assertion)**: Classify every hit into `AFFIRMED_PLANNED`, `AFFIRMED_PERFORMED_INDEX`, `CONDITIONAL`, `HISTORICAL`, or `NEGATED`.
   - **Tier 3 (GLiNER-BioMed INT8 ONNX)**: Extract fine-grained spans (`Target Vessel`, `Staged Timeframe`, `Stent Type`, `Stenosis %`, `LVEF %`) on Tier-1/2 candidate sentences.
   - **Tier 4 (Fuzzy OCR & Static Embedding Sieve)**: Catch OCR errors (`stged PCl`) via RapidFuzz and synonym variants via lightweight static clinical embeddings.
   - **Tier 5 (Portable Local Ollama Arbitrator)**: Invoke local quantized LLM (`Qwen2.5-3B-Instruct-Q4_K_M` or `Llama-3.2-3B-Instruct-Q4_K_M`) **only** when Tier 2 flags `CONDITIONAL` or conflicting assertions (`<2%` of documents).

## Verification

Run the MCP tool `test_sieve_tiers_on_text` or execute `pytest portable_app/tests/test_sieve_pipeline.py` to confirm 100% precision/recall across early-section conclusions, newline delimiters, negated staged PCI, and multi-concept cardiology extraction.
