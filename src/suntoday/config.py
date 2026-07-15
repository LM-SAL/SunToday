"""
Provide full config support for the entire library.
"""

from pathlib import Path

from pydantic import model_validator
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
        dotenv_filtering="match_prefix",
        extra="forbid",
    )
    cron_frequency: int = 10  # minutes
    db_host: str = "db"
    db_name: str = "suntoday"
    db_password: str = "suntoday_user_password"  # NOQA: S105
    db_port: int = 5432
    db_user: str = "suntoday_user"
    # Built from the db_* components below if not set explicitly via env.
    # Password is intentionally omitted: the container DB uses trust auth.
    db_url: str = ""
    fig_dpi: int = 300
    host_save_directory: Path = Path("./images")  # Docker Compose bind source
    jsoc_base_url: str = "http://jsoc.stanford.edu"
    jsoc_info_url: str = "http://jsoc2.stanford.edu/cgi-bin/ajax/jsoc_info"
    # Credentials for the authenticated test data series. Not shipped in code:
    # set SUNTODAY_JSOC_USER / SUNTODAY_JSOC_PASSWORD via .env or CI secrets.
    jsoc_password: str = ""
    jsoc_str_fmt: str = "%Y.%m.%d_%H:%M:%S_TAI"
    jsoc_user: str = ""
    log_level: str = "INFO"
    map_fig_size: float = 4096 / fig_dpi  # pixels / dpi = inches
    resize_fig_size: int = 1024  # pixels
    # Slope of the tone curve around mid-gray: >1 darkens shadows and brightens
    # highlights across the whole image, 1.0 = no change.
    rgb_contrast: float = 1.3
    # Luminance above this rolls off smoothly toward white instead of clipping.
    # Higher = rolloff starts later = brighter highlights, closer to hard clip.
    rgb_knee_shoulder: float = 0.50
    # If set, generated files are uploaded to this S3 bucket at the end of each
    # main job. Credentials come from standard AWS environment variables
    # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_DEFAULT_REGION.
    s3_bucket: str = ""
    save_directory: Path = Path("./")
    sdo_fig_name_large: str = "f{}.jpg"
    sdo_fig_name_small: str = "l{}.jpg"
    sdo_fig_name_thumb: str = "t{}.jpg"
    test_env: bool = False
    thumb_fig_size: int = 256  # pixels
    timeseries_fig_x_size: float = 1536 / fig_dpi  # pixels / dpi = inches
    timeseries_fig_y_size: float = 4608 / fig_dpi  # pixels / dpi = inches

    @model_validator(mode="after")
    def _build_db_url(self) -> "Settings":
        if not self.db_url:
            self.db_url = f"postgresql+psycopg2://{self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}"
        return self
