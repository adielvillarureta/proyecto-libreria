# run.py — punto de entrada. Toda la app vive en app/ + .env
import os

from app import create_app

app = create_app()
application = app  # alias para servidores WSGI (gunicorn, waitress)

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        debug=os.getenv("FLASK_DEBUG") == "1",
    )
