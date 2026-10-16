# DEDAN Health Clinical API (backend-v2).
#
#   docker build -t dedan-api backend-v2
#   docker run -p 8000:8000 --env-file backend-v2/.env dedan-api
#
# Production needs at least: ENVIRONMENT=production, REALTIME_TOKEN_SECRET,
# DEDAN_DATABASE_URL (PostgreSQL), CORS_ORIGINS, SMSETHIOPIA_API_KEY, SMTP_HOST.
# The app refuses to start, or refuses the affected feature, without them.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt

COPY . .

# Never run as root.
RUN useradd --create-home --uid 10001 dedan \
    && mkdir -p /tmp/dedan_images \
    && chown -R dedan /app /tmp/dedan_images
USER dedan

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "main_clinical:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
