import json, math, shutil, subprocess
from pathlib import Path

import numpy as np
import pytest

from fishlen.geometry import catmull_rom, curve_length, length_cm, project_arclen, svl_cm
from fishlen.schema import Animal, Ruler, Source

WEB = Path(__file__).resolve().parent.parent / 'web'


def test_straight_line_length_is_exact():
    P = [(0, 0), (30, 40), (60, 80), (90, 120)]
    assert curve_length(P) == pytest.approx(150, rel=1e-9)


def test_curve_passes_through_points_and_beats_chords_on_an_arc():
    th = np.linspace(0, np.pi, 8)
    P = np.c_[np.cos(th), np.sin(th)] * 100
    C = catmull_rom(P)
    for p in P:
        assert np.min(np.linalg.norm(C - p, axis=1)) < 1e-9
    chord = np.linalg.norm(np.diff(P, axis=0), axis=1).sum()
    assert chord < curve_length(P) <= math.pi * 100 * 1.001


def test_length_cm_uses_ruler_scale():
    a = Animal(id='a', midline=[(0, 0), (500, 0)], source=Source(kind='human', name='t'))
    r = Ruler(p1=(0, 0), p2=(750, 0), length_mm=150, source='manual')     # 5 px per mm
    assert length_cm(a, r) == pytest.approx(10.0)
    assert length_cm(a, None) is None


def test_svl_projects_vent_onto_midline():
    a = Animal(id='a', midline=[(0, 0), (500, 0)], vent=(200, 37), source=Source(kind='human', name='t'))
    r = Ruler(p1=(0, 0), p2=(750, 0), length_mm=150, source='manual')
    assert svl_cm(a, r) == pytest.approx(4.0)                       # 200 px at 5 px/mm
    assert svl_cm(a.model_copy(update={'vent': None}), r) is None


@pytest.mark.skipif(not (WEB / 'src' / 'geometry.ts').exists() or shutil.which('node') is None,
                    reason='web UI geometry or node not available')
def test_web_geometry_matches_python(tmp_path):
    """The UI computes lengths live; it must agree with the exported numbers."""
    rng = np.random.default_rng(0)
    cases = [np.cumsum(rng.normal(0, 30, (k, 2)), axis=0).tolist() for k in (2, 3, 5, 8, 12)]
    js = (WEB / 'src' / 'geometry.ts').read_text()
    js = js.replace('export ', '')
    js = js.replace(': Pt[]', '').replace(': Pt', '').replace(': number', '').replace('type Pt = [number, number];', '')
    script = tmp_path / 'g.mjs'
    vents = [rng.normal(0, 40, 2).tolist() for _ in cases]
    script.write_text(js + f'\nconst C = {json.dumps(cases)}, V = {json.dumps(vents)};'
                      '\nconsole.log(JSON.stringify([C.map(p => curveLength(p)), C.map((p, i) => svlPx(p, V[i]))]));')
    lens, svls = json.loads(subprocess.run(['node', str(script)], capture_output=True, text=True, check=True).stdout)
    for P, v, L, S in zip(cases, vents, lens, svls):
        assert L == pytest.approx(curve_length(P), rel=1e-9)
        assert S == pytest.approx(project_arclen(catmull_rom(P), v), rel=1e-9, abs=1e-9)
