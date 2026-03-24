"""Configuration management for the Spotify SMPL application."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SpotifyConfig:
    """Spotify API configuration from environment variables."""

    client_id: str
    client_secret: str
    redirect_uri: str
    auth_show_dialog: bool

    @classmethod
    def from_env(cls) -> SpotifyConfig:
        """Load configuration from environment variables."""
        client_id = _require_env("SPOTIPY_CLIENT_ID")
        client_secret = _require_env("SPOTIPY_CLIENT_SECRET")
        redirect_uri = _require_env("SPOTIPY_REDIRECT_URI")
        auth_show_dialog = _parse_bool(
            os.getenv("SPOTIFY_AUTH_SHOW_DIALOG", "0")
        )
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            auth_show_dialog=auth_show_dialog,
        )


@dataclass(frozen=True)
class TuningConfig:
    """Audio feature tuning parameters."""

    max_speechiness: float
    min_instrumentalness: float
    track_limit: int
    country: str

    @classmethod
    def from_env(cls) -> TuningConfig:
        """Load tuning configuration from environment variables."""
        max_speechiness = float(os.getenv("SPOTIFY_MAX_SPEECHINESS", "0.08"))
        min_instrumentalness = float(
            os.getenv("SPOTIFY_MIN_INSTRUMENTALNESS", "0.6")
        )
        track_limit = int(os.getenv("SPOTIFY_TRACK_LIMIT", "30"))
        country = os.getenv("SPOTIFY_COUNTRY", "US")
        return cls(
            max_speechiness=max_speechiness,
            min_instrumentalness=min_instrumentalness,
            track_limit=track_limit,
            country=country,
        )


@dataclass(frozen=True)
class APILimitsConfig:
    """API-specific limits and constraints."""

    max_albums: int
    catalog_track_cap: int
    artist_albums_page_max: int = 10  # Spotify API hard limit

    @classmethod
    def from_env(cls) -> APILimitsConfig:
        """Load API limits from environment variables."""
        max_albums = int(os.getenv("SPOTIFY_MAX_ALBUMS", "40"))
        catalog_track_cap = int(os.getenv("SPOTIFY_CATALOG_TRACK_CAP", "450"))
        return cls(
            max_albums=max_albums,
            catalog_track_cap=catalog_track_cap,
        )


def _require_env(name: str) -> str:
    """Get required environment variable or raise error."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill in all required values."
        )
    return value


def _parse_bool(value: str) -> bool:
    """Parse boolean value from environment variable string."""
    return value.strip().lower() in ("1", "true", "yes")
