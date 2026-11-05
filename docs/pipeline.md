# Working on one pipeline stage

The prediction pipeline is five stages with fixed contracts (`fishlen/pipeline/base.py`). Each can be
developed, swapped and scored on its own; the review tool supplies the ground truth.

| Stage | Input → output | Baseline (`impl`) | Owner |
|---|---|---|---|
| `detector` | photo → boxes + label + score | `grounding_dino` | |
| `segmenter` | photo + boxes → masks (clean crops, overlap separation) | `sam2_box` | segmentation |
| `classifier` | photo + boxes → species (+ scores) | `gdino_crop` | classification |
| `ruler` | photo → ruler (two points + real distance) or None | `ticks_v1` | ruler detection |
| `keypoints` | photo + boxes → midline points + scores | `onnx_topdown` | keypoints |

## The loop

1. **Write an implementation**: add a file in `fishlen/pipeline/stages/`:

   ```python
   from ..registry import register
   from ...schema import Ruler

   @register('ruler', 'my_ruler')
   class MyRuler:
       version = '1'                       # bump when behaviour changes; it's recorded on every prediction
       def __init__(self, threshold=0.5):  # anything here is settable from config / CLI
           self.threshold = threshold
       def find(self, image):              # image: RGB uint8 (H, W, 3), EXIF-rotated
           ...
           return Ruler(p1=(x1, y1), p2=(x2, y2), length_mm=150, source='auto', method='my_ruler',
                        confidence=score, needs_check=score < self.threshold)
   ```

   Shared heavy models (Grounding DINO, SAM2) are in `pipeline/shared.py`, loaded once per process.

2. **Score it on its own** against reviewed photos:

   ```bash
   python -m fishlen.cli eval ruler --impl my_ruler --param threshold=0.7
   python -m fishlen.cli eval detection --impl grounding_dino --segmenter my_segmenter
   python -m fishlen.cli eval classifier --impl my_classifier
   python -m fishlen.cli eval keypoints --param model=models/keypoints/<new export>
   ```

   Every run prints a summary and saves per-photo/per-animal rows to `data/evals/<stage>-<impl>-<time>.csv`,
   so two versions can be compared row by row. What each evaluation isolates:

   - **ruler**: px/mm vs rulers a person set (rulers whose distance came from the tick detector are excluded).
   - **detection**: detector + segmenter vs reviewed animals: found / partial (mask cuts the animal) / missed /
     merged (one detection covers 2+ animals) / false. Uses masks when the segmenter gives them.
   - **classifier**: species from **ground-truth boxes**, so detection errors don't count against it.
   - **keypoints**: length error from **ground-truth boxes**; photos the model was trained on are left out.

3. **Use it**: select it for a project in `data/pipeline.json` (only the stages you change):

   ```json
   {"ruler": {"impl": "my_ruler", "threshold": 0.7}}
   ```

   `python -m fishlen.cli stages` shows what's available and selected. New predictions (CLI `predict`, or the
   tool's Predict buttons) use it; each record stores which `impl@version` produced it (`pipeline` field).

4. **Close the loop in the tool**: reviewers fix what the stage got wrong; those fixes are the next round's
   ground truth. More reviewed photos → better evaluations.

## Getting better ground truth for your stage

- **Ruler**: in the tool, set rulers by hand on the 0 and 15 cm marks (R) on a varied set of photos — glare,
  partly covered rulers, far-away shots. These are the only independent ruler labels.
- **Segmentation / overlap**: label touching and overlapping animals carefully by hand; the detection eval
  reports partial and merged cases specifically.
- **Classification**: check species on every reviewed animal (1/2/3 keys); salamanders are the weak spot now.

## Current baseline numbers (2026-11-04, 19–20 reviewed photos)

| Stage | Result |
|---|---|
| detection (`grounding_dino` + `sam2_box`) | recall 0.96 (161/167), precision 0.95; 4 partial, 2 missed, 2 merged, 8 false |
| classifier (`gdino_crop`) | accuracy 0.83 — but 28 of 29 salamanders called trout |
| keypoints (`onnx_topdown`, 20 held-out animals) | median length error 1.0 %, mean 3.1 %, worst 27 % (overlapping fish) |
| ruler (`ticks_v1`) | no independent ground truth yet (see above) |
