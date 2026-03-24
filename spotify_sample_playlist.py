"""Spotify playlist creation for artists with instrumental track selection."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from spotipy import Spotify
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from config import APILimitsConfig, SpotifyConfig, TuningConfig
from constants import (
    AUDIO_FEATURES_BATCH_SIZE,
    ALBUM_TRACKS_BATCH_SIZE,
    INSTRUMENTAL_WEIGHT,
    PLAYLIST_ADD_ITEMS_BATCH_SIZE,
    SPOTIFY_CACHE_PATH,
    SPOTIFY_PLAYLIST_NAME_SUFFIX,
    SPOTIFY_SCOPES,
    VOCAL_WEIGHT,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


class SpotifyAuthError(RuntimeError):
    """Raised when Spotify authentication fails."""

    pass


class SpotifyAPIError(RuntimeError):
    """Raised when Spotify API returns an error."""

    pass


def _init_logger() -> None:
    """Initialize logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def get_spotify() -> Spotify:
    """Create authenticated Spotify client."""
    load_dotenv()
    config = SpotifyConfig.from_env()

    auth_manager = SpotifyOAuth(
        client_id=config.client_id,
        client_secret=config.client_secret,
        redirect_uri=config.redirect_uri,
        scope=SPOTIFY_SCOPES,
        cache_path=SPOTIFY_CACHE_PATH,
        open_browser=True,
        show_dialog=config.auth_show_dialog,
    )

    return Spotify(auth_manager=auth_manager)


def _chunked(
    items: list[str],
    size: int,
) -> Iterator[list[str]]:
    """Yield successive chunks of items."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _calculate_track_score(speechiness: float, instrumentalness: float) -> float:
    """Calculate score for track suitability (higher = better for chopping)."""
    return (instrumentalness * INSTRUMENTAL_WEIGHT) + (
        (1.0 - speechiness) * VOCAL_WEIGHT
    )


def _find_first_artist(sp: Spotify, query: str, market: str) -> dict:
    """Find first artist matching query in given market."""
    logger.info(f"Searching for artist: {query}")
    result = sp.search(q=query, type="artist", limit=5)
    items = result.get("artists", {}).get("items", [])

    if not items:
        raise ValueError(f"Artist not found: {query}")

    artist = items[0]
    logger.info(f'Found artist: {artist.get("name")} (ID: {artist.get("id")})')
    return artist


def _get_artist_top_tracks(
    sp: Spotify,
    artist_id: str,
    market: str,
) -> list[str]:
    """Get top tracks for artist using market parameter."""
    try:
        result = sp.artist_top_tracks(artist_id, country=market)
        track_ids = [t["id"] for t in result.get("tracks", []) if t.get("id")]
        logger.info(f"Found {len(track_ids)} top tracks for artist")
        return track_ids
    except SpotifyException as e:
        if getattr(e, "http_status", None) == 403:
            logger.warning("Permission denied for top tracks (403)")
            return []
        raise


def _get_artist_album_ids(
    sp: Spotify,
    artist_id: str,
    market: str,
    max_albums: int,
    page_size: int = 10,
) -> list[str]:
    """Fetch album IDs for artist, deduplicating across paginated results."""
    seen: set[str] = set()
    album_ids: list[str] = []
    offset = 0

    logger.info(f"Fetching artist albums (max: {max_albums})")

    while len(album_ids) < max_albums:
        try:
            result = sp.artist_albums(
                artist_id,
                album_type="album,single",
                country=market,
                limit=min(page_size, max_albums),
                offset=offset,
            )
        except SpotifyException as e:
            if getattr(e, "http_status", None) == 403:
                logger.warning("Permission denied for artist albums (403)")
                break
            raise

        items = result.get("items", [])
        if not items:
            break

        for album in items:
            album_id = album.get("id")
            if album_id and album_id not in seen:
                seen.add(album_id)
                album_ids.append(album_id)
                if len(album_ids) >= max_albums:
                    break

        offset += page_size

    logger.info(f"Found {len(album_ids)} albums")
    return album_ids[:max_albums]


def _get_tracks_from_album(
    sp: Spotify,
    album_id: str,
    artist_id: str,
    market: str,
) -> list[str]:
    """Get track IDs from album, filtering only tracks by the target artist."""
    track_ids: list[str] = []
    offset = 0

    while True:
        try:
            result = sp.album_tracks(
                album_id,
                limit=ALBUM_TRACKS_BATCH_SIZE,
                offset=offset,
                market=market,
            )
        except SpotifyException as e:
            if getattr(e, "http_status", None) == 403:
                logger.warning("Permission denied for album tracks (403)")
                break
            raise

        items = result.get("items", [])
        for track in items:
            if track.get("id"):
                # Check if target artist is credited on this track
                is_credited = any(
                    a.get("id") == artist_id
                    for a in track.get("artists", [])
                )
                if is_credited:
                    track_ids.append(track["id"])

        offset += ALBUM_TRACKS_BATCH_SIZE
        if len(items) < ALBUM_TRACKS_BATCH_SIZE:
            break

    return track_ids


def _get_candidate_tracks(
    sp: Spotify,
    artist_id: str,
    market: str,
    limits: APILimitsConfig,
) -> list[str]:
    """Collect candidate track IDs from artist's catalog with deduplication."""
    track_ids: list[str] = []
    seen: set[str] = set()

    def add_track(track_id: str) -> None:
        if track_id not in seen and len(track_ids) < limits.catalog_track_cap:
            seen.add(track_id)
            track_ids.append(track_id)

    # Add top tracks first
    for track_id in _get_artist_top_tracks(sp, artist_id, market):
        add_track(track_id)

    # Add tracks from albums
    album_ids = _get_artist_album_ids(
        sp,
        artist_id,
        market,
        limits.max_albums,
        limits.artist_albums_page_max,
    )
    for album_id in album_ids:
        if len(track_ids) >= limits.catalog_track_cap:
            break
        for track_id in _get_tracks_from_album(sp, album_id, artist_id, market):
            add_track(track_id)

    logger.info(f"Collected {len(track_ids)} candidate tracks")
    if not track_ids:
        raise SpotifyAPIError("No tracks found for artist in this market")

    return track_ids


