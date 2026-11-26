"""
Writing the outputs: atomic saves, planning FITS files and the S3 upload.
"""

import mimetypes
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
import numpy as np
from astropy.io import fits

from suntoday import logger

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable

    import sunpy.map as smap

__all__ = [
    "atomic_save",
    "save_fits",
    "sync_to_s3",
]


@contextmanager
def atomic_save(final_path: Path) -> Generator[Path]:
    """
    Yield a temp path beside ``final_path`` and move it into place on success.

    Readers such as the webpage never see a half-written file, and a failed
    write leaves nothing behind. The temp file is in the same directory, so
    the move is atomic, and it keeps the extension (``f171.tmp-<id>.jpg``)
    for writers that choose the format from it.

    Yields
    ------
    pathlib.Path
        The temp path to write to.
    """
    final_path = Path(final_path)
    tmp_path = final_path.with_name(f"{final_path.stem}.tmp-{uuid.uuid4().hex}{final_path.suffix}")
    try:
        yield tmp_path
        tmp_path.replace(final_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _s3_key(path: Path, root: Path, prefix: str) -> str:
    key = path.relative_to(root).as_posix()
    return f"{prefix}/{key}" if prefix else key


def _copy_to_mostrecent(
    s3_client, paths: list[Path], bucket: str, prefix: str, upload_root: Path, mostrecent_root: Path
) -> None:
    """
    Copy dated objects to their stable latest keys without re-uploading bytes.
    """
    for path in sorted(paths):
        source_key = _s3_key(path, upload_root, prefix)
        destination_key = _s3_key(path, mostrecent_root, f"{prefix}/mostrecent".strip("/"))
        s3_client.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": source_key},
            Key=destination_key,
            MetadataDirective="COPY",
        )


def sync_to_s3(
    files: Iterable[Path],
    bucket: str,
    root_save_directory: Path,
    *,
    mostrecent_root: Path | None = None,
) -> None:
    """
    Upload files to S3 under keys that mirror their local layout.

    Each key is the file's path relative to ``root_save_directory``, after
    any prefix given in ``bucket``. boto3 reads the credentials from the
    standard ``AWS_*`` environment variables.

    Parameters
    ----------
    files : iterable of pathlib.Path
        Files to upload.
    bucket : str
        Bucket name, optionally with an ``s3://`` scheme and a key prefix,
        e.g. ``s3://suntoday.lmsal.com/sdomedia/SunInTime``.
    root_save_directory : pathlib.Path
        Directory the keys are relative to.
    mostrecent_root : pathlib.Path, optional
        Also copy each object to ``mostrecent/``, keyed relative to this
        directory.

    Raises
    ------
    ValueError
        If a file is outside ``root_save_directory`` or ``mostrecent_root``.
    """
    root_save_directory = root_save_directory.resolve()
    mostrecent_root = mostrecent_root.resolve() if mostrecent_root is not None else None
    paths = [Path(path).resolve() for path in files]
    for path in paths:
        if not path.is_relative_to(root_save_directory):
            msg = f"Cannot upload {path}: file is outside root directory {root_save_directory}"
            raise ValueError(msg)
        if mostrecent_root is not None and not path.is_relative_to(mostrecent_root):
            msg = f"Cannot copy {path}: file is outside mostrecent root {mostrecent_root}"
            raise ValueError(msg)

    bucket_name, _, prefix = bucket.removeprefix("s3://").strip("/").partition("/")
    s3_client = boto3.client("s3")
    key_directories = set()
    for path in sorted(paths):
        key = _s3_key(path, root_save_directory, prefix)
        if key_directory := key.rpartition("/")[0]:
            key_directories.add(key_directory)
        if path.name == "aia_light_curves.gif":
            content_type = "image/png"
        elif path.suffix.lower() == ".fits":
            content_type = "image/fits"
        else:
            content_type = mimetypes.guess_type(path.name)[0]
        extra_args = {"ContentType": content_type} if content_type else {}
        if path.suffix.lower() in {".gif", ".jpg"}:
            extra_args["CacheControl"] = "max-age=300, must-revalidate"
        s3_client.upload_file(str(path), bucket_name, key, ExtraArgs=extra_args)
    if mostrecent_root is not None:
        _copy_to_mostrecent(s3_client, paths, bucket_name, prefix, root_save_directory, mostrecent_root)
    destinations = ", ".join(sorted(key_directories)) or prefix
    logger.info(f"Uploaded {len(paths)} files to s3://{bucket_name}/{destinations}")


def save_fits(amap: smap.GenericMap, save_directory: Path, filename: str, *, quantize: bool = False) -> Path:
    """
    Save a map as a compressed FITS file.

    With ``quantize`` the pixels are stored as quantized float32 instead of
    as the map holds them. That is lossy, and only smaller where the noise
    is far above one count: it halves the HMI files, while the integer AIA
    maps are both exact and a third smaller left as they are.

    Returns
    -------
    pathlib.Path
        The saved file.
    """
    # The empty keyword is invalid. BLANK is invalid for float output and
    # names a null value that none of these maps contain.
    amap.meta.pop("", None)
    amap.meta.pop("blank", None)
    data = amap.data.astype(np.float32) if quantize else amap.data
    with atomic_save(save_directory / filename) as tmp_path:
        # Not amap.save: it writes the map's own pixels, and swapping those
        # for the quantized copy would change what is plotted afterwards.
        fits.HDUList([fits.PrimaryHDU(), fits.CompImageHDU(data, amap.fits_header)]).writeto(tmp_path)
    return save_directory / filename
