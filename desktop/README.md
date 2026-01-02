# LocalStream Server

A FastAPI-based music streaming server with JWT authentication.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure the server by editing `settings.json`:
```json
{
    "server": {
        "host": "0.0.0.0",
        "port": 8192,
        "ssl": {
            "enabled": true,
            "cert_file": "/path/to/fullchain.pem",
            "key_file": "/path/to/privkey.pem"
        }
    },
    "users": [
        {
            "username": "your_username",
            "password": "your_password"
        }
    ],
    "security": {
        "secret_key": null,
        "access_token_expire_hours": 720
    },
    "paths": {
        "data_dir": "data",
        "music_dir": "data/music",
        "playlists_file": "data/playlists.json"
    }
}
```

**Note:** The `secret_key` will be auto-generated on first run if set to `null`.

3. Run the server:
```bash
python main.py
```

## Settings

### Server Configuration
- **host**: Server bind address (default: "0.0.0.0")
- **port**: Server port (default: 8192)
- **ssl.enabled**: Enable HTTPS (default: true)
- **ssl.cert_file**: Path to SSL certificate
- **ssl.key_file**: Path to SSL private key

### Users
Add one or more users with username and password. Passwords are hashed with SHA256.

### Security
- **secret_key**: JWT secret key (auto-generated if null)
- **access_token_expire_hours**: Token expiration time (default: 720 hours/30 days)

### Paths
- **data_dir**: Root directory for server data
- **music_dir**: Directory containing music files
- **playlists_file**: JSON file storing playlists

## API Endpoints

- `POST /auth/login` - Authenticate and get JWT token
- `GET /auth/verify` - Verify JWT token
- `GET /playlists` - Get all playlists
- `POST /playlists` - Update playlists
- `POST /music/upload` - Upload music file
- `GET /music/list` - List all music files
- `GET /music/list_with_hashes` - List music files with MD5 hashes
- `GET /music/{filename}` - Download music file
- `GET /music/{filename}/info` - Get file info and hash
- `DELETE /music/{filename}` - Delete music file
- `GET /health` - Health check endpoint
