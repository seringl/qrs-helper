# QRS Helper

A self-hosted web app for creating branded **QR codes**, **Bitly short links**,
and **print-ready cards** from a single form. Built with Flask and packaged to
run entirely in Docker — the only thing you install is Docker itself.

> Replace the placeholders below (your name/org and repo URL) before publishing.

## What it does

- **Full card** — creates a Bitly short link, a branded QR code (logo embedded
  by QRCode Monkey), and a print-ready 4.25" × 5.5" card. Clicks are tracked.
- **QR code only** — a branded QR for a URL you already have, delivered as a
  high-resolution PNG and a vector SVG, plus the full framed card.
- **Short link only** — just a tidy, tracked Bitly link.

Other features: user accounts with roles (local or LDAP), an admin area for
logos / Bitly domains / card templates / app settings, a click-analytics
dashboard, and automatic hourly analytics harvesting.

## Card templates

Admins design cards in **Admin → Card Templates** with live-preview sliders
(each with − / + buttons) for the outer and inner corner radius, QR size, and the
vertical position of the call-to-action and URL text. Card text uses Inter
SemiBold (CTA) and Inter Light (URL).

## Quick start

You need [Docker](https://docs.docker.com/get-docker/) and a
[Bitly API token](https://app.bitly.com/settings/api).

```bash
git clone https://github.com/seringl/qrs-helper.git
cd qrs-helper
cp .env.example .env        # edit .env: set SECRET_KEY and BITLY_API_TOKEN
docker compose up --build -d
```

The first build downloads the base image, Python packages, and fonts (Inter +
Bebas Neue) — a few minutes. After that, startups take seconds.

Get the one-time admin password from the log:

```bash
docker compose logs app | grep -A 3 "Initial admin"
```

Then open `https://your-server-address` (a self-signed certificate is generated
on first run; click through the browser warning for testing). Log in as
`qrsadmin`, set a new password, and follow the in-app **Help → Admin & setup**
checklist.

Generate a `SECRET_KEY` with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Documentation

- **SERVER_INSTALL_GUIDE.md** — step-by-step server install, updates, backups,
  and troubleshooting.
- **DESIGN.md** — full technical design (architecture, database schema, APIs,
  card spec, security).

## External services

- **Bitly** (required) — short links + click analytics. You supply your own token.
- **QRCode Monkey** (free, no key) — QR styling and logo embedding.
- **Dinopass** (optional) — memorable first-run admin password; falls back to a
  local random password if unreachable.

## Tests

```bash
docker compose exec app pytest
```

## License

Add your chosen license here (MIT is a common, permissive choice). See
PUBLISHING_GUIDE.md for guidance.
