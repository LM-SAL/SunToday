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

24hr movies: 304‑211‑171 | 94‑335‑193 | 211‑193‑171 | 171‑B(los)
304-171 movies: 0‑6UT | 6‑12UT | 12‑18UT | 18‑24UT
211-193-171 movies: 0‑6UT | 6‑12UT | 12‑18UT | 18‑24UT
211-193-171 running-ratio movies: 0‑6UT | 6‑12UT | 12‑18UT | 18‑24UT

This is set up to run on a docker container.
Mount points are configured by the docker-compose.yml file.
The images are updated on a 10-minute cadence.

## Setup

- Copy the relevant environment file to .env and update any values as required.
- Add the correct path to the mounted drive where to store the outputs in docker-compose.yml.
- Install docker and docker-compose
- Create database volume

```bash
docker volume create pgdata
```

- Build images

```bash
docker-compose build
```

- Up the container

```bash
docker-compose up
```

## Tests

Runs are run via tox which you will need to install into your Python environment.
You can find them by running:

```bash
$ tox -l
py
py-figure
py-figure-generate
codestyle
```

The first one (py) will run all of the tests with the Python version you are using.
The second one (py-figure) will run the figure tests and check the hashes to the PNGs stored in the repository.
The third one (py-figure-generate) will generate the test PNGs stored in the repository.
Final one (codestyle) is a check for the automated coding tools.

## Future Work

1. Add PFSS fieldlines
2. Add movies
