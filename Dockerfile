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

RUN mkdir /app
RUN mkdir /app/wheels
ARG SUNTODAY_SAVE_DIRECTORY
RUN mkdir -p $SUNTODAY_SAVE_DIRECTORY

COPY --from=builder /wheels /app/wheels
RUN pip --trusted-host pypi.org --trusted-host files.pythonhosted.org install --no-cache /app/wheels/*
RUN rm -rf /app/wheels

COPY . /app
WORKDIR /app
RUN pip --trusted-host pypi.org --trusted-host files.pythonhosted.org install /app/.

ENV MPLBACKEND=module://mplcairo.base
# This is set to avoid any potential issues with downloading files
ENV PARFIVE_TOTAL_TIMEOUT=100

CMD ["python", "/app/src/suntoday/main.py"]
