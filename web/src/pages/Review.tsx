import { useEffect, useRef, useState } from 'react';
import {
  Animal, AnimalStatus, api, ConflictError, fmtCm, isLowConfidence, lengthCm, minScore, mmPerPx,
  Photo, PhotoRecord, RejectReason, Ruler, Settings, Species,
} from '../api';
import Stage, { Tool } from '../components/Stage';
import { dist, Pt, svlPx } from '../geometry';
import { LINE } from '../colors';
import { busyIds, predict, useJobs, useOnPredicted } from '../jobs';
import { currentUser, go } from '../nav';

type SaveState = 'saved' | 'saving' | 'unsaved' | 'error' | 'conflict';
const SAVE_TEXT: Record<SaveState, string> = {
  saved: 'All changes saved', saving: 'Saving…', unsaved: 'Unsaved changes', error: 'Save failed', conflict: 'Conflict — reload',
};
const STATUS_TEXT: Record<AnimalStatus, string> = { pending: 'To review', accepted: 'Accepted', rejected: 'Rejected' };
const PHOTO_TAGS = ['junk', 'overlap', 'needs expert'];
const OBSERVATIONS = ['occluded', 'truncated', 'head_uncertain', 'tail_uncertain'];
const HINTS: Record<Tool, string> = {
  select: 'Select: click an animal, drag its points to fix it. Double-click its line to add a point, Alt-click a point to remove it.',
  add: 'Add animal: click the snout, then along the middle of the body, then the tail tip. Enter to finish, Backspace to undo a click, Esc to cancel. Right-drag or Space-drag to pan.',
  redraw: 'Redraw: click a new midline from snout to tail for the selected animal. Enter to finish, Esc to cancel. Right-drag to pan.',
  vent: 'Vent: click the vent of the selected animal (end of the trunk, just behind the hind legs).',
  ruler: 'Ruler: drag the ruler ends onto the 0 and 15 cm marks, or click two marks to draw a new ruler.',
  pan: 'Pan: drag to move around the photo.',
};
const TOOLS: [Tool, string, string][] = [
  ['select', 'Select', 'V'], ['add', 'Add', 'N'], ['redraw', 'Redraw', 'D'], ['vent', 'Vent', 'T'], ['ruler', 'Ruler', 'R'], ['pan', 'Pan', 'Space'],
];
const newId = () => Math.random().toString(16).slice(2, 10).padEnd(8, '0');

