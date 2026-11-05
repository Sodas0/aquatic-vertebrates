"""Export a trained MMPose top-down heatmap model to ONNX for fishlen (run in the `mmpose` env).

    python scripts/export_keypoints_onnx.py \
        --config ../playground/keypoints/configs/hrnet_w32_dark_midline8.py \
        --checkpoint ../playground/outputs/03_train/hrnet_w32_dark_midline8_run2/epoch_210.pth \
        --name hrnet_w32_dark_midline8_run2 \
        --reference-photos IMG_8585.jpg 20250820_144303.jpg --labels ../playground/labels \
        --img-dir "../playground/data/2025 Synoptic pictures"

Writes models/keypoints/<name>/{model.onnx, meta.json}. The ONNX graph is backbone + head only
(normalized 256x256 RGB crops -> heatmaps); cropping, flip test and DARK decoding live in
fishlen/pipeline/keypoints_onnx.py. With --reference-photos it also saves MMPose's own predictions
for those photos (boxes from hand labels) to tests/fixtures/keypoints_reference.json, which the
parity test compares against.
"""
import argparse, json, os, re
from pathlib import Path

import numpy as np
import torch
from mmengine.config import Config
from mmpose.apis import inference_topdown, init_model

APP = Path(__file__).resolve().parent.parent


class Net(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, x):
        return self.model.head.forward(self.model.extract_feat(x))


def label_boxes(labels_dir, image, pad=0.1):
    """Same boxes as the playground's infer.py: midline extent padded by 10% of body length."""
    for f in sorted(Path(labels_dir).glob(f'*/{Path(image).stem}.json')):
        out = []
        for an in json.loads(f.read_text())['animals']:
            P = np.array(an['midline'], float)
            tl = np.linalg.norm(np.diff(P, axis=0), axis=1).sum()
            out.append(np.r_[P.min(0) - pad * tl, P.max(0) + pad * tl].tolist())
        return out
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--checkpoint', required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--reference-photos', nargs='*', default=[])
    ap.add_argument('--labels', type=Path)
    ap.add_argument('--img-dir', type=Path)
    ap.add_argument('--dataset-dir', type=Path, help='folder with the COCO train.json/val.json the model was trained on; '
                    'recorded in meta.json so evaluations can leave those photos out')
    a = ap.parse_args()

    config, ckpt = str(Path(a.config).resolve()), str(Path(a.checkpoint).resolve())
    cfg = Config.fromfile(config)
    cwd = os.getcwd()
    os.chdir(Path(config).parent.parent.parent)          # playground/: configs use paths relative to it
    model = init_model(config, ckpt, device='cpu').eval()
    os.chdir(cwd)

    codec = cfg.codec
    out = APP / 'models' / 'keypoints' / a.name
    out.mkdir(parents=True, exist_ok=True)
    W, H = codec['input_size']
    meta = dict(
        name=a.name, kind='topdown_heatmap', num_keypoints=cfg.model['head']['out_channels'],
        input_size=[W, H], heatmap_size=list(codec['heatmap_size']), sigma=codec['sigma'],
        decode='dark' if codec.get('unbiased') else 'argmax', blur_kernel_size=11, bbox_padding=1.25,
        mean=cfg.model['data_preprocessor']['mean'], std=cfg.model['data_preprocessor']['std'], color='rgb',
        flip_test=cfg.model['test_cfg'].get('flip_test', False), shift_heatmap=cfg.model['test_cfg'].get('shift_heatmap', False),
        flip_indices=list(range(cfg.model['head']['out_channels'])),
        keypoints='midline, snout -> tail, equal arc-length spacing',
        trained_from=Path(ckpt).name, config=Path(config).name)
    if a.dataset_dir:
        names = lambda f: sorted({re.sub(r'_[a-z0-9-]+_\d{3}\.jpg$', '.jpg', i['file_name'])
                                  for i in json.loads((a.dataset_dir / f).read_text())['images']})
        meta.update(trained_on=names('train.json'), validated_on=names('val.json'))

    # reference predictions FIRST: torch.onnx.export restores the wrapper's train/eval mode afterwards,
    # and a wrapper left in train mode would silently switch BatchNorm to batch statistics

    if a.reference_photos:
        ref = {}
        for name in a.reference_photos:
            boxes = label_boxes(a.labels, name)
            res = inference_topdown(model, str(a.img_dir / name), np.array(boxes), bbox_format='xyxy')
            ref[name] = [dict(box=b, keypoints=r.pred_instances.keypoints[0].tolist(),
                              scores=r.pred_instances.keypoint_scores[0].tolist()) for b, r in zip(boxes, res)]
        f = APP / 'tests' / 'fixtures' / 'keypoints_reference.json'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(dict(model=a.name, photos=ref)))
        print('reference predictions ->', f, {k: len(v) for k, v in ref.items()})

    torch.onnx.export(Net(model).eval(), torch.zeros(1, 3, H, W), str(out / 'model.onnx'), opset_version=17,
                      input_names=['input'], output_names=['heatmaps'],
                      dynamic_axes={'input': {0: 'batch'}, 'heatmaps': {0: 'batch'}})
    (out / 'meta.json').write_text(json.dumps(meta, indent=1))
    print('wrote', out)


if __name__ == '__main__':
    main()
