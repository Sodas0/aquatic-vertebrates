from conftest import jpeg_bytes


def add(project, **kw):
    photo, _ = project.add_photo(jpeg_bytes(**kw), 'tray.jpg')
    return photo


def test_duplicate_upload_is_detected(client):
    _, project = client
    a, new_a = project.add_photo(jpeg_bytes(), 'a.jpg')
    b, new_b = project.add_photo(jpeg_bytes(), 'copy-of-a.jpg')
    assert new_a and not new_b and a.id == b.id
    assert project.counts()['all'] == 1


def test_exif_rotation_sets_display_size(client):
    _, project = client
    p = add(project, w=400, h=300, orientation=6)       # rotated 90 degrees
    assert (p.width, p.height) == (300, 400)


def test_record_roundtrip_conflict_and_summary(client):
    c, project = client
    p = add(project)
    rec = c.get(f'/api/photos/{p.id}').json()['record']
    assert rec['revision'] == 0 and rec['status'] == 'new'
    rec.update(status='predicted', ruler=dict(p1=[0, 0], p2=[750, 0], length_mm=150, source='auto'),
               animals=[dict(id='x1', species='trout', midline=[[0, 0], [500, 0]], scores=[0.9, 0.1],
                             flags=dict(touching=True), source=dict(kind='model', name='m1'))])
    r = c.put(f'/api/photos/{p.id}/record', json=rec)
    assert r.status_code == 200 and r.json()['revision'] == 1
    assert c.put(f'/api/photos/{p.id}/record', json=rec).status_code == 409        # stale revision
    row = c.get('/api/photos').json()['items'][0]
    assert row['status'] == 'predicted' and row['n_pending'] == 1 and row['n_low_confidence'] == 1
    assert set(row['tags']) == {'trout', 'overlap'}
    assert c.get('/api/photos', params={'tag': 'low confidence'}).json()['items']
    assert c.get('/api/photos/next').json()['id'] == p.id
    csv = c.get('/api/export.csv').text.splitlines()
    assert len(csv) == 2 and ',10.0,' in csv[1]                                    # 500 px at 5 px/mm


def test_bulk_mark_reviewed(client):
    c, project = client
    p = add(project)
    rec = project.get_record(p.id)
    project.save_record(rec.model_copy(update={'status': 'predicted'}))
    assert c.post('/api/photos/bulk', json={'ids': [p.id], 'action': 'mark_reviewed'}).json()['updated'] == [p.id]
    assert project.get_record(p.id).status == 'reviewed'


def test_images_and_errors(client):
    c, project = client
    p = add(project)
    assert c.get(f'/api/photos/{p.id}/image').headers['content-type'] == 'image/jpeg'
    assert c.get(f'/api/photos/{p.id}/thumb').status_code == 200
    assert c.get('/api/photos/doesnotexist').status_code == 404
    bad = project.get_record(p.id).model_dump()
    bad['animals'] = [dict(id='y', midline=[[0, 0]], source=dict(kind='human', name='t'))]   # 1-point midline
    assert c.put(f'/api/photos/{p.id}/record', json=bad).status_code == 422


def test_upload_dedupes_and_rejects_non_images(client):
    c, project = client
    files = [('files', ('a.jpg', jpeg_bytes(color=(10, 20, 30)), 'image/jpeg')),
             ('files', ('a-copy.jpg', jpeg_bytes(color=(10, 20, 30)), 'image/jpeg')),
             ('files', ('notes.txt', b'hello', 'text/plain'))]
    r = c.post('/api/photos/upload', files=files).json()
    a, dup, bad = r['photos']
    assert a['id'] and not a['duplicate'] and dup['duplicate'] and dup['id'] == a['id']
    assert bad['id'] is None and 'not a readable image' in bad['error']
    assert r['job'] is None and project.counts()['all'] == 1


def test_predict_job_runs_in_background(client, monkeypatch):
    import time
    import fishlen.jobs
    c, project = client
    seen = []
    monkeypatch.setattr(fishlen.jobs, 'predict_one', lambda proj, pid, force=False: seen.append(pid) or f'{pid}: ok')
    r = c.post('/api/photos/upload', files=[('files', ('b.jpg', jpeg_bytes(color=(1, 2, 3)), 'image/jpeg'))],
               data={'predict': 'true'}).json()
    job = r['job']
    assert job and job['total'] == 1
    for _ in range(50):
        if c.get(f"/api/jobs/{job['id']}").json()['status'] == 'done':
            break
        time.sleep(0.05)
    j = c.get(f"/api/jobs/{job['id']}").json()
    assert j['status'] == 'done' and j['done'] == 1 and seen == [r['photos'][0]['id']]
    assert c.post('/api/predict', json={'ids': ['nope']}).status_code == 400