def _get_audio_features(
    sp: Spotify,
    track_ids: list[str],
) -> dict[str, dict] | None:
    """Fetch audio features for tracks, or return None if permission denied."""
    logger.info(f"Fetching audio features for {len(track_ids)} tracks")
    audio_by_track_id: dict[str, dict] = {}

    try:
        for batch in _chunked(track_ids, AUDIO_FEATURES_BATCH_SIZE):
            features = sp.audio_features(batch)
            for track_id, feature in zip(batch, features or []):
                if feature:
                    audio_by_track_id[track_id] = feature
    except SpotifyException as e:
        if getattr(e, "http_status", None) == 403:
            logger.warning(
                "Audio features API not available (403) - will use fallback selection"
            )
            return None
        raise

    logger.info(f"Retrieved features for {len(audio_by_track_id)} tracks")
    return audio_by_track_id


def _select_tracks_by_features(
    audio_by_track_id: dict[str, dict],
    candidate_track_ids: list[str],
    tuning: TuningConfig,
) -> list[str]:
    """Select tracks using audio feature analysis with adaptive thresholds."""
    logger.info("Selecting tracks by audio features")

    # Adaptive thresholds: relax gradually if strict thresholds don't yield enough
    threshold_passes = [
        (tuning.max_speechiness, tuning.min_instrumentalness),
        (min(tuning.max_speechiness * 2.0, 0.25), tuning.min_instrumentalness * 0.75),
        (min(tuning.max_speechiness * 3.0, 0.35), tuning.min_instrumentalness * 0.5),
        (0.5, 0.1),  # Final fallback
    ]

    selected: list[str] = []
    seen: set[str] = set()

    for max_speechiness, min_instrumentalness in threshold_passes:
        # Score and rank candidates for this pass
        scored: list[tuple[float, str]] = []

        for track_id in candidate_track_ids:
            if track_id in seen:
                continue

            features = audio_by_track_id.get(track_id)
            if not features:
                continue

            speechiness = features.get("speechiness")
            instrumentalness = features.get("instrumentalness")

            if speechiness is None or instrumentalness is None:
                continue

            # Apply threshold
            if (
                speechiness <= max_speechiness
                and instrumentalness >= min_instrumentalness
            ):
                score = _calculate_track_score(speechiness, instrumentalness)
                scored.append((score, track_id))

        # Add highest-scored tracks from this pass
        scored.sort(reverse=True, key=lambda x: x[0])
        for _, track_id in scored:
            if len(selected) >= tuning.track_limit:
                break
            seen.add(track_id)
            selected.append(track_id)

        if len(selected) >= tuning.track_limit:
            break

    logger.info(f"Selected {len(selected)} tracks using audio features")
    return selected[: tuning.track_limit]


def _get_track_durations(
    sp: Spotify,
    track_ids: list[str],
    market: str,
) -> dict[str, int]:
    """Fetch track durations (usually works when audio-features is blocked)."""
    logger.info(f"Fetching track durations for {len(track_ids)} tracks")
    durations: dict[str, int] = {}

    try:
        for batch in _chunked(track_ids, ALBUM_TRACKS_BATCH_SIZE):
            result = sp.tracks(batch, market=market)
            for track in result.get("tracks", []) or []:
                if track and track.get("id"):
                    durations[track["id"]] = int(track.get("duration_ms", 0))
    except SpotifyException as e:
        if getattr(e, "http_status", None) == 403:
            logger.warning("Track duration API not available (403)")
            return {}
        raise

    logger.info(f"Retrieved durations for {len(durations)} tracks")
    return durations


