"""HTTP API for the review tool. The full contract is generated at /docs (OpenAPI).

    FISHLEN_DATA=data uvicorn server.main:app --port 8000

Serves the built web UI (web/dist) at / when it exists.
"""
import csv, io, os
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fishlen import __version__
from fishlen.geometry import length_cm, svl_cm
from fishlen.schema import SCHEMA_VERSION, Photo, PhotoRecord
from fishlen.store import Conflict, Project
from fishlen.jobs import JobQueue

ROOT = Path(__file__).resolve().parent.parent
project = Project(Path(os.environ.get('FISHLEN_DATA', ROOT / 'data')))
jobs = JobQueue(project)          # one background worker; models load on the first prediction
app = FastAPI(title='fishlen', version=__version__,
              description='Fish and salamander length measurement: photos, rulers, midlines, review.')


# ---------- models for responses / requests
class PhotoSummary(BaseModel):
    id: str
    filename: str
    status: str
    tags: list[str]
    n_animals: int
    n_pending: int
    n_low_confidence: int
    ruler_check: bool
    updated_at: Optional[str]


class PhotoList(BaseModel):
    items: list[PhotoSummary]
    counts: dict[str, int]


class PhotoDetail(BaseModel):
    photo: Photo
    record: PhotoRecord


class BulkAction(BaseModel):
    ids: list[str]
    action: Literal['mark_reviewed']


class Uploaded(BaseModel):
    id: Optional[str]
    filename: str
    duplicate: bool = False
    error: Optional[str] = None


class UploadResult(BaseModel):
    photos: list[Uploaded]
    job: Optional[dict] = None


class PredictRequest(BaseModel):
    ids: list[str]
    force: bool = False


class Settings(BaseModel):
    schema_version: int
    ruler_length_mm: float
    display_unit: Literal['cm', 'mm']


SETTINGS = Settings(schema_version=SCHEMA_VERSION, ruler_length_mm=150.0, display_unit='cm')


def _photo_or_404(pid) -> Photo:
    p = project.get_photo(pid)
    if p is None:
        raise HTTPException(404, 'no such photo')
    return p


# ---------- routes
@app.get('/api/settings', response_model=Settings)
def settings():
    return SETTINGS


@app.get('/api/photos', response_model=PhotoList)
def list_photos(status: Optional[str] = None, tag: Optional[str] = None, q: Optional[str] = None,
                sort: Literal['name', 'updated', 'priority'] = 'name'):
    return PhotoList(items=project.list_photos(status, tag, q, sort), counts=project.counts())


@app.get('/api/photos/next')
def next_to_review(after: Optional[str] = None):
    """The next photo waiting for review (low-confidence animals first)."""
    return {'id': project.next_to_review(after)}


@app.get('/api/photos/{pid}', response_model=PhotoDetail)
def get_photo(pid: str):
    return PhotoDetail(photo=_photo_or_404(pid), record=project.get_record(pid))


@app.put('/api/photos/{pid}/record', response_model=PhotoRecord)
def save_record(pid: str, record: PhotoRecord):
    """Save a record. `record.revision` must equal the stored revision (else 409); it is incremented."""
    _photo_or_404(pid)
    if record.photo_id != pid:
        raise HTTPException(400, 'photo_id does not match the URL')
    try:
        return project.save_record(record, expected_revision=record.revision)
    except Conflict as e:
        raise HTTPException(409, f'Someone else saved this photo meanwhile ({e}). Reload to see their changes.')


@app.post('/api/photos/bulk')
def bulk(body: BulkAction):
    done = []
    for pid in body.ids:
        rec = project.get_record(pid)
        if rec is None:
            continue
        if body.action == 'mark_reviewed' and rec.status == 'predicted':
            project.save_record(rec.model_copy(update={'status': 'reviewed'}))
            done.append(pid)
    return {'updated': done}


@app.post('/api/photos/upload', response_model=UploadResult)
async def upload(files: list[UploadFile] = File(...), predict: bool = Form(False)):
    """Add photos. The same file uploaded twice is recognised (by content) and not stored again.
    With predict=true, new photos are queued for prediction."""
    out = []
    for f in files:
        data = await f.read()
        try:
            photo, is_new = project.add_photo(data, Path(f.filename or 'photo.jpg').name)
            out.append(Uploaded(id=photo.id, filename=photo.filename, duplicate=not is_new))
        except Exception as e:                      # not an image, corrupt file, ...
            out.append(Uploaded(id=None, filename=f.filename or '?', error=f'not a readable image ({type(e).__name__})'))
    new_ids = [u.id for u in out if u.id and not u.duplicate]
    job = jobs.submit(new_ids) if predict and new_ids else None
    return UploadResult(photos=out, job=job)


@app.post('/api/predict')
def predict(body: PredictRequest):
    """Queue photos for prediction. Reviewed photos are skipped unless force=true; hand labels are always kept."""
    ids = [i for i in body.ids if project.get_photo(i)]
    if not ids:
        raise HTTPException(400, 'no known photo ids')
    return jobs.submit(ids, force=body.force)


@app.get('/api/jobs')
def list_jobs():
    return jobs.list()


@app.get('/api/jobs/{jid}')
def get_job(jid: str):
    j = jobs.get(jid)
    if j is None:
        raise HTTPException(404, 'no such job')
    return j


@app.get('/api/photos/{pid}/image')
def image(pid: str):
    _photo_or_404(pid)
    return FileResponse(project.images.display(pid), media_type='image/jpeg',
                        headers={'Cache-Control': 'private, max-age=86400'})


@app.get('/api/photos/{pid}/thumb')
def thumb(pid: str):
    _photo_or_404(pid)
    return FileResponse(project.images.thumb(pid), media_type='image/jpeg',
                        headers={'Cache-Control': 'private, max-age=86400'})


@app.get('/api/export.csv')
def export_csv(include_pending: bool = Query(True, description='also export animals not yet accepted')):
    """One row per non-rejected animal, length in cm."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['photo', 'photo_id', 'animal_id', 'species', 'status', 'length_cm', 'svl_cm', 'edited', 'touching',
                'min_score', 'ruler_source', 'ruler_needs_check', 'photo_status', 'source'])
    for row in project.list_photos():
        rec = project.get_record(row['id'])
        for a in rec.animals:
            if a.status == 'rejected' or (a.status == 'pending' and not include_pending):
                continue
            L, S = length_cm(a, rec.ruler), svl_cm(a, rec.ruler)
            w.writerow([row['filename'], rec.photo_id, a.id, a.species, a.status,
                        '' if L is None else round(L, 1), '' if S is None else round(S, 1), a.flags.edited, a.flags.touching,
                        '' if a.min_score is None else round(a.min_score, 3),
                        rec.ruler.source if rec.ruler else 'none', rec.ruler.needs_check if rec.ruler else '',
                        rec.status, f'{a.source.kind}:{a.source.name}'])
    return Response(buf.getvalue(), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="fish_lengths.csv"'})


# ---------- web UI (built by `npm run build` in web/)
DIST = ROOT / 'web' / 'dist'
if DIST.exists():
    app.mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets')

    @app.get('/{path:path}', include_in_schema=False)
    def spa(path: str):
        if path.startswith('api/'):
            raise HTTPException(404, 'no such API route')
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / 'index.html')
