"""Run the configured stages on one photo and turn the result into a PhotoRecord.

Config: a dict {stage: {"impl": name, **params}}. DEFAULT_CONFIG is overridden by
<project>/pipeline.json if present (only the stages it names), so a team member can point one stage at
a new implementation without editing code.
"""
import json, time, uuid, warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from ..schema import Animal, Flags, PhotoRecord, Ruler, Source
from .base import STAGES, Detection, KeypointResult
from .registry import build

DEFAULT_CONFIG = {
    'detector': {'impl': 'grounding_dino'},
    'segmenter': {'impl': 'sam2_box'},
    'classifier': {'impl': 'gdino_crop'},
    'ruler': {'impl': 'ticks_v1'},
    'keypoints': {'impl': 'onnx_topdown', 'model': 'models/keypoints/hrnet_w32_dark_midline8_run2'},
}


MODELS = Path(__file__).resolve().parent.parent.parent / 'models'


def load_config(project_root: Optional[Path] = None, overrides: Optional[dict] = None) -> dict:
    cfg = {k: dict(v) for k, v in DEFAULT_CONFIG.items()}
    f = Path(project_root) / 'pipeline.json' if project_root else None
    if f and f.exists():
        cfg.update(json.loads(f.read_text()))
    if overrides:
        cfg.update(overrides)
    return with_fallbacks(cfg)


def with_fallbacks(cfg: dict) -> dict:
    """Swap stages whose model files are missing for no-model fallbacks, so the pipeline always runs."""
    from .shared import sam2_checkpoint
    kp = cfg['keypoints']
    if kp['impl'] == 'onnx_topdown':
        d = Path(kp.get('model', '')) if Path(kp.get('model', '')).is_absolute() else MODELS.parent / kp.get('model', '')
        if not (d / 'model.onnx').exists():
            warnings.warn(f'keypoint model {d} not found: using mask_axis (straight lines, no model)')
            cfg['keypoints'] = {'impl': 'mask_axis'}
    if not Path(sam2_checkpoint()).exists():
        for stage, needs_sam, fallback in (('segmenter', 'sam2_box', 'none'), ('ruler', 'ticks_v1', 'none')):
            if cfg[stage]['impl'] == needs_sam:
                warnings.warn(f'SAM2 weights not found ({sam2_checkpoint()}): {stage} -> {fallback}')
                cfg[stage] = {'impl': fallback}
    return cfg


@dataclass
class Result:
    detections: list[Detection]
    keypoints: list[KeypointResult]
    ruler: Optional[Ruler]
    provenance: dict[str, str]
    seconds: float


def touching(masks, frac=0.005):
    """Per mask: does it (dilated by `frac` of the image width) touch another mask?"""
    if len(masks) < 2:
        return [False] * len(masks)
    k = max(3, int(frac * masks[0].shape[1] / 4) | 1)
    small = [cv2.dilate(cv2.resize(m.astype(np.uint8), None, fx=0.25, fy=0.25, interpolation=cv2.INTER_NEAREST),
                        np.ones((k, k), np.uint8)) > 0 for m in masks]
    return [any((small[i] & small[j]).any() for j in range(len(small)) if j != i) for i in range(len(small))]


class Pipeline:
    def __init__(self, config: dict):
        self.config = config
        self.stages = {s: build(s, config[s]) for s in STAGES}

    @property
    def provenance(self):
        return {s: f'{st.name}@{st.version}' for s, st in self.stages.items()}

    def run(self, image: np.ndarray) -> Result:
        t = time.time()
        dets = self.stages['detector'].detect(image)
        dets = self.stages['segmenter'].segment(image, dets)
        dets = self.stages['classifier'].classify(image, dets)
        kps = self.stages['keypoints'].predict(image, dets)
        ruler = self.stages['ruler'].find(image)
        return Result(dets, kps, ruler, self.provenance, time.time() - t)

    def to_record(self, res: Result, rec: PhotoRecord) -> PhotoRecord:
        """Replace a record's model output with this result. Hand-made animals are kept."""
        model_name = self.provenance['keypoints']
        touch = touching([d.mask for d in res.detections]) if all(d.mask is not None for d in res.detections) else [False] * len(res.detections)
        animals = [a for a in rec.animals if a.source.kind != 'model']
        for d, k, t in zip(res.detections, res.keypoints, touch):
            animals.append(Animal(
                id=uuid.uuid4().hex[:8], species=d.species if d.species in ('trout', 'salamander', 'other') else 'unknown',
                midline=[tuple(map(float, p)) for p in np.round(k.points, 2)], scores=[round(float(s), 3) for s in k.scores],
                box=tuple(round(v, 1) for v in d.box), status='pending', flags=Flags(touching=t),
                source=Source(kind='model', name=model_name)))
        ruler = rec.ruler if rec.ruler is not None and rec.ruler.source == 'manual' else res.ruler
        return rec.model_copy(update=dict(status='predicted', animals=animals, ruler=ruler, auto_ruler=res.ruler,
                                          pipeline=res.provenance))


def load_image(path) -> np.ndarray:
    from PIL import Image, ImageOps
    return np.array(ImageOps.exif_transpose(Image.open(path)).convert('RGB'))
