from mineru_ocr import config


def test_plaintext_user_config_and_environment_precedence(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    config.save_token('owner-"token"')
    assert config.get_token() == 'owner-"token"'
    assert "owner-" in path.read_text(encoding="utf-8")
    assert config.config_status()["effective_source"] == "config"

    monkeypatch.setenv("MINERU_API_TOKEN", "environment-token")
    assert config.get_token() == "environment-token"
    assert config.config_status()["effective_source"] == "environment"


def test_clear_token(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    config.save_token("plain-token")
    assert config.clear_token()
    assert not path.exists()
