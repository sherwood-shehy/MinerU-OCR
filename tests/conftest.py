"""Keep offline tests away from real credentials, job caches and network."""
import socket

import pytest

from mineru_ocr import config, storage, records


@pytest.fixture(autouse=True)
def isolated_local_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.toml")
    monkeypatch.setattr(records, "default_work_dir", lambda: tmp_path / "records")
    monkeypatch.setattr(storage, "cache_root", lambda: tmp_path / "jobs")
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    def no_network(*args, **kwargs):
        raise AssertionError("Offline tests must not open network connections")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
