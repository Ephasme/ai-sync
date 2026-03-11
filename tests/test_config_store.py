from ai_sync import config_store


def test_write_and_load_config(tmp_path) -> None:
    data = {"op_account_identifier": "example.1password.com", "secret_provider": "1password"}
    config_store.write_config(data, tmp_path)
    loaded = config_store.load_config(tmp_path)
    assert loaded["op_account_identifier"] == "example.1password.com"


def test_resolve_op_account_identifier_prefers_env(monkeypatch, tmp_path) -> None:
    config_store.write_config({"op_account_identifier": "from-config.1password.com", "secret_provider": "1password"}, tmp_path)
    monkeypatch.setenv("OP_ACCOUNT", "FromEnv")
    assert config_store.resolve_op_account_identifier(tmp_path) == "FromEnv"


def test_resolve_op_account_identifier_from_config(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OP_ACCOUNT", raising=False)
    config_store.write_config({"op_account_identifier": "from-config.1password.com", "secret_provider": "1password"}, tmp_path)
    assert config_store.resolve_op_account_identifier(tmp_path) == "from-config.1password.com"
