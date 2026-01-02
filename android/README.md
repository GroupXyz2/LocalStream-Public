# LocalStream Android

Simple Android music player that syncs playlists from your server with authentication.

## Setup

1. Install Android Studio
2. Open this `android` folder as a project
3. Build and run on your phone
4. Configure server settings in the app

## Server Setup

Your server must be running the LocalStream FastAPI server (see `../server/README.md`).

The server provides:
- `/auth/login` - JWT authentication
- `/playlists` - Playlists.json with auth
- `/music/` - Music files with auth

## Features

- View all synced playlists
- Play songs with ExoPlayer
- Basic playback controls (play/pause, next, previous)
- Background playback
- Authenticated sync from server
- JWT token-based security

## Usage

1. Click the sync button (bottom right)
2. App authenticates with server
3. Playlists and songs download
4. Select a playlist to view songs
5. Tap a song to play

## Security

- All API calls require JWT authentication
- Credentials are stored in the app (hardcoded - for production, use secure storage)
- HTTPS required for production use
