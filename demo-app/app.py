"""Local dev server — imports the Vercel API and serves the static page."""
import os
from flask import send_from_directory
from dotenv import load_dotenv

load_dotenv()

from api.index import app  # noqa: E402


@app.route("/")
def index():
    return send_from_directory("public", "index.html")


if __name__ == "__main__":
    app.run(port=5050, debug=True)
