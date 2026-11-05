# fishlen

Measure trout and salamander lengths from tray photos, and review/correct the results.

```
web/      React + Vite + TypeScript UI (Photos home, Review workspace)
server/   FastAPI: REST API (contract at /docs), serves the built UI
fishlen/  Python library: data format, geometry, storage, prediction pipeline (fishlen/pipeline/), CLI
scripts/  one-off tools (import from the playground)
tests/    pytest (+ e2e_review.py, a browser test run by hand)
docs/     pipeline.md (START HERE to work on a stage), placeholders.md (what's weak), schema.md, decisions.md
models/   model files, git-ignored: keypoints/<name>/{model.onnx, meta.json}, sam2/
data/     project data, git-ignored: photos/, display/, thumbs/, fishlen.db
```

## Setup (once)

```bash
conda env create -f environment.yml
conda activate fishlen
pip install -e ".[ml,dev]"            # ml = torch, transformers, SAM2, onnxruntime; dev = pytest, selenium
(cd web && npm ci && npm run build)
```

**Model files are not in git** (the keypoint model is 114 MB, over GitHub's file limit). Put them in `models/`:

```
models/keypoints/hrnet_w32_dark_midline8_run2/{model.onnx, meta.json}
models/sam2/sam2.1_hiera_large.pt
```

On the OSU HPC, copy them from `/nfs/hpc/share/dasso/ai-capstone/app/models/`. Or rebuild the keypoint
model from an MMPose checkpoint with `scripts/export_keypoints_onnx.py`, and get SAM2 weights from
https://github.com/facebookresearch/sam2. Grounding DINO downloads itself from Hugging Face on first use.

Start a project from your own photos: run the server, then use **Add photos** in the UI.

## Run

```bash
conda activate fishlen
cd /nfs/hpc/share/dasso/ai-capstone/app
(cd web && npm run build)                      # after UI changes
uvicorn server.main:app --port 8000            # -> http://localhost:8000  (API contract: /docs)
```

UI development with hot reload: run the server as above, then `cd web && npm run dev` and open
http://localhost:5173 (it forwards /api to :8000).

## Prediction pipeline and per-stage evaluation

Install the model extras once: `pip install -e ".[ml,dev]"` (GPU recommended; the keypoint model also runs on CPU).

```bash
python -m fishlen.cli stages                    # implementations per stage, and which is selected
python -m fishlen.cli predict --status new --limit 20
python -m fishlen.cli eval ruler|detection|classifier|keypoints [--impl NAME] [--param key=value]
```

See **docs/pipeline.md** for adding a stage implementation and the evaluation loop. The keypoint model is
exported from MMPose with `scripts/export_keypoints_onnx.py` (mmpose env); `tests/test_keypoints_onnx.py`
checks the export reproduces MMPose exactly.

## Tests

```bash
pytest                                          # backend + UI/Python length parity
python tests/e2e_review.py http://localhost:8000 /tmp/shots   # browser tests (review, labeling);
python tests/e2e_label.py  http://localhost:8000 /tmp/shots   # run them on a throwaway data copy
python tests/e2e_predict.py http://localhost:8000 /tmp/shots new.jpg existing.jpg   # real models, GPU
```

## Data

`FISHLEN_DATA` picks the project folder (default `data/`). First-time import from the playground:
`python scripts/import_playground.py --playground ../playground --data data`.
