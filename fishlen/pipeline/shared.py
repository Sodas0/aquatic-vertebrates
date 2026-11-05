"""Heavy models loaded once per process and shared between stages (the ruler finder reuses the
animal detector's Grounding DINO and SAM2). Paths come from environment variables so a deployment can
move them:  FISHLEN_SAM2_CHECKPOINT, FISHLEN_DEVICE.
"""
import functools, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GD_ID = 'IDEA-Research/grounding-dino-base'


def device():
    import torch
    return os.environ.get('FISHLEN_DEVICE') or ('cuda' if torch.cuda.is_available() else 'cpu')


@functools.lru_cache(maxsize=None)
def grounding_dino(model_id: str = GD_ID):
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    return AutoProcessor.from_pretrained(model_id), AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device()).eval()


@functools.lru_cache(maxsize=None)
def sam2(config: str = 'configs/sam2.1/sam2.1_hiera_l.yaml', checkpoint: str = ''):
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    return SAM2ImagePredictor(build_sam2(config, checkpoint or sam2_checkpoint(), device=device()))


SAM2_URL = 'https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt'


def sam2_checkpoint() -> str:
    return os.environ.get('FISHLEN_SAM2_CHECKPOINT') or str(ROOT / 'models' / 'sam2' / 'sam2.1_hiera_large.pt')


def gd_detect(image, prompt, box_thresh, text_thresh, nms_iou, model_id=GD_ID):
    """Grounding DINO boxes for a text prompt (xyxy, scores, labels), highest score first after NMS."""
    import torch, torchvision
    from PIL import Image
    proc, model = grounding_dino(model_id)
    inputs = proc(images=Image.fromarray(image), text=prompt, return_tensors='pt').to(device())
    with torch.no_grad():
        r = proc.post_process_grounded_object_detection(model(**inputs), inputs.input_ids, threshold=box_thresh,
                                                        text_threshold=text_thresh, target_sizes=[image.shape[:2]])[0]
    keep = torchvision.ops.nms(r['boxes'], r['scores'], nms_iou).cpu()
    return r['boxes'].cpu()[keep].numpy(), r['scores'].cpu()[keep].numpy(), [r['text_labels'][i] for i in keep]


def sam_masks(image, boxes):
    """One boolean mask per xyxy box."""
    import numpy as np, torch
    if len(boxes) == 0:
        return np.zeros((0, *image.shape[:2]), bool)
    pred = sam2()
    pred.set_image(image)
    ctx = torch.autocast('cuda', dtype=torch.bfloat16) if device() == 'cuda' else torch.autocast('cpu', enabled=False)
    with torch.inference_mode(), ctx:
        masks, _, _ = pred.predict(box=np.asarray(boxes), multimask_output=False)
    return masks.reshape(-1, *image.shape[:2]).astype(bool)
