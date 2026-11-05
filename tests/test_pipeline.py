"""Stage plumbing: implementations plug in by name, the runner chains them, and re-predicting keeps
hand-made work."""
import numpy as np
import pytest

from fishlen.pipeline import Detection, KeypointResult, Pipeline, available, register
from fishlen.schema import Animal, PhotoRecord, Ruler, Source


@register('detector', 'test_two_boxes')
class TwoBoxes:
    def detect(self, image):
        return [Detection(box=(10, 10, 60, 20), score=0.9, label='fish'), Detection(box=(10, 40, 90, 50), score=0.8, label='salamander')]


@register('segmenter', 'test_masks')
class Masks:
    def segment(self, image, dets):
        for d in dets:
            m = np.zeros(image.shape[:2], bool)
            x0, y0, x1, y1 = map(int, d.box)
            m[y0:y1, x0:x1] = True
            d.mask = m
        return dets


@register('classifier', 'test_label')
class Label:
    def classify(self, image, dets):
        for d in dets:
            d.species = 'trout' if d.label == 'fish' else 'salamander'
        return dets


@register('ruler', 'test_ruler')
class FixedRuler:
    version = '7'

    def find(self, image):
        return Ruler(p1=(0, 0), p2=(150, 0), length_mm=150, source='auto', method='test')


@register('keypoints', 'test_line')
class Line:
    def predict(self, image, dets):
        return [KeypointResult(points=np.array([[d.box[0], d.box[1]], [d.box[2], d.box[3]]], float),
                               scores=np.array([0.9, 0.2]), crop_box=d.box) for d in dets]


CFG = {'detector': {'impl': 'test_two_boxes'}, 'segmenter': {'impl': 'test_masks'}, 'classifier': {'impl': 'test_label'},
       'ruler': {'impl': 'test_ruler'}, 'keypoints': {'impl': 'test_line'}}


def test_registry_lists_test_and_baseline_stages():
    a = available()
    assert 'test_ruler' in a['ruler'] and 'ticks_v1' in a['ruler'] and 'onnx_topdown' in a['keypoints']


def test_unknown_implementation_is_a_clear_error():
    with pytest.raises(ValueError, match='available'):
        Pipeline({**CFG, 'ruler': {'impl': 'nope'}})


def test_runner_chains_stages_and_keeps_hand_work():
    pipe = Pipeline(CFG)
    res = pipe.run(np.zeros((100, 100, 3), np.uint8))
    assert [d.species for d in res.detections] == ['trout', 'salamander']
    assert res.provenance['ruler'] == 'test_ruler@7'
    hand = Animal(id='h1', midline=[(1, 1), (5, 5)], source=Source(kind='human', name='me'), status='accepted')
    old_model = Animal(id='m1', midline=[(1, 1), (5, 5)], source=Source(kind='model', name='old'))
    manual = Ruler(p1=(0, 0), p2=(300, 0), length_mm=150, source='manual')
    rec = pipe.to_record(res, PhotoRecord(photo_id='x', animals=[hand, old_model], ruler=manual))
    assert rec.status == 'predicted' and rec.pipeline == res.provenance
    assert [a.id for a in rec.animals][:1] == ['h1'] and 'm1' not in [a.id for a in rec.animals]   # model output replaced
    assert len(rec.animals) == 3 and rec.animals[1].species == 'trout' and rec.animals[1].box == (10, 10, 60, 20)
    assert rec.ruler == manual and rec.auto_ruler.method == 'test'                                  # hand ruler kept
    assert rec.animals[1].flags.touching is False


def test_missing_model_files_fall_back_to_no_model_stages(monkeypatch):
    from fishlen.pipeline.runner import DEFAULT_CONFIG, with_fallbacks
    monkeypatch.setenv('FISHLEN_SAM2_CHECKPOINT', '/nonexistent/sam2.pt')
    cfg = {k: dict(v) for k, v in DEFAULT_CONFIG.items()}
    cfg['keypoints'] = {'impl': 'onnx_topdown', 'model': 'models/keypoints/does-not-exist'}
    with pytest.warns(UserWarning):
        cfg = with_fallbacks(cfg)
    assert (cfg['keypoints']['impl'], cfg['segmenter']['impl'], cfg['ruler']['impl']) == ('mask_axis', 'none', 'none')


def test_mask_axis_draws_a_flagged_line_along_the_mask():
    from fishlen.pipeline import build
    m = np.zeros((100, 200), bool)
    m[40:60, 20:180] = True
    r = build('keypoints', {'impl': 'mask_axis'}).predict(None, [Detection(box=(20, 40, 179, 59), score=1, mask=m)])[0]
    assert len(r.points) == 8 and r.scores.max() == 0
    assert abs(r.points[0][1] - 49.5) < 1 and r.points[-1][0] - r.points[0][0] > 150
