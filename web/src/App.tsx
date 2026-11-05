import { useEffect, useState } from 'react';
import { api, Settings } from './api';
import { startPolling, useJobs } from './jobs';
import { currentUser, go, setCurrentUser } from './nav';
import Photos from './pages/Photos';
import Review from './pages/Review';

function useRoute() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const f = () => setHash(location.hash);
    addEventListener('hashchange', f);
    return () => removeEventListener('hashchange', f);
  }, []);
  const m = hash.match(/^#\/review\/([0-9a-f]+)/);
  return m ? { page: 'review' as const, id: m[1] } : { page: 'photos' as const, id: null };
}

export default function App() {
  const route = useRoute();
  const [settings, setSettings] = useState<Settings | null>(null);
  useEffect(() => { api.settings().then(setSettings); startPolling(); }, []);
  const jobs = useJobs();
  const running = jobs.filter((j) => j.status === 'queued' || j.status === 'running');
  const todo = running.reduce((n, j) => n + j.total, 0), done = running.reduce((n, j) => n + j.done, 0);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3 12c3-5 9-6 14-2l4-3v10l-4-3c-5 4-11 3-14-2z" /><circle cx="16" cy="11" r="0.8" />
          </svg>
          Fish Length Review <small>/ 2025 Synoptic survey</small>
        </div>
        <nav className="nav" aria-label="Main">
          <a href="#/" className={route.page === 'photos' ? 'on' : ''}>Photos</a>
          <a href="#/review" className={route.page === 'review' ? 'on' : ''}
             onClick={(e) => { e.preventDefault(); go.nextReview(); }}>Review</a>
          <a href={api.exportUrl}>Export CSV</a>
        </nav>
        {running.length > 0 && (
          <span className="jobpill" role="status" aria-live="polite">
            <span className="spinner" aria-hidden="true" /> Predicting {done} of {todo} photo{todo === 1 ? '' : 's'}…
          </span>
        )}
        <div className="right row">
          <label className="row" style={{ gap: 6 }}>Your name
            <input className="inline-num" style={{ width: 110 }} defaultValue={currentUser() === 'unknown' ? '' : currentUser()}
                   placeholder="for hand labels" onChange={(e) => setCurrentUser(e.target.value)} />
          </label>
          <span>{settings && `Ruler: ${settings.ruler_length_mm / 10} cm · Units: ${settings.display_unit}`}</span>
        </div>
      </header>
      {route.page === 'photos' ? <Photos /> : settings && <Review key={route.id} id={route.id!} settings={settings} />}
    </div>
  );
}
