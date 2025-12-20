"""
LocalStream Server Sync Client
Syncs playlists and music files to the server
"""
import os
import json
import requests
from pathlib import Path
from typing import Optional, Dict, Tuple
import hashlib

class ServerSync:
    def __init__(self, server_url: str, username: str, password: str):
        """Initialize sync client
        
        Args:
            server_url: Server URL (e.g., https://your-domain.com:8443)
            username: Username for authentication
            password: Password for authentication
        """
        self.server_url = server_url.rstrip('/')
        self.username = username
        self.password = password
        self.token: Optional[str] = None
        self.session = requests.Session()
    
    def get_file_hash(self, file_path: Path) -> Optional[str]:
        """Calculate MD5 hash of a file"""
        try:
            md5 = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    md5.update(chunk)
            return md5.hexdigest()
        except Exception as e:
            print(f"Failed to hash {file_path.name}: {e}")
            return None
    
    def login(self) -> bool:
        """Login and get JWT token"""
        try:
            response = self.session.post(
                f"{self.server_url}/auth/login",
                json={"username": self.username, "password": self.password},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                self.token = data["access_token"]
                self.session.headers.update({
                    "Authorization": f"Bearer {self.token}"
                })
                return True
            return False
        except Exception as e:
            print(f"Login failed: {e}")
            return False
    
    def sync_playlists(self, playlists_file: Path) -> bool:
        """Upload playlists.json to server"""
        if not self.token:
            if not self.login():
                return False
        
        try:
            with open(playlists_file, 'rb') as f:
                files = {'file': ('playlists.json', f, 'application/json')}
                response = self.session.post(
                    f"{self.server_url}/playlists",
                    files=files,
                    timeout=30
                )
                return response.status_code == 200
        except Exception as e:
            print(f"Playlist sync failed: {e}")
            return False
    
    def sync_music_file(self, file_path: Path) -> bool:
        """Upload a single music file to server"""
        if not self.token:
            if not self.login():
                return False
        
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (file_path.name, f, 'audio/mpeg')}
                response = self.session.post(
                    f"{self.server_url}/music/upload",
                    files=files,
                    timeout=120
                )
                return response.status_code == 200
        except Exception as e:
            print(f"Music file sync failed for {file_path.name}: {e}")
            return False
    
    def get_server_files_with_hashes(self) -> Dict[str, str]:
        """Get all server files with their hashes in one call"""
        if not self.token:
            if not self.login():
                return {}
        
        try:
            print("Requesting server file hashes (this may take a moment for large libraries)...")
            response = self.session.get(
                f"{self.server_url}/music/list_with_hashes",
                timeout=300 
            )
            if response.status_code == 200:
                data = response.json().get("files", {})
                print(f"Received {len(data)} file hashes from server")
                return data
            else:
                print(f"Server returned status {response.status_code}")
            return {}
        except Exception as e:
            print(f"Failed to get server file hashes: {e}")
            return {}
    
    def get_server_files(self) -> set:
        """Get list of files already on server"""
        if not self.token:
            if not self.login():
                return set()
        
        try:
            response = self.session.get(
                f"{self.server_url}/music/list",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return set(data.get("files", []))
            return set()
        except Exception as e:
            print(f"Failed to get server file list: {e}")
            return set()
    
    def delete_server_file(self, filename: str) -> bool:
        """Delete a file from server"""
        if not self.token:
            if not self.login():
                return False
        
        try:
            response = self.session.delete(
                f"{self.server_url}/music/{filename}",
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to delete {filename}: {e}")
            return False
    
    def sync_all_music(self, playlists_data: Dict, base_dir: Path, progress_callback=None) -> Tuple[int, int, int, int]:
        """Sync all music files from playlists with smart change detection
        
        Returns:
            (success_count, fail_count, skip_count, deleted_count)
        """
        if not self.token:
            if not self.login():
                return (0, 0, 0, 0)
        
        local_files = {}
        print("Calculating local file hashes...")
        for playlist_data in playlists_data.values():
            song_paths = playlist_data.get("song_paths", [])
            if song_paths:
                for path in song_paths:
                    if path:
                        file_path = Path(path)
                        if file_path.exists() and file_path.name not in local_files:
                            local_hash = self.get_file_hash(file_path)
                            if local_hash:
                                local_files[file_path.name] = {
                                    "path": file_path,
                                    "hash": local_hash
                                }
            else:
                for song in playlist_data.get("songs", []):
                    path = song.get("path")
                    if path:
                        file_path = Path(path)
                        if file_path.exists() and file_path.name not in local_files:
                            local_hash = self.get_file_hash(file_path)
                            if local_hash:
                                local_files[file_path.name] = {
                                    "path": file_path,
                                    "hash": local_hash
                                }
        
        print(f"Fetching server file list with hashes...")
        server_file_hashes = self.get_server_files_with_hashes()
        server_files = set(server_file_hashes.keys())
        
        success_count = 0
        fail_count = 0
        skip_count = 0
        deleted_count = 0
        
        files_to_delete = server_files - set(local_files.keys())
        for filename in files_to_delete:
            if progress_callback:
                progress_callback(0, len(local_files), f"Deleting {filename}")
            if self.delete_server_file(filename):
                deleted_count += 1
        
        total = len(local_files)
        for i, (filename, file_info) in enumerate(local_files.items(), 1):
            if progress_callback:
                progress_callback(i, total, filename)
            
            file_path = file_info["path"]
            local_hash = file_info["hash"]
            
            if filename in server_file_hashes:
                server_hash = server_file_hashes[filename]
                if server_hash == local_hash:
                    skip_count += 1
                    continue
                else:
                    if progress_callback:
                        progress_callback(i, total, f"Updating {filename}")
            
            if self.sync_music_file(file_path):
                success_count += 1
            else:
                fail_count += 1
        
        return (success_count, fail_count, skip_count, deleted_count)
    
    def full_sync(self, playlists_file: Path, playlists_data: Dict, progress_callback=None) -> bool:
        """Perform full sync of playlists and music files"""
        if not self.login():
            print("Login failed")
            return False
        
        print("Syncing playlists...")
        if not self.sync_playlists(playlists_file):
            print("Failed to sync playlists")
            return False

        print("Syncing music files...")
        base_dir = playlists_file.parent
        success, fail, skip, deleted = self.sync_all_music(playlists_data, base_dir, progress_callback)
        
        print(f"Sync complete: {success} uploaded, {skip} skipped, {deleted} deleted, {fail} failed")
        return fail == 0
