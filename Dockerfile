FROM python:3.13-slim AS builder

RUN mkdir /wheels
WORKDIR /wheels

COPY requirements_full.txt .
RUN pip --trusted-host pypi.org --trusted-host files.pythonhosted.org wheel --wheel-dir /wheels -r requirements_full.txt
RUN rm requirements_full.txt

FROM python:3.13-slim

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

# This is set to avoid any potential issues with downloading files
ENV PARFIVE_TOTAL_TIMEOUT=100

CMD ["python", "/app/src/suntoday/main.py"]
