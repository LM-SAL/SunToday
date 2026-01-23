import os
from pathlib import Path


def test_settings_no_env() -> None:
    # This will only pass if you have removed the .env file
    from suntoday.config import Settings

    # Test that the default settings are correct
    settings = Settings()
    assert str(settings.save_directory) == str(Path())
    assert settings.jsoc_info_url == "http://jsoc2.stanford.edu/cgi-bin/ajax/jsoc_info"
    # Should be overridden by the conftest.py fixture
    assert settings.test_env is True


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
