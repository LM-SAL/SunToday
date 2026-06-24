import os
from pathlib import Path


def test_settings_no_env(monkeypatch) -> None:
    # This will only pass if you have removed the .env file
    monkeypatch.delenv("SUNTODAY_DB_URL", raising=False)

    from suntoday.config import Settings

    # Test that the default settings are correct
    settings = Settings()
    assert settings.cron_frequency == 10
    assert str(settings.save_directory) == str(Path())
    assert settings.jsoc_info_url == "http://jsoc2.stanford.edu/cgi-bin/ajax/jsoc_info"
    # Should be overridden by tox.
    assert settings.test_env is True
    expected_db_url = (
        f"postgresql+psycopg2://{settings.db_user}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )
    assert settings.db_url == expected_db_url


def test_settings_with_env() -> None:
    # This will only pass if you have removed the .env file
    os.environ["SUNTODAY_SAVE_DIRECTORY"] = "./YOLO"
    os.environ["SUNTODAY_JSOC_INFO_URL"] = "./VSO"

    from suntoday.config import Settings

    # Test that the environment variables override the defaults
    settings = Settings()
    assert str(settings.save_directory) == str(Path("./YOLO"))
    assert settings.jsoc_info_url == "./VSO"

    del os.environ["SUNTODAY_SAVE_DIRECTORY"]
    del os.environ["SUNTODAY_JSOC_INFO_URL"]

    # Test that the variables are back to normal
    settings = Settings()
    assert str(settings.save_directory) == str(Path())
    assert settings.jsoc_info_url == "http://jsoc2.stanford.edu/cgi-bin/ajax/jsoc_info"
