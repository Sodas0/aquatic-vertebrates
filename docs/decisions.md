# Decisions

Short records of choices that shape the codebase, newest last.

1. **One record shape for labels and predictions.** Labeling is reviewing with an "Add animal" tool;
   a reviewed photo is training data. Avoids two tools and two formats.
2. **Store pixels + ruler, compute lengths.** Display units (cm) and curve method can change without
   touching data; edits can't leave stale lengths.
3. **Keep model output beside human edits** (`model_midline`, `auto_ruler`), so model error can be
   measured on reviewed photos and edits can be undone.
4. **FastAPI + generated OpenAPI contract** so the UI and any future backend agree on an exact spec.
5. **SQLite index + one JSON document per photo.** Simple to back up and inspect; the summary columns
   make filtering fast. Swap for Postgres only if multi-user hosting needs it.
6. **Optimistic concurrency via `revision`.** Two tabs or two people can't silently overwrite each other.
7. **React + Vite + TypeScript, hash routes, no UI framework.** Small, standard, deployable as static
   files behind any server. The length calculation is an exact port of Python's, checked by a test.
8. **Auto rulers are stored on the 0–15 cm convention** (re-centred, same scale) so auto and manual
   rulers mean the same thing to a person editing them.
9. **Run locally now, stay hostable** (deployment undecided): no auth yet; nothing assumes a single
   machine except the default data folder.
10. **Pipeline = five stages with fixed contracts and a name registry** (detector, segmenter, classifier,
    ruler, keypoints). Teams iterate on one stage in isolation, score it against reviewed photos with the
    other stages replaced by ground truth, then select it per project in `pipeline.json`. Records store
    `impl@version` per stage.
11. **Keypoint model runs as ONNX** (onnxruntime), exported from MMPose; crop, flip test and DARK decoding are
    reimplemented and checked to match MMPose to 0.0002 px. One environment, no MMPose at prediction time.
12. **OpenCV pinned to 4.10** (the training environment's): its bilinear warp rounds differently across
    versions and moved keypoints of hard cases by ~1 px.
13. **Predictions never overwrite hand work**: re-predicting replaces model animals only; hand-drawn animals
    and hand-set rulers are kept; reviewed photos are skipped unless forced.
14. **Background jobs**: one worker thread in the server process, models loaded on first use. Enough for one
    lab machine; a hosted deployment would move this to a separate worker process.
