// Types mirror fishlen/schema.py (schema_version 1) and server/main.py. The full API contract is
// at /docs. If these drift, the server rejects saves with 422, so keep both in step.
import { curveLength, dist, Pt } from './geometry';

export type Species = 'trout' | 'salamander' | 'other' | 'unknown';
export type AnimalStatus = 'pending' | 'accepted' | 'rejected';
export type RejectReason = 'junk' | 'overlap' | 'other';
export type PhotoStatus = 'new' | 'predicted' | 'reviewed';

export interface Ruler {
  p1: Pt; p2: Pt; length_mm: number; source: 'auto' | 'manual';
  method?: string | null; confidence?: number | null; needs_check: boolean;
}
export interface Animal {
  id: string; species: Species; midline: Pt[]; model_midline?: Pt[] | null; scores?: number[] | null;
  vent?: Pt | null; box?: [number, number, number, number] | null; status: AnimalStatus; reject_reason?: RejectReason | null;
  flags: { touching: boolean; edited: boolean; observations: string[] };
  source: { kind: 'model' | 'human' | 'import'; name: string }; note: string;
}
export interface PhotoRecord {
  schema_version: number; photo_id: string; revision: number; status: PhotoStatus; tags: string[];
  ruler: Ruler | null; auto_ruler: Ruler | null; animals: Animal[]; pipeline: Record<string, string>; notes: string;
}
export interface Photo { id: string; filename: string; width: number; height: number; added_at: string; }
export interface PhotoSummary {
  id: string; filename: string; status: PhotoStatus; tags: string[]; n_animals: number; n_pending: number;
  n_low_confidence: number; ruler_check: boolean; updated_at: string | null;
}
export interface PhotoList { items: PhotoSummary[]; counts: Record<string, number>; }
export interface Settings { schema_version: number; ruler_length_mm: number; display_unit: 'cm' | 'mm'; }

export const LOW_CONFIDENCE = 0.3;   // same as fishlen/geometry.py

export class ConflictError extends Error {}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (r.status === 409) throw new ConflictError((await r.json()).detail);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const api = {
  settings: () => req<Settings>('/api/settings'),
  photos: (p: { status?: string; tag?: string; q?: string; sort?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries(p).filter(([, v]) => v) as [string, string][]);
    return req<PhotoList>('/api/photos?' + qs);
  },
  next: (after?: string) => req<{ id: string | null }>('/api/photos/next' + (after ? '?after=' + after : '')),
  photo: (id: string) => req<{ photo: Photo; record: PhotoRecord }>(`/api/photos/${id}`),
  save: (rec: PhotoRecord) => req<PhotoRecord>(`/api/photos/${rec.photo_id}/record`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(rec),
  }),
  bulk: (ids: string[], action: 'mark_reviewed') => req<{ updated: string[] }>('/api/photos/bulk', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids, action }),
  }),
  upload: async (files: File[], predict: boolean) => {
    const fd = new FormData();
    files.forEach((f) => fd.append('files', f, f.name));
    fd.append('predict', predict ? 'true' : 'false');
    return req<{ photos: { id: string | null; filename: string; duplicate: boolean; error: string | null }[]; job: import('./jobs').Job | null }>(
      '/api/photos/upload', { method: 'POST', body: fd });
  },
  imageUrl: (id: string) => `/api/photos/${id}/image`,
  thumbUrl: (id: string) => `/api/photos/${id}/thumb`,
  exportUrl: '/api/export.csv',
};

// ---- measurement helpers (display only; nothing here is stored)
export function mmPerPx(r: Ruler | null): number | null {
  return r ? r.length_mm / dist(r.p1, r.p2) : null;
}
export function lengthCm(a: Animal, r: Ruler | null): number | null {
  const k = mmPerPx(r);
  return k ? (curveLength(a.midline) * k) / 10 : null;
}
export function minScore(a: Animal): number | null {
  return a.scores && a.scores.length ? Math.min(...a.scores) : null;
}
export function isLowConfidence(a: Animal): boolean {
  const s = minScore(a);
  return s !== null && s < LOW_CONFIDENCE;
}
export const fmtCm = (v: number | null) => (v === null ? '—' : `${v.toFixed(1)} cm`);
