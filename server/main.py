#!/usr/bin/env python3
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import shutil

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import jwt
import uvicorn
from pydantic import BaseModel

SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 720 
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
MUSIC_DIR = DATA_DIR / "music"
PLAYLISTS_FILE = DATA_DIR / "playlists.json"

DATA_DIR.mkdir(exist_ok=True)
MUSIC_DIR.mkdir(exist_ok=True)

USERS_DB = {
    "GroupXyz": {
        "username": "Admin",
        "password_hash": hashlib.sha256("Password".encode()).hexdigest()
    }
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
    
    cert_file = Path("/etc/letsencrypt/live/downloader.groupxyz.me/fullchain.pem")
    key_file = Path("/etc/letsencrypt/live/downloader.groupxyz.me/privkey.pem")
    
    use_ssl = cert_file.exists() and key_file.exists()
    
    if use_ssl:
        print(f"Starting HTTPS server on https://0.0.0.0:8192")
        print(f"Using certificates: {cert_file} and {key_file}")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8192,
            ssl_keyfile=str(key_file),
            ssl_certfile=str(cert_file),
            reload=False
        )
    else:
        print("WARNING: SSL certificates not found!")
        print("Starting HTTP server on http://0.0.0.0:8192")
        print("\nTo enable HTTPS, place your Let's Encrypt certificates:")
        print(f"  - {cert_file}")
        print(f"  - {key_file}")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8192,
            reload=False
        )

