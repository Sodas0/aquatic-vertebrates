import { useEffect, useMemo, useRef, useState } from 'react';
import { api, PhotoList, PhotoStatus } from '../api';
import { busyIds, predict, trackJob, useJobs, useOnPredicted } from '../jobs';
import { go } from '../nav';

const STATUS_LABEL: Record<PhotoStatus, string> = { new: 'Not processed', predicted: 'Needs review', reviewed: 'Reviewed' };
const STATUS_CHIPS: [string, string][] = [['', 'All'], ['predicted', 'Needs review'], ['reviewed', 'Reviewed'], ['new', 'Not processed']];
const TAGS = ['trout', 'salamander', 'overlap', 'junk', 'low confidence', 'ruler check'];

function usePersisted<T>(key: string, init: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try { const s = sessionStorage.getItem(key); return s ? JSON.parse(s) : init; } catch { return init; }
  });
  return [v, (x: T) => { setV(x); try { sessionStorage.setItem(key, JSON.stringify(x)); } catch { /* storage off */ } }];
}

export default function Photos() {
  const [status, setStatus] = usePersisted('f.status', '');
  const [tag, setTag] = usePersisted('f.tag', '');
  const [q, setQ] = usePersisted('f.q', '');
  const [sort, setSort] = usePersisted('f.sort', 'name');
  const [view, setView] = usePersisted<'table' | 'grid'>('f.view', 'table');
  const [data, setData] = useState<PhotoList | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [predictAfter, setPredictAfter] = usePersisted('f.predictAfter', true);
  const [notice, setNotice] = useState<{ text: string; err?: boolean } | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const jobs = useJobs();
  const busySet = busyIds(jobs);

  const load = () => api.photos({ status, tag, q, sort }).then(setData);
  useEffect(() => { const t = setTimeout(load, q ? 200 : 0); return () => clearTimeout(t); }, [status, tag, q, sort]);
  useOnPredicted(() => { void load(); }, [status, tag, q, sort]);

  const upload = async (files: File[]) => {
    const images = files.filter((f) => /\.(jpe?g|png|heic|tiff?)$/i.test(f.name) || f.type.startsWith('image/'));
    if (!images.length) { setNotice({ text: 'No image files to add.', err: true }); return; }
    setBusy(true);
    setNotice({ text: `Uploading ${images.length} photo${images.length === 1 ? '' : 's'}…` });
    try {
      const r = await api.upload(images, predictAfter);
      const added = r.photos.filter((x) => x.id && !x.duplicate).length;
      const dups = r.photos.filter((x) => x.duplicate).length, bad = r.photos.filter((x) => x.error);
      if (r.job) trackJob(r.job);
      setNotice({
        err: bad.length > 0,
        text: `Added ${added} photo${added === 1 ? '' : 's'}` + (dups ? ` · ${dups} already here (skipped)` : '') +
          (bad.length ? ` · ${bad.length} not readable: ${bad.map((b) => b.filename).join(', ')}` : '') +
          (r.job ? ' · predicting in the background' : ''),
      });
      setStatus(r.job ? 'predicted' : 'new');
      await load();
    } catch (e) {
      setNotice({ text: 'Upload failed: ' + e, err: true });
    } finally { setBusy(false); }
  };
  const runPredict = async (ids: string[], what: string) => {
    if (!ids.length) return;
    await predict(ids);
    setNotice({ text: `Predicting ${ids.length} ${what} in the background. You can keep working.` });
    setSelected(new Set());
  };

  const items = data?.items ?? [];
  const c = data?.counts ?? {};
  const toggle = (id: string) => {
    const s = new Set(selected);
    s.has(id) ? s.delete(id) : s.add(id);
    setSelected(s);
  };
  const allOn = items.length > 0 && items.every((i) => selected.has(i.id));
  const selItems = useMemo(() => items.filter((i) => selected.has(i.id)), [items, selected]);
  const canReview = selItems.filter((i) => i.status === 'predicted').map((i) => i.id);

  const markReviewed = async () => {
    setBusy(true);
    try { await api.bulk(canReview, 'mark_reviewed'); setSelected(new Set()); await load(); } finally { setBusy(false); }
  };
  const open = (id: string) => go.review(id);
  const canPredict = selItems.filter((i) => i.status !== 'reviewed' && !busySet.has(i.id)).map((i) => i.id);

  return (
    <main className="page"
          onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDragging(true); } }}
          onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
          onDrop={(e) => { e.preventDefault(); setDragging(false); void upload(Array.from(e.dataTransfer.files)); }}>
      {dragging && <div className="dropzone"><div>Drop photos to add them</div></div>}
      <input ref={fileInput} type="file" accept="image/*" multiple className="sr-only" tabIndex={-1} aria-label="Add photos" data-testid="file-input"
             onChange={(e) => { void upload(Array.from(e.target.files ?? [])); e.target.value = ''; }} />
      <div className="page-head">
        <div>
          <h1>Photos</h1>
          <p>{c.all ?? 0} photos · {c.predicted ?? 0} need review · {c.reviewed ?? 0} reviewed · {c.new ?? 0} not processed</p>
        </div>
        <div className="actions">
          <label className="row" style={{ gap: 6, color: 'var(--muted)' }}>
            <input type="checkbox" checked={predictAfter} onChange={(e) => setPredictAfter(e.target.checked)} /> predict after adding
          </label>
          <button className="btn" disabled={busy} onClick={() => fileInput.current?.click()}>Add photos</button>
          {(c.new ?? 0) > 0 && (
            <button className="btn" onClick={async () => {
              const all = await api.photos({ status: 'new' });
              await runPredict(all.items.filter((i) => !i.n_animals && !busySet.has(i.id)).map((i) => i.id), 'unprocessed photos');
            }}>Predict all unprocessed</button>
          )}
          <button className="btn primary" disabled={!c.predicted} onClick={() => go.nextReview()}>
            Review next ({c.predicted ?? 0})
          </button>
        </div>
      </div>

      <div className="filters">
        {STATUS_CHIPS.map(([k, label]) => (
          <button key={k} className={'chip' + (status === k ? ' on' : '')} aria-pressed={status === k} onClick={() => setStatus(k)}>
            {label}<span className="n">{k ? c[k] ?? 0 : c.all ?? 0}</span>
          </button>
        ))}
        <span className="sep" />
        <label>
          <span className="sr-only">Tag</span>
          <select className="btn" value={tag} onChange={(e) => setTag(e.target.value)}>
            <option value="">Any tag</option>
            {TAGS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <div className="grow">
          <label className="search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#5f5e58" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
            <span className="sr-only">Search photos</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search photos" />
          </label>
          <label>
            <span className="sr-only">Sort</span>
            <select className="btn" value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="name">Sort: name</option>
              <option value="updated">Sort: recently updated</option>
              <option value="priority">Sort: review priority</option>
            </select>
          </label>
          <div role="group" aria-label="View">
            <button className={'chip' + (view === 'table' ? ' on' : '')} aria-pressed={view === 'table'} onClick={() => setView('table')}>Table</button>{' '}
            <button className={'chip' + (view === 'grid' ? ' on' : '')} aria-pressed={view === 'grid'} onClick={() => setView('grid')}>Grid</button>
          </div>
        </div>
      </div>

      {notice && (
        <div className={'notice' + (notice.err ? ' err' : '')} role="status">
          {notice.text}<button className="btn link" style={{ marginLeft: 'auto' }} onClick={() => setNotice(null)}>Dismiss</button>
        </div>
      )}

      {selected.size > 0 && (
        <div className="selectbar" role="region" aria-label="Selection actions">
          <b>{selected.size} selected</b>
          <button className="btn primary" disabled={!canPredict.length} onClick={() => runPredict(canPredict, 'photos')}
                  title={canPredict.length < selected.size ? 'Reviewed photos are not re-predicted' : undefined}>
            Predict{canPredict.length ? ` (${canPredict.length})` : ''}
          </button>
          <button className="btn" disabled={!canReview.length || busy} onClick={markReviewed}>
            Mark reviewed{canReview.length ? ` (${canReview.length})` : ''}
          </button>
          <button className="btn link" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}

      {data && !items.length && <div className="card-box empty">No photos match these filters.</div>}

      {view === 'table' && items.length > 0 && (
        <div className="card-box">
          <table className="photos">
            <thead>
              <tr>
                <th style={{ width: 36, paddingLeft: 14 }}>
                  <input type="checkbox" aria-label="Select all shown" checked={allOn}
                         onChange={() => setSelected(allOn ? new Set() : new Set(items.map((i) => i.id)))} />
                </th>
                <th>Photo</th><th>Status</th><th>Animals</th><th>To review</th><th>Tags</th><th>Updated</th><th />
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} className={selected.has(it.id) ? 'sel' : ''}>
                  <td style={{ paddingLeft: 14 }}>
                    <input type="checkbox" aria-label={'Select ' + it.filename} checked={selected.has(it.id)} onChange={() => toggle(it.id)} />
                  </td>
                  <td>
                    <div className="row" style={{ gap: 12, flexWrap: 'nowrap' }}>
                      <img className="thumb" src={api.thumbUrl(it.id)} loading="lazy" alt="" />
                      <button className="namebtn" onClick={() => open(it.id)}>{it.filename}</button>
                    </div>
                  </td>
                  <td>{busySet.has(it.id) ? <span className="pill predicted"><span className="spinner" style={{ display: 'inline-block', width: 10, height: 10, marginRight: 6 }} />Predicting</span>
                    : <span className={'pill ' + it.status}>{it.status === 'new' && it.n_animals ? 'Labeling' : STATUS_LABEL[it.status]}</span>}</td>
                  <td>{it.n_animals || '—'}</td>
                  <td>{it.n_pending || '—'}</td>
                  <td>
                    {it.tags.map((t) => <span key={t} className="tag">{t}</span>)}
                    {it.n_low_confidence > 0 && <span className="tag" style={{ color: 'var(--danger)' }}>{it.n_low_confidence} low confidence</span>}
                    {it.ruler_check && <span className="tag" style={{ color: 'var(--danger)' }}>ruler check</span>}
                  </td>
                  <td style={{ color: 'var(--muted)' }}>{it.updated_at?.replace('T', ' ').slice(0, 16) ?? '—'}</td>
                  <td style={{ textAlign: 'right', paddingRight: 14 }}>
                    <button className="btn" onClick={() => open(it.id)}>
                      {it.status === 'predicted' ? 'Review' : it.status === 'new' ? 'Label' : 'Open'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {view === 'grid' && items.length > 0 && (
        <div className="grid">
          {items.map((it) => (
            <div key={it.id} className="gcard" style={selected.has(it.id) ? { outline: '2px solid var(--accent)' } : undefined}>
              <button className="namebtn" style={{ width: '100%' }} onClick={() => open(it.id)} aria-label={'Open ' + it.filename}>
                <img src={api.thumbUrl(it.id)} loading="lazy" alt="" />
              </button>
              <div className="meta">
                <label className="row" style={{ gap: 6 }}>
                  <input type="checkbox" checked={selected.has(it.id)} onChange={() => toggle(it.id)} />
                  <b style={{ fontSize: 13 }}>{it.filename}</b>
                </label>
                <div><span className={'pill ' + it.status}>{it.status === 'new' && it.n_animals ? 'Labeling' : STATUS_LABEL[it.status]}</span>{' '}
                  {it.n_animals > 0 && <span className="tag">{it.n_animals} animals{it.n_pending ? `, ${it.n_pending} to review` : ''}</span>}
                </div>
                <div>{it.tags.map((t) => <span key={t} className="tag">{t}</span>)}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
