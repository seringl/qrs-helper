# QRS Helper — DESIGN.md §13
FROM python:3.11-slim

# cairo for CairoSVG, fontconfig so cairo can find Inter, curl/unzip for
# build-time asset downloads (curl is kept for the compose healthcheck),
# openssl for first-run self-signed cert generation.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 fontconfig curl unzip openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/qrs-helper

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build-time assets → staged in /opt/vendor; the entrypoint copies them into
# app/static at runtime so they survive the ./app bind mount in dev mode.
# Inter v4.0 from the official repo release (NOT Google Fonts — §3).
RUN mkdir -p /opt/vendor/fonts /opt/vendor/vendor \
    && curl -fsSL -o /tmp/inter.zip \
        https://github.com/rsms/inter/releases/download/v4.0/Inter-4.0.zip \
    && unzip -q /tmp/inter.zip -d /tmp/inter \
    # Card text uses SemiBold (600) for the CTA and Light (300) for the URL.
    # ExtraBold is kept available for the menu/UI.
    && find /tmp/inter -name "Inter-ExtraBold.ttf" -exec cp {} /opt/vendor/fonts/ \; \
    && find /tmp/inter -name "Inter-SemiBold.ttf" -exec cp {} /opt/vendor/fonts/ \; \
    && find /tmp/inter -name "Inter-Light.ttf" -exec cp {} /opt/vendor/fonts/ \; \
    && test -f /opt/vendor/fonts/Inter-ExtraBold.ttf \
    && test -f /opt/vendor/fonts/Inter-SemiBold.ttf \
    && test -f /opt/vendor/fonts/Inter-Light.ttf \
    && rm -rf /tmp/inter /tmp/inter.zip \
    # Register Inter with fontconfig so CairoSVG can render card text
    && mkdir -p /usr/local/share/fonts \
    && cp /opt/vendor/fonts/*.ttf /usr/local/share/fonts/ \
    && fc-cache -f \
    # Locally cached UI assets (offline use — §3)
    # Bebas Neue (menu bar title) from the Google Fonts repo (OFL licence)
    && curl -fsSL -o /opt/vendor/fonts/BebasNeue-Regular.ttf \
        https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf \
    && test -s /opt/vendor/fonts/BebasNeue-Regular.ttf \
    && curl -fsSL -o /opt/vendor/vendor/bootstrap.min.css \
        https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css \
    && curl -fsSL -o /opt/vendor/vendor/bootstrap.bundle.min.js \
        https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js \
    && curl -fsSL -o /opt/vendor/vendor/chart.umd.min.js \
        https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js

COPY . .
RUN chmod +x docker-entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    FLASK_APP=run.py

EXPOSE 5000
ENTRYPOINT ["./docker-entrypoint.sh"]
