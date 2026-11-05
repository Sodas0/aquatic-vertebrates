# Data format — schema_version 1

Source of truth: `fishlen/schema.py`. UI mirror: `web/src/api.ts`. Change all three together and bump
`SCHEMA_VERSION` when a change is not backward compatible.

## Conventions
- **Coordinates** are pixels of the EXIF-rotated, full-resolution photo (`/api/photos/{id}/image`).
- **Lengths are never stored.** Length = smooth curve (centripetal Catmull-Rom) through the midline,
  times the ruler scale `ruler.length_mm / |p2 - p1|`. Displayed in cm.
- **Photo id** = first 16 hex characters of the SHA-256 of the original file, so re-uploading the same
  file is detected as a duplicate.

## PhotoRecord (one per photo)
| field | meaning |
|---|---|
| `schema_version` | 1 |
| `photo_id` | photo id |
| `revision` | incremented on every save; a save with an old revision is refused (409) |
| `status` | `new` (no predictions) · `predicted` (needs review) · `reviewed` |
| `tags` | photo-level tags set by people: `junk`, `overlap`, `needs expert` |
| `ruler` | current ruler (may be edited) or null |
| `auto_ruler` | the detector's ruler, untouched, for "reset to auto" |
| `animals` | list of Animal |
| `notes` | free text |

## Ruler
`p1`, `p2` (points), `length_mm` (real distance between them), `source` (`auto` | `manual`),
`method` (`ticks`, `ends`, `hand`), `confidence`, `needs_check`.
Convention: the endpoints sit on the 0 and 15 cm marks, so `length_mm = 150`. Imported hand labels
may use other spans; `length_mm` always states the span.

## Animal
| field | meaning |
|---|---|
| `id` | short random id, stable across edits |
| `species` | `trout` · `salamander` · `other` · `unknown` |
| `midline` | snout → tail, ≥ 2 points (model: 8 evenly spaced; hand labels: any number) |
| `model_midline` | the model's original points, kept once a person edits them |
| `scores` | per-point model confidence (the weakest < 0.3 = "low confidence") |
| `vent` | optional point, for snout–vent length |
| `status` | `pending` · `accepted` · `rejected` (+ `reject_reason`: `junk` · `overlap` · `other`) |
| `flags` | `touching` (mask touches another animal), `edited`, `observations` (`occluded`, `truncated`, …) |
| `source` | `{kind: model|human|import, name}` — model version or person |

A reviewed photo's accepted animals are training labels: hand labels and corrected predictions share
this shape.
