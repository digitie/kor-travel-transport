FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y git postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY backend /app
COPY scripts /app/scripts

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[dev]"

# Opinet의 실험적 지역별 화면 수집기가 사용하는 Chromium과 Linux 런타임을
# 이미지에 포함한다. 수집기는 TRANSPORT_COLLECTION_ENABLED=true일 때만 실행된다.
RUN playwright install --with-deps chromium

COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /app/backups

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
