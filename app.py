"""Flask web application for Spotify playlist creation."""

from __future__ import annotations

import logging
import threading
import time
import traceback
import webbrowser

from flask import Flask, render_template, request

from constants import DEFAULT_HOST, DEFAULT_PORT
from spotify_sample_playlist import (
    SpotifyAPIError,
    SpotifyAuthError,
    create_playlist_for_artist,
)

logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def _open_browser() -> None:
    """Open browser to app URL after a short delay."""
    time.sleep(0.5)
    webbrowser.open(f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/")


@app.get("/")
def index():
    """Render main page."""
    return render_template("index.html")


@app.post("/create")
def create():
    """Handle playlist creation request."""
    artist = (request.form.get("artist") or "").strip()
    track_limit_raw = (request.form.get("track_limit") or "").strip()
    track_limit = None

    if track_limit_raw:
        try:
            track_limit = int(track_limit_raw)
        except ValueError:
            logger.warning(f"Invalid track limit value: {track_limit_raw}")
            track_limit = None

    result_url = None
    error = None

    if not artist:
        error = "Artist name is required"
        logger.warning("Playlist creation attempt with empty artist name")
    else:
        try:
            logger.info(f"Creating playlist for: {artist}")
            result_url = create_playlist_for_artist(artist, track_limit=track_limit)
            logger.info(f"Successfully created playlist: {result_url}")
        except (SpotifyAuthError, SpotifyAPIError) as e:
            error = str(e)
            logger.error(f"Spotify error: {e}", exc_info=True)
        except ValueError as e:
            error = f"Invalid input: {e}"
            logger.error(f"Validation error: {e}", exc_info=True)
        except Exception as e:
            error = f"Unexpected error: {type(e).__name__}"
            logger.error(f"Unexpected error: {e}", exc_info=True)
            traceback.print_exc()

    return render_template("index.html", result_url=result_url, error=error, artist=artist)


if __name__ == "__main__":
    logger.info(f"Starting server on {DEFAULT_HOST}:{DEFAULT_PORT}")
    # Note: Flask debug uses reloader which may start twice. Keep it off.
    threading.Thread(target=_open_browser, daemon=True).start()
    app.run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=False)

