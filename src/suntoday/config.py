"""
Provide full config support for the entire library.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings"]


class Settings(BaseSettings):
    """
    Default configuration.

    These can be overridden using environment variables.
    e.g., ``export suntoday_save_directory = "./"`` or via a .env file.
    """

    model_config: SettingsConfigDict = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="suntoday_",
    )
    cron_frequency: int = 30  # minutes
    db_host: str = "db"
    db_name: str = "suntoday"
    db_password: str = "suntoday_user_password"  # NOQA: S105
    db_port: int = 5432
    db_user: str = "suntoday_user"
    db_url: str = f"postgresql+psycopg2://{db_user}@{db_host}:{db_port}/{db_name}"
    fig_dpi: int = 300
    jsoc_base_url: str = "http://jsoc.stanford.edu"
    jsoc_delay: int = 120  # minutes
    jsoc_info_url: str = "http://jsoc2.stanford.edu/cgi-bin/ajax/jsoc_info"
    # Credentials for the authenticated test data series. Not shipped in code:
    # set SUNTODAY_JSOC_USER / SUNTODAY_JSOC_PASSWORD via .env or CI secrets.
    jsoc_password: str = ""
    jsoc_str_fmt: str = "%Y.%m.%d_%H:%M:%S_TAI"
    jsoc_user: str = ""
    log_level: str = "INFO"
    map_fig_size: float = 4096 / fig_dpi  # pixels / dpi = inches
    resize_fig_size: int = 1024  # pixels
    rgb_contrast: float = 1.2
    save_directory: Path = Path("./")
    sdo_fig_name_large: str = "f{}.jpg"
    sdo_fig_name_small: str = "l{}.jpg"
    test_env: bool = False
    timeseries_fig_x_size: float = (1024 * 2) / fig_dpi  # pixels / dpi = inches
    timeseries_fig_y_size: float = (1024 * 6) / fig_dpi  # pixels / dpi = inches
