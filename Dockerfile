FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libGL si libglib sunt cerute de OpenCV; libpq de psycopg.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libgl1 \
        libglib2.0-0 \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

RUN python -c "import compileall, sys; sys.exit(0 if compileall.compile_dir('apps', quiet=2) else 1)"

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
