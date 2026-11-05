"""Prediction pipeline: swappable stages (detector, segmenter, classifier, ruler, keypoints).
See base.py for the stage contracts and registry.py for adding an implementation."""
from .base import STAGES, Detection, KeypointResult
from .registry import available, build, register
from .runner import DEFAULT_CONFIG, Pipeline, load_config, load_image
