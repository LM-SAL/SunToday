FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcairo2-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir /wheels
WORKDIR /wheels

COPY requirements-full.txt .
RUN pip --trusted-host pypi.org --trusted-host files.pythonhosted.org wheel --wheel-dir /wheels -r requirements-full.txt
RUN rm requirements-full.txt

FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/images

# Bind-mount the wheels from the builder stage so they never land in a layer;
# a COPY + rm would keep them in the image and roughly double its size.
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip --trusted-host pypi.org --trusted-host files.pythonhosted.org install --no-cache /wheels/*

COPY . /app
WORKDIR /app
# --no-deps: dependencies are already installed from the pinned wheels above.
# Without it, this would re-resolve deps off PyPI and could drift from the pins.
RUN pip --trusted-host pypi.org --trusted-host files.pythonhosted.org install --no-deps /app/.

# This is set to avoid any potential issues with downloading files
ENV PARFIVE_TOTAL_TIMEOUT=100
ENV SUNTODAY_SAVE_DIRECTORY=/app/images

ENTRYPOINT ["python", "/app/src/suntoday/main.py"]
