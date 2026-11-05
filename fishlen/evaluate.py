"""Per-stage evaluation against photos people have reviewed in the tool (the ground truth).

Each stage is scored on its own, with the other stages' outputs replaced by ground truth where
possible, so a change to one stage can be measured without the others getting in the way:

  ruler       predicted px/mm vs the reviewed ruler (default: only rulers a person set or moved)
  detection   detector (+ segmenter) vs reviewed animals: found / missed / merged / partial / false
  classifier  species, given ground-truth boxes
  keypoints   length error, given ground-truth boxes (photos the model trained on are left out)

Results print as a summary and are saved as CSV under <project>/evals/.
"""
import csv, json, time
from pathlib import Path

import numpy as np

from .geometry import catmull_rom, curve_length, mm_per_px
from .pipeline.base import Detection
from .pipeline.registry import build
from .pipeline.runner import load_image


# rulers that are not independent of the tick detector (their distance was set from its measurement)
NOT_INDEPENDENT = {'hand_tick_corrected'}


def reviewed(project):
    """(photo row, record) for every reviewed photo."""
    for row in project.list_photos(status='reviewed'):
        yield row, project.get_record(row['id'])


def live_animals(rec):
    return [a for a in rec.animals if a.status != 'rejected']


def gt_detection(animal):
    """Ground-truth detection: the midline's extent (the keypoint stage adds its own padding)."""
    P = np.asarray(animal.midline, float)
    return Detection(box=(*P.min(0), *P.max(0)), score=1.0, label=animal.species, species=animal.species)


