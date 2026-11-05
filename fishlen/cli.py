"""Command line: list stage implementations, run predictions, evaluate one stage.

    python -m fishlen.cli stages
    python -m fishlen.cli predict --ids 1a2b3c... | --status new --limit 20 [--force]
    python -m fishlen.cli eval ruler      [--impl ticks_v1] [--param span_mm=150] [--gt manual|all]
    python -m fishlen.cli eval detection  [--impl grounding_dino] [--segmenter sam2_box]
    python -m fishlen.cli eval classifier [--impl detector_label]
    python -m fishlen.cli eval keypoints  [--impl onnx_topdown] [--param model=models/keypoints/<name>] [--include-trained]

--data picks the project folder (default: $FISHLEN_DATA or ./data). Without --impl, a stage uses what
the project's pipeline config selects (runner.DEFAULT_CONFIG overridden by <data>/pipeline.json).
"""
import argparse, json, os, sys, time
from pathlib import Path

from .store import Project


def parse_params(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition('=')
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def stage_spec(cfg, stage, impl, params):
    spec = dict(cfg[stage]) if not impl or impl == cfg[stage]['impl'] else {'impl': impl}
    spec.update(params)
    return spec


def main(argv=None):
    ap = argparse.ArgumentParser(prog='fishlen')
    ap.add_argument('--data', type=Path, default=Path(os.environ.get('FISHLEN_DATA', 'data')))
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('stages', help='list available implementations per stage')
    p = sub.add_parser('predict', help='run the pipeline on photos and save the predictions')
    p.add_argument('--ids', nargs='*')
    p.add_argument('--status', choices=['new', 'predicted', 'reviewed'])
    p.add_argument('--limit', type=int)
    p.add_argument('--force', action='store_true', help='also re-predict reviewed photos (hand labels are kept)')
    e = sub.add_parser('eval', help='evaluate one stage against reviewed photos')
    e.add_argument('stage', choices=['ruler', 'detection', 'classifier', 'keypoints'])
    e.add_argument('--impl')
    e.add_argument('--param', nargs='*', help='implementation parameters, key=value (values parsed as JSON when possible)')
    e.add_argument('--segmenter', help='segmenter for the detection eval')
    e.add_argument('--gt', choices=['manual', 'all'], default='manual', help='ruler eval: which reviewed rulers count as truth')
    e.add_argument('--include-trained', action='store_true', help='keypoints eval: include photos the model trained on')
    a = ap.parse_args(argv)

    from .pipeline import available, load_config
    if a.cmd == 'stages':
        cfg = load_config(a.data)
        for stage, impls in available().items():
            print(f"{stage:11s} {', '.join(impls):40s} (selected: {cfg[stage]['impl']})")
        return

    project = Project(a.data)
    cfg = load_config(a.data)

    if a.cmd == 'predict':
        from .jobs import predict_photos
        ids = a.ids or [r['id'] for r in project.list_photos(status=a.status)][:a.limit]
        for msg in predict_photos(project, ids, force=a.force):
            print(msg)
        return

    from . import evaluate as ev
    params = parse_params(a.param)
    t = time.time()
    if a.stage == 'ruler':
        summary, f = ev.eval_ruler(project, stage_spec(cfg, 'ruler', a.impl, params), gt=a.gt)
    elif a.stage == 'detection':
        summary, f = ev.eval_detection(project, stage_spec(cfg, 'detector', a.impl, params),
                                       stage_spec(cfg, 'segmenter', a.segmenter, {}))
    elif a.stage == 'classifier':
        summary, f = ev.eval_classifier(project, stage_spec(cfg, 'classifier', a.impl, params))
    else:
        summary, f = ev.eval_keypoints(project, stage_spec(cfg, 'keypoints', a.impl, params), include_trained=a.include_trained)
    print(json.dumps(summary, indent=1))
    print(f'details -> {f}  ({time.time() - t:.0f}s)')


if __name__ == '__main__':
    sys.exit(main())
