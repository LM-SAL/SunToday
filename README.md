# SunToday Figure Generation Library

This repository contains the code to generate the figures for the SunToday webpage.

This includes:

- The AIA JPEGs in three sizes: full resolution 4096 px (`f*.jpg`), 1024 px (`l*.jpg`), and 256 px thumbnails (`t*.jpg`).
  - 131
  - 1600
  - 1700
  - 171
  - 193
  - 211
  - 211 - 193 - 171
  - 304
  - 304 - 211 - 171
  - 335
  - 94
  - 94 - 335 - 193
- The HMI JPEGs in the same three sizes.
  - 171 - B_LOS
  - B_LOS
  - Continuum
- PFSS variants of every JPEG above, anchored to the matched NOAA-hosted GONG synoptic-map time and produced by a separate scheduled job: each is saved with the field line overlay (`*pfss`) and without (`*pfssnolines`).
- Planning FITS files for every AIA image channel and the HMI B_LOS and continuum. AIA 4500 is FITS-only and is
  written only when its hourly frame falls inside the query window.
- The combination of the AIA lightcurves with GOES.

Future movie support will need to produce the following:

24-hour movies:

- 304‑211‑171 | 94‑335‑193 | 211‑193‑171 | 171‑B(los)

304-171 movies:

- 0‑6UT | 6‑12UT | 12‑18UT | 18‑24UT

211-193-171 movies:

- 0‑6UT | 6‑12UT | 12‑18UT | 18‑24UT

211-193-171 running-ratio movies:

- 0‑6UT | 6‑12UT | 12‑18UT | 18‑24UT

This is set up to run in a Docker container.
Mount points are configured by `docker-compose.yml`.
The images are regenerated on a fixed cadence, configurable via `SUNTODAY_CRON_FREQUENCY` (minutes, default 10).
The PFSS job runs on its own cadence, `SUNTODAY_PFSS_CRON_FREQUENCY` (minutes, default 90).
NOAA's GONG index covers only the latest three days, so older PFSS backfills are unavailable.

## Setup

- Provision the EC2 instance (t2.medium, Amazon Linux 2023).
- Install git, clone the repository, and run the provisioning script:

```bash
sudo dnf install -y git
git clone https://github.com/LM-SAL/SunToday.git
cd SunToday
sudo ./tools/setup_ec2.sh
```

The script installs Docker, pinned and checksum-verified buildx and compose CLI plugins, and the NFS client; adds you to the `docker` group; mounts the image share at `/opt/SunInTime` via `/etc/fstab`; and sets the `virt_use_nfs` SELinux boolean (AL2023 runs SELinux in permissive mode by default; the boolean keeps NFS writable if enforcing mode is ever enabled). Override the default export on a new host with `sudo NFS_EXPORT=server:/path ./tools/setup_ec2.sh`. It is safe to re-run. Log out and back in, or run `newgrp docker`, before running Docker without `sudo`.

- Copy the relevant environment file to `.env` and update its values.
- Set `HOST_UID`/`HOST_GID` in `.env` to a uid/gid that can write to the NFS share (e.g. `id -u ec2-user`); the default is 500, which owns the legacy date directories on the share.
- Set `SUNTODAY_HOST_SAVE_DIRECTORY` to the host output directory; it defaults to `./images`. Compose mounts it at the fixed container path `/app/images`.
- To upload generated files after each job, set `SUNTODAY_S3_BUCKET` (optionally including a key prefix, e.g. `s3://suntoday.lmsal.com/sdomedia/SunInTime`) plus `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_DEFAULT_REGION` in `.env`. If temporary credentials are used, also set `AWS_SESSION_TOKEN`. Leave `SUNTODAY_S3_BUCKET` unset to skip uploads. Static keys are used for now; an EC2 IAM role can replace them later.

Ensure the NFS export permissions allow the container to write. Changing permissions before mounting only changes the hidden local mount point.

PostgreSQL uses a Docker-managed local volume; no host database directory or permission setup is required.
The Postgres port is never exposed; the app reaches the DB over the internal compose network.

- Build and start the containers:

```bash
docker compose up -d --build
```

### Updating

```bash
git pull
docker compose up -d --build --remove-orphans
docker image prune -f  # reclaim space from superseded build layers
```

### Database backup

The database volume survives container recreation and `docker compose down`, but not `docker compose down -v`. Create a portable backup with:

```bash
docker compose exec -T db pg_dump -U suntoday_user -d suntoday --format=custom > suntoday-db.dump
```

Restore it with:

```bash
docker compose stop suntoday
docker compose exec -T db pg_restore -U suntoday_user -d suntoday --clean --if-exists < suntoday-db.dump
docker compose start suntoday
```

## One-off

You can run a single job for a specific date/time.

- Run a one-off container:

```bash
docker compose run --rm suntoday --date 2026-02-04
```

- Exec into the running container:

```bash
docker exec -it <container_name> python /app/src/suntoday/main.py --date 2026-02-04
```

Accepted formats:

- Date only: `YYYY-MM-DD` (interpreted as the end of that day, 23:57 UTC, so
  the products represent the day's final state)
- Datetime: ISO-8601, e.g. `2026-02-04T12:30:00Z`

One-off runs upload only to the dated S3 prefix; the `mostrecent/` mirror is
updated by scheduled runs alone, so a backfill can never replace the latest
images on the webpage.

Add `--pfss` to also run the PFSS overlay job after the main job (requires `--date`):

```bash
docker compose run --rm suntoday --date 2026-02-04 --pfss
```

Add `--force` to regenerate even when the database says the images for that
date are already current (requires `--date`):

```bash
docker compose run --rm suntoday --date 2026-02-04 --force
```

## Tests

Tests run via tox, which must be installed in your Python environment.
List the environments with:

```bash
$ tox -l
py
py-online
py-figure
codestyle
```

- `py` runs the offline tests only; the network (remote-data) tests are skipped.
- `py-online` runs the network tests. These hit the JSOC test server, so you must provide credentials via `SUNTODAY_JSOC_USER` and `SUNTODAY_JSOC_PASSWORD` (e.g. exported in your shell or in a `.env` file).
- `py-figure` renders every figure product into `figure_test_images/rendered` with a browsable HTML summary. Nothing is compared, so eyeball it.
- `codestyle` is a check for the automated coding tools.

For the real JPEG products (all three sizes, as the pipeline writes them) run
`python tools/render_products.py`, which needs no network.

## Future Work

1. Add movies
