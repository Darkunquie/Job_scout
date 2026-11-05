# Playwright's image ships Chromium + its system libs at the version requirements.txt pins.
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FASTEMBED_CACHE_PATH=/cache/fastembed
WORKDIR /srv

COPY requirements.txt .
RUN pip install --break-system-packages -r requirements.txt

COPY app ./app
# /cache holds the embedding model; created here so the named volume inherits pwuser ownership.
RUN mkdir -p /cache/fastembed && chown -R pwuser:pwuser /cache
USER pwuser

EXPOSE 8010
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8010", "--proxy-headers", "--forwarded-allow-ips=*"]
