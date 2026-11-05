"""Midline geometry. The web UI has an exact port of catmull_rom/curve_length (web/src/geometry.ts);
tests/test_geometry.py checks both agree.
"""
import numpy as np

LOW_CONFIDENCE = 0.3     # an animal whose weakest point scores below this needs a closer look


def dedupe(P, eps=1e-6):
    P = np.asarray(P, float)
    keep = np.r_[True, np.linalg.norm(np.diff(P, axis=0), axis=1) > eps]
    return P[keep]


def arclen(P):
    P = np.asarray(P, float)
    return float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())


def catmull_rom(P, alpha=0.5, per_seg=64):
    """Centripetal (alpha=0.5) Catmull-Rom through all points; ends padded by reflection."""
    P = dedupe(P)
    if len(P) < 3:
        return P
    Q = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = []
    for i in range(len(Q) - 3):
        p0, p1, p2, p3 = Q[i:i + 4]
        t0 = 0.0
        t1 = t0 + np.linalg.norm(p1 - p0) ** alpha
        t2 = t1 + np.linalg.norm(p2 - p1) ** alpha
        t3 = t2 + np.linalg.norm(p3 - p2) ** alpha
        t = np.linspace(t1, t2, per_seg, endpoint=False)[:, None]
        a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
        a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
        a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
        b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
        b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
        out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    return np.vstack(out + [P[-1:]])


def curve_length(P):
    """Length in px of the smooth curve through the midline points."""
    return arclen(catmull_rom(P))


def mm_per_px(ruler):
    return ruler.length_mm / float(np.hypot(ruler.p2[0] - ruler.p1[0], ruler.p2[1] - ruler.p1[1]))


def length_cm(animal, ruler):
    """Body length in cm, or None without a ruler."""
    if ruler is None:
        return None
    return curve_length(animal.midline) * mm_per_px(ruler) / 10


def project_arclen(P, q):
    """Distance along polyline P (from its first point) to the point on P closest to q."""
    P, q = np.asarray(P, float), np.asarray(q, float)
    a, d = P[:-1], np.diff(P, axis=0)
    L2 = (d ** 2).sum(1)
    u = np.clip(((q - a) * d).sum(1) / np.where(L2 > 0, L2, 1), 0, 1)
    k = int(np.linalg.norm(a + u[:, None] * d - q, axis=1).argmin())
    seg = np.sqrt(L2)
    return float(seg[:k].sum() + u[k] * seg[k])


def svl_cm(animal, ruler):
    """Snout-vent length in cm: along the midline curve to the point nearest the vent."""
    if ruler is None or animal.vent is None:
        return None
    return project_arclen(catmull_rom(animal.midline), animal.vent) * mm_per_px(ruler) / 10