def _select_tracks_by_duration(
    candidate_track_ids: list[str],
    durations: dict[str, int],
    track_limit: int,
) -> list[str]:
    """Select tracks by duration (fallback when audio-features unavailable)."""
    logger.info("Selecting tracks by duration (fallback)")

    if not durations:
        logger.warning("No duration data available, using arbitrary selection")
        return list(dict.fromkeys(candidate_track_ids))[:track_limit]

    # Rank by duration (longer = more instrumental)
    ranked = sorted(
        candidate_track_ids,
        key=lambda tid: durations.get(tid, 0),
        reverse=True,
    )

    selected: list[str] = []
    seen: set[str] = set()

    for track_id in ranked:
        if track_id not in seen:
            selected.append(track_id)
            seen.add(track_id)
            if len(selected) >= track_limit:
                break

    logger.info(f"Selected {len(selected)} tracks using duration")
    return selected[:track_limit]


def create_playlist_for_artist(
    artist_name: str,
    *,
    track_limit: int | None = None,
) -> str:
    """
    Create Spotify playlist for artist with instrumental track selection.

    Args:
        artist_name: Name of artist to search for
        track_limit: Override for number of tracks (uses config default if None)

    Returns:
        URL to created playlist

    Raises:
        ValueError: If artist name is empty
        SpotifyAuthError: If authentication fails
        SpotifyAPIError: If API calls fail
    """
    _init_logger()

    if not artist_name or not artist_name.strip():
        raise ValueError("Artist name cannot be empty")

    logger.info(f"Creating playlist for artist: {artist_name}")

    # Load configurations
    tuning = TuningConfig.from_env()
    if track_limit is not None:
        logger.info(f"Overriding track limit to {track_limit}")
        tuning = TuningConfig(
            max_speechiness=tuning.max_speechiness,
            min_instrumentalness=tuning.min_instrumentalness,
            track_limit=track_limit,
            country=tuning.country,
        )

    limits = APILimitsConfig.from_env()
    sp = get_spotify()

    # Get current user
    try:
        user = sp.current_user()
        user_id = user.get("id")
        if not user_id:
            raise SpotifyAuthError("Could not retrieve Spotify user ID")
        logger.info(f"Authenticated as user: {user_id}")
    except SpotifyException as e:
        raise SpotifyAuthError(f"Authentication failed: {e}") from e

    # Find artist
    try:
        artist = _find_first_artist(sp, artist_name, tuning.country)
        artist_id = artist["id"]
        display_name = artist.get("name", artist_name).strip()
    except (ValueError, SpotifyException) as e:
        raise SpotifyAPIError(f"Artist lookup failed: {e}") from e

    # Collect candidate tracks
    try:
        candidate_track_ids = _get_candidate_tracks(
            sp,
            artist_id,
            tuning.country,
            limits,
        )
    except SpotifyException as e:
        raise SpotifyAPIError(f"Failed to get candidate tracks: {e}") from e

    # Select tracks (prefer audio features, fall back to duration)
    audio_features = _get_audio_features(sp, candidate_track_ids)
    if audio_features:
        selected_track_ids = _select_tracks_by_features(
            audio_features,
            candidate_track_ids,
            tuning,
        )
    else:
        # Fallback: use duration
        durations = _get_track_durations(sp, candidate_track_ids, tuning.country)
        selected_track_ids = _select_tracks_by_duration(
            candidate_track_ids,
            durations,
            tuning.track_limit,
        )

    if not selected_track_ids:
        raise SpotifyAPIError(
            "Could not select any tracks. "
            "Try a different SPOTIFY_COUNTRY or check your API permissions."
        )

    # Build playlist
    playlist_name = f"{display_name} {SPOTIFY_PLAYLIST_NAME_SUFFIX}"
    logger.info(f"Creating playlist: {playlist_name} with {len(selected_track_ids)} tracks")

    try:
        playlist = sp.current_user_playlist_create(
            name=playlist_name,
            public=False,
            description="",
        )
        playlist_id = playlist["id"]
        logger.info(f"Created playlist (ID: {playlist_id})")
    except SpotifyException as e:
        if getattr(e, "http_status", None) == 403:
            raise SpotifyAPIError(
                "Playlist creation denied (403). "
                "Check that your Spotify app is authorized with playlist-modify scopes "
                "and your account is added to the app's authorized users."
            ) from e
        raise

    # Add tracks to playlist
    selected_uris = [f"spotify:track:{tid}" for tid in selected_track_ids]
    try:
        for batch in _chunked(selected_uris, PLAYLIST_ADD_ITEMS_BATCH_SIZE):
            sp.playlist_add_items(playlist_id, batch)
        logger.info(f"Successfully added {len(selected_uris)} tracks to playlist")
    except SpotifyException as e:
        if getattr(e, "http_status", None) == 403:
            raise SpotifyAPIError(
                "Adding tracks to playlist denied (403). "
                "Ensure playlist modification permissions are granted."
            ) from e
        raise

    playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"
    logger.info(f"Playlist created: {playlist_url}")
    return playlist_url

