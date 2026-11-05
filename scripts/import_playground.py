"""One-time import of the playground's photos, hand labels and predictions into a fishlen project.

    python scripts/import_playground.py --playground ../playground --data data

- every photo in <playground>/data/2025 Synoptic pictures (skipping '-1' copies)
- labels/<annotator>/<stem>.json  -> reviewed photo, accepted animals, source human:<annotator>
- predictions/<stem>.json         -> predicted/reviewed photo, animals as reviewed in the old tool
Hand labels win when a photo has both. Photos that already have animals are skipped unless --force.
"""
import argparse, json, uuid

import numpy as np
from pathlib import Path

from fishlen.schema import Animal, Flags, PhotoRecord, Ruler, Source
from fishlen.store import Project

OLD_MODEL = 'hrnet_w32_dark_midline8_run2/epoch_210'


def new_id():
    return uuid.uuid4().hex[:8]


def from_label(pid, d):
    r = d.get('ruler')
    # hand clicks whose distance was later set from the ruler's tick scale: not independent ground truth
    method = 'hand_tick_corrected' if r and r.get('mm_source', '').startswith('tick') else 'hand'
    ruler = Ruler(p1=r['p1'], p2=r['p2'], length_mm=r['mm'], source='manual', method=method) if r and r.get('p2') else None
    animals = [Animal(id=new_id(), species=a['species'], midline=a['midline'], vent=a.get('vent'), status='accepted',
                      flags=Flags(observations=a.get('flags', [])), source=Source(kind='human', name=d['annotator']),
                      note=a.get('note', ''))
               for a in d['animals'] if len(a['midline']) >= 2]
    return PhotoRecord(photo_id=pid, status='reviewed' if d.get('status') == 'done' else 'predicted',
                       ruler=ruler, animals=animals)


def to_marks(p1, p2, length_mm, span_mm=150.0):
    """Same scale, but endpoints re-centred on a 15 cm span: the 'ends on the 0 and 15 cm marks' convention."""
    p1, p2 = np.asarray(p1, float), np.asarray(p2, float)
    c, u = (p1 + p2) / 2, (p2 - p1) / np.linalg.norm(p2 - p1)
    half = span_mm / (length_mm / np.linalg.norm(p2 - p1)) / 2
    return (c - u * half).round(2).tolist(), (c + u * half).round(2).tolist(), span_mm


def from_prediction(pid, d):
    r = d.get('ruler')
    ruler = None
    if r:
        p1, p2, mm = (to_marks(r['p1'], r['p2'], r['mm']) if r.get('method') == 'ticks' and r.get('source', 'auto') == 'auto'
                      else (r['p1'], r['p2'], r['mm']))
        ruler = Ruler(p1=p1, p2=p2, length_mm=mm, source=r.get('source', 'auto'), method=r.get('method'),
                      confidence=r.get('tick_score'), needs_check=bool(r.get('needs_check')))
    animals = []
    for a in d['animals']:
        reason = a.get('reject_reason')
        animals.append(Animal(
            id=new_id(), species=a.get('species', 'unknown') if a.get('species') in ('trout', 'salamander', 'other') else 'unknown',
            midline=a['keypoints'], scores=a.get('scores'), status=a.get('status', 'pending'),
            reject_reason=reason if reason in ('junk', 'overlap') else ('other' if a.get('status') == 'rejected' else None),
            flags=Flags(touching=bool(a.get('touching')), edited=bool(a.get('edited'))),
            source=Source(kind='model', name=OLD_MODEL)))
    tags = [t for t in d.get('tags', []) if t in ('junk', 'overlap')]
    return PhotoRecord(photo_id=pid, status='reviewed' if d.get('status') == 'reviewed' else 'predicted',
                       tags=tags, ruler=ruler, auto_ruler=ruler if ruler and ruler.source == 'auto' else None,
                       animals=animals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--playground', type=Path, required=True)
    ap.add_argument('--data', type=Path, default=Path('data'))
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    pg = a.playground
    project = Project(a.data)
    labels = {}
    for f in sorted((pg / 'labels').glob('*/*.json')):
        d = json.loads(f.read_text())
        labels.setdefault(Path(d['image']).stem, d)       # first annotator
    preds = {f.stem: json.loads(f.read_text()) for f in (pg / 'predictions').glob('*.json')}

    photos = sorted(p for p in (pg / 'data' / '2025 Synoptic pictures').glob('*.jpg') if not p.stem.endswith('-1'))
    n = {'photos': 0, 'duplicates': 0, 'labeled': 0, 'predicted': 0, 'skipped': 0}
    for i, p in enumerate(photos):
        photo, is_new = project.add_photo(p.read_bytes(), p.name)
        n['photos' if is_new else 'duplicates'] += 1
        src = labels.get(p.stem) or preds.get(p.stem)
        if src is None:
            continue
        cur = project.get_record(photo.id)
        if cur.animals and not a.force:
            n['skipped'] += 1
            continue
        rec = from_label(photo.id, src) if p.stem in labels else from_prediction(photo.id, src)
        project.save_record(rec)
        n['labeled' if p.stem in labels else 'predicted'] += 1
        if (i + 1) % 50 == 0:
            print(f'{i + 1}/{len(photos)}')
    print(n, project.counts())


if __name__ == '__main__':
    main()
