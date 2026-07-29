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
- PFSS variants of every JPEG above, anchored to the matched GONG ADAPT file time and produced by a separate scheduled job: each is saved with the field line overlay (`*pfss`) and without (`*pfssnolines`).
- Planning FITS files for every AIA channel (plus 4500, which is FITS-only) and the HMI B_LOS and continuum.
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

## Setup

- Provision the EC2 instance.
- Install Docker, the NFS client, and the Docker Compose plugin.

```bash
sudo yum update -y
sudo yum install -y docker nfs-utils
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker "$USER"
sudo mkdir -p /usr/libexec/docker/cli-plugins
BUILDX_VERSION=$(curl -s https://api.github.com/repos/docker/buildx/releases/latest | grep -oP '"tag_name": "\K[^"]+') sudo curl -Lo /usr/libexec/docker/cli-plugins/docker-buildx "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-amd64"
sudo chmod +x /usr/libexec/docker/cli-plugins/docker-buildx
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m) -o /usr/libexec/docker/cli-plugins/docker-compose
sudo chmod +x /usr/libexec/docker/cli-plugins/docker-compose
docker compose version
```

Log out and back in, or run `newgrp docker`, before running Docker without `sudo`.

- Copy the relevant environment file to `.env` and update its values.
- Set `HOST_UID`/`HOST_GID` in `.env` to a uid/gid that can write to the NFS share (e.g. `id -u ec2-user`); the default is 500, which owns the legacy date directories on the share.
- Set `SUNTODAY_HOST_SAVE_DIRECTORY` to the host output directory; it defaults to `./images`. Compose mounts it at the fixed container path `/app/images`.
- To upload generated files after each job, set `SUNTODAY_S3_BUCKET` (optionally including a key prefix, e.g. `s3://suntoday.lmsal.com/sdomedia/SunInTime`) plus `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_DEFAULT_REGION` in `.env`. If temporary credentials are used, also set `AWS_SESSION_TOKEN`. Leave `SUNTODAY_S3_BUCKET` unset to skip uploads. Static keys are used for now; an EC2 IAM role can replace them later.
- Configure the NFS drive to mount automatically at `/opt/SunInTime`. Add this line to `/etc/fstab`:

```text
nfs.aws.lmsal.com:/mnt/SunInTime /opt/SunInTime nfs defaults,_netdev 0 0
```

Then create and verify the mount:

```bash
sudo mkdir -p /opt/SunInTime
sudo mount -a
mountpoint /opt/SunInTime
```

Ensure the NFS export permissions allow the container to write. Changing permissions before mounting only changes the hidden local mount point.

On SELinux-enabled systems, Compose uses `:Z` for local bind mounts. NFS also requires the appropriate host policy:

```bash
sudo setsebool -P virt_use_nfs 1
```

PostgreSQL uses a Docker-managed local volume; no host database directory or permission setup is required.
An Adminer database browser is published on port 1234 (System: PostgreSQL, Server: db, User: suntoday_user, Database: suntoday, no password); the Postgres port itself is never exposed.

- Build the images.

```bash
docker compose build
```

- Start the containers.

```bash
docker compose up
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

- Date only: `YYYY-MM-DD` (interpreted as midnight UTC)
- Datetime: ISO-8601, e.g. `2026-02-04T12:30:00Z`

Add `--pfss` to run the PFSS overlay job instead of the main job (requires `--date`):

```bash
docker compose run --rm suntoday --date 2026-02-04 --pfss
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
