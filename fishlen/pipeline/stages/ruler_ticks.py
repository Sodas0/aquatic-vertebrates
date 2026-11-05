"""Ruler scale from the ruler's millimetre ticks (ported from playground/keypoints/ruler.py).

1. Grounding DINO "ruler." -> top few boxes -> SAM2 mask -> smallest rotated rectangle.
2. Straighten the strip; average brightness along the long axis in thin bands near each long edge.
3. The strongest FFT peak near the 1 mm spacing predicted by the ruler's width (+-15%, which excludes the
   1/16" and 1/32" inch ticks on the other edge) gives px per mm, refined to sub-pixel.
4. No candidate with a clear tick pattern -> fall back to end-to-end length, flagged needs_check.
The result follows the tool's convention: endpoints on a 15 cm span (0 and 15 cm marks), same scale.
"""
import cv2
import numpy as np

from ...schema import Ruler
from .. import shared
from ..registry import register


def _rotated_rect(mask):
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    (cx, cy), (w, h), ang = cv2.minAreaRect(max(cs, key=cv2.contourArea))
    if w < h:
        w, h, ang = h, w, ang + 90
    return np.array([cx, cy]), float(w), float(h), float(ang)


def _strip(gray, c, length, width, ang):
    M = cv2.getRotationMatrix2D((float(c[0]), float(c[1])), ang, 1.0)
    M[:, 2] += [length / 2 - c[0], width / 2 - c[1]]
    return cv2.warpAffine(gray, M, (int(round(length)), int(round(width))), flags=cv2.INTER_CUBIC)


@register('ruler', 'ticks_v1')
class TickRuler:
    version = '1'

    def __init__(self, span_mm=150.0, end_to_end_mm=159.0, ruler_width_mm=31.7, window=0.15, min_score=8.0,
                 px_per_mm=(2.0, 15.0), candidates=3, box_thresh=0.2):
        self.span_mm, self.end_to_end_mm, self.width_mm = span_mm, end_to_end_mm, ruler_width_mm
        self.window, self.min_score, self.px_per_mm = window, min_score, px_per_mm
        self.candidates, self.box_thresh = candidates, box_thresh

    def _tick_period(self, s, guess):
        H, N = s.shape
        lo_px, hi_px = self.px_per_mm
        if not lo_px * (1 + self.window) <= guess <= hi_px * (1 - self.window) or N < 20 * guess:
            return 0.0, None
        nfft = 1 << 16
        f = np.fft.rfftfreq(nfft)
        sel = (f >= 1 / (guess * (1 + self.window))) & (f <= 1 / (guess * (1 - self.window)))
        ref = (f >= 1 / (6 * hi_px)) & (f <= 1 / (0.8 * lo_px))
        best = (0.0, None)
        for lo in np.r_[np.arange(0.02, 0.25, 0.03), np.arange(0.75, 0.98, 0.03)]:
            band = s[int(lo * H):int((lo + 0.06) * H) + 1].astype(float).mean(0)
            k = max(3, int(round(3 * guess)))
            band = band - np.convolve(band, np.ones(k) / k, mode='same')
            P = np.abs(np.fft.rfft(band * np.hanning(N), nfft)) ** 2
            i = np.flatnonzero(sel)[P[sel].argmax()]
            score = P[i] / np.median(P[ref])
            if score > best[0]:
                a, b, c = np.log(P[i - 1:i + 2] + 1e-12)
                d = 0.5 * (a - c) / (a - 2 * b + c)
                best = (float(score), float(1 / (f[i] + d * (f[1] - f[0]))))
        return best

    def find(self, image):
        boxes, scores, _ = shared.gd_detect(image, 'ruler.', self.box_thresh, 0.25, 0.5)
        if not len(boxes):
            return None
        boxes, scores = boxes[:self.candidates], scores[:self.candidates]
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        best = None
        for m in shared.sam_masks(image, boxes):
            if not m.any():
                continue
            c, L, W, ang = _rotated_rect(m)
            score, period = (self._tick_period(_strip(gray, c, L, W, ang), W / self.width_mm) if L / W >= 1.2 else (0.0, None))
            if best is None or score > best[0]:
                best = (score, period, c, L, ang)
        score, period, c, L, ang = best
        u = np.array([np.cos(np.radians(ang)), np.sin(np.radians(ang))])
        if score >= self.min_score:
            px_per_mm, method, check = period, 'ticks', False
        else:
            px_per_mm, method, check = L / self.end_to_end_mm, 'ends', True
        half = self.span_mm * px_per_mm / 2
        return Ruler(p1=tuple((c - u * half).round(2)), p2=tuple((c + u * half).round(2)), length_mm=self.span_mm,
                     source='auto', method=method, confidence=round(float(score), 1), needs_check=check)
