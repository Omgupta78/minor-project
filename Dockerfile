# FaceID Attendance production image
FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git libopenblas-dev liblapack-dev libx11-dev libjpeg62-turbo-dev zlib1g-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --upgrade pip wheel && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libopenblas0 liblapack3 libx11-6 libjpeg62-turbo libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY . .
ENV ATTENDANCE_DB=/data/attendance.db FACES_DIR=/data/faces HOST=0.0.0.0 PORT=8000 OPEN_BROWSER=0 COOKIE_SECURE=1 PRODUCTION=1 ALLOW_SIGNUP=0 WEB_CONCURRENCY=1 SESSION_HOURS=12
RUN mkdir -p /data/faces && chmod 755 /data
VOLUME ["/data"]
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /data /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
