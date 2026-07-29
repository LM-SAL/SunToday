FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.30 /uv /usr/local/bin/uv

# pycairo ships no Linux wheel, so it builds from source against the cairo
# headers (needed by the mplcairo rendering backend).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcairo2-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Use the image's CPython; never let uv download a managed interpreter.
ENV UV_NO_MANAGED_PYTHON=1 UV_LINK_MODE=copy

RUN uv venv --python 3.13 /opt/venv

COPY requirements-full.txt /tmp/requirements-full.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/venv/bin/python -r /tmp/requirements-full.txt

COPY . /app
# --no-deps: dependencies are already installed from the pinned lockfile above.
# Without it, this would re-resolve deps off PyPI and could drift from the pins.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/venv/bin/python --no-deps /app/.

FROM python:3.13-slim

# Runtime shared library for pycairo/mplcairo.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Copied to the same path as in the builder: the venv's console scripts
# hardcode /opt/venv shebangs.
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
ENV PATH="/opt/venv/bin:${PATH}"

RUN mkdir -p /app/images
WORKDIR /app

# Fail a stalled JSOC/GOES download after 100 s instead of hanging the job
# on aiohttp's defaults.
ENV PARFIVE_TOTAL_TIMEOUT=100
ENV SUNTODAY_SAVE_DIRECTORY=/app/images

# Cap BLAS thread pools to the t2.medium's 2 cores instead of the default
# (auto-detects host core count, which can wildly overshoot the container's cgroup limit).
ENV OPENBLAS_NUM_THREADS=2
ENV OMP_NUM_THREADS=2
ENV MKL_NUM_THREADS=2
ENV NUMEXPR_NUM_THREADS=2

ENTRYPOINT ["python", "/app/src/suntoday/main.py"]
