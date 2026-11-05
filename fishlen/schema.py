"""Data format, version 1. Documented in docs/schema.md; change both together.

One PhotoRecord per photo holds everything a person or model says about it: the ruler and the
animals. Hand labels and model predictions use the same Animal shape; `source` says which.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = 1

Point = tuple[float, float]
Species = Literal['trout', 'salamander', 'other', 'unknown']
AnimalStatus = Literal['pending', 'accepted', 'rejected']
RejectReason = Literal['junk', 'overlap', 'other']
PhotoStatus = Literal['new', 'predicted', 'reviewed']


class Source(BaseModel):
    kind: Literal['model', 'human', 'import']
    name: str                                   # model version id, or the person's name


class Ruler(BaseModel):
    """Two points on the ruler and the real distance between them.

    Convention for new rulers: p1/p2 sit on the 0 and 15 cm marks, so length_mm = 150.
    Imported hand labels may use other spans; length_mm always says what the span is.
    """
    p1: Point
    p2: Point
    length_mm: float = Field(gt=0)
    source: Literal['auto', 'manual']
    method: Optional[str] = None                # 'ticks', 'ends', 'hand', ...
    confidence: Optional[float] = None
    needs_check: bool = False


class Flags(BaseModel):
    touching: bool = False                      # mask touches another animal's mask
    edited: bool = False                        # a person moved the model's points
    observations: list[str] = []                # e.g. 'occluded', 'truncated', 'head_uncertain'


class Animal(BaseModel):
    id: str
    species: Species = 'unknown'
    midline: list[Point]                        # snout -> tail, any number of points >= 2
    model_midline: Optional[list[Point]] = None  # untouched model output, kept once edited
    scores: Optional[list[float]] = None        # per-point model confidence
    vent: Optional[Point] = None
    box: Optional[tuple[float, float, float, float]] = None   # detector/segmenter box (x0, y0, x1, y1)
    status: AnimalStatus = 'pending'
    reject_reason: Optional[RejectReason] = None
    flags: Flags = Flags()
    source: Source
    note: str = ''

    @field_validator('midline')
    @classmethod
    def _two_points(cls, v):
        if len(v) < 2:
            raise ValueError('midline needs at least 2 points')
        return v

    @property
    def min_score(self) -> Optional[float]:
        return min(self.scores) if self.scores else None


class PhotoRecord(BaseModel):
    schema_version: int = SCHEMA_VERSION
    photo_id: str
    revision: int = 0                           # bumped on every save; stale saves are refused
    status: PhotoStatus = 'new'
    tags: list[str] = []
    ruler: Optional[Ruler] = None
    auto_ruler: Optional[Ruler] = None          # untouched detector output, for "reset to auto"
    animals: list[Animal] = []
    pipeline: dict[str, str] = {}               # stage -> "impl@version" that produced the predictions
    notes: str = ''


class Photo(BaseModel):
    """A stored photo (the index row). `id` is the first 16 hex chars of the file's SHA-256."""
    id: str
    filename: str
    width: int                                  # after EXIF rotation
    height: int
    added_at: str
