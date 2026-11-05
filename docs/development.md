# Development

## Layout

```
web/      React + Vite + TypeScript UI (Photos home, Review workspace)
server/   FastAPI: REST API (contract at http://localhost:8000/docs), serves the built UI
fishlen/  Python library: data format, geometry, storage, prediction pipeline (fishlen/pipeline/), CLI
scripts/  one-off tools: import from the playground, export a keypoint model to ONNX
tests/    pytest, plus browser tests (e2e_*.py) run by hand
models/   model files (git-ignored): keypoints/<name>/{model.onnx, meta.json}, sam2/sam2.1_hiera_large.pt
data/     project data (git-ignored): photos/, display/, thumbs/, fishlen.db, pipeline.json, evals/
```

## UI with hot reload

Run the server, then `cd web && npm run dev` and open http://localhost:5173 (it forwards /api to :8000).
Run `npm run build` before using the UI through the server on :8000.

## Command line

```bash
python -m fishlen.cli stages                           # implementations per stage, and which is selected
python -m fishlen.cli predict --status new --limit 20  # predict without the UI
python -m fishlen.cli eval ruler|detection|classifier|keypoints [--impl NAME] [--param key=value]
```

## Tests

```bash
pytest                                                    # backend, UI/Python length parity, ONNX vs MMPose
python tests/e2e_review.py  http://localhost:8000 /tmp/shots                       # browser tests: run on a
python tests/e2e_label.py   http://localhost:8000 /tmp/shots                       # throwaway copy of data/
python tests/e2e_predict.py http://localhost:8000 /tmp/shots new.jpg existing.jpg  # real models, GPU
```

## Models

- Keypoints: exported from an MMPose checkpoint with `scripts/export_keypoints_onnx.py` (run in an MMPose
  environment). `tests/test_keypoints_onnx.py` checks the export reproduces MMPose.
- SAM2 weights: https://github.com/facebookresearch/sam2 (`sam2.1_hiera_large.pt`), or set
  `FISHLEN_SAM2_CHECKPOINT`.
- Grounding DINO downloads from Hugging Face on first use.

## Data

`FISHLEN_DATA` picks the project folder (default `data/`). One-time import from the playground:
`python scripts/import_playground.py --playground ../playground --data data`.
