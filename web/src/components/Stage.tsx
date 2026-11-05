// The photo with its overlay: pan/zoom, select animals, drag midline points / vents / ruler ends,
// insert and remove points, and draw new midlines and rulers. Coordinates handed out are
// full-resolution image pixels.
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { PhotoRecord } from '../api';
import { fmtCm, isLowConfidence, lengthCm } from '../api';
import { DRAFT, HALO, LINE, RULER, SNOUT, TAIL, VENT } from '../colors';
import { catmullRom, Pt } from '../geometry';

export type Tool = 'select' | 'ruler' | 'pan' | 'add' | 'redraw' | 'vent';

type Target =
  | { kind: 'point'; i: number; j: number }
  | { kind: 'vent'; i: number }
  | { kind: 'ruler'; key: 'p1' | 'p2' }
  | { kind: 'curve'; i: number }
  | { kind: 'bg' };

interface Props {
  src: string; width: number; height: number; rec: PhotoRecord; sel: number; tool: Tool; hidden: boolean;
  fitSignal: number; spaceDown: boolean; draft: Pt[] | null;
  onSelect(i: number): void;
  onDragStart(): void;                         // a point or vent starts moving (for undo)
  onPointMove(i: number, j: number, p: Pt): void;
  onVentMove(i: number, p: Pt): void;
  onRulerDragStart(key: 'p1' | 'p2'): void;
  onRulerMove(key: 'p1' | 'p2', p: Pt): void;
  onDragEnd(): void;
  onNewRuler(p1: Pt, p2: Pt): void;
  onDraftPoint(p: Pt): void;                   // add / redraw tools
  onVent(p: Pt): void;                         // vent tool
  onInsertPoint(i: number, p: Pt): void;       // double-click a line
  onRemovePoint(i: number, j: number): void;   // Alt-click a point
}

const DRAW_TOOLS: Tool[] = ['add', 'redraw', 'vent', 'ruler'];
const CLICK_SLOP = 10;   // px a click may wander in the drawing tools and still count as a click
const PAN_START = 6;     // px of movement before an empty-space drag in Select starts panning

