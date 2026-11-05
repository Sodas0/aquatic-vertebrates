// Exact port of fishlen/geometry.py (centripetal Catmull-Rom, alpha 0.5, 64 samples per segment).
// tests/test_geometry.py runs this file with node and compares it to Python. Keep the type
// annotations to `: Pt`, `: Pt[]` and `: number` so that test can strip them.
export type Pt = [number, number];

export function dist(a: Pt, b: Pt): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

export function dedupe(P: Pt[]): Pt[] {
  return P.filter((p, i) => i === 0 || dist(p, P[i - 1]) > 1e-6);
}

export function plen(P: Pt[]): number {
  let t = 0;
  for (let i = 1; i < P.length; i++) t += dist(P[i], P[i - 1]);
  return t;
}

function lerp(a: Pt, b: Pt, ta: number, tb: number, t: number): Pt {
  return [((tb - t) * a[0] + (t - ta) * b[0]) / (tb - ta), ((tb - t) * a[1] + (t - ta) * b[1]) / (tb - ta)];
}

export function catmullRom(P0: Pt[], perSeg = 64): Pt[] {
  const P = dedupe(P0);
  if (P.length < 3) return P;
  const n = P.length;
  const first: Pt = [2 * P[0][0] - P[1][0], 2 * P[0][1] - P[1][1]];
  const last: Pt = [2 * P[n - 1][0] - P[n - 2][0], 2 * P[n - 1][1] - P[n - 2][1]];
  const Q = [first, ...P, last];
  const out = [];
  for (let i = 0; i < Q.length - 3; i++) {
    const p0 = Q[i], p1 = Q[i + 1], p2 = Q[i + 2], p3 = Q[i + 3];
    const t0 = 0;
    const t1 = t0 + Math.sqrt(dist(p1, p0));
    const t2 = t1 + Math.sqrt(dist(p2, p1));
    const t3 = t2 + Math.sqrt(dist(p3, p2));
    for (let j = 0; j < perSeg; j++) {
      const t = t1 + ((t2 - t1) * j) / perSeg;
      const a1 = lerp(p0, p1, t0, t1, t), a2 = lerp(p1, p2, t1, t2, t), a3 = lerp(p2, p3, t2, t3, t);
      out.push(lerp(lerp(a1, a2, t0, t2, t), lerp(a2, a3, t1, t3, t), t1, t2, t));
    }
  }
  out.push(P[n - 1]);
  return out;
}

export function curveLength(P: Pt[]): number {
  return plen(catmullRom(P));
}

// Distance along polyline P (from its first point) to the point on P closest to q.
export function projectArclen(P: Pt[], q: Pt): number {
  let best = Infinity, at = 0, acc = 0;
  for (let i = 1; i < P.length; i++) {
    const a = P[i - 1], b = P[i], dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy, seg = Math.sqrt(L2);
    const u = L2 > 0 ? Math.max(0, Math.min(1, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L2)) : 0;
    const d = Math.hypot(a[0] + u * dx - q[0], a[1] + u * dy - q[1]);
    if (d < best) { best = d; at = acc + u * seg; }
    acc += seg;
  }
  return at;
}

// Snout-vent length in px: along the midline curve to the vent.
export function svlPx(midline: Pt[], vent: Pt): number {
  return projectArclen(catmullRom(midline), vent);
}
