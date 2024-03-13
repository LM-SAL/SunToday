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
    db_user: str = "suntoday_user"
    db_password: str = "suntoday_user_password"  # NOQA: S105
    db_host: str = "db"  # Container name from docker-compose
    db_port: int = 5432
    db_name: str = "suntoday"
    db_url: str = f"postgresql+psycopg2://{db_user}@{db_host}:{db_port}/{db_name}"
    fig_dpi: int = 300
    jsoc_base_url: str = "http://jsoc.stanford.edu"
    jsoc_delay: int = 30  # minutes
    jsoc_info_url: str = "http://jsoc2.stanford.edu/cgi-bin/ajax/jsoc_info"
    jsoc_password: str = "hmiteam"  # NOQA: S105
    jsoc_str_fmt: str = "%Y.%m.%d_%H:%M:%S_TAI"
    jsoc_user: str = "hmiteam"
    map_fig_size: float = 4096 / fig_dpi  # pixels / dpi = inches
    resize_fig_size: int = 1024  # pixels
    save_directory: Path = Path("./")
    sdo_fig_name_large: str = "f{}.jpg"
    sdo_fig_name_small: str = "l{}.jpg"
    test_env: bool = False
    timeseries_fig_x_size: float = (1024 * 2) / fig_dpi  # pixels / dpi = inches
    timeseries_fig_y_size: float = (1024 * 6) / fig_dpi  # pixels / dpi = inches
