# LocalStream

A cross-platform music streaming ecosystem with desktop player, server backend, and Android client.

## Architecture

LocalStream consists of three components that work together to provide synchronized music playback across devices:

### Desktop Application (`LocalStream.pyw`)

PyQt6-based music player with Spotify integration and local library management.

**Key Features:**
- MP3/MP4 audio playback with volume normalization (LUFS)
- Playlist management with persistent storage
- Spotify song/album/playlist download via spotdl
- Server synchronization for cross-device library access
- Metadata editing and album artwork management
- Strict deduplication (filename or filename+size based)

**Requirements:** Python 3.8+, PyQt6, mutagen, pyloudnorm

```bash
python LocalStream.pyw
```

### Server (`server/`)

FastAPI-based REST API for music file hosting and playlist synchronization.

**Key Features:**
- JWT authentication with configurable users
- RESTful API for playlist and music file management
- MD5-based file integrity verification
- SSL/TLS support with Let's Encrypt
- Configurable via `settings.json`

**Requirements:** Python 3.8+, FastAPI, uvicorn, PyJWT

See [server/README.md](server/README.md) for detailed setup.

### Android Application (`android/`)

Kotlin-based mobile client for streaming synchronized playlists.

**Key Features:**
- Playlist browsing and playback
- Server sync with automatic file downloads
- Persistent settings (SharedPreferences)
- Background playback service

**Requirements:** Android SDK, Gradle

## Setup

1. **Server**: Configure `server/settings.json` with credentials and SSL certificates, then run `python server/main.py`
2. **Desktop**: Install dependencies via `pip install -r requirements.txt`, configure `settings.json`, run `LocalStream.pyw`
3. **Android**: Configure server URL/credentials in app settings, sync playlists

## Configuration Files

- `settings.json` - Desktop app configuration (music folders, server credentials)
- `playlists.json` - Playlist storage with song metadata
- `server/settings.json` - Server configuration (users, paths, SSL)

## Synchronization

All components use JWT authentication and MD5 checksums to maintain library consistency. The server acts as the central repository, with desktop and mobile clients syncing bidirectionally.
