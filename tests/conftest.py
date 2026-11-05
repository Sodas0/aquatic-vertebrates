import importlib, io

import pytest
from PIL import Image


def jpeg_bytes(w=400, h=300, color=(200, 200, 200), orientation=None):
    im = Image.new('RGB', (w, h), color)
    buf = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        im.save(buf, 'JPEG', exif=exif)
    else:
        im.save(buf, 'JPEG')
    return buf.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """API client on an empty project in a temp dir."""
    monkeypatch.setenv('FISHLEN_DATA', str(tmp_path / 'data'))
    import server.main
    importlib.reload(server.main)
    from fastapi.testclient import TestClient
    return TestClient(server.main.app), server.main.project
