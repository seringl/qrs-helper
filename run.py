"""Application entry point.

In Docker the entrypoint starts Gunicorn (production) or the Flask dev
server (development). Running this file directly is for local development
only: python run.py
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
