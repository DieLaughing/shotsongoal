FROM python:3.13-slim
LABEL org.opencontainers.image.source="https://github.com/DieLaughing/shotsongoal" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SOG_DATA=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sog ./sog
COPY web ./web

EXPOSE 8788
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8788/healthz')"
CMD ["uvicorn", "sog.app:app", "--host", "0.0.0.0", "--port", "8788", "--proxy-headers", "--forwarded-allow-ips", "*"]
