FROM ghcr.io/astral-sh/uv:0.11.21 AS uv
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y git postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY backend /app
COPY scripts /app/scripts
# Backend regression container also verifies the committed shared Dagster environment contract.
# This file contains no credentials; runtime secrets stay in the host-only env file.
COPY docker-compose.shared.yml /app/compose-contract/docker-compose.shared.yml

# 빈 전용 환경에 lock의 정확한 버전·VCS revision을 설치한다.
# pyproject만 읽는 pip 설치는 같은 version의 오래된 provider commit을 남길 수 있다.
RUN uv sync --locked --extra dev --python /usr/local/bin/python --no-managed-python

# Opinet의 실험적 지역별 화면 수집기가 사용하는 Chromium과 Linux 런타임을
# 이미지에 포함한다. 수집기는 TRANSPORT_COLLECTION_ENABLED=true일 때만 실행된다.
RUN playwright install --with-deps chromium

COPY .env.server14.example /app/compose-contract/.env.server14.example
COPY docs/openapi.json /app/compose-contract/openapi.json
COPY docker-compose.yml /app/compose-contract/docker-compose.yml
COPY docker-compose.transport-admin.yml /app/compose-contract/docker-compose.transport-admin.yml
COPY deploy/transport-admin /app/compose-contract/deploy/transport-admin
COPY packages/kor-travel-transport-admin/frontend /app/compose-contract/packages/kor-travel-transport-admin/frontend

COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /app/backups

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
