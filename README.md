# aquatic-vertebrates (fishlen)

Measure trout and salamander lengths from tray photos. Upload photos, the pipeline predicts each animal's
midline and the ruler scale, and you review, fix or label them by hand. Reviewed photos become the ground
truth for improving each part of the pipeline.

## Setup

Easiest: open this folder in Claude Code and ask *"set up this repo and run the tool"*.

Or by hand, on a GPU node:

```bash
conda env create -f environment.yml && conda activate fishlen
pip install -e ".[ml,dev]"
(cd web && npm ci && npm run build)
```

Model files aren't in git (too big). Ask Soham for the `models/` folder and put it in the repo root.

## Run

```bash
conda activate fishlen
uvicorn server.main:app --port 8000      # then open http://localhost:8000
```

## Work on your part of the pipeline

The pipeline is five swappable stages: detector, segmenter, classifier, ruler, keypoints.

1. Add your version as one file in `fishlen/pipeline/stages/`.
2. Score it: `python -m fishlen.cli eval <stage> --impl <your_version>`
3. Use it: set it in `data/pipeline.json`.

Read **[docs/pipeline.md](docs/pipeline.md)** first. **[docs/placeholders.md](docs/placeholders.md)** lists
what's weak today and the scores to beat. More: [development](docs/development.md) ·
[data format](docs/schema.md) · [design decisions](docs/decisions.md).
