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
The images are updated on a 10-minute cadence.

## Setup

- Copy the relevant environment file to .env and update any values as required.
- Add the correct path to the mounted drive where to store the outputs in docker-compose.yml.
- Install docker and docker-compose
- Create local database folder and output folder for the images.
- If you are on an SELinux-enabled system (e.g., Fedora/RHEL), the bind mounts need relabeling so containers can write to them.
  The compose file already uses `:Z`, but the host directories must still exist:

```bash
mkdir -p pgdata images
```

- If you see permission errors for the bind mounts, make the directories writable for local dev

```bash
chmod 777 pgdata images
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
- `py-online` runs the network tests. These hit the JSOC test server, so you must
  provide credentials via `SUNTODAY_JSOC_USER` and `SUNTODAY_JSOC_PASSWORD`
  (e.g. exported in your shell or in a `.env` file).
- `py-figure` compares only deterministic figure tests against the stored baselines.
- `codestyle` is a check for the automated coding tools.

To update stored figure baselines, run `tox -e py-figure-generate`. This also
generates live remote-data figures when the JSOC credentials are available.

## Future Work

1. Add PFSS fieldlines
2. Add movies
