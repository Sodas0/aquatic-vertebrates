"""No-model keypoint fallback: a straight midline along the animal's long axis.

Uses the mask's smallest rotated rectangle when the segmenter gives a mask, else the box's longer side.
Head vs tail is not known, so points run left->right / top->bottom, and every score is 0 so the tool flags
each animal as low confidence for a person to fix. It exists so the pipeline runs without trained models.
"""
import cv2
import numpy as np

from ..base import KeypointResult
from ..registry import register


@register('keypoints', 'mask_axis')
class MaskAxisKeypoints:
    version = '1'

    def __init__(self, n_points=8):
        self.n = n_points

    def predict(self, image, dets):
        out = []
        for d in dets:
            x0, y0, x1, y1 = d.box
            if d.mask is not None and d.mask.any():
                cs, _ = cv2.findContours(d.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                (cx, cy), (w, h), ang = cv2.minAreaRect(max(cs, key=cv2.contourArea))
                if w < h:
                    w, ang = h, ang + 90
                u = np.array([np.cos(np.radians(ang)), np.sin(np.radians(ang))]) * w / 2
                a, b = np.array([cx, cy]) - u, np.array([cx, cy]) + u
            elif x1 - x0 >= y1 - y0:
                a, b = np.array([x0, (y0 + y1) / 2]), np.array([x1, (y0 + y1) / 2])
            else:
                a, b = np.array([(x0 + x1) / 2, y0]), np.array([(x0 + x1) / 2, y1])
            if (a[0], a[1]) > (b[0], b[1]):
                a, b = b, a
            pts = a + np.linspace(0, 1, self.n)[:, None] * (b - a)
            out.append(KeypointResult(points=pts, scores=np.zeros(self.n), crop_box=d.box))
        return out
