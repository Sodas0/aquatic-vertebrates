# Placeholders: what is a stand-in today

Everything below works end to end, but is a weak substitute for a robust product. Ordered roughly by how
much it limits measurement quality. "Score" = current number from `python -m fishlen.cli eval ...`.

## Pipeline stages (swap via `fishlen/pipeline/stages/`, see pipeline.md)

| Stage | Today | Why it's weak | Score |
|---|---|---|---|
| **classifier** `gdino_crop` | zero-shot Grounding DINO on each crop | never trained on our animals; calls nearly every salamander a trout | 83 % overall, **1/29 salamanders** |
| **segmenter** `sam2_box` | SAM2 prompted with the detector's box | no overlap handling: touching fish merge or get cut; crops given to the keypoint model are unmasked rectangles | 4 partial, 2 merged of 167 |
| **detector** `grounding_dino` | zero-shot text prompt "fish. salamander.", hand-set thresholds | debris, cables, leaves become "animals"; small/faint fish missed; no junk filter | recall 0.96, precision 0.95 |
| **ruler** `ticks_v1` | FFT of the ruler's mm tick marks | one ruler model assumed (width 31.7 mm, ends 159 mm); fails when a fish covers it or under heavy glare; no confidence calibration | **no independent ground truth yet** |
| **keypoints** `onnx_topdown` | HRNet-W32 + DARK fine-tuned from AP-10K | ~160 animals, one annotator, unmasked crops; fails on overlapping fish | median 1.0 %, worst 27 % length error (20 held-out animals) |
| **keypoints** `mask_axis` | fallback when no model file: straight line along the mask | no bends, head/tail unknown, every animal flagged | — |

**Missing entirely:** a mask/cropper that feeds the keypoint model clean, single-animal crops (and a model
retrained on them), and mask/segmentation labeling in the tool (ground truth for the segmenter).

## Measurement

- **One scale per photo.** No correction for camera tilt or for fish sitting at a different depth than the
  ruler (refraction, parallax).
- **"Low confidence" = weakest keypoint score < 0.3** and **"touching" = dilated masks overlap**: both
  hand-picked rules, not calibrated against errors.
- **Annotator agreement never measured.** We don't know the human error floor the model should match.

## Workflow and infrastructure

- **Training is outside the app**: reviewed photos → training set → MMPose training → ONNX export are manual
  steps (playground scripts + `scripts/export_keypoints_onnx.py`). Planned as Phase 3.
- **Background jobs** run in a thread inside the web server: one at a time, lost on restart.
- **No accounts.** "Your name" is a free-text box; no permissions or audit trail beyond `source.name`.
- **Single machine storage**: SQLite + a local photo folder, no backups.
- **Hard-coded settings**: project title, ruler length (15 cm), units (cm), species list (trout, salamander,
  other).
- **No CI**: browser tests (`tests/e2e_*.py`) are run by hand; model files aren't versioned in git.
