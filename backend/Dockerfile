FROM ghcr.io/astral-sh/uv:0.11.21@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946 AS uv
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"
COPY --from=uv /uv /uvx /bin/
RUN python -m venv /opt/venv

WORKDIR /app

# pg_dump/pg_restore(backup_restore.py)는 공용 PG 서버와 같은 major(18)여야 한다 — Debian 기본
# postgresql-client는 배포판 major(trixie=17)라 18 서버를 덤프하지 못한다. PGDG에서 major를 명시한다.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates curl \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install --no-install-recommends -y git postgresql-client-18 libgdal-dev g++ \
    && rm -rf /var/lib/apt/lists/*

# GDAL binding은 시스템 ABI에 맞추되 소스 변경마다 native 재컴파일하지 않는다.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "GDAL==$(gdal-config --version)"

COPY --chmod=0644 backend/pyproject.toml backend/uv.lock /app/

RUN uv export --locked --extra dev --no-emit-project --no-hashes \
        --format requirements.txt --output-file /tmp/backend-requirements.txt \
    && pip install --no-cache-dir --no-deps -r /tmp/backend-requirements.txt

# Opinet의 실험적 지역별 화면 수집기가 사용하는 Chromium과 Linux 런타임을
# 이미지에 포함한다. 수집기는 TRANSPORT_COLLECTION_ENABLED=true일 때만 실행된다.
RUN playwright install --with-deps chromium

COPY backend /app
COPY scripts /app/scripts
# Backend regression container also verifies the committed shared Dagster environment contract.
# This file contains no credentials; runtime secrets stay in the host-only env file.
COPY docker-compose.shared.yml /app/compose-contract/docker-compose.shared.yml

RUN pip install --no-cache-dir -e ".[dev]" --no-deps && pip check

# 최종 인터프리터의 stdlib을 root 권한에서 미리 컴파일한다. 런타임에서 이 helper를 호출하지 않는다(무효 cache의 암묵적 컴파일은 별도).
RUN python -I -m kortravelcommon.build_bytecode --stdlib

COPY .env.prod.example /app/compose-contract/.env.prod.example
COPY docs/openapi.json /app/compose-contract/openapi.json
# 이미지 안의 기존 regression도 네 역할 Dockerfile 계약을 같은 소스에서 검사한다.
COPY frontend/Dockerfile /app/compose-contract/frontend/Dockerfile
COPY docker-compose.yml /app/compose-contract/docker-compose.yml
COPY docker-compose.transport-admin.yml /app/compose-contract/docker-compose.transport-admin.yml
# 회귀 컨테이너에서 legacy DB와 실험 fixture의 간격을 구분해 확인한다.
COPY docker-compose.db.yml docker-compose.live.yml /app/compose-contract/
# Odroid code-server 포트 overlay 계약(test_transport_override_contract.py)도 같은 무비밀 계약 사본으로 둔다.
COPY transport.override.yml /app/compose-contract/transport.override.yml
COPY deploy/transport-admin /app/compose-contract/deploy/transport-admin
COPY packages/kor-travel-transport-admin/frontend /app/compose-contract/packages/kor-travel-transport-admin/frontend

COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /app/backups

ARG RELEASE_SHA=unknown
ENV RELEASE_SHA=${RELEASE_SHA}

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
