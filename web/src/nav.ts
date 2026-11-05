import { api } from './api';

// Routes are hash-based so any static host works:  #/   and   #/review/<photo id>
export const go = {
  photos: () => { location.hash = '#/'; },
  review: (id: string) => { location.hash = '#/review/' + id; },
  async nextReview(after?: string) {
    const { id } = await api.next(after);
    if (id) go.review(id);
    else go.photos();                    // nothing left to review: back to the list
  },
};

// Who is labeling: stored in this browser, recorded as the source of hand labels.
export function currentUser(): string {
  try { return localStorage.getItem('fishlen.user')?.trim() || 'unknown'; } catch { return 'unknown'; }
}
export function setCurrentUser(name: string) {
  try { localStorage.setItem('fishlen.user', name.trim()); } catch { /* storage off */ }
}
