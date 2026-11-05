"""Running the pipeline on stored photos: a generator for the CLI and a background queue for the server.

Models load once per process (first job) and stay in memory. Photos marked reviewed are skipped unless
forced; hand-made animals and hand-set rulers are always kept (Pipeline.to_record).
"""
import json, threading, time, traceback, uuid
from collections import OrderedDict
from typing import Optional

from .pipeline import Pipeline, load_config
from .pipeline.runner import load_image
from .store import Conflict

_pipelines: dict[str, Pipeline] = {}
_lock = threading.Lock()


def get_pipeline(project) -> Pipeline:
    cfg = load_config(project.root)
    key = json.dumps(cfg, sort_keys=True)
    with _lock:
        if key not in _pipelines:
            _pipelines.clear()                      # config changed: drop the old one
            _pipelines[key] = Pipeline(cfg)
        return _pipelines[key]


def predict_one(project, pid, force=False) -> str:
    rec = project.get_record(pid)
    photo = project.get_photo(pid)
    if rec is None:
        return f'{pid}: no such photo'
    if rec.status == 'reviewed' and not force:
        return f'{photo.filename}: reviewed, skipped'
    pipe = get_pipeline(project)
    res = pipe.run(load_image(project.images.original(pid)))
    try:
        project.save_record(pipe.to_record(res, rec), expected_revision=rec.revision)
    except Conflict:
        return f'{photo.filename}: edited by someone while predicting, not overwritten'
    ruler = res.ruler.method if res.ruler else 'no ruler'
    return f'{photo.filename}: {len(res.detections)} animals, ruler {ruler} ({res.seconds:.1f}s)'


def predict_photos(project, ids, force=False):
    for pid in ids:
        yield predict_one(project, pid, force)


class JobQueue:
    """One worker thread; jobs run in submission order."""

    def __init__(self, project, keep=50):
        self.project, self.keep = project, keep
        self.jobs: OrderedDict[str, dict] = OrderedDict()
        self.cv = threading.Condition()
        threading.Thread(target=self._work, daemon=True, name='fishlen-jobs').start()

    def submit(self, ids, force=False) -> dict:
        job = dict(id=uuid.uuid4().hex[:8], kind='predict', photo_ids=list(ids), force=force, status='queued',
                   done=0, total=len(ids), current=None, messages=[], error=None,
                   created=time.strftime('%Y-%m-%dT%H:%M:%S'), finished=None)
        with self.cv:
            self.jobs[job['id']] = job
            while len(self.jobs) > self.keep:
                oldest = next(iter(self.jobs))
                if self.jobs[oldest]['status'] in ('queued', 'running'):
                    break
                self.jobs.pop(oldest)
            self.cv.notify()
        return job

    def list(self):
        with self.cv:
            return [dict(j) for j in reversed(self.jobs.values())]

    def get(self, jid) -> Optional[dict]:
        with self.cv:
            j = self.jobs.get(jid)
            return dict(j) if j else None

    def _next(self):
        with self.cv:
            while True:
                for j in self.jobs.values():
                    if j['status'] == 'queued':
                        j['status'] = 'running'
                        return j
                self.cv.wait()

    def _work(self):
        while True:
            job = self._next()
            for pid in job['photo_ids']:
                job['current'] = pid
                try:
                    job['messages'].append(predict_one(self.project, pid, job['force']))
                except Exception as e:                                  # keep going with the next photo
                    job['messages'].append(f'{pid}: failed: {e}')
                    job['error'] = traceback.format_exc(limit=3)
                job['done'] += 1
            job.update(status='done' if not job['error'] else 'done_with_errors', current=None,
                       finished=time.strftime('%Y-%m-%dT%H:%M:%S'))