const pathD = (P: Pt[]) => P.map((p, k) => (k ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');

function targetOf(el: Element | null): Target {
  const d = (el as HTMLElement | null)?.dataset;
  if (d?.kind === 'point') return { kind: 'point', i: +d.i!, j: +d.j! };
  if (d?.kind === 'vent') return { kind: 'vent', i: +d.i! };
  if (d?.kind === 'ruler') return { kind: 'ruler', key: d.key as 'p1' | 'p2' };
  if (d?.kind === 'curve') return { kind: 'curve', i: +d.i! };
  return { kind: 'bg' };
}

export default function Stage(p: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ s: 0.2, x: 0, y: 0 });
  const [mouse, setMouse] = useState<Pt | null>(null);
  const [rulerStart, setRulerStart] = useState<Pt | null>(null);
  const drag = useRef<null | { t: Target; sx: number; sy: number; v: typeof view; moved: boolean; panOnly: boolean; far: number }>(null);

  const fit = () => {
    const el = box.current;
    if (!el || !p.width) return;
    const s = Math.min(el.clientWidth / p.width, el.clientHeight / p.height) * 0.97;
    setView({ s, x: (el.clientWidth - p.width * s) / 2, y: (el.clientHeight - p.height * s) / 2 });
  };
  useLayoutEffect(fit, [p.fitSignal, p.width, p.height]);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => fit());
    ro.observe(el);
    return () => ro.disconnect();
  }, [p.width, p.height]);
  useEffect(() => setRulerStart(null), [p.tool, p.rec.photo_id]);

  const toImg = (e: { clientX: number; clientY: number }): Pt => {
    const r = box.current!.getBoundingClientRect();
    return [(e.clientX - r.left - view.x) / view.s, (e.clientY - r.top - view.y) / view.s];
  };

  const onWheel = (e: React.WheelEvent) => {
    const r = box.current!.getBoundingClientRect();
    const k = Math.exp(-e.deltaY * 0.0015), sx = e.clientX - r.left, sy = e.clientY - r.top;
    setView((v) => {
      const s = Math.min(Math.max(v.s * k, 0.02), 20), kk = s / v.s;
      return { s, x: sx - (sx - v.x) * kk, y: sy - (sy - v.y) * kk };
    });
  };

  const onPointerDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    let t = targetOf(e.target as Element);
    const panOnly = p.tool === 'pan' || p.spaceDown || e.button !== 0 || p.hidden;
    if (panOnly) t = { kind: 'bg' };
    else if (p.tool === 'ruler' && t.kind !== 'ruler') t = { kind: 'bg' };
    else if (p.tool !== 'ruler' && t.kind === 'ruler') t = { kind: 'bg' };
    else if (p.tool !== 'select' && t.kind !== 'ruler') t = { kind: 'bg' };   // drawing tools: clicks add points
    if (t.kind === 'point' && e.altKey) { p.onRemovePoint(t.i, t.j); drag.current = null; return; }
    drag.current = { t, sx: e.clientX, sy: e.clientY, v: view, moved: false, panOnly, far: 0 };
    if (t.kind === 'point' || t.kind === 'vent') p.onSelect(t.i);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    setMouse(toImg(e));
    const d = drag.current;
    if (!d) return;
    const moved = Math.hypot(e.clientX - d.sx, e.clientY - d.sy);
    d.far = Math.max(d.far, moved);
    const isHandle = d.t.kind === 'point' || d.t.kind === 'vent' || d.t.kind === 'ruler';
    // empty space: drawing tools never pan with the left button (so clicks always land);
    // Select pans only after a deliberate drag
    if (!isHandle && !d.panOnly && (DRAW_TOOLS.includes(p.tool) || moved < PAN_START)) return;
    if (!d.moved && (!isHandle || moved > 3)) {
      d.moved = true;                       // a drag starts only once the pointer actually moves
      if (d.t.kind === 'point' || d.t.kind === 'vent') p.onDragStart();
      if (d.t.kind === 'ruler') p.onRulerDragStart(d.t.key);
    }
    if (!d.moved) return;
    if (d.t.kind === 'point') p.onPointMove(d.t.i, d.t.j, toImg(e));
    else if (d.t.kind === 'vent') p.onVentMove(d.t.i, toImg(e));
    else if (d.t.kind === 'ruler') p.onRulerMove(d.t.key, toImg(e));
    else setView({ ...d.v, x: d.v.x + e.clientX - d.sx, y: d.v.y + e.clientY - d.sy });
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.t.kind === 'point' || d.t.kind === 'vent' || d.t.kind === 'ruler') { if (d.moved) p.onDragEnd(); return; }
    if (d.panOnly || d.moved || d.far > CLICK_SLOP) return;
    const q = toImg(e);                     // a click
    if (p.tool === 'ruler') {
      if (!rulerStart) setRulerStart(q);
      else { p.onNewRuler(rulerStart, q); setRulerStart(null); }
    } else if (p.tool === 'add' || p.tool === 'redraw') p.onDraftPoint(q);
    else if (p.tool === 'vent') p.onVent(q);
    else if (p.tool === 'select') p.onSelect(d.t.kind === 'curve' ? d.t.i : -1);
  };

  const onDoubleClick = (e: React.MouseEvent) => {
    const t = targetOf(e.target as Element);
    if (p.tool === 'select' && t.kind === 'curve') p.onInsertPoint(t.i, toImg(e));
  };

  const s = view.s, r = p.rec;
  const cursor = p.tool === 'pan' || p.spaceDown ? 'grab' : DRAW_TOOLS.includes(p.tool) ? 'crosshair' : 'default';
  const order = r.animals.map((_, i) => i).filter((i) => i !== p.sel).concat(p.sel >= 0 && p.sel < r.animals.length ? [p.sel] : []);
  const editPts = p.tool === 'select';

  return (
    <div ref={box} className="stage" style={{ cursor }} onWheel={onWheel} onPointerDown={onPointerDown}
         onPointerMove={onPointerMove} onPointerUp={onPointerUp} onDoubleClick={onDoubleClick}
         onPointerLeave={() => setMouse(null)} onContextMenu={(e) => e.preventDefault()} data-testid="stage">
      <div className="layer" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${s})` }}>
        <img src={p.src} width={p.width} height={p.height} alt="Tray photo" draggable={false} />
        {!p.hidden && (
          <svg width={p.width} height={p.height} aria-hidden="true">
            {r.ruler && (() => {
              const c = r.ruler.needs_check ? SNOUT : RULER, editable = p.tool === 'ruler';
              return (
                <g>
                  <line x1={r.ruler.p1[0]} y1={r.ruler.p1[1]} x2={r.ruler.p2[0]} y2={r.ruler.p2[1]}
                        stroke={HALO} strokeOpacity={0.6} strokeWidth={7} vectorEffect="non-scaling-stroke" />
                  <line x1={r.ruler.p1[0]} y1={r.ruler.p1[1]} x2={r.ruler.p2[0]} y2={r.ruler.p2[1]}
                        stroke={c} strokeWidth={3} vectorEffect="non-scaling-stroke" />
                  {(['p1', 'p2'] as const).map((k) => (
                    <circle key={k} data-kind="ruler" data-key={k} cx={r.ruler![k][0]} cy={r.ruler![k][1]}
                            r={(editable ? 9 : 6) / s} fill="#fff" stroke={c} strokeWidth={3} 
                            vectorEffect="non-scaling-stroke" style={{ cursor: editable ? 'move' : undefined }} />
                  ))}
                  <Tag x={r.ruler.p2[0]} y={r.ruler.p2[1]} s={s} color={c} fill={c} ink="#fff"
                       text={`Ruler · ${(r.ruler.length_mm / 10).toFixed(1)} cm${r.ruler.needs_check ? ' · check' : ''}`} />
                </g>
              );
            })()}
            {rulerStart && mouse && (
              <g style={{ pointerEvents: 'none' }}>
                <line x1={rulerStart[0]} y1={rulerStart[1]} x2={mouse[0]} y2={mouse[1]} stroke={HALO} strokeOpacity={0.6}
                      strokeWidth={6} vectorEffect="non-scaling-stroke" />
                <line x1={rulerStart[0]} y1={rulerStart[1]} x2={mouse[0]} y2={mouse[1]} stroke={RULER}
                      strokeWidth={2.5} vectorEffect="non-scaling-stroke" />
                <circle cx={rulerStart[0]} cy={rulerStart[1]} r={6 / s} fill="#fff" stroke={RULER} strokeWidth={3} vectorEffect="non-scaling-stroke" />
              </g>
            )}
            {order.map((i) => {
              const a = r.animals[i], isSel = i === p.sel, col = LINE[a.status], rejected = a.status === 'rejected';
              const dimmed = p.tool === 'redraw' && isSel;
              const d = pathD(catmullRom(a.midline));
              const label = `${i + 1} · ` + (a.status === 'rejected' ? a.reject_reason ?? 'rejected'
                : fmtCm(lengthCm(a, r.ruler)) + (isLowConfidence(a) ? ' ?' : ''));
              return (
                <g key={a.id} opacity={dimmed ? 0.35 : rejected && !isSel ? 0.65 : 1}>
                  {isSel && <path d={d} fill="none" stroke="#fff" strokeWidth={11} strokeLinecap="round" vectorEffect="non-scaling-stroke" />}
                  <path d={d} fill="none" stroke={HALO} strokeOpacity={0.6} strokeWidth={isSel ? 8 : 7} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                  <path d={d} fill="none" stroke={col} strokeWidth={isSel ? 4 : 3} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                  <path data-kind="curve" data-i={i} d={d} fill="none" stroke="transparent" strokeWidth={16}
                        vectorEffect="non-scaling-stroke" style={{ pointerEvents: editPts ? 'stroke' : 'none', cursor: 'pointer' }} />
                  {(isSel || a.status !== 'rejected') && a.midline.map((q, j) => {
                    const last = j === a.midline.length - 1;
                    const fill = j === 0 ? SNOUT : last ? TAIL : isSel ? '#fff' : col;
                    return (
                      <circle key={j} data-kind="point" data-i={i} data-j={j} cx={q[0]} cy={q[1]}
                              r={(isSel ? 6 : j === 0 || last ? 4.5 : 3) / s} fill={fill} stroke={HALO}
                              strokeWidth={isSel ? 2 : 1.5} vectorEffect="non-scaling-stroke"
                              style={{ pointerEvents: editPts ? 'all' : 'none', cursor: 'move' }} />
                    );
                  })}
                  {a.vent && (
                    <path data-kind="vent" data-i={i} vectorEffect="non-scaling-stroke"
                          d={`M${a.vent[0]} ${a.vent[1] - 9 / s} L${a.vent[0] - 8 / s} ${a.vent[1] + 6 / s} L${a.vent[0] + 8 / s} ${a.vent[1] + 6 / s} Z`}
                          fill={VENT} stroke="#fff" strokeWidth={1.5}
                          style={{ pointerEvents: editPts ? 'all' : 'none', cursor: 'move' }} />
                  )}
                  <Tag x={a.midline[0][0]} y={a.midline[0][1]} s={s} color={col} fill="#fff" ink="#1c1c1a" text={label} bold={isSel} />
                </g>
              );
            })}
            {p.draft && p.draft.length > 0 && (
              <g style={{ pointerEvents: 'none' }}>
                <path d={pathD(mouse ? [...p.draft, mouse] : p.draft)} fill="none" stroke={HALO} strokeOpacity={0.6}
                      strokeWidth={7} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                <path d={pathD(mouse ? [...p.draft, mouse] : p.draft)} fill="none" stroke={DRAFT} strokeWidth={3}
                      strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                {p.draft.map((q, j) => (
                  <circle key={j} cx={q[0]} cy={q[1]} r={(j === 0 ? 7 : 5) / s} fill={j === 0 ? SNOUT : DRAFT}
                          stroke={HALO} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
                ))}
              </g>
            )}
          </svg>
        )}
      </div>
      <div className="float">
        <button onClick={fit} onPointerDown={(e) => e.stopPropagation()}>Fit (F)</button>
        <span style={{ background: 'rgba(255,255,255,.92)', padding: '6px 10px', borderRadius: 6 }}>{Math.round(s * 100)}%</span>
      </div>
    </div>
  );
}

function Tag(t: { x: number; y: number; s: number; text: string; color: string; fill: string; ink: string; bold?: boolean }) {
  const fs = 12 / t.s, pad = 6 / t.s, w = (t.text.length * 7 + 12) / t.s, h = 20 / t.s;
  const x = t.x + 8 / t.s, y = t.y - h - 8 / t.s;
  return (
    <g style={{ pointerEvents: 'none' }}>
      <rect x={x} y={y} width={w} height={h} rx={4 / t.s} fill={t.fill} stroke={t.color} strokeWidth={t.bold ? 2 : 1} vectorEffect="non-scaling-stroke" />
      <text x={x + pad} y={y + h - 6 / t.s} fontSize={fs} fontWeight={600} fill={t.ink} fontFamily="Inter, system-ui, sans-serif">{t.text}</text>
    </g>
  );
}
