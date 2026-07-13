# SunToday Figure Generation Library

This repository contains the code to generate the figures for the SunToday webpage.

This includes:

- The AIA JPEGs in 4k and 1k resolution without magnetic field lines.
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
- The HMI JPEGS in 4k and 1k resolution without magnetic field lines.
  - 171 - B_LOS
  - B_LOS
  - Continuum
- The combination of the AIA lightcurves with GOES.

In future if we want to add movie support it will need to produce the following:

24HR movies:

- 304‑211‑171 | 94‑335‑193 | 211‑193‑171 | 171‑B(los)

304-171 movies:

- 0‑6UT | 6‑12UT | 12‑18UT | 18‑24UT

211-193-171 movies:

- 0‑6UT | 6‑12UT | 12‑18UT | 18‑24UT

211-193-171 running-ratio movies:

- 0‑6UT | 6‑12UT | 12‑18UT | 18‑24UT

This is set up to run on a docker container.
Mount points are configured by the docker-compose.yml file.
The images are regenerated on a fixed cadence, configurable via `SUNTODAY_CRON_FREQUENCY` (minutes, default 10).

## Setup

- Setup the correct EC2 instance
- Install docker and docker-compose

```bash
sudo yum update -y
sudo yum install -y docker
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -a -G docker ec2-user
sudo mkdir -p /usr/libexec/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m) -o /usr/libexec/docker/cli-plugins/docker-compose
sudo chmod +x /usr/libexec/docker/cli-plugins/docker-compose
```

- Copy the relevant (production or test) environment file to .env and update any values as required.
- Set `SUNTODAY_HOST_SAVE_DIRECTORY` to the host output directory; it defaults to `./images`. Compose mounts it at the fixed container path `/app/images`.
- To also upload the generated files to an S3 bucket at the end of each job, set `SUNTODAY_S3_BUCKET` (may include a key prefix, e.g. `s3://suntoday.lmsal.com/sdomedia/SunInTime`) plus the standard AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`) in the .env file. Leave `SUNTODAY_S3_BUCKET` unset to skip the upload.
- Mount the NFS drive for the output images.

```shell
sudo mkdir -p /opt/SunInTime
sudo chmod 777 -R /opt/SunInTime/
sudo mount -t nfs nfs.aws.lmsal.com:/mnt/SunInTime /opt/SunInTime
```

- If you are on an SELinux-enabled system (e.g., Fedora/RHEL), the bind mounts need relabeling so containers can write to them.
  The compose file already uses `:Z`, but the host directories must still exist:

- Create local database folder.

```bash
mkdir -p pgdata
```

- If you see permission errors for the bind mounts, make the directories writable for local dev

```bash
chmod 777 pgdata
```

- Build images

```bash
docker-compose build
```

- Up the container

```bash
docker-compose up
```

## One off

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

## Tests

Runs are run via tox which you will need to install into your Python environment.
You can find them by running:

```bash
$ tox -l
py
py-online
py-figure
codestyle
```

- `py` runs the offline tests only; the network (remote-data) tests are skipped.
- `py-online` runs the network tests. These hit the JSOC test server, so you must provide credentials via `SUNTODAY_JSOC_USER` and `SUNTODAY_JSOC_PASSWORD` (e.g. exported in your shell or in a `.env` file).
- `py-figure` compares only deterministic figure tests against the stored baselines.
- `codestyle` is a check for the automated coding tools.

To update stored figure baselines, run `tox -e py-figure-generate`.
This also generates live remote-data figures when the JSOC credentials are available.

## Future Work

1. Add PFSS fieldlines
2. Add movies
