"""Project storage: SQLite index of photos + one PhotoRecord JSON document per photo.

The `photos` table keeps a denormalized summary (status, tags, counts) so the photo list can be
filtered and sorted without parsing every record. It is rewritten on every save.
"""
import json, sqlite3, threading, time
from pathlib import Path
from typing import Optional

from .geometry import LOW_CONFIDENCE
from .images import ImageStore
from .schema import Photo, PhotoRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
  id TEXT PRIMARY KEY, filename TEXT NOT NULL, width INTEGER, height INTEGER, added_at TEXT,
  status TEXT NOT NULL DEFAULT 'new', tags TEXT NOT NULL DEFAULT '[]',
  n_animals INTEGER NOT NULL DEFAULT 0, n_pending INTEGER NOT NULL DEFAULT 0,
  n_low_confidence INTEGER NOT NULL DEFAULT 0, ruler_check INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS records (photo_id TEXT PRIMARY KEY REFERENCES photos(id), doc TEXT NOT NULL);
"""

SORTS = {
    'name': 'filename ASC',
    'updated': 'updated_at DESC, filename ASC',
    'priority': "status != 'predicted', n_low_confidence DESC, n_pending DESC, filename ASC",
}


class Conflict(Exception):
    """The record was saved by someone else since it was loaded."""


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def summary(rec: PhotoRecord) -> dict:
    live = [a for a in rec.animals if a.status != 'rejected']
    tags = set(rec.tags)
    for a in live:
        if a.species in ('trout', 'salamander'):
            tags.add(a.species)
        if a.flags.touching:
            tags.add('overlap')
    low = sum(1 for a in live if a.min_score is not None and a.min_score < LOW_CONFIDENCE)
    return dict(status=rec.status, tags=json.dumps(sorted(tags)), n_animals=len(live),
                n_pending=sum(a.status == 'pending' for a in rec.animals), n_low_confidence=low,
                ruler_check=int(rec.ruler is None or rec.ruler.needs_check) if rec.animals else 0)


class Project:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.images = ImageStore(self.root)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(self.root / 'fishlen.db', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---- photos
    def add_photo(self, data: bytes, filename: str) -> tuple[Photo, bool]:
        pid, w, h, _ = self.images.ingest(data, filename)
        with self._lock:
            row = self.db.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone()
            if row:
                return Photo(**{k: row[k] for k in Photo.model_fields}), False
            photo = Photo(id=pid, filename=filename, width=w, height=h, added_at=now())
            rec = PhotoRecord(photo_id=pid)
            self.db.execute('INSERT INTO photos (id, filename, width, height, added_at, updated_at) VALUES (?,?,?,?,?,?)',
                            (pid, filename, w, h, photo.added_at, photo.added_at))
            self.db.execute('INSERT INTO records VALUES (?,?)', (pid, rec.model_dump_json()))
            self.db.commit()
        return photo, True

    def get_photo(self, pid) -> Optional[Photo]:
        row = self.db.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone()
        return Photo(**{k: row[k] for k in Photo.model_fields}) if row else None

    def list_photos(self, status=None, tag=None, q=None, sort='name'):
        sql, args = 'SELECT * FROM photos WHERE 1=1', []
        if status:
            sql += ' AND status=?'; args.append(status)
        if q:
            sql += ' AND filename LIKE ?'; args.append(f'%{q}%')
        sql += ' ORDER BY ' + SORTS.get(sort, SORTS['name'])
        rows = [dict(r) | {'tags': json.loads(r['tags'])} for r in self.db.execute(sql, args)]
        if tag == 'low confidence':
            rows = [r for r in rows if r['n_low_confidence']]
        elif tag == 'ruler check':
            rows = [r for r in rows if r['ruler_check']]
        elif tag:
            rows = [r for r in rows if tag in r['tags']]
        return rows

    def counts(self):
        out = {'all': 0, 'new': 0, 'predicted': 0, 'reviewed': 0}
        for s, n in self.db.execute('SELECT status, COUNT(*) FROM photos GROUP BY status'):
            out[s] = n
            out['all'] += n
        return out

    def next_to_review(self, after=None):
        ids = [r['id'] for r in self.list_photos(status='predicted', sort='priority')]
        if not ids:
            return None
        if after in ids:
            rest = ids[ids.index(after) + 1:] + ids[:ids.index(after)]
            return rest[0] if rest else None
        return ids[0]

    # ---- records
    def get_record(self, pid) -> Optional[PhotoRecord]:
        row = self.db.execute('SELECT doc FROM records WHERE photo_id=?', (pid,)).fetchone()
        return PhotoRecord.model_validate_json(row['doc']) if row else None

    def save_record(self, rec: PhotoRecord, expected_revision: Optional[int] = None) -> PhotoRecord:
        """Save; if expected_revision is given and differs from the stored one, raise Conflict."""
        with self._lock:
            cur = self.get_record(rec.photo_id)
            if cur is None:
                raise KeyError(rec.photo_id)
            if expected_revision is not None and cur.revision != expected_revision:
                raise Conflict(f'stored revision {cur.revision}, yours {expected_revision}')
            rec = rec.model_copy(update={'revision': cur.revision + 1})
            s = summary(rec)
            self.db.execute('UPDATE records SET doc=? WHERE photo_id=?', (rec.model_dump_json(), rec.photo_id))
            self.db.execute('UPDATE photos SET status=?, tags=?, n_animals=?, n_pending=?, n_low_confidence=?, '
                            'ruler_check=?, updated_at=? WHERE id=?',
                            (s['status'], s['tags'], s['n_animals'], s['n_pending'], s['n_low_confidence'],
                             s['ruler_check'], now(), rec.photo_id))
            self.db.commit()
        return rec
