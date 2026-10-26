"""Settings must not depend on the directory the server is started from."""
from pathlib import Path

from app.core import config

API_DIR = Path(config.__file__).resolve().parents[2]


def test_env_file_is_the_api_folders():
    assert Path(config.Settings.model_config["env_file"]) == API_DIR / ".env"


def test_relative_sqlite_path_is_anchored_to_the_api_folder(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    s = config.Settings(database_url="sqlite+aiosqlite:///./smartfarm.db")
    assert s.database_url == f"sqlite+aiosqlite:///{(API_DIR / 'smartfarm.db').as_posix()}"


def test_other_database_urls_are_untouched():
    for url in ("", "postgresql+psycopg://u:p@db:5432/smartfarm",
                "sqlite+aiosqlite:///D:/data/farm.db", "sqlite+aiosqlite:///:memory:"):
        assert config.Settings(database_url=url).database_url == url
