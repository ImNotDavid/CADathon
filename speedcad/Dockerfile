FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATA_DIR=/data PORT=3000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static ./static

# run as an unprivileged user; /data is created here so a new named volume inherits this ownership
RUN useradd --system --uid 10001 speedcad && mkdir -p /data && chown speedcad /data
USER speedcad
VOLUME /data

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/api/state', timeout=4)"

# waitress: production WSGI server, listening on all interfaces so the tunnel container can reach it.
# HTTPS ends at Cloudflare, so trust its X-Forwarded-* headers (makes cookies Secure). Trusting every
# source is acceptable only because nothing reaches this container except through the tunnel network.
CMD ["waitress-serve", "--host=0.0.0.0", "--port=3000", "--threads=16", \
     "--trusted-proxy=*", "--trusted-proxy-headers=x-forwarded-for x-forwarded-proto x-forwarded-host", \
     "--clear-untrusted-proxy-headers", "app:app"]
