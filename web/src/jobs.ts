// Background prediction jobs: one shared store, polled only while something is running.
// Pages subscribe with useJobs(); when a job finishes, 'fishlen:predicted' fires with its photo ids.
import { useEffect, useState } from 'react';

export interface Job {
  id: string; kind: string; photo_ids: string[]; force: boolean;
  status: 'queued' | 'running' | 'done' | 'done_with_errors';
  done: number; total: number; current: string | null; messages: string[]; error: string | null;
  created: string; finished: string | null;
}

let jobs: Job[] = [];
const listeners = new Set<(j: Job[]) => void>();
let timer: number | undefined;

const active = (j: Job) => j.status === 'queued' || j.status === 'running';

async function poll() {
  const r = await fetch('/api/jobs');
  if (!r.ok) return;
  const next: Job[] = await r.json();
  const finished = next.filter((j) => !active(j) && jobs.some((o) => o.id === j.id && active(o)));
  jobs = next;
  listeners.forEach((f) => f(jobs));
  for (const j of finished)
    window.dispatchEvent(new CustomEvent('fishlen:predicted', { detail: { ids: j.photo_ids, job: j } }));
  window.clearTimeout(timer);
  if (jobs.some(active)) timer = window.setTimeout(poll, 1500);
}

export function startPolling() { void poll(); }

export async function predict(ids: string[], force = false): Promise<Job> {
  const r = await fetch('/api/predict', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids, force }),
  });
  if (!r.ok) throw new Error(await r.text());
  const job: Job = await r.json();
  jobs = [job, ...jobs];
  listeners.forEach((f) => f(jobs));
  window.clearTimeout(timer);
  timer = window.setTimeout(poll, 800);
  return job;
}

export function trackJob(job: Job) {
  jobs = [job, ...jobs.filter((j) => j.id !== job.id)];
  listeners.forEach((f) => f(jobs));
  window.clearTimeout(timer);
  timer = window.setTimeout(poll, 800);
}

export function useJobs(): Job[] {
  const [j, setJ] = useState(jobs);
  useEffect(() => { listeners.add(setJ); return () => { listeners.delete(setJ); }; }, []);
  return j;
}

/** Photo ids waiting for or undergoing prediction. */
export function busyIds(list: Job[]): Set<string> {
  const s = new Set<string>();
  for (const j of list) if (active(j)) j.photo_ids.slice(j.done).forEach((id) => s.add(id));
  return s;
}

/** Re-run `fn` whenever a prediction job that touched one of these photos (or any, if omitted) finishes. */
export function useOnPredicted(fn: (ids: string[]) => void, deps: unknown[] = []) {
  useEffect(() => {
    const h = (e: Event) => fn((e as CustomEvent).detail.ids);
    window.addEventListener('fishlen:predicted', h);
    return () => window.removeEventListener('fishlen:predicted', h);
  }, deps);
}
