# nd_project (in progress)

Spotify instrument-heavy playlist generator for artists.

## Setup

### 1. Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate     # On Windows
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Spotify API

Copy `.env.example` to `.env` and add your Spotify API credentials:

```bash
cp .env.example .env
```

Then edit `.env` with your:
- `SPOTIPY_CLIENT_ID`
- `SPOTIPY_CLIENT_SECRET`
- `SPOTIPY_REDIRECT_URI`

Get these from https://developer.spotify.com/dashboard

### 4. Run the App

```bash
python3 app.py
```

The app will open in your browser at `http://127.0.0.1:5000/`

## Features

- Create playlists of instrumental tracks from any artist
- Configurable track limit and filtering preferences
- Flask web interface for easy playlist creation

## Environment Variables

See `.env.example` for all available configuration options.