export default function Review({ id, settings }: { id: string; settings: Settings }) {
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [rec, setRec] = useState<PhotoRecord | null>(null);
  const recRef = useRef<PhotoRecord | null>(null);
  const [sel, setSel] = useState(-1);
  const [tool, setToolState] = useState<Tool>('select');
  const [draft, setDraft] = useState<Pt[] | null>(null);
  const [species, setSpeciesDefault] = useState<Species>('trout');
  const [hidden, setHidden] = useState(false);
  const [fitSignal, setFitSignal] = useState(0);
  const [space, setSpace] = useState(false);
  const [save, setSave] = useState<SaveState>('saved');
  const [banner, setBanner] = useState<{ text: string; err?: boolean } | null>(null);
  const [reviewQueue, setReviewQueue] = useState<string[]>([]);
  const [labelQueue, setLabelQueue] = useState<string[]>([]);
  const past = useRef<PhotoRecord[]>([]);
  const future = useRef<PhotoRecord[]>([]);
  const [, rerender] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const jobs = useJobs();
  const predicting = busyIds(jobs).has(id);
  const [confirmRepredict, setConfirmRepredict] = useState(false);

  // ---------- load
  const loadRecord = () => api.photo(id).then(({ photo, record }) => {
    setPhoto(photo); recRef.current = record; setRec(record);
    past.current = []; future.current = [];
    setSel(record.animals.findIndex((a) => a.status === 'pending'));
  }).catch((e) => setBanner({ text: 'Could not load photo: ' + e, err: true }));
  useOnPredicted((ids) => {
    if (!ids.includes(id)) return;
    if (pending.current) setBanner({ text: 'Predictions finished. Save your edits, then reload to see them.' });
    else { void loadRecord(); setBanner({ text: 'Predictions loaded. Accept, fix or reject each animal.' }); }
  }, [id]);
  const startPredict = async () => {
    if (rec && rec.animals.some((a) => a.source.kind === 'model') && !confirmRepredict) {
      setConfirmRepredict(true); setTimeout(() => setConfirmRepredict(false), 4000); return;
    }
    setConfirmRepredict(false);
    await flushAndWait();
    await predict([id], rec?.status === 'reviewed');
  };
  useEffect(() => {
    void loadRecord();
    api.photos({ status: 'predicted', sort: 'priority' }).then((l) => setReviewQueue(l.items.map((i) => i.id)));
    api.photos({ status: 'new', sort: 'name' }).then((l) => setLabelQueue(l.items.map((i) => i.id)));
  }, [id]);
  useEffect(() => { if (banner && !banner.err) { const t = setTimeout(() => setBanner(null), 5000); return () => clearTimeout(t); } }, [banner]);

  // ---------- saving: debounced, one request at a time, revision-checked
  const timer = useRef<number>();
  const inFlight = useRef(false);
  const dirty = useRef(false);      // edits made while a save was in flight
  const pending = useRef(false);    // edits not yet saved
  const flush = async (): Promise<void> => {
    window.clearTimeout(timer.current);
    if (inFlight.current) { dirty.current = true; return; }
    const r = recRef.current;
    if (!r) return;
    inFlight.current = true; dirty.current = false; setSave('saving');
    try {
      const saved = await api.save(r);
      if (recRef.current) recRef.current = { ...recRef.current, revision: saved.revision };
      setRec((cur) => (cur ? { ...cur, revision: saved.revision } : cur));
      if (!dirty.current) pending.current = false;
      setSave(dirty.current ? 'unsaved' : 'saved');
    } catch (e) {
      dirty.current = false;
      if (e instanceof ConflictError) { setSave('conflict'); setBanner({ text: e.message, err: true }); }
      else { setSave('error'); setBanner({ text: 'Could not save: ' + e, err: true }); }
    } finally {
      inFlight.current = false;
      if (dirty.current) void flush();
    }
  };
  const flushAndWait = async () => {
    while (inFlight.current) await new Promise((r) => setTimeout(r, 40));
    if (pending.current) await flush();
    while (inFlight.current) await new Promise((r) => setTimeout(r, 40));
  };
  const schedule = () => {
    pending.current = true;
    setSave('unsaved');
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flush(), 600);
  };
  useEffect(() => () => { if (pending.current) void flush(); }, []);
  useEffect(() => {
    const f = (e: BeforeUnloadEvent) => { if (save !== 'saved') e.preventDefault(); };
    addEventListener('beforeunload', f);
    return () => removeEventListener('beforeunload', f);
  }, [save]);

  // ---------- edits (with undo history)
  const set = (next: PhotoRecord) => { recRef.current = next; setRec(next); schedule(); rerender((x) => x + 1); };
  const remember = () => {
    if (!recRef.current) return;
    past.current.push(recRef.current);
    if (past.current.length > 200) past.current.shift();
    future.current = [];
  };
  const update = (fn: (r: PhotoRecord) => PhotoRecord) => { if (!recRef.current) return; remember(); set(fn(recRef.current)); };
  const live = (fn: (r: PhotoRecord) => PhotoRecord) => { if (recRef.current) set(fn(recRef.current)); };   // no history (drags)
  const undo = () => {
    const prev = past.current.pop(), cur = recRef.current;
    if (!prev || !cur) return;
    future.current.push(cur); set({ ...prev, revision: cur.revision });
    setSel((s) => Math.min(s, prev.animals.length - 1));
  };
  const redo = () => {
    const next = future.current.pop(), cur = recRef.current;
    if (!next || !cur) return;
    past.current.push(cur); set({ ...next, revision: cur.revision });
    setSel((s) => Math.min(s, next.animals.length - 1));
  };

  const patchAnimal = (r: PhotoRecord, i: number, fn: (a: Animal) => Animal): PhotoRecord =>
    ({ ...r, animals: r.animals.map((a, k) => (k === i ? fn(a) : a)) });
  // a person changing a model's points: keep the original once, mark edited
  const humanEdit = (a: Animal, midline: Pt[]): Animal => ({
    ...a, midline,
    model_midline: a.model_midline ?? (a.source.kind === 'model' ? a.midline : null),
    flags: { ...a.flags, edited: a.source.kind === 'model' ? true : a.flags.edited },
  });

  const nextPending = (r: PhotoRecord, from: number) => {
    const n = r.animals.length;
    for (let k = 1; k <= n; k++) { const j = (from + k) % n; if (r.animals[j].status === 'pending') return j; }
    return from;
  };
  const setStatus = (i: number, status: AnimalStatus, reason: RejectReason | null = null, advance = true) => {
    if (i < 0 || !recRef.current) return;
    update((r) => patchAnimal(r, i, (a) => ({ ...a, status, reject_reason: reason })));
    if (advance && status !== 'pending' && recRef.current) setSel(nextPending(recRef.current, i));
  };
  const setSpecies = (i: number, s: Species) => { setSpeciesDefault(s); update((r) => patchAnimal(r, i, (a) => ({ ...a, species: s }))); };
  const toggleObservation = (i: number, o: string) => update((r) => patchAnimal(r, i, (a) => ({
    ...a, flags: { ...a.flags, observations: a.flags.observations.includes(o) ? a.flags.observations.filter((x) => x !== o) : [...a.flags.observations, o] },
  })));
  const acceptRemaining = () => update((r) => ({ ...r, animals: r.animals.map((a) => (a.status === 'pending' ? { ...a, status: 'accepted' } : a)) }));
  const restoreModel = (i: number) => update((r) => patchAnimal(r, i, (a) => a.model_midline
    ? { ...a, midline: a.model_midline, model_midline: null, flags: { ...a.flags, edited: false } } : a));
  const deleteAnimal = (i: number) => {
    if (i < 0) return;
    update((r) => ({ ...r, animals: r.animals.filter((_, k) => k !== i) }));
    setSel(-1);
    setBanner({ text: 'Animal deleted. Ctrl+Z brings it back.' });
  };

  // points and vents
  const onPointMove = (i: number, j: number, p: Pt) => live((r) => patchAnimal(r, i, (a) => humanEdit(a, a.midline.map((q, m) => (m === j ? p : q)))));
  const onVentMove = (i: number, p: Pt) => live((r) => patchAnimal(r, i, (a) => ({ ...a, vent: p })));
  const onInsertPoint = (i: number, p: Pt) => update((r) => patchAnimal(r, i, (a) => {
    let best = 0, bd = Infinity;                       // insert into the nearest segment
    for (let k = 0; k < a.midline.length - 1; k++) {
      const [x0, y0] = a.midline[k], [x1, y1] = a.midline[k + 1], dx = x1 - x0, dy = y1 - y0, L2 = dx * dx + dy * dy || 1;
      const u = Math.max(0, Math.min(1, ((p[0] - x0) * dx + (p[1] - y0) * dy) / L2));
      const d = Math.hypot(x0 + u * dx - p[0], y0 + u * dy - p[1]);
      if (d < bd) { bd = d; best = k; }
    }
    return humanEdit(a, [...a.midline.slice(0, best + 1), p, ...a.midline.slice(best + 1)]);
  }));
  const onRemovePoint = (i: number, j: number) => {
    const a = recRef.current?.animals[i];
    if (!a) return;
    if (a.midline.length <= 2) { setBanner({ text: 'A midline needs at least 2 points.' }); return; }
    update((r) => patchAnimal(r, i, (b) => humanEdit(b, b.midline.filter((_, m) => m !== j))));
  };
  const onVent = (p: Pt) => {
    if (sel < 0) { setBanner({ text: 'Select an animal first, then place its vent.' }); return; }
    update((r) => patchAnimal(r, sel, (a) => ({ ...a, vent: p })));
    setTool('select');
  };
  const removeVent = (i: number) => update((r) => patchAnimal(r, i, (a) => ({ ...a, vent: null })));

  // drawing new midlines
  const setTool = (t: Tool) => {
    if ((t === 'redraw' || t === 'vent') && sel < 0) { setBanner({ text: `Select an animal first, then ${t === 'redraw' ? 'redraw it' : 'place its vent'}.` }); return; }
    setToolState(t);
    setDraft(t === 'add' || t === 'redraw' ? [] : null);
  };
  const finishDraft = () => {
    if (!draft) return;
    if (draft.length < 2) { setBanner({ text: 'Click at least the snout and the tail tip, then press Enter.' }); return; }
    if (tool === 'add') {
      const a: Animal = {
        id: newId(), species, midline: draft, model_midline: null, scores: null, vent: null, status: 'accepted',
        reject_reason: null, flags: { touching: false, edited: false, observations: [] },
        source: { kind: 'human', name: currentUser() }, note: '',
      };
      update((r) => ({ ...r, animals: [...r.animals, a] }));
      setSel(recRef.current!.animals.length - 1);
      setDraft([]);                                    // stay in Add for the next animal
    } else if (tool === 'redraw' && sel >= 0) {
      update((r) => patchAnimal(r, sel, (a) => humanEdit(a, draft)));
      setToolState('select'); setDraft(null);
    }
  };

  // ruler
  const toManual = (r: Ruler): Ruler => {
    const k = mmPerPx(r)!, L = dist(r.p1, r.p2), c: Pt = [(r.p1[0] + r.p2[0]) / 2, (r.p1[1] + r.p2[1]) / 2];
    const u: Pt = [(r.p2[0] - r.p1[0]) / L, (r.p2[1] - r.p1[1]) / L], half = settings.ruler_length_mm / k / 2;
    return { p1: [c[0] - u[0] * half, c[1] - u[1] * half], p2: [c[0] + u[0] * half, c[1] + u[1] * half],
             length_mm: settings.ruler_length_mm, source: 'manual', method: 'hand', confidence: null, needs_check: false };
  };
  const onRulerDragStart = () => {
    const r = recRef.current?.ruler;
    if (!r) return;
    remember();
    if (r.source === 'auto') {
      set({ ...recRef.current!, ruler: toManual(r) });
      setBanner({ text: `Ruler set to manual (${settings.ruler_length_mm / 10} cm): place its ends on the 0 and ${settings.ruler_length_mm / 10} cm marks.` });
    }
  };
  const onRulerMove = (key: 'p1' | 'p2', p: Pt) => live((r) => (r.ruler ? { ...r, ruler: { ...r.ruler, [key]: p, source: 'manual', needs_check: false } } : r));
  const onNewRuler = (p1: Pt, p2: Pt) => update((r) => ({
    ...r, ruler: { p1, p2, length_mm: settings.ruler_length_mm, source: 'manual', method: 'hand', confidence: null, needs_check: false },
  }));
  const setRulerSpan = (cm: number) => { if (cm > 0) update((r) => (r.ruler ? { ...r, ruler: { ...r.ruler, length_mm: cm * 10 } } : r)); };
  const resetRuler = () => update((r) => ({ ...r, ruler: r.auto_ruler }));

  // photo
  const toggleTag = (t: string) => update((r) => ({ ...r, tags: r.tags.includes(t) ? r.tags.filter((x) => x !== t) : [...r.tags, t] }));
  const navigate = async (to: () => void) => { await flushAndWait(); to(); };
  const labeling = rec?.status === 'new';
  const finish = async () => {
    const wasNew = recRef.current?.status === 'new';
    update((r) => ({ ...r, status: 'reviewed' }));
    await flushAndWait();
    if (wasNew) {
      const i = labelQueue.indexOf(id), rest = labelQueue.filter((x) => x !== id);
      const next = rest.length ? rest[Math.max(0, i) % rest.length] : null;
      if (next) go.review(next); else go.photos();
    } else go.nextReview(id);
  };
  const reopen = () => update((r) => ({ ...r, status: r.animals.some((a) => a.source.kind === 'model') ? 'predicted' : 'new' }));

  // ---------- keyboard
  const keys = useRef<(e: KeyboardEvent) => void>(() => {});
  keys.current = (e: KeyboardEvent) => {
    const t = e.target as HTMLElement;
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(t.tagName)) return;
    const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey;
    const n = recRef.current?.animals.length ?? 0;
    if (k === ' ') { setSpace(true); e.preventDefault(); return; }
    if (mod && k === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (mod && k === 'y') { e.preventDefault(); redo(); return; }
    if (mod && k === 'enter') { e.preventDefault(); void finish(); return; }
    if (mod || e.altKey) return;
    if (draft) {                                         // while drawing a midline
      if (k === 'enter') { finishDraft(); e.preventDefault(); return; }
      if (k === 'backspace') { setDraft(draft.slice(0, -1)); e.preventDefault(); return; }
      if (k === 'escape') { if (draft.length) setDraft([]); else setTool('select'); e.preventDefault(); return; }
    }
    if (k === 'v' || k === 'escape') setTool('select');
    else if (k === 'n') setTool('add');
    else if (k === 'd') setTool('redraw');
    else if (k === 't') setTool('vent');
    else if (k === 'r') setTool('ruler');
    else if (k === 'f') setFitSignal((x) => x + 1);
    else if (k === 'h') setHidden((x) => !x);
    else if (k === 'a') setStatus(sel, 'accepted');
    else if (k === 'j') setStatus(sel, 'rejected', 'junk');
    else if (k === 'o') setStatus(sel, 'rejected', 'overlap');
    else if (k === 'u') setStatus(sel, 'pending', null, false);
    else if (k === 'delete') deleteAnimal(sel);
    else if (k === '1' || k === '2' || k === '3') {
      const sp = ({ '1': 'trout', '2': 'salamander', '3': 'other' } as const)[k];
      if (tool === 'add' || sel < 0) setSpeciesDefault(sp);     // in Add mode: species of the NEXT animal
      else setSpecies(sel, sp);
    }
    else if (k === 'tab' && n) setSel((s) => (s + (e.shiftKey ? n - 1 : 1)) % n);
    else return;
    e.preventDefault();
  };
  useEffect(() => {
    const down = (e: KeyboardEvent) => keys.current(e);
    const up = (e: KeyboardEvent) => { if (e.key === ' ') setSpace(false); };
    addEventListener('keydown', down); addEventListener('keyup', up);
    return () => { removeEventListener('keydown', down); removeEventListener('keyup', up); };
  }, []);
  useEffect(() => { listRef.current?.querySelector('.animal.sel')?.scrollIntoView({ block: 'nearest' }); }, [sel]);

  if (!rec || !photo) return <div className="empty">{banner?.text ?? 'Loading…'}</div>;

  const queue = labeling ? labelQueue : reviewQueue;
  const qi = queue.indexOf(id);
  const neighbor = (d: number) => (queue.length ? queue[((qi < 0 ? (d > 0 ? -1 : 0) : qi) + d + queue.length) % queue.length] : null);
  const counts = { accepted: 0, pending: 0, rejected: 0 } as Record<AnimalStatus, number>;
  rec.animals.forEach((a) => { counts[a.status] += 1; });
  const ruler = rec.ruler, k = mmPerPx(ruler);
  const empty = !rec.animals.length && !draft;

  return (
    <>
      <div className="rv-bar">
        <button className="btn link" onClick={() => navigate(go.photos)}>← All photos</button>
        <span className="title">{photo.filename}</span>
        <span className={'pill ' + rec.status}>
          {rec.status === 'predicted' ? 'Needs review' : rec.status === 'reviewed' ? 'Reviewed' : rec.animals.length ? 'Labeling' : 'Not labeled'}
        </span>
        {qi >= 0 && <span style={{ color: 'var(--muted)' }}>Photo {qi + 1} of {queue.length} {labeling ? 'not yet labeled' : 'needing review'}</span>}
        <div className="right">
          <span style={{ color: save === 'saved' ? 'var(--muted)' : save === 'error' || save === 'conflict' ? 'var(--danger)' : 'var(--pending-ink)' }}
                role="status">{SAVE_TEXT[save]}</span>
          {rec.status !== 'reviewed' && (
            <button className="btn" disabled={predicting} onClick={startPredict}
                    title="Run the model on this photo. Hand-drawn animals and a hand-set ruler are kept.">
              {predicting ? <><span className="spinner" style={{ display: 'inline-block', marginRight: 6 }} />Predicting…</>
                : confirmRepredict ? 'Click again: replace model animals' : rec.animals.some((a) => a.source.kind === 'model') ? 'Re-predict' : 'Predict'}
            </button>
          )}
          <button className="btn" disabled={!neighbor(-1)} onClick={() => navigate(() => go.review(neighbor(-1)!))}>‹ Prev</button>
          <button className="btn" disabled={!neighbor(1)} onClick={() => navigate(() => go.review(neighbor(1)!))}>Next ›</button>
          {rec.status === 'reviewed'
            ? <button className="btn" onClick={reopen}>Reopen</button>
            : <button className="btn primary" onClick={finish} title="Ctrl+Enter">{labeling ? 'Done & next' : 'Mark reviewed & next'}</button>}
        </div>
      </div>

      <div className="rv-body">
        <div className="toolbar" role="toolbar" aria-label="Tools">
          {TOOLS.map(([t, name, key]) => (
            <button key={t} className={'tool' + (tool === t ? ' on' : '')} aria-pressed={tool === t} title={`${name} (${key})`}
                    disabled={(t === 'redraw' || t === 'vent') && sel < 0} onClick={() => setTool(t)}>
              {name}<small>{key}</small>
            </button>
          ))}
          <span className="sep" />
          <button className="tool" disabled={!past.current.length} onClick={undo} title="Undo (Ctrl+Z)">Undo<small>Ctrl Z</small></button>
          <button className="tool" disabled={!future.current.length} onClick={redo} title="Redo (Ctrl+Shift+Z)">Redo<small>⇧ Ctrl Z</small></button>
          <button className="tool" aria-pressed={hidden} onClick={() => setHidden((x) => !x)} title="Hide overlay (H)">{hidden ? 'Show' : 'Hide'}<small>H</small></button>
        </div>

        <div className="stage-wrap">
          <div style={{ position: 'relative', flex: 1, display: 'flex' }}>
            {banner && <div className={'banner' + (banner.err ? ' err' : '')} role="alert">
              {banner.text}{' '}
              {save === 'conflict' ? <button className="btn" onClick={() => location.reload()}>Reload</button>
                : <button className="btn link" style={{ color: '#fff' }} onClick={() => setBanner(null)}>Dismiss</button>}
            </div>}
            {empty && tool === 'select' && (
              <div className="empty-card" role="region" aria-label="Get started">
                <b>No animals on this photo yet.</b>
                <p>Trace each fish or salamander from snout to tail{ruler ? '' : ', and set the ruler'}.</p>
                <div className="row" style={{ justifyContent: 'center' }}>
                  <button className="btn primary" onClick={() => setTool('add')}>Label by hand (N)</button>
                  <button className="btn" disabled={predicting} onClick={startPredict}>{predicting ? 'Predicting…' : 'Predict'}</button>
                </div>
              </div>
            )}
            <Stage src={api.imageUrl(id)} width={photo.width} height={photo.height} rec={rec} sel={sel} tool={tool}
                   hidden={hidden} fitSignal={fitSignal} spaceDown={space} draft={draft}
                   onSelect={setSel} onDragStart={remember} onPointMove={onPointMove} onVentMove={onVentMove}
                   onRulerDragStart={onRulerDragStart} onRulerMove={onRulerMove} onDragEnd={() => rerender((x) => x + 1)}
                   onNewRuler={onNewRuler} onDraftPoint={(p) => setDraft((d) => [...(d ?? []), p])} onVent={onVent}
                   onInsertPoint={onInsertPoint} onRemovePoint={onRemovePoint} />
          </div>
          <div className="hint">
            <b>{HINTS[tool]}</b>
            {draft ? (
              <span className="row">
                {draft.length} point{draft.length === 1 ? '' : 's'} ·
                {tool === 'add' && (
                  <label className="row" style={{ gap: 4 }}>species
                    <select className="btn" style={{ padding: '2px 6px' }} value={species} onChange={(e) => setSpeciesDefault(e.target.value as Species)}>
                      <option value="trout">trout (1)</option><option value="salamander">salamander (2)</option><option value="other">other (3)</option>
                    </select>
                  </label>
                )}
                <button className="btn primary" disabled={draft.length < 2} onClick={finishDraft}>Finish (Enter)</button>
                <button className="btn" onClick={() => setTool('select')}>Cancel (Esc)</button>
              </span>
            ) : (
              <span>A accept · J junk · O overlap · U undo status · Delete remove · 1/2/3 species · Tab next · Ctrl+Z undo · scroll to zoom · F fit</span>
            )}
          </div>
        </div>

        <aside className="side" aria-label="Details">
          <section className="panel">
            <h2>Ruler {!ruler ? <span className="pill warn">Missing</span>
              : ruler.needs_check ? <span className="pill warn">Check</span>
              : ruler.source === 'auto' ? <span className="pill accepted">✓ Auto-detected</span>
              : <span className="pill new">Manual</span>}</h2>
            {ruler ? (
              <>
                <p>{(1 / k!).toFixed(2)} px per mm{ruler.source === 'auto' && ruler.method === 'ticks' ? ", read from the ruler's mm ticks" : ''}.
                  {' '}Use the Ruler tool (R) to drag its ends; lengths update instantly.</p>
                <label className="row">Distance between ruler ends
                  <input className="inline-num" type="number" step="0.1" min="0.1" value={(ruler.length_mm / 10).toFixed(1)}
                         onChange={(e) => setRulerSpan(parseFloat(e.target.value))} /> cm
                </label>
                {rec.auto_ruler && ruler.source !== 'auto' && <button className="btn link" style={{ alignSelf: 'flex-start' }} onClick={resetRuler}>Reset to auto-detected</button>}
              </>
            ) : (
              <>
                <p>No ruler yet: lengths can't be measured. Click the 0 and {settings.ruler_length_mm / 10} cm marks on the ruler.</p>
                <button className="btn" style={{ alignSelf: 'flex-start' }} onClick={() => setTool('ruler')}>Set ruler (R)</button>
              </>
            )}
          </section>

          <section className="panel">
            <h2>Photo tags</h2>
            <div className="row">
              {PHOTO_TAGS.map((t) => (
                <label key={t} className="row" style={{ gap: 4 }}>
                  <input type="checkbox" checked={rec.tags.includes(t)} onChange={() => toggleTag(t)} /> {t}
                </label>
              ))}
            </div>
          </section>

          <section style={{ display: 'flex', flexDirection: 'column', gap: 8 }} ref={listRef}>
            <div className="row">
              <h2 style={{ margin: 0, fontSize: 14 }}>Animals</h2>
              <span style={{ color: 'var(--muted)' }}>{counts.accepted} accepted · {counts.pending} to review · {counts.rejected} rejected</span>
            </div>
            <div className="row">
              <button className="btn" onClick={() => setTool('add')}>+ Add animal (N)</button>
              {counts.pending > 0 && <button className="btn" style={{ marginLeft: 'auto' }} onClick={acceptRemaining}>Accept remaining ({counts.pending})</button>}
            </div>
            {rec.animals.map((a, i) => {
              const isSel = i === sel, s = minScore(a), low = isLowConfidence(a);
              const svl = a.vent && k ? (svlPx(a.midline, a.vent) * k) / 10 : null;
              const notes = [a.flags.touching && 'touching another animal', a.flags.edited && 'edited',
                             a.source.kind === 'human' && `hand label (${a.source.name})`].filter(Boolean);
              return (
                <div key={a.id} className={'animal' + (isSel ? ' sel' : '')}>
                  <button className="head" onClick={() => setSel(i)} aria-expanded={isSel}>
                    <span className="num" style={{ background: LINE[a.status], color: '#0b0b0a', boxShadow: 'inset 0 0 0 1.5px rgba(0,0,0,.35)' }}>{i + 1}</span>
                    <span style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 0 }}>
                      <span className="row" style={{ alignItems: 'baseline' }}>
                        <span className="len">{a.status === 'rejected' ? '—' : fmtCm(lengthCm(a, ruler))}</span>
                        <span style={{ color: 'var(--muted)' }}>{a.species}{svl !== null ? ` · SVL ${svl.toFixed(1)} cm` : ''}</span>
                      </span>
                      {s !== null && (
                        <span className="conf">
                          <span className="bar"><span style={{ width: `${Math.round(s * 100)}%`, background: low ? 'var(--danger)' : s < 0.6 ? 'var(--pending)' : 'var(--accepted)' }} /></span>
                          <span style={low ? { color: 'var(--danger)', fontWeight: 600 } : undefined}>
                            {low ? `Low confidence ${Math.round(s * 100)}% — check` : `Confidence ${Math.round(s * 100)}%`}
                          </span>
                        </span>
                      )}
                    </span>
                    <span className={'pill ' + a.status}>{a.status === 'rejected' ? `Rejected · ${a.reject_reason}` : STATUS_TEXT[a.status]}</span>
                  </button>
                  {isSel && (
                    <>
                      <div className="actions">
                        <button className="btn good" onClick={() => setStatus(i, 'accepted')}>Accept · A</button>
                        <button className="btn" onClick={() => setStatus(i, 'rejected', 'junk')}>Junk · J</button>
                        <button className="btn" onClick={() => setStatus(i, 'rejected', 'overlap')}>Overlap · O</button>
                        {a.status !== 'pending' && <button className="btn link" onClick={() => setStatus(i, 'pending', null, false)}>Undo status · U</button>}
                      </div>
                      <div className="row" style={{ paddingTop: 8 }}>
                        <label className="row" style={{ gap: 6 }}>Species
                          <select className="btn" style={{ padding: '3px 6px' }} value={a.species} onChange={(e) => setSpecies(i, e.target.value as Species)}>
                            <option value="trout">trout</option><option value="salamander">salamander</option>
                            <option value="other">other</option><option value="unknown">unknown</option>
                          </select>
                        </label>
                        <button className="btn" onClick={() => setTool('redraw')}>Redraw · D</button>
                        <button className="btn" onClick={() => setTool('vent')}>{a.vent ? 'Move vent' : 'Add vent'} · T</button>
                        {a.vent && <button className="btn link" onClick={() => removeVent(i)}>Remove vent</button>}
                      </div>
                      <div className="row" style={{ paddingTop: 6 }}>
                        {OBSERVATIONS.map((o) => (
                          <label key={o} className="row" style={{ gap: 4, fontSize: 13 }}>
                            <input type="checkbox" checked={a.flags.observations.includes(o)} onChange={() => toggleObservation(i, o)} />
                            {o.replace('_', ' ')}
                          </label>
                        ))}
                      </div>
                      <div className="row" style={{ paddingTop: 6 }}>
                        {a.model_midline && <button className="btn link" onClick={() => restoreModel(i)}>Restore model points</button>}
                        <button className="btn link" style={{ color: 'var(--danger)', marginLeft: 'auto' }} onClick={() => deleteAnimal(i)}>Delete animal</button>
                      </div>
                      {notes.length > 0 && <p style={{ margin: '6px 0 0', color: 'var(--muted)', fontSize: 12 }}>{notes.join(' · ')}</p>}
                    </>
                  )}
                </div>
              );
            })}
          </section>
        </aside>
      </div>
    </>
  );
}