def _save(project, stage, impl, rows):
    out = Path(project.root) / 'evals'
    out.mkdir(exist_ok=True)
    f = out / f'{stage}-{impl}-{time.strftime("%Y%m%d-%H%M%S")}.csv'
    if rows:
        with open(f, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return f


def _image(project, pid):
    return load_image(project.images.original(pid))


# ---------------------------------------------------------------- ruler
def eval_ruler(project, spec, gt='manual', log=print):
    finder = build('ruler', spec)
    rows = []
    for row, rec in reviewed(project):
        if rec.ruler is None or (gt == 'manual' and (rec.ruler.source != 'manual' or rec.ruler.method in NOT_INDEPENDENT)):
            continue
        truth = 1 / mm_per_px(rec.ruler)
        t = time.time()
        pred = finder.find(_image(project, row['id']))
        r = dict(photo=row['filename'], truth_px_per_mm=round(truth, 4), seconds=round(time.time() - t, 2))
        if pred is None:
            r.update(pred_px_per_mm='', error_pct='', method='not found', needs_check='')
        else:
            k = 1 / mm_per_px(pred)
            r.update(pred_px_per_mm=round(k, 4), error_pct=round(100 * (k - truth) / truth, 2), method=pred.method,
                     needs_check=pred.needs_check)
        rows.append(r)
        log(f"  {r['photo']:24s} {r['method']:9s} error {r['error_pct']}%")
    errs = np.array([abs(r['error_pct']) for r in rows if r['error_pct'] != ''])
    summary = dict(photos=len(rows), not_found=sum(r['method'] == 'not found' for r in rows),
                   within_1pct=int((errs <= 1).sum()), within_2pct=int((errs <= 2).sum()),
                   median_abs_error_pct=round(float(np.median(errs)), 2) if len(errs) else None,
                   worst_abs_error_pct=round(float(errs.max()), 2) if len(errs) else None)
    return summary, _save(project, 'ruler', finder.name, rows)


# ---------------------------------------------------------------- detection (+ segmentation)
def _coverage(animal, det, pad=0.05):
    """Fraction of points along the animal's midline curve that fall inside the detection."""
    C = catmull_rom(animal.midline)
    C = C[np.linspace(0, len(C) - 1, 30).astype(int)]
    if det.mask is not None:
        H, W = det.mask.shape
        x = np.clip(C[:, 0].round().astype(int), 0, W - 1)
        y = np.clip(C[:, 1].round().astype(int), 0, H - 1)
        return float(det.mask[y, x].mean())
    x0, y0, x1, y1 = det.box
    px, py = pad * (x1 - x0), pad * (y1 - y0)
    return float(((C[:, 0] >= x0 - px) & (C[:, 0] <= x1 + px) & (C[:, 1] >= y0 - py) & (C[:, 1] <= y1 + py)).mean())


def eval_detection(project, det_spec, seg_spec, full=0.8, part=0.3, log=print):
    detector, segmenter = build('detector', det_spec), build('segmenter', seg_spec)
    rows = []
    for row, rec in reviewed(project):
        gts = live_animals(rec)
        if not gts:
            continue
        img = _image(project, row['id'])
        dets = segmenter.segment(img, detector.detect(img))
        cov = np.array([[_coverage(g, d) for d in dets] for g in gts]).reshape(len(gts), len(dets))
        found = (cov >= full).any(1) if dets else np.zeros(len(gts), bool)
        partial = ~found & ((cov >= part).any(1) if dets else False)
        per_det = (cov >= full).sum(0) if dets else np.array([])
        r = dict(photo=row['filename'], animals=len(gts), detections=len(dets), found=int(found.sum()),
                 partial=int(np.sum(partial)), missed=int(len(gts) - found.sum() - np.sum(partial)),
                 merged_detections=int((per_det >= 2).sum()), false_detections=int(((cov >= part).sum(0) == 0).sum()) if dets else 0)
        rows.append(r)
        log(f"  {r['photo']:24s} {r['found']}/{r['animals']} found, {r['partial']} partial, {r['missed']} missed, "
            f"{r['merged_detections']} merged, {r['false_detections']} false")
    tot = {k: sum(r[k] for r in rows) for k in ('animals', 'detections', 'found', 'partial', 'missed', 'merged_detections', 'false_detections')}
    summary = dict(photos=len(rows), **tot,
                   recall=round(tot['found'] / tot['animals'], 3) if tot['animals'] else None,
                   precision=round(1 - tot['false_detections'] / tot['detections'], 3) if tot['detections'] else None)
    return summary, _save(project, 'detection', f'{detector.name}+{segmenter.name}', rows)


# ---------------------------------------------------------------- classifier
def eval_classifier(project, spec, log=print):
    clf = build('classifier', spec)
    rows = []
    for row, rec in reviewed(project):
        gts = [a for a in live_animals(rec) if a.species in ('trout', 'salamander', 'other')]
        if not gts:
            continue
        out = clf.classify(_image(project, row['id']), [Detection(box=gt_detection(a).box, score=1.0) for a in gts])
        for a, d in zip(gts, out):
            rows.append(dict(photo=row['filename'], animal=a.id, truth=a.species, predicted=d.species, correct=a.species == d.species))
        log(f"  {row['filename']:24s} {sum(r['correct'] for r in rows if r['photo'] == row['filename'])}/{len(gts)} correct")
    classes = sorted({r['truth'] for r in rows} | {r['predicted'] for r in rows})
    confusion = {t: {p: sum(1 for r in rows if r['truth'] == t and r['predicted'] == p) for p in classes} for t in classes}
    summary = dict(animals=len(rows), accuracy=round(np.mean([r['correct'] for r in rows]), 3) if rows else None,
                   confusion_truth_by_predicted=confusion)
    return summary, _save(project, 'classifier', clf.name, rows)


# ---------------------------------------------------------------- keypoints
def eval_keypoints(project, spec, include_trained=False, log=print):
    kp = build('keypoints', spec)
    trained = set(getattr(kp, 'meta', {}).get('trained_on', []))
    rows, skipped = [], 0
    for row, rec in reviewed(project):
        gts = live_animals(rec)
        if not gts:
            continue
        if row['filename'] in trained and not include_trained:
            skipped += 1
            continue
        out = kp.predict(_image(project, row['id']), [gt_detection(a) for a in gts])
        for a, k in zip(gts, out):
            L_true, L_pred = curve_length(a.midline), curve_length(k.points)
            rows.append(dict(photo=row['filename'], animal=a.id, species=a.species, in_training=row['filename'] in trained,
                             true_px=round(L_true, 1), pred_px=round(L_pred, 1), length_error_pct=round(100 * (L_pred - L_true) / L_true, 2),
                             snout_error_pct_of_length=round(100 * float(np.linalg.norm(k.points[0] - np.array(a.midline[0]))) / L_true, 2),
                             tail_error_pct_of_length=round(100 * float(np.linalg.norm(k.points[-1] - np.array(a.midline[-1]))) / L_true, 2),
                             min_score=round(float(k.scores.min()), 3)))
        log(f"  {row['filename']:24s} {len(gts)} animals")
    e = np.array([abs(r['length_error_pct']) for r in rows])
    summary = dict(animals=len(rows), photos_skipped_trained_on=skipped,
                   mean_abs_length_error_pct=round(float(e.mean()), 2) if len(e) else None,
                   median_abs_length_error_pct=round(float(np.median(e)), 2) if len(e) else None,
                   within_2pct=int((e <= 2).sum()), within_5pct=int((e <= 5).sum()),
                   worst_abs_length_error_pct=round(float(e.max()), 2) if len(e) else None)
    return summary, _save(project, 'keypoints', kp.name, rows)
