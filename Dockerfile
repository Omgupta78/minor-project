# FaceID Attendance - production image
#
# dlib (the library behind face_recognition) is compiled from source during
# `pip install`, so this image needs a C++ toolchain and cmake. That build is
# slow: expect 5-15 minutes the first time. It is done in a builder stage so
# the toolchain does not travel into the final image.

# ---------------------------------------------------------------- builder
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        libopenblas-dev \
        liblapack-dev \
        libx11-dev \
        libjpeg62-turbo-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Build wheels once, install them in the runtime stage.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip wheel \
    && /opt/venv/bin/pip install -r requirements.txt

# ---------------------------------------------------------------- runtime
FROM python:3.11-slim

# Runtime shared libraries only. No compiler in the shipped image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libopenblas0 \
        liblapack3 \
        libx11-6 \
        libjpeg62-turbo \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY . .

# The database and the enrolment photographs must outlive the container.
# Mount a volume at /data or the next deploy wipes the attendance history.
ENV ATTENDANCE_DB=/data/attendance.db \
    FACES_DIR=/data/faces \
    HOST=0.0.0.0 \
    PORT=8000 \
    OPEN_BROWSER=0 \
    COOKIE_SECURE=1

RUN mkdir -p /data/faces && chmod 755 /data
VOLUME ["/data"]

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /data /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
