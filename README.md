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

**Model files are optional.** Without them the tool still runs: labeling and review work fully, and
predictions fall back to stages that need no trained model (lower quality). To get better predictions:

- SAM2 masks + automatic ruler: `mkdir -p models/sam2 && curl -L -o models/sam2/sam2.1_hiera_large.pt https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt`
- Keypoint model: train your own and export it (see [docs/development.md](docs/development.md)), or skip it.
- Grounding DINO downloads itself on first use.

## Run

```bash
conda activate fishlen
uvicorn server.main:app --port 8000      # then open http://localhost:8000
```

## What's incomplete

These are the parts we need to build. Each is a stage you can work on in isolation.

| Needed | Why | Today |
|---|---|---|
| **Robust classifier** (trout vs salamander, …) | species is reported per animal | zero-shot stand-in: 1 of 29 salamanders right |
| **Mask / cropper for the keypoint model** | neighbors in the crop confuse the midline on touching or overlapping fish | rectangular crops; worst length error 27 % on overlaps |
| **Segmentation in the labeler** | ground truth for masks and overlap separation; today the tool only labels midlines | not started |
| **Ruler detection / classification** | the scale multiplies every length; must handle glare, covered rulers, other ruler types | tick-mark reader, fails when covered; no hand-set rulers to score it yet |

Full list with scores: [docs/placeholders.md](docs/placeholders.md).

## Work on your part

The pipeline is five swappable stages: detector, segmenter, classifier, ruler, keypoints.

1. Add your version as one file in `fishlen/pipeline/stages/`.
2. Score it: `python -m fishlen.cli eval <stage> --impl <your_version>`
3. Use it: set it in `data/pipeline.json`.

Read **[docs/pipeline.md](docs/pipeline.md)** first. More: [development](docs/development.md) ·
[data format](docs/schema.md) · [design decisions](docs/decisions.md).
