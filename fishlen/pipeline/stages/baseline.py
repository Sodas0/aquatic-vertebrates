"""Baseline implementations: Grounding DINO detection, SAM2 box-prompted masks, species from the
detector's text label. Starting points to beat, not final answers.
"""
import numpy as np

from ..base import Detection
from ..registry import register
from .. import shared


@register('detector', 'grounding_dino')
class GroundingDinoDetector:
    """Text-prompted boxes. Same settings as the playground notebook."""
    version = '1'

    def __init__(self, prompt='fish. salamander.', box_thresh=0.3, text_thresh=0.25, nms_iou=0.5):
        self.prompt, self.box_thresh, self.text_thresh, self.nms_iou = prompt, box_thresh, text_thresh, nms_iou

    def detect(self, image):
        boxes, scores, labels = shared.gd_detect(image, self.prompt, self.box_thresh, self.text_thresh, self.nms_iou)
        return [Detection(box=tuple(map(float, b)), score=float(s), label=l) for b, s, l in zip(boxes, scores, labels)]


@register('segmenter', 'sam2_box')
class Sam2BoxSegmenter:
    """One SAM2 mask per detection box; the box is tightened to the mask. Drops empty masks."""
    version = '1'

    def segment(self, image, dets):
        out = []
        for d, m in zip(dets, shared.sam_masks(image, [d.box for d in dets])):
            ys, xs = np.nonzero(m)
            if len(xs):
                d.mask, d.box = m, (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
                out.append(d)
        return out


@register('segmenter', 'none')
class NoSegmenter:
    """Keep detector boxes, no masks."""
    version = '1'

    def segment(self, image, dets):
        return dets


@register('classifier', 'detector_label')
class DetectorLabelClassifier:
    """Species = the text prompt that matched ('fish' -> trout). Placeholder for a real classifier."""
    version = '1'

    def __init__(self, mapping=None):
        self.mapping = mapping or {'fish': 'trout', 'salamander': 'salamander'}

    def classify(self, image, dets):
        for d in dets:
            d.species = self.mapping.get(d.label, 'unknown')
            d.species_scores = {d.species: d.score}
        return dets


@register('classifier', 'gdino_crop')
class GroundingDinoCropClassifier:
    """Zero-shot: ask Grounding DINO 'fish or salamander' on each animal's padded crop and take the
    best-scoring label. Works from the box alone, so it can be evaluated in isolation."""
    version = '1'

    def __init__(self, labels=None, pad=0.15, box_thresh=0.05, text_thresh=0.05):
        self.labels = labels or {'fish': 'trout', 'salamander': 'salamander'}
        self.pad, self.box_thresh, self.text_thresh = pad, box_thresh, text_thresh

    def classify(self, image, dets):
        H, W = image.shape[:2]
        prompt = ' '.join(f'{k}.' for k in self.labels)
        for d in dets:
            x0, y0, x1, y1 = d.box
            p = self.pad * max(x1 - x0, y1 - y0)
            crop = image[int(max(0, y0 - p)):int(min(H, y1 + p)), int(max(0, x0 - p)):int(min(W, x1 + p))]
            scores = {v: 0.0 for v in self.labels.values()}
            if crop.size:
                _, s, l = shared.gd_detect(crop, prompt, self.box_thresh, self.text_thresh, 0.5)
                for si, li in zip(s, l):
                    for k, v in self.labels.items():
                        if k in li:
                            scores[v] = max(scores[v], float(si))
            best = max(scores, key=scores.get)
            d.species = best if scores[best] > 0 else 'unknown'
            d.species_scores = {k: round(v, 3) for k, v in scores.items()}
        return dets


@register('ruler', 'none')
class NoRuler:
    """No automatic ruler; a person sets it in the tool."""
    version = '1'

    def find(self, image):
        return None
