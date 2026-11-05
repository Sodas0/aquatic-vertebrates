"""The ONNX keypoint runtime must reproduce MMPose's predictions (crop, flip test, DARK decoding).
Reference: tests/fixtures/keypoints_reference.json, written by scripts/export_keypoints_onnx.py."""
import json
from pathlib import Path

import numpy as np
import pytest

APP = Path(__file__).resolve().parent.parent
REF = APP / 'tests' / 'fixtures' / 'keypoints_reference.json'
IMG_DIR = APP.parent / 'playground' / 'data' / '2025 Synoptic pictures'

pytest.importorskip('onnxruntime')


@pytest.mark.skipif(not REF.exists() or not IMG_DIR.exists(), reason='reference fixture or photos not available')
def test_onnx_matches_mmpose():
    from fishlen.pipeline import build, load_image
    ref = json.loads(REF.read_text())
    kp = build('keypoints', {'impl': 'onnx_topdown', 'model': f"models/keypoints/{ref['model']}"})
    worst_px, worst_score, n = 0.0, 0.0, 0
    for name, animals in ref['photos'].items():
        img = load_image(IMG_DIR / name)
        out = kp.predict_boxes(img, [a['box'] for a in animals])
        for a, (pts, scores) in zip(animals, out):
            worst_px = max(worst_px, float(np.abs(pts - np.array(a['keypoints'])).max()))
            worst_score = max(worst_score, float(np.abs(scores - np.array(a['scores'])).max()))
            n += 1
    print(f'{n} animals: worst keypoint difference {worst_px:.4f} px, worst score difference {worst_score:.5f}')
    assert n == 20
    assert worst_px < 0.01 and worst_score < 1e-4
