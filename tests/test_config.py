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


def test_doubao_config_is_local_and_preserves_mineru_token(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    config.save_token("mineru-token")
    config.save_doubao_key("doubao-key")

    assert config.get_token() == "mineru-token"
    assert config.get_doubao_config()["api_key"] == "doubao-key"
    assert config.config_status()["doubao_key_set"] is True
    assert "doubao-key" in path.read_text(encoding="utf-8")

    assert config.clear_doubao_key()
    assert config.get_token() == "mineru-token"
    assert config.get_doubao_config()["api_key"] is None
    assert "doubao-key" not in path.read_text(encoding="utf-8")
