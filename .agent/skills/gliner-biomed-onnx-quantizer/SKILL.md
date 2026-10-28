---
name: gliner-biomed-onnx-quantizer
description: Export and dynamically quantize GLiNER-BioMed models (Ihor/gliner-biomed-bi-small-v1.0 or Ihor/gliner-biomed-base-v1.0) to INT8 ONNX format for CPU-only Windows inference under 500 MB RAM. Use when preparing local zero-shot biomedical NER weights for the portable Windows bundle.
---
# GLiNER-BioMed INT8 ONNX Quantizer

Convert Hugging Face PyTorch weights of `GLiNER-BioMed` into an offline, CPU-optimized INT8 ONNX model directory that runs without internet access or admin rights on a 16 GB RAM Windows PC.

## Model Selection for 16 GB RAM CPU Target

- **Default High-Throughput Model**: `Ihor/gliner-biomed-bi-small-v1.0` (Bi-encoder architecture: pre-computes cardiology entity label embeddings once at startup, yielding 3-4x faster CPU inference and `<380 MB` RAM).
- **High-Accuracy Alternative**: `Ihor/gliner-biomed-base-v1.0` (`~520 MB` RAM in INT8 ONNX).

## Workflow

1. Run `scripts/export_int8_onnx.py` on the unrestricted Windows development machine.
2. Verify that `model_quantized.onnx`, `tokenizer.json`, and `gliner_config.json` are saved inside `dist/cardio-tagger-portable/models/gliner_biomed_int8/`.
3. Configure `onnxruntime.SessionOptions()` in worker processes with:
   - `intra_op_num_threads = 2`
   - `inter_op_num_threads = 1`
   - `execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL`
   - `graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL`
