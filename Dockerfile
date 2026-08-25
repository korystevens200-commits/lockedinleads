FROM python:3.11-slim

WORKDIR /app

# Installed first so the layer is cached when only application code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080 \
    APP_ENV=production \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1

# Mount a volume here so leads and conversations survive a redeploy.
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request,os;urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8080')}/api/public/config\",timeout=4)"

CMD ["python3", "-u", "server.py"]
