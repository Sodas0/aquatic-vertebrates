"""Photo files: ingest (hash, dedupe, keep original bytes), display JPEG (EXIF-rotated) and thumbnail.

Layout under the data dir:
    photos/<id><ext>     original bytes, untouched
    display/<id>.jpg     EXIF-rotated full-resolution JPEG (what coordinates refer to)
    thumbs/<id>.jpg      <= 320 px thumbnail
"""
import hashlib, io
from pathlib import Path

from PIL import Image, ImageOps

THUMB_PX = 320


def photo_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


class ImageStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        for d in ('photos', 'display', 'thumbs'):
            (self.root / d).mkdir(parents=True, exist_ok=True)

    def original(self, pid):
        hits = sorted((self.root / 'photos').glob(pid + '.*'))
        return hits[0] if hits else None

    def ingest(self, data: bytes, filename: str):
        """Store a photo. Returns (id, width, height, is_new). Size is after EXIF rotation."""
        pid = photo_id(data)
        im = Image.open(io.BytesIO(data))
        im.verify()                                     # reject non-images early
        is_new = self.original(pid) is None
        if is_new:
            ext = Path(filename).suffix.lower() or '.jpg'
            (self.root / 'photos' / (pid + ext)).write_bytes(data)
        w, h = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).size
        return pid, w, h, is_new

    def display(self, pid) -> Path:
        p = self.root / 'display' / (pid + '.jpg')
        if not p.exists():
            im = ImageOps.exif_transpose(Image.open(self.original(pid))).convert('RGB')
            tmp = p.with_suffix('.tmp')
            im.save(tmp, 'JPEG', quality=92)
            tmp.replace(p)
        return p

    def thumb(self, pid) -> Path:
        p = self.root / 'thumbs' / (pid + '.jpg')
        if not p.exists():
            im = Image.open(self.original(pid))
            im.draft('RGB', (THUMB_PX * 2, THUMB_PX * 2))   # fast reduced-size JPEG decode
            im = ImageOps.exif_transpose(im).convert('RGB')
            im.thumbnail((THUMB_PX, THUMB_PX))
            tmp = p.with_suffix('.tmp')
            im.save(tmp, 'JPEG', quality=80)
            tmp.replace(p)
        return p
