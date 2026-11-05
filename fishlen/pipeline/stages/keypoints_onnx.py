"""Top-down heatmap keypoint model exported to ONNX (scripts/export_keypoints_onnx.py), run with
onnxruntime. Reproduces MMPose's test-time path exactly: bbox padding 1.25 -> square -> affine crop,
flip test with shifted heatmaps, DARK sub-pixel decoding (functions adapted from MMPose, Apache-2.0).
tests/test_keypoints_onnx.py checks the output against MMPose's own predictions.
"""
import json
from itertools import product
from pathlib import Path

import cv2
import numpy as np

from ..base import KeypointResult
from ..registry import register

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _third_point(a, b):
    d = a - b
    return b + np.r_[-d[1], d[0]]


def warp_matrix(center, scale, output_size, inv=False):
    """mmpose get_warp_matrix with rot=0, shift=0, fix_aspect_ratio=True."""
    src_w = scale[0]
    dst_w, dst_h = output_size
    src = np.zeros((3, 2), np.float32)
    dst = np.zeros((3, 2), np.float32)
    src[0] = center
    src[1] = center + np.array([src_w * -0.5, 0.0])
    dst[0] = [dst_w * 0.5, dst_h * 0.5]
    dst[1] = np.array([dst_w * 0.5, dst_h * 0.5]) + np.array([dst_w * -0.5, 0.0])
    src[2] = _third_point(src[0], src[1])
    dst[2] = _third_point(dst[0], dst[1])
    return cv2.getAffineTransform(dst, src) if inv else cv2.getAffineTransform(src, dst)


def gaussian_blur(heatmaps, kernel=11):
    border = (kernel - 1) // 2
    K, H, W = heatmaps.shape
    for k in range(K):
        origin_max = np.max(heatmaps[k])
        dr = np.zeros((H + 2 * border, W + 2 * border), dtype=np.float32)
        dr[border:-border, border:-border] = heatmaps[k].copy()
        dr = cv2.GaussianBlur(dr, (kernel, kernel), 0)
        heatmaps[k] = dr[border:-border, border:-border].copy()
        heatmaps[k] *= origin_max / np.max(heatmaps[k])
    return heatmaps


def decode_dark(heatmaps, blur_kernel=11):
    """(K, H, W) heatmaps -> (K, 2) locations in heatmap pixels, (K,) scores."""
    K, H, W = heatmaps.shape
    flat = heatmaps.reshape(K, -1)
    y, x = np.unravel_index(np.argmax(flat, axis=1), (H, W))
    locs = np.stack((x, y), axis=-1).astype(np.float32)
    vals = np.amax(flat, axis=1)
    locs[vals <= 0.0] = -1
    hm = gaussian_blur(heatmaps.copy(), blur_kernel)
    np.maximum(hm, 1e-10, hm)
    np.log(hm, hm)
    for k in range(K):
        x, y = locs[k].astype(int)
        if 1 < x < W - 2 and 1 < y < H - 2:
            dx = 0.5 * (hm[k, y, x + 1] - hm[k, y, x - 1])
            dy = 0.5 * (hm[k, y + 1, x] - hm[k, y - 1, x])
            dxx = 0.25 * (hm[k, y, x + 2] - 2 * hm[k, y, x] + hm[k, y, x - 2])
            dxy = 0.25 * (hm[k, y + 1, x + 1] - hm[k, y - 1, x + 1] - hm[k, y + 1, x - 1] + hm[k, y - 1, x - 1])
            dyy = 0.25 * (hm[k, y + 2, x] - 2 * hm[k, y, x] + hm[k, y - 2, x])
            if dxx * dyy - dxy ** 2 != 0:
                hess = np.array([[dxx, dxy], [dxy, dyy]])
                locs[k] += (-np.linalg.inv(hess) @ np.array([dx, dy])).astype(np.float32)
    return locs, vals


@register('keypoints', 'onnx_topdown')
class OnnxTopdownKeypoints:
    version = '1'

    def __init__(self, model='models/keypoints/hrnet_w32_dark_midline8_run2', box_pad=0.1, providers=None):
        d = Path(model) if Path(model).is_absolute() else ROOT / model
        self.meta = json.loads((d / 'meta.json').read_text())
        self.version = self.meta['name']
        import os
        import onnxruntime as ort
        avail = ort.get_available_providers()
        opts = ort.SessionOptions()
        # set threads explicitly: on cluster jobs (cgroups) the default thread pinning fails noisily
        opts.intra_op_num_threads = max(1, min(8, len(os.sched_getaffinity(0))))
        self.sess = ort.InferenceSession(str(d / 'model.onnx'), sess_options=opts, providers=providers or
                                         [p for p in ('CUDAExecutionProvider', 'CPUExecutionProvider') if p in avail])
        self.box_pad = box_pad
        self.mean = np.array(self.meta['mean'], np.float32)
        self.std = np.array(self.meta['std'], np.float32)

    def crop_box(self, det):
        """The detection box padded by box_pad x its longer side (how training boxes were made)."""
        x0, y0, x1, y1 = det.box
        p = self.box_pad * max(x1 - x0, y1 - y0)
        return (x0 - p, y0 - p, x1 + p, y1 + p)

    def predict_boxes(self, image, boxes):
        """Run on explicit xyxy boxes (used by evaluation with ground-truth boxes)."""
        if not len(boxes):
            return []
        W, H = self.meta['input_size']
        hw, hh = self.meta['heatmap_size']
        crops, frames = [], []
        for x0, y0, x1, y1 in boxes:
            # float64 like MMPose: float32 centers shift crops by a fraction of a pixel, which moves
            # keypoints of hard (e.g. overlapping) animals by up to ~1 px
            center = np.array([(x0 + x1) / 2, (y0 + y1) / 2], np.float64)
            scale = np.array([x1 - x0, y1 - y0], np.float64) * self.meta['bbox_padding']
            w, h = scale
            scale = np.array([w, w / (W / H)] if w > h * (W / H) else [h * (W / H), h], np.float64)
            crop = cv2.warpAffine(image, warp_matrix(center, scale, (W, H)), (W, H), flags=cv2.INTER_LINEAR)
            crops.append(crop)
            frames.append((center, scale))
        x = ((np.stack(crops).astype(np.float32) - self.mean) / self.std).transpose(0, 3, 1, 2)
        if self.meta['flip_test']:
            x = np.concatenate([x, x[..., ::-1]])
        hm = self.sess.run(None, {'input': np.ascontiguousarray(x)})[0]
        n = len(crops)
        if self.meta['flip_test']:
            f = hm[n:][..., ::-1][:, self.meta['flip_indices']].copy()
            if self.meta['shift_heatmap']:
                f[..., 1:] = f[..., :-1].copy()
            hm = (hm[:n] + f) * 0.5
        out = []
        for k in range(n):
            locs, vals = decode_dark(hm[k].copy(), self.meta['blur_kernel_size'])
            center, scale = frames[k]
            pts = locs * np.array([W / hw, H / hh], np.float32)          # heatmap -> input pixels
            pts = pts / np.array([W, H]) * scale + center - 0.5 * scale
            out.append((pts.astype(float), vals.astype(float)))
        return out

    def predict(self, image, dets):
        boxes = [self.crop_box(d) for d in dets]
        return [KeypointResult(points=p, scores=s, crop_box=b) for (p, s), b in zip(self.predict_boxes(image, boxes), boxes)]
