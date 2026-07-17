import os
from pathlib import Path

import pytest


def test_settings_no_env(monkeypatch) -> None:
    monkeypatch.delenv("SUNTODAY_DB_URL", raising=False)

    from suntoday.config import Settings

    # Test that the default settings are correct.
    # _env_file=None keeps a local .env file from overriding the defaults.
    settings = Settings(_env_file=None)
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
    os.environ["SUNTODAY_SAVE_DIRECTORY"] = "./YOLO"
    os.environ["SUNTODAY_JSOC_INFO_URL"] = "./VSO"

    from suntoday.config import Settings

    # Test that the environment variables override the defaults
    settings = Settings(_env_file=None)
    assert str(settings.save_directory) == str(Path("./YOLO"))
    assert settings.jsoc_info_url == "./VSO"

    del os.environ["SUNTODAY_SAVE_DIRECTORY"]
    del os.environ["SUNTODAY_JSOC_INFO_URL"]

    # Test that the variables are back to normal
    settings = Settings(_env_file=None)
    assert str(settings.save_directory) == str(Path())
    assert settings.jsoc_info_url == "http://jsoc2.stanford.edu/cgi-bin/ajax/jsoc_info"


def test_settings_allows_aws_dotenv_values(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SUNTODAY_S3_BUCKET=s3://my-bucket\nAWS_DEFAULT_REGION=us-west-1\n")

    from suntoday.config import Settings

    assert Settings(_env_file=env_file).s3_bucket == "s3://my-bucket"


def test_settings_rejects_unknown_suntoday_dotenv_values(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SUNTODAY_S3_BUKET=s3://my-bucket\nAWS_DEFAULT_REGION=us-west-1\n")

    from suntoday.config import Settings

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        Settings(_env_file=env_file)
