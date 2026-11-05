"""Name -> implementation registry for pipeline stages.

    @register('ruler', 'my_ruler_v2')
    class MyRuler:
        version = '2'
        def __init__(self, some_param=1): ...
        def find(self, image): ...

Then select it in a pipeline config: {"ruler": {"impl": "my_ruler_v2", "some_param": 3}}.
Modules under fishlen/pipeline/stages/ are imported automatically, so a new file there is enough.
"""
import importlib, pkgutil

from .base import STAGES

_REGISTRY: dict[str, dict[str, type]] = {s: {} for s in STAGES}
_loaded = False


def register(stage: str, name: str):
    if stage not in _REGISTRY:
        raise ValueError(f'unknown stage {stage!r}; stages are {STAGES}')

    def deco(cls):
        cls.name = name
        cls.version = getattr(cls, 'version', '0')
        _REGISTRY[stage][name] = cls
        return cls
    return deco


def _load_all():
    global _loaded
    if not _loaded:
        from . import stages
        for m in pkgutil.iter_modules(stages.__path__):
            importlib.import_module(f'{stages.__name__}.{m.name}')
        _loaded = True


def available() -> dict[str, list[str]]:
    _load_all()
    return {s: sorted(v) for s, v in _REGISTRY.items()}


def build(stage: str, spec: dict):
    """spec = {"impl": name, **params}"""
    _load_all()
    spec = dict(spec)
    name = spec.pop('impl')
    try:
        cls = _REGISTRY[stage][name]
    except KeyError:
        raise ValueError(f'no {stage} implementation {name!r}; available: {sorted(_REGISTRY[stage])}') from None
    return cls(**spec)
