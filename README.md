# LocalStream Desktop

A PyQt6-based music player with Spotify integration, playlist management, and server synchronization.

## Requirements

- Python 3.8+
- PyQt6
- mutagen
- pyloudnorm
- soundfile
- numpy

## Installation

```bash
pip install -r requirements.txt
```

## Features

- **Audio Playback**: Supports MP3 and MP4 audio/video files
- **Playlist Management**: Create, edit, and organize playlists with persistent storage
- **Spotify Integration**: Download songs, albums, and playlists via spotdl
- **Server Sync**: Two-way synchronization with LocalStream server
- **Volume Normalization**: LUFS-based audio normalization for consistent playback
- **Metadata Editing**: View and edit song information and album artwork
- **Strict Deduplication**: Prevents duplicate songs based on filename or filename+size
- **Folder Import**: Bulk import audio files from directories

## Configuration

Settings are stored in `settings.json`:

```json
{
    "music_folder": "path/to/music",
    "download_dir": "path/to/downloads",
    "server_url": "https://your-server.com:8192",
    "server_username": "username",
    "server_password": "password",
    "auto_sync_enabled": false,
    "auto_sync_interval": 300000
}
```

Playlists are stored in `playlists.json` with song metadata and file paths.

## Usage

Run the application:
```bash
python LocalStream.pyw
```

### Keyboard Shortcuts

- **Space**: Play/Pause
- **Right Arrow**: Next track
- **Left Arrow**: Previous track

### Server Sync

Configure server credentials in `settings.json`, then use the sync button to:
- Upload local playlists to server
- Download missing songs from server
- Maintain synchronized music library across devices

## Technical Details

- **Audio Engine**: PyQt6 QMediaPlayer with QAudioOutput
- **Metadata**: mutagen library for ID3/MP4 tag reading/writing
- **Normalization**: pyloudnorm (EBU R128 standard, -14 LUFS target)
- **Authentication**: JWT token-based server authentication
- **File Hashing**: MD5 checksums for duplicate detection and sync verification
