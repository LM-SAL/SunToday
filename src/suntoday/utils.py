"""
Utility functions for image processing and visualization.
"""

import mimetypes
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import boto3
import numpy as np
import sunpy.map as smap
from astropy.io.fits import CompImageHDU

from suntoday import logger

__all__ = [
    "atomic_save",
    "save_fits",
    "sync_to_s3",
]


@contextmanager
def atomic_save(final_path: Path) -> Iterator[Path]:
    """
    Write to a sibling temp file and atomically move it into place on success.

    Prevents readers (e.g. the webpage) from ever seeing a half-written file,
    and avoids leaving a corrupt file behind if writing fails mid-way. The
    temp file lives in the same directory so ``Path.replace`` is atomic.

    The temp file keeps the final extension (``f171.tmp-<unique>.jpg``) so that
    format-from-extension writers (matplotlib, PIL, sunpy) still work.

    Parameters
    ----------
    final_path : pathlib.Path
        The destination path. The caller writes to the yielded temp path.

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
    Upload files to an S3 bucket.

    Object keys are the file paths relative to ``root_save_directory``,
    appended to any key prefix included in ``bucket``, so the bucket mirrors
    the local layout after the key prefix.

    Credentials are read by boto3 from the standard AWS environment variables
    (``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``, ``AWS_DEFAULT_REGION``).

    Parameters
    ----------
    files : iterable of pathlib.Path
        Files to upload.
    bucket : str
        Destination bucket, optionally with a key prefix and ``s3://`` scheme,
        e.g. ``s3://suntoday.lmsal.com/sdomedia/SunInTime``.
    root_save_directory : pathlib.Path
        Root directory the object keys are made relative to.
    mostrecent_root : pathlib.Path, optional
        When set, copy the uploaded objects to ``mostrecent/`` using paths
        relative to this directory.

    Raises
    ------
    ValueError
        If a file is outside ``root_save_directory``.
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


def save_fits(amap: smap.GenericMap, save_directory: Path, filename: str) -> Path:
    """
    Save a SunPy map as a compressed FITS file.

    Parameters
    ----------
    amap : sunpy.map.GenericMap
        The map to write to disk.
    save_directory : pathlib.Path
        Directory to write the FITS file into.
    filename : str
        Name of the FITS file to create.

    Returns
    -------
    pathlib.Path
        Saved FITS path.
    """
    # Empty and integer-only keywords are invalid in the float output.
    amap.meta.pop("", None)
    amap.meta.pop("blank", None)
    with atomic_save(save_directory / filename) as tmp_path:
        amap._data = amap.data.astype(np.float32)  # ruff:ignore[private-member-access]
        amap.save(tmp_path, overwrite=True, hdu_type=CompImageHDU)
    return save_directory / filename
