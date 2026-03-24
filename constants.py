"""Application constants."""

from __future__ import annotations

# Spotify API constants
SPOTIFY_CACHE_PATH = ".spotify_token_cache"
SPOTIFY_PLAYLIST_NAME_SUFFIX = "SMPL"

# Audio feature scoring weights
INSTRUMENTAL_WEIGHT = 0.7
VOCAL_WEIGHT = 0.3

# API request batching
AUDIO_FEATURES_BATCH_SIZE = 100
ALBUM_TRACKS_BATCH_SIZE = 50
PLAYLIST_ADD_ITEMS_BATCH_SIZE = 100

# Spotify OAuth scopes
SPOTIFY_SCOPES = (
    "user-read-private user-read-email "
    "playlist-modify-private playlist-modify-public"
)

# Flask server
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
