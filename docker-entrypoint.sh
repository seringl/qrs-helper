#!/bin/sh
# First-run + start script — DESIGN.md v2.3 §13.2
set -e

echo "── QRS Helper ─────────────────────────────────────────────"

# 1. Static assets: copy build-time downloads into app/static. Needed
#    because dev mode bind-mounts ./app over the image's copy.
mkdir -p app/static/fonts app/static/vendor
for f in /opt/vendor/fonts/*; do
  [ -f "app/static/fonts/$(basename "$f")" ] || cp "$f" app/static/fonts/
done
for f in /opt/vendor/vendor/*; do
  [ -f "app/static/vendor/$(basename "$f")" ] || cp "$f" app/static/vendor/
done

# 2. Self-signed TLS certificate for nginx on first run (§13.2/§16.2).
#    Production replaces these files with a real certificate.
SSL_DIR=instance/ssl
mkdir -p "$SSL_DIR"
if [ ! -f "$SSL_DIR/cert.pem" ] || [ ! -f "$SSL_DIR/key.pem" ]; then
  echo "Generating self-signed TLS certificate (replace for production)…"
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout "$SSL_DIR/key.pem" -out "$SSL_DIR/cert.pem" \
    -subj "/CN=localhost" >/dev/null 2>&1
fi

# 3. Schema + first-run data (idempotent): dirs, tables, qrsadmin, seeds.
#    If a migrations/ tree exists, apply it first.
if [ -d migrations ]; then
  flask db upgrade
fi
flask init-app

# 3b. If a brand-new admin account was just created, surface its one-time
#     password prominently here — the very last thing before the server
#     starts — so it's easy to spot even with `docker compose up -d` logs.
PW_FILE=instance/INITIAL_ADMIN_PASSWORD.txt
if [ -f "$PW_FILE" ]; then
  echo ""
  echo "############################################################"
  echo "#                                                          #"
  echo "#   INITIAL ADMIN LOGIN  (one time — change on first login) #"
  echo "#                                                          #"
  while IFS= read -r line; do echo "#   $line"; done < "$PW_FILE"
  echo "#                                                          #"
  echo "#   Saved at: $PW_FILE"
  echo "#   (this file is removed automatically after you reset it) #"
  echo "############################################################"
  echo ""
fi

# 4. Start the server (§16.2 — Gunicorn in production, dev server otherwise)
if [ "$FLASK_ENV" = "development" ]; then
  echo "Starting Flask development server (FLASK_ENV=development)…"
  exec flask run --host 0.0.0.0 --port 5000
else
  echo "Starting Gunicorn…"
  exec gunicorn -w 4 -b 0.0.0.0:5000 --access-logfile - "app:create_app()"
fi
