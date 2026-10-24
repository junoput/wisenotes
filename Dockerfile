# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
ENV PYTHONDONTWRITEBYTECODE=1 PIP_ROOT_USER_ACTION=ignore PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
# runtime deps only; every dependency ships a wheel, so no compiler is needed
RUN pip install --upgrade pip && pip install .

FROM python:3.12-slim
# service.version and deployment.environment on every log record (app/logs.py);
# deploy/deploy.sh passes the commit as WISENOTES_VERSION. The image is built
# only to serve the operator's notes, so it says prod; -e overrides it.
ARG WISENOTES_VERSION=unknown
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WISENOTES_DATA_DIR=/app/data \
    WISENOTES_VERSION=$WISENOTES_VERSION WISENOTES_ENVIRONMENT=prod
WORKDIR /app
COPY --from=build /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=build /usr/local/bin /usr/local/bin
COPY app app
RUN useradd --create-home appuser && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
# /app/data is where notes live; mount a host directory there (deploy/deploy.sh does)
VOLUME ["/app/data"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
