#!/usr/bin/env python3
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import shutil
import json

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import jwt
import uvicorn
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
SETTINGS_FILE = BASE_DIR / "settings.json"

def load_settings():
    if not SETTINGS_FILE.exists():
        print(f"ERROR: Settings file not found at {SETTINGS_FILE}")
        print("Please create settings.json with your configuration.")
        exit(1)
    
    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
        settings = json.load(f)
    
    if settings["security"]["secret_key"] is None:
        settings["security"]["secret_key"] = secrets.token_hex(32)
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4)
    
    return settings

CONFIG = load_settings()

SECRET_KEY = CONFIG["security"]["secret_key"]
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = CONFIG["security"]["access_token_expire_hours"]

DATA_DIR = BASE_DIR / CONFIG["paths"]["data_dir"]
MUSIC_DIR = BASE_DIR / CONFIG["paths"]["music_dir"]
PLAYLISTS_FILE = BASE_DIR / CONFIG["paths"]["playlists_file"]

DATA_DIR.mkdir(exist_ok=True)
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

USERS_DB = {
    user["username"]: {
        "username": user["username"],
        "password_hash": hashlib.sha256(user["password"].encode()).hexdigest()
    }
    for user in CONFIG["users"]
}

app = FastAPI(title="LocalStream Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

@app.post("/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    user = USERS_DB.get(request.username)
    if not user or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    access_token = create_access_token(data={"sub": user["username"]})
    return TokenResponse(access_token=access_token)

@app.get("/auth/verify")
async def verify(user: dict = Depends(verify_token)):
    return {"status": "ok", "username": user.get("sub")}

@app.get("/playlists")
async def get_playlists(user: dict = Depends(verify_token)):
    if not PLAYLISTS_FILE.exists():
        return {}
    import json
    with open(PLAYLISTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

@app.post("/playlists")
async def update_playlists(
    file: UploadFile = File(...),
    user: dict = Depends(verify_token)
):
    content = await file.read()
    PLAYLISTS_FILE.write_bytes(content)
    return {"status": "ok", "message": "Playlists updated"}

@app.post("/music/upload")
async def upload_music(
    file: UploadFile = File(...),
    user: dict = Depends(verify_token)
):
    file_path = MUSIC_DIR / file.filename
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"status": "ok", "filename": file.filename}

@app.get("/music/list")
async def list_music(user: dict = Depends(verify_token)):
    files = [f.name for f in MUSIC_DIR.iterdir() if f.is_file()]
    return {"files": files}

@app.get("/music/list_with_hashes")
async def list_music_with_hashes(user: dict = Depends(verify_token)):
    """Get all files with their MD5 hashes in one call (async for performance)"""
    import asyncio
    
    files_with_hashes = {}
    file_paths = [f for f in MUSIC_DIR.iterdir() if f.is_file()]
    
    def calculate_hash(file_path: Path) -> tuple:
        """Calculate hash for a single file"""
        try:
            md5 = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    md5.update(chunk)
            return (file_path.name, md5.hexdigest())
        except Exception as e:
            print(f"Error hashing {file_path.name}: {e}")
            return (file_path.name, None)
    
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(calculate_hash, file_paths))
    
    for filename, hash_value in results:
        if hash_value:
            files_with_hashes[filename] = hash_value
    
    return {"files": files_with_hashes}

@app.get("/music/{filename}")
async def get_music(filename: str, user: dict = Depends(verify_token)):
    file_path = MUSIC_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    media_type = None
    if filename.lower().endswith('.mp4'):
        media_type = "video/mp4"
    elif filename.lower().endswith('.mp3'):
        media_type = "audio/mpeg"
    
    return FileResponse(file_path, media_type=media_type)

@app.get("/music/{filename}/info")
async def get_music_info(filename: str, user: dict = Depends(verify_token)):
    file_path = MUSIC_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            md5.update(chunk)
    
    return {
        "filename": filename,
        "size": file_path.stat().st_size,
        "hash": md5.hexdigest()
    }

@app.delete("/music/{filename}")
async def delete_music(filename: str, user: dict = Depends(verify_token)):
    file_path = MUSIC_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    file_path.unlink()
    return {"status": "ok", "message": f"File {filename} deleted"}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import sys
    
    server_config = CONFIG["server"]
    ssl_config = server_config["ssl"]
    
    cert_file = Path(ssl_config["cert_file"]) if ssl_config["enabled"] else None
    key_file = Path(ssl_config["key_file"]) if ssl_config["enabled"] else None
    
    use_ssl = ssl_config["enabled"] and cert_file and cert_file.exists() and key_file and key_file.exists()
    
    host = server_config["host"]
    port = server_config["port"]
    
    if use_ssl:
        print(f"Starting HTTPS server on https://{host}:{port}")
        print(f"Using certificates: {cert_file} and {key_file}")
        uvicorn.run(
            app,
            host=host,
            port=port,
            ssl_keyfile=str(key_file),
            ssl_certfile=str(cert_file),
            reload=False
        )
    else:
        if ssl_config["enabled"]:
            print("WARNING: SSL is enabled but certificates not found!")
            if cert_file:
                print(f"  Certificate: {cert_file}")
            if key_file:
                print(f"  Key: {key_file}")
        print(f"Starting HTTP server on http://{host}:{port}")
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=False
        )
