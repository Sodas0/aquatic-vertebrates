"""Stage contracts. Each pipeline stage is a small class with a fixed input/output shape, so one stage
can be swapped, evaluated or iterated on without touching the others.

    detector    image                      -> list[Detection]          (find animals: box, label, score)
    segmenter   image, list[Detection]     -> list[Detection]          (fill .mask; may split/merge/drop)
    classifier  image, list[Detection]     -> list[Detection]          (fill .species, .species_scores)
    ruler       image                      -> Ruler | None             (scale; None = person sets it)
    keypoints   image, list[Detection]     -> list[KeypointResult]     (midline points per detection)

`image` is always an RGB uint8 array (H, W, 3) of the EXIF-rotated photo; all coordinates are its
pixels. Implementations register themselves with @register(stage, name) in registry.py and are picked
by name in the pipeline config (see runner.DEFAULT_CONFIG). Every implementation has `name` and
`version`; both are written into each record's `pipeline` field, so results stay traceable.
"""
from dataclasses import dataclass, field
from typing import Optional, Protocol

import numpy as np

from ..schema import Ruler

STAGES = ('detector', 'segmenter', 'classifier', 'ruler', 'keypoints')


@dataclass
class Detection:
    box: tuple[float, float, float, float]          # x0, y0, x1, y1 (tight, unpadded)
    score: float
    label: str = ''                                  # detector's own label, e.g. the text prompt that matched
    mask: Optional[np.ndarray] = None                # bool (H, W), from the segmenter
    species: str = 'unknown'                         # from the classifier: trout | salamander | other | unknown
    species_scores: dict[str, float] = field(default_factory=dict)


@dataclass
class KeypointResult:
    points: np.ndarray                               # (K, 2) snout -> tail
    scores: np.ndarray                               # (K,)
    crop_box: tuple[float, float, float, float]      # the box the model actually looked at


class Stage(Protocol):
    name: str
    version: str


class Detector(Stage, Protocol):
    def detect(self, image: np.ndarray) -> list[Detection]: ...


class Segmenter(Stage, Protocol):
    def segment(self, image: np.ndarray, dets: list[Detection]) -> list[Detection]: ...


class Classifier(Stage, Protocol):
    def classify(self, image: np.ndarray, dets: list[Detection]) -> list[Detection]: ...


class RulerFinder(Stage, Protocol):
    def find(self, image: np.ndarray) -> Optional[Ruler]: ...


class KeypointModel(Stage, Protocol):
    def predict(self, image: np.ndarray, dets: list[Detection]) -> list[KeypointResult]: ...


def mask_box(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    return (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())) if len(xs) else None
