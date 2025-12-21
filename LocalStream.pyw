"""
LocalStream - Native Music Player
A high-quality music player with Spotify-like features
"""

import sys
import os
import csv
import json
import random
import subprocess
import threading
import hashlib
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QSlider, QLabel, 
                             QListWidget, QListWidgetItem, QLineEdit, QSplitter,
                             QFileDialog, QMessageBox, QFrame, QInputDialog, QMenu,
                             QDialog, QTextEdit, QProgressBar)
from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal, QUrl, QByteArray, QPoint, QMimeData, QThread, QObject
from PyQt6.QtGui import QIcon, QFont, QPalette, QColor, QPixmap, QPainter, QAction, QDrag
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
import mutagen
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC


class DownloadDialog(QDialog):
    """Dialog window with console output for downloads"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Downloading from Spotify")
        self.setModal(False)
        self.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(self)
        
        self.status_label = QLabel("Initializing download...")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)
        
        console_label = QLabel("Console Output:")
        console_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(console_label)
        
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid #3e3e3e;
            }
        """)
        layout.addWidget(self.console)
        
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn)
        
    def append_output(self, text):
        """Append text to console"""
        self.console.append(text)
        self.console.verticalScrollBar().setValue(
            self.console.verticalScrollBar().maximum()
        )
    
    def set_status(self, text):
        """Update status label"""
        self.status_label.setText(text)
    
    def set_progress_range(self, min_val, max_val):
        """Set progress bar range"""
        self.progress_bar.setRange(min_val, max_val)
    
    def set_progress_value(self, value):
        """Set progress bar value"""
        self.progress_bar.setValue(value)
    
    def enable_close(self):
        """Enable close button when done"""
        self.close_btn.setEnabled(True)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)


class SongInfoDialog(QDialog):
    """Dialog to display song information with a copy button"""
    def __init__(self, song_info_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Song Information")
        self.setMinimumSize(400, 250)
        
        layout = QVBoxLayout(self)
        
        self.text_label = QLabel(song_info_text)
        self.text_label.setTextFormat(Qt.TextFormat.RichText)
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.text_label)
        
        self.plain_text = song_info_text.replace('<b>', '').replace('</b>', '').replace('<br>', '\n')
        
        button_layout = QHBoxLayout()
        
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        button_layout.addWidget(self.copy_btn)
        
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
    
    def copy_to_clipboard(self):
        """Copy song info to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.plain_text)
        self.copy_btn.setText("Copied!")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy"))


class TranslationWorker(QObject):
    finished = pyqtSignal(list, str)
    
    def __init__(self, synced_lyrics, current_lyrics, target_language):
        super().__init__()
        self.synced_lyrics = synced_lyrics
        self.current_lyrics = current_lyrics
        self.target_language = target_language
    
    def run(self):
        try:
            from googletrans import Translator
            translator = Translator()
            
            if self.synced_lyrics:
                full_text = "\n".join([text for _, text in self.synced_lyrics])
                
                try:
                    result = translator.translate(full_text, dest=self.target_language)
                    translated_lines = result.text.split('\n')
                    
                    translated_synced = []
                    for i, (timestamp, _) in enumerate(self.synced_lyrics):
                        if i < len(translated_lines):
                            translated_synced.append((timestamp, translated_lines[i]))
                        else:
                            translated_synced.append((timestamp, self.synced_lyrics[i][1]))
                    
                    self.finished.emit(translated_synced, "")
                except Exception as e:
                    print(f"Translation error: {e}")
                    self.finished.emit([], "")
            
            elif self.current_lyrics:
                try:
                    result = translator.translate(self.current_lyrics, dest=self.target_language)
                    self.finished.emit([], result.text)
                except Exception as e:
                    print(f"Translation error: {e}")
                    self.finished.emit([], "")
            else:
                self.finished.emit([], "")
                
        except Exception as e:
            print(f"Translation error: {e}")
            import traceback
            traceback.print_exc()
            self.finished.emit([], "")


class DownloadWorker(QObject):
    """Worker for downloading in separate thread"""
    output = pyqtSignal(str)
    status = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(bool, str, list)
    
    def __init__(self, url, download_dir):
        super().__init__()
        self.url = url
        self.download_dir = download_dir
        self.should_stop = False
    
    def run(self):
        """Run download process"""
        try:
            self.status.emit("Starting download...")
            self.output.emit(f"Download directory: {self.download_dir}\n")
            self.output.emit(f"Spotify URL: {self.url}\n")
            self.output.emit("-" * 60 + "\n\n")
            
            existing_files = set(Path(self.download_dir).glob("*.mp3"))
            
            cmd = [
                sys.executable,
                "-m",
                "spotdl",
                "download",
                self.url,
                "--output", str(self.download_dir),
                "--format", "mp3",
                "--bitrate", "320k",
                "--print-errors",
                "--simple-tui"
            ]
            
            self.output.emit(f"Running: {' '.join(cmd)}\n\n")
            
            import os
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            
            creation_flags = 0
            if sys.platform == 'win32':
                creation_flags = 0x08000000 
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=0,
                universal_newlines=True,
                env=env,
                creationflags=creation_flags
            )
            
            import time
            while True:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue
                    
                if self.should_stop:
                    process.terminate()
                    self.finished.emit(False, "Cancelled by user", [])
                    return
                    
                self.output.emit(line.rstrip())
            
            process.wait()
            
            if process.returncode == 0:
                self.status.emit("Download complete! Loading songs...")
                self.output.emit("\n" + "-" * 60 + "\n")
                self.output.emit("Download completed successfully!\n")
                self.output.emit("Loading song metadata...\n\n")
                
                songs = []
                all_mp3_files = set(Path(self.download_dir).glob("*.mp3"))
                mp3_files = list(all_mp3_files - existing_files)
                mp3_files = list(all_mp3_files - existing_files)
                
                for i, file in enumerate(mp3_files):
                    try:
                        self.output.emit(f"Loading: {file.name}\n")
                        audio = MP3(file)
                        duration = int(audio.info.length)
                        
                        title = file.stem
                        artist = "Unknown Artist"
                        album = "Unknown Album"
                        
                        if audio.tags:
                            title = str(audio.tags.get("TIT2", title))
                            artist = str(audio.tags.get("TPE1", artist))
                            album = str(audio.tags.get("TALB", album))
                        
                        album_art_data = None
                        try:
                            if audio.tags:
                                for tag in audio.tags.values():
                                    if hasattr(tag, 'mime') and tag.mime.startswith('image/'):
                                        album_art_data = tag.data
                                        break
                        except:
                            pass
                        
                        song_info = {
                            "title": title,
                            "artist": artist,
                            "album": album,
                            "duration": duration,
                            "path": str(file),
                            "filename": file.name,
                            "album_art": album_art_data
                        }
                        songs.append(song_info)
                    except Exception as e:
                        self.output.emit(f"Error loading {file.name}: {e}\n")
                
                self.output.emit(f"\nSuccessfully loaded {len(songs)} songs!\n")
                self.finished.emit(True, "", songs)
            else:
                self.finished.emit(False, "Download process failed", [])
        except Exception as e:
            self.finished.emit(False, str(e), [])
    
    def stop(self):
        """Stop the download"""
        self.should_stop = True


class MusicPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LocalStream - Your Music Library")
        self.setGeometry(100, 100, 1400, 800)
        
        self.create_icons()
        
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.7)
        
        self.music_folder = Path(__file__).parent / "Music"
        self.current_playlist = []
        self.current_playlist_name = None
        self.current_index = -1
        self.is_playing = False
        self.is_shuffle = False
        self.repeat_mode = 0
        self.queue = []
        self.play_history = []
        
        self.playlists = {}
        self.playlists_file = Path(__file__).parent / "playlists.json"
        
        self.settings_file = Path(__file__).parent / "settings.json"
        
        self.active_downloads = []
        
        self.current_lyrics = ""
        self.lyrics_visible = False
        self.synced_lyrics = []
        self.current_lyric_index = -1
        self.translation_language = "en" 
        self.original_lyrics = ""
        self.original_synced_lyrics = []
        self.translation_enabled = False
        self.translator = None
        
        self.server_url = ""
        self.server_username = ""
        self.server_password = ""
        self.auto_sync_enabled = False
        self.auto_sync_interval = 300000
        self.last_playlists_hash = None
        
        self.setup_ui()
        self.apply_dark_theme()
        
        self.load_settings()
        
        self.load_music_library()
        self.load_playlists()
        self.refresh_playlist_sidebar()
  
        self.current_playlist_name = None
        self.view_label.setText("Your Library")
        self.display_songs(self.all_songs)
        
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(self.update_duration)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_ui)
        self.update_timer.start(100)
        
        self.auto_sync_timer = QTimer()
        self.auto_sync_timer.timeout.connect(self.auto_sync_check)
        if self.auto_sync_enabled and self.server_url:
            self.auto_sync_timer.start(self.auto_sync_interval)
    
    def create_icons(self):
        """Create SVG icons for the UI"""
        self.icons = {}
        
        play_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>'''
        
        pause_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/></svg>'''
        
        next_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 4l10 8-10 8V4zm12 0v16h2V4h-2z"/></svg>'''
        
        prev_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M18 4v16l-10-8 10-8zM6 4h2v16H6V4z"/></svg>'''
        
        shuffle_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M10.59 9.17L5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41l-1.41 1.41 3.13 3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z"/></svg>'''
        
        repeat_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/></svg>'''
        
        repeat_one_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4zm-6-2h2V9h-2v2h-1v2h1v4z"/></svg>'''
        
        volume_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>'''
        
        search_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>'''
        
        home_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>'''
        
        library_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-1 9H9V9h10v2zm-4 4H9v-2h6v2zm4-8H9V5h10v2z"/></svg>'''
        
        playlist_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M15 6H3v2h12V6zm0 4H3v2h12v-2zM3 16h8v-2H3v2zM17 6v8.18c-.31-.11-.65-.18-1-.18-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3V8h3V6h-5z"/></svg>'''
        
        microphone_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>'''
        
        folder_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>'''
        
        music_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>'''
        
        self.icons = {
            'play': self.svg_to_icon(play_svg, 20, "#000000"),
            'pause': self.svg_to_icon(pause_svg, 20, "#000000"),
            'next': self.svg_to_icon(next_svg, 20, "#b3b3b3"),
            'prev': self.svg_to_icon(prev_svg, 20, "#b3b3b3"),
            'shuffle': self.svg_to_icon(shuffle_svg, 20, "#b3b3b3"),
            'repeat': self.svg_to_icon(repeat_svg, 20, "#b3b3b3"),
            'repeat_one': self.svg_to_icon(repeat_one_svg, 20, "#b3b3b3"),
            'volume': self.svg_to_icon(volume_svg, 18, "#b3b3b3"),
            'search': self.svg_to_icon(search_svg, 18, "#b3b3b3"),
            'home': self.svg_to_icon(home_svg, 18, "#b3b3b3"),
            'library': self.svg_to_icon(library_svg, 18, "#b3b3b3"),
            'playlist': self.svg_to_icon(playlist_svg, 18, "#b3b3b3"),
            'microphone': self.svg_to_icon(microphone_svg, 18, "#b3b3b3"),
            'folder': self.svg_to_icon(folder_svg, 18, "#b3b3b3"),
            'music': self.svg_to_icon(music_svg, 18, "#b3b3b3"),
        }
    
    def svg_to_icon(self, svg_string, size, color="#b3b3b3"):
        """Convert SVG string to QIcon with specified color"""
        svg_string = svg_string.replace('fill="currentColor"', f'fill="{color}"')
        
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        renderer = QSvgRenderer(QByteArray(svg_string.encode()))
        renderer.render(painter)
        painter.end()
        
        return QIcon(pixmap)
    
    def setup_ui(self):
        """Create the main UI layout"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        sidebar = self.create_sidebar()
        splitter.addWidget(sidebar)
        
        main_content = self.create_main_content()
        splitter.addWidget(main_content)
        
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 1150])
        
        main_layout.addWidget(splitter)
        
        player_control = self.create_player_controls()
        main_layout.addWidget(player_control)
    
    def create_sidebar(self):
        """Create the left sidebar with navigation"""
        sidebar = QFrame()
        sidebar.setMaximumWidth(250)
        sidebar.setStyleSheet("background-color: #000000; border-right: 1px solid #282828;")
        
        layout = QVBoxLayout(sidebar)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 20, 10, 10)
        
        title = QLabel("LocalStream")
        title.setStyleSheet("color: #1DB954; font-size: 28px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)
        
        self.nav_buttons = {}
        nav_items = [
            ("Home", "home", self.icons['home']),
            ("Search", "search", self.icons['search']),
            ("Library", "library", self.icons['library']),
        ]
        
        for text, key, icon in nav_items:
            btn = QPushButton(icon, f"  {text}")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #b3b3b3;
                    text-align: left;
                    padding: 10px 15px;
                    border: none;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    color: #ffffff;
                    background-color: #282828;
                }
                QPushButton:pressed {
                    background-color: #181818;
                }
            """)
            btn.setIconSize(QSize(20, 20))
            btn.clicked.connect(lambda checked, k=key: self.switch_view(k))
            layout.addWidget(btn)
            self.nav_buttons[key] = btn
        
        layout.addSpacing(20)
        
        playlists_label = QLabel("PLAYLISTS")
        playlists_label.setStyleSheet("color: #b3b3b3; font-size: 12px; font-weight: bold; padding: 10px;")
        layout.addWidget(playlists_label)
        
        self.create_playlist_btn = QPushButton("+ Create Playlist")
        self.create_playlist_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #b3b3b3;
                text-align: left;
                padding: 8px 15px;
                border: none;
                font-size: 13px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.create_playlist_btn.clicked.connect(self.create_new_playlist)
        layout.addWidget(self.create_playlist_btn)
        
        self.import_playlist_btn = QPushButton(self.icons['folder'], " Import Folder")
        self.import_playlist_btn.setIconSize(QSize(18, 18))
        self.import_playlist_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #b3b3b3;
                text-align: left;
                padding: 8px 15px;
                border: none;
                font-size: 13px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.import_playlist_btn.clicked.connect(self.import_playlist_from_folder)
        layout.addWidget(self.import_playlist_btn)
        
        self.import_spotify_btn = QPushButton(self.icons['music'], " Import from Spotify")
        self.import_spotify_btn.setIconSize(QSize(18, 18))
        self.import_spotify_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #b3b3b3;
                text-align: left;
                padding: 8px 15px;
                border: none;
                font-size: 13px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.import_spotify_btn.clicked.connect(self.import_from_spotify)
        layout.addWidget(self.import_spotify_btn)
        
        self.playlist_list = QListWidget()
        self.playlist_list.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                color: #b3b3b3;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 8px 15px;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background-color: #282828;
                color: #ffffff;
            }
            QListWidget::item:selected {
                background-color: #282828;
                color: #ffffff;
            }
        """)
        self.playlist_list.itemClicked.connect(self.on_playlist_selected)
        self.playlist_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_list.customContextMenuRequested.connect(self.show_playlist_context_menu)
        self.playlist_list.setAcceptDrops(True)
        self.playlist_list.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        self.playlist_list.dragEnterEvent = self.playlist_drag_enter
        self.playlist_list.dropEvent = self.playlist_drop
        layout.addWidget(self.playlist_list)
        
        layout.addStretch()
        
        return sidebar
    
    def create_main_content(self):
        """Create the main content area"""
        main_widget = QWidget()
        main_widget.setStyleSheet("background-color: #121212;")
        
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search for songs, artists...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #242424;
                color: #ffffff;
                border: none;
                border-radius: 20px;
                padding: 12px 20px;
                font-size: 14px;
            }
            QLineEdit:focus {
                background-color: #2a2a2a;
            }
        """)
        self.search_input.textChanged.connect(self.on_search)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)
        
        layout.addSpacing(20)
        
        self.view_label = QLabel("Your Library")
        self.view_label.setStyleSheet("color: #ffffff; font-size: 32px; font-weight: bold;")
        layout.addWidget(self.view_label)
        
        layout.addSpacing(10)
        
        self.song_list = QListWidget()
        self.song_list.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                color: #b3b3b3;
            }
            QListWidget::item {
                border-bottom: 1px solid #1a1a1a;
                background-color: transparent;
            }
            QListWidget::item:hover {
                background-color: #282828;
            }
            QListWidget::item:selected {
                background-color: #3e3e3e;
            }
        """)
        self.song_list.itemDoubleClicked.connect(self.on_song_item_double_clicked)
        self.song_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.song_list.customContextMenuRequested.connect(self.show_song_context_menu)
        self.song_list.setDragEnabled(True)
        self.song_list.setAcceptDrops(True)
        self.song_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.song_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.song_list.model().rowsMoved.connect(self.on_songs_reordered)
        
        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.setStyleSheet("QSplitter::handle { background-color: #282828; }")
        content_splitter.addWidget(self.song_list)
        
        self.lyrics_panel = QTextEdit()
        self.lyrics_panel.setReadOnly(True)
        self.lyrics_panel.setStyleSheet("""
            QTextEdit {
                background-color: #121212;
                border-left: 1px solid #282828;
                color: #b3b3b3;
                font-size: 15px;
                line-height: 2.0;
                padding: 30px;
            }
        """)
        self.lyrics_panel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lyrics_panel.setVisible(self.lyrics_visible)
        content_splitter.addWidget(self.lyrics_panel)
        
        content_splitter.setStretchFactor(0, 3)
        content_splitter.setStretchFactor(1, 1)
        
        layout.addWidget(content_splitter, 1)
        
        return main_widget
    
    def create_player_controls(self):
        """Create the bottom player control bar"""
        player_widget = QFrame()
        player_widget.setFixedHeight(90)
        player_widget.setStyleSheet("background-color: #181818; border-top: 1px solid #282828;")
        
        layout = QVBoxLayout(player_widget)
        layout.setContentsMargins(15, 5, 15, 5)
        
        top_row = QHBoxLayout()
        
        now_playing = QHBoxLayout()
        self.album_art = QLabel()
        self.album_art.setFixedSize(56, 56)
        self.album_art.setStyleSheet("background-color: #282828; border-radius: 4px;")
        self.album_art.setScaledContents(True)
        now_playing.addWidget(self.album_art)
        
        track_info = QVBoxLayout()
        track_info.setSpacing(2)
        self.track_title = QLabel("No track playing")
        self.track_title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")
        self.track_artist = QLabel("")
        self.track_artist.setStyleSheet("color: #b3b3b3; font-size: 12px;")
        track_info.addWidget(self.track_title)
        track_info.addWidget(self.track_artist)
        now_playing.addLayout(track_info)
        now_playing.addStretch()
        
        top_row.addLayout(now_playing, 1)
        
        controls = QHBoxLayout()
        controls.setSpacing(15)
        
        self.shuffle_btn = QPushButton(self.icons['shuffle'], "")
        self.prev_btn = QPushButton(self.icons['prev'], "")
        self.play_btn = QPushButton(self.icons['play'], "")
        self.next_btn = QPushButton(self.icons['next'], "")
        self.repeat_btn = QPushButton(self.icons['repeat'], "")
        
        control_buttons = [self.shuffle_btn, self.prev_btn, self.play_btn, 
                          self.next_btn, self.repeat_btn]
        
        for btn in control_buttons:
            btn.setFixedSize(36, 36)
            btn.setIconSize(QSize(20, 20))
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #b3b3b3;
                    border: none;
                    border-radius: 18px;
                    font-size: 18px;
                }
                QPushButton:hover {
                    color: #ffffff;
                    background-color: #282828;
                }
                QPushButton:pressed {
                    background-color: #3e3e3e;
                }
            """)
            controls.addWidget(btn)
        
        self.play_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                border: none;
                border-radius: 18px;
            }
            QPushButton:hover {
                background-color: #1DB954;
            }
        """)
        self.play_btn.setIconSize(QSize(18, 18))
        
        self.shuffle_btn.clicked.connect(self.toggle_shuffle)
        self.prev_btn.clicked.connect(self.play_previous)
        self.play_btn.clicked.connect(self.toggle_play)
        self.next_btn.clicked.connect(self.play_next)
        self.repeat_btn.clicked.connect(self.toggle_repeat)
        
        top_row.addLayout(controls, 1)
        
        volume_layout = QHBoxLayout()
        volume_layout.addStretch()
        
        self.lyrics_btn = QPushButton(self.icons['microphone'], "")
        self.lyrics_btn.setFixedSize(32, 32)
        self.lyrics_btn.setIconSize(QSize(18, 18))
        self.lyrics_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #b3b3b3;
                border: none;
                border-radius: 16px;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: #282828;
            }
            QPushButton:pressed {
                background-color: #3e3e3e;
            }
        """)
        self.lyrics_btn.clicked.connect(self.toggle_lyrics)
        self.lyrics_btn.setToolTip("Toggle Lyrics")
        volume_layout.addWidget(self.lyrics_btn)
        
        translate_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12.87 15.07l-2.54-2.51.03-.03c1.74-1.94 2.98-4.17 3.71-6.53H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z"/></svg>'''
        self.translate_btn = QPushButton(self.svg_to_icon(translate_svg, 18, "#b3b3b3"), "")
        self.translate_btn.setFixedSize(32, 32)
        self.translate_btn.setIconSize(QSize(18, 18))
        self.translate_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #b3b3b3;
                border: none;
                border-radius: 16px;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: #282828;
            }
            QPushButton:pressed {
                background-color: #3e3e3e;
            }
        """)
        self.translate_btn.clicked.connect(self.open_translation_settings)
        self.translate_btn.setToolTip("Translation Settings")
        volume_layout.addWidget(self.translate_btn)
        
        volume_layout.addSpacing(15)
        
        volume_icon = QLabel()
        volume_icon.setPixmap(self.icons['volume'].pixmap(18, 18))
        volume_layout.addWidget(volume_icon)
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        self.volume_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #4d4d4d;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #1DB954;
            }
            QSlider::sub-page:horizontal {
                background: #1DB954;
                border-radius: 2px;
            }
        """)
        volume_layout.addWidget(self.volume_slider)
        
        top_row.addLayout(volume_layout, 1)
        layout.addLayout(top_row)
        
        progress_layout = QHBoxLayout()
        
        self.time_label = QLabel("0:00")
        self.time_label.setStyleSheet("color: #b3b3b3; font-size: 11px;")
        self.time_label.setFixedWidth(40)
        progress_layout.addWidget(self.time_label)
        
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.sliderMoved.connect(self.on_seek)
        self.progress_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #4d4d4d;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #1DB954;
            }
            QSlider::sub-page:horizontal {
                background: #ffffff;
                border-radius: 2px;
            }
        """)
        progress_layout.addWidget(self.progress_slider)
        
        self.duration_label = QLabel("0:00")
        self.duration_label.setStyleSheet("color: #b3b3b3; font-size: 11px;")
        self.duration_label.setFixedWidth(40)
        progress_layout.addWidget(self.duration_label)
        
        layout.addLayout(progress_layout)
        
        return player_widget
    
    def apply_dark_theme(self):
        """Apply Spotify-like dark theme"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #000000;
            }
            QScrollBar:vertical {
                background: #121212;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: #4d4d4d;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #5d5d5d;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
    
    def load_music_library(self):
        """Scan and load all music files from the folder"""
        self.all_songs = []
        
        if not self.music_folder.exists():
            QMessageBox.warning(self, "Music Folder Not Found", 
                              f"Could not find folder: {self.music_folder}")
            return
        
        for file in self.music_folder.glob("*.mp3"):
            try:
                audio = MP3(file)
                duration = int(audio.info.length)
                
                title = file.stem
                artist = "Unknown Artist"
                album = "Unknown Album"
                
                if audio.tags:
                    title = str(audio.tags.get("TIT2", title))
                    artist = str(audio.tags.get("TPE1", artist))
                    album = str(audio.tags.get("TALB", album))
                
                album_art_data = None
                try:
                    if audio.tags:
                        for tag in audio.tags.values():
                            if hasattr(tag, 'mime') and tag.mime.startswith('image/'):
                                album_art_data = tag.data
                                break
                except:
                    pass
                
                song_info = {
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "duration": duration,
                    "path": str(file),
                    "filename": file.name,
                    "album_art": album_art_data
                }
                self.all_songs.append(song_info)
            except Exception as e:
                print(f"Error loading {file.name}: {e}")
        
        self.all_songs.sort(key=lambda x: x["title"])
    
    def load_playlists(self):
        """Load playlists from JSON file"""
        if not self.playlists_file.exists():
            return
        
        try:
            with open(self.playlists_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            songs_by_path = {song["path"]: song for song in self.all_songs}
            
            for name, playlist_data in data.items():
                song_paths = playlist_data.get("song_paths", [])
                songs = []
                
                for path in song_paths:
                    if path in songs_by_path:
                        songs.append(songs_by_path[path])
                    elif Path(path).exists():
                        try:
                            audio = MP3(path)
                            duration = int(audio.info.length)
                            
                            title = Path(path).stem
                            artist = "Unknown Artist"
                            album = "Unknown Album"
                            album_art = None
                            
                            if hasattr(audio, 'tags') and audio.tags:
                                if 'TIT2' in audio.tags:
                                    title = str(audio.tags['TIT2'])
                                if 'TPE1' in audio.tags:
                                    artist = str(audio.tags['TPE1'])
                                if 'TALB' in audio.tags:
                                    album = str(audio.tags['TALB'])
                                
                                for tag in audio.tags.values():
                                    if isinstance(tag, APIC):
                                        album_art = tag.data
                                        break
                            
                            song = {
                                "path": path,
                                "title": title,
                                "artist": artist,
                                "album": album,
                                "duration": duration,
                                "album_art": album_art
                            }
                            songs.append(song)
                        except Exception as e:
                            print(f"Error loading song {path}: {e}")
                
                if songs:
                    self.playlists[name] = {
                        "songs": songs,
                        "created": playlist_data.get("created", "unknown"),
                        "persistent": playlist_data.get("persistent", False)
                    }
        except Exception as e:
            print(f"Error loading playlists: {e}")
    
    def save_playlists(self):
        """Save playlists to JSON file"""
        try:
            data = {}
            for name, playlist in self.playlists.items():
                data[name] = {
                    "song_paths": [song["path"] for song in playlist["songs"]],
                    "created": playlist.get("created", "unknown"),
                    "persistent": playlist.get("persistent", False)
                }
            
            with open(self.playlists_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
            if hasattr(self, 'last_playlists_hash'):
                self.last_playlists_hash = self.get_playlists_hash()
        except Exception as e:
            print(f"Error saving playlists: {e}")
    
    def refresh_playlist_sidebar(self):
        """Refresh the playlist list in sidebar"""
        self.playlist_list.clear()
        
        for name in sorted(self.playlists.keys()):
            playlist_item = QListWidgetItem(self.icons['playlist'], name)
            self.playlist_list.addItem(playlist_item)
    
    def create_new_playlist(self):
        """Create a new empty playlist"""
        name, ok = QInputDialog.getText(self, "Create Playlist", "Playlist name:")
        
        if ok and name:
            if name in self.playlists:
                QMessageBox.warning(self, "Playlist Exists", f"A playlist named '{name}' already exists.")
                return
            
            self.playlists[name] = {
                "songs": [],
                "created": "user",
                "persistent": False
            }
            self.save_playlists()
            self.refresh_playlist_sidebar()
            QMessageBox.information(self, "Playlist Created", f"Playlist '{name}' created successfully!")
    
    def import_playlist_from_folder(self):
        """Import a playlist from a folder containing MP3 files"""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder with MP3 Files")
        
        if not folder:
            return
        
        folder_path = Path(folder)
        folder_name = folder_path.name
        
        name, ok = QInputDialog.getText(self, "Import Playlist", 
                                       "Playlist name:", text=folder_name)
        
        if not ok or not name:
            return
        
        if name in self.playlists:
            reply = QMessageBox.question(self, "Playlist Exists", 
                                        f"A playlist named '{name}' already exists. Replace it?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return
        
        songs = []
        mp3_files = list(folder_path.glob("*.mp3"))
        
        for file in mp3_files:
            try:
                audio = MP3(file)
                duration = int(audio.info.length)
                
                title = file.stem
                artist = "Unknown Artist"
                album = "Unknown Album"
                
                if audio.tags:
                    title = str(audio.tags.get("TIT2", title))
                    artist = str(audio.tags.get("TPE1", artist))
                    album = str(audio.tags.get("TALB", album))
                
                album_art_data = None
                try:
                    if audio.tags:
                        for tag in audio.tags.values():
                            if hasattr(tag, 'mime') and tag.mime.startswith('image/'):
                                album_art_data = tag.data
                                break
                except:
                    pass
                
                song_info = {
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "duration": duration,
                    "path": str(file),
                    "filename": file.name,
                    "album_art": album_art_data
                }
                songs.append(song_info)
            except Exception as e:
                print(f"Error loading {file.name}: {e}")
        
        if not songs:
            QMessageBox.warning(self, "No Songs Found", "No MP3 files found in the selected folder.")
            return
        
        songs.sort(key=lambda x: x["filename"])
        
        for song in songs:
            if song["path"] not in [s["path"] for s in self.all_songs]:
                self.all_songs.append(song)
        
        self.playlists[name] = {
            "songs": songs,
            "created": "imported",
            "persistent": False
        }
        self.save_playlists()
        self.refresh_playlist_sidebar()
        
        QMessageBox.information(self, "Import Complete", 
                               f"Imported {len(songs)} songs into playlist '{name}'!")
    
    def import_from_spotify(self):
        """Import songs from Spotify URL using spotdl"""
        url, ok = QInputDialog.getText(self, "Import from Spotify", 
                                       "Enter Spotify URL (song, album, or playlist):")
        
        if not ok or not url:
            return
        
        if not ("spotify.com" in url or "spotify:" in url):
            QMessageBox.warning(self, "Invalid URL", "Please enter a valid Spotify URL.")
            return
        
        name, ok = QInputDialog.getText(self, "Playlist Name", 
                                       "Enter name for the playlist:")
        
        if not ok or not name:
            return
        
        try:
            subprocess.run([sys.executable, "-m", "spotdl", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            reply = QMessageBox.question(self, "spotdl Not Found", 
                                        "spotdl is not installed. Install it now?\n\n"
                                        "This will run: pip install spotdl",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                install_dialog = DownloadDialog(None)
                install_dialog.setWindowTitle("Installing spotdl")
                install_dialog.set_status("Installing spotdl...")
                install_dialog.show()
                
                def install_thread():
                    try:
                        install_dialog.append_output("Running: pip install spotdl\n\n")
                        process = subprocess.Popen(
                            [sys.executable, "-m", "pip", "install", "spotdl"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, universal_newlines=True
                        )
                        
                        for line in process.stdout:
                            install_dialog.append_output(line.rstrip())
                        
                        process.wait()
                        
                        if process.returncode == 0:
                            install_dialog.set_status("Installation complete!")
                            install_dialog.append_output("\n✓ spotdl installed successfully!\n")
                        else:
                            install_dialog.set_status("Installation failed!")
                            install_dialog.append_output("\n✗ Installation failed!\n")
                        
                        install_dialog.enable_close()
                    except Exception as e:
                        install_dialog.set_status("Installation failed!")
                        install_dialog.append_output(f"\n✗ Error: {e}\n")
                        install_dialog.enable_close()
                
                thread = threading.Thread(target=install_thread, daemon=True)
                thread.start()
                
                result = install_dialog.exec()
                
                try:
                    subprocess.run([sys.executable, "-m", "spotdl", "--version"], capture_output=True, check=True)
                except:
                    QMessageBox.critical(self, "Installation Failed", 
                                       "spotdl installation failed. Please install manually.")
                    return
            else:
                return
        
        download_dir = self.music_folder / name
        download_dir.mkdir(exist_ok=True)
        
        dialog = DownloadDialog(None)
        dialog.show()
        
        worker = DownloadWorker(url, download_dir)
        thread = QThread()
        worker.moveToThread(thread)
        
        download_data = {
            'worker': worker,
            'thread': thread,
            'dialog': dialog,
            'name': name
        }
        self.active_downloads.append(download_data)
        
        worker.output.connect(dialog.append_output)
        worker.status.connect(dialog.set_status)
        worker.progress.connect(lambda min_v, max_v: dialog.set_progress_range(min_v, max_v))
        
        def on_finished(success, error_msg, songs):
            if success:
                dialog.set_status(f"✓ Complete! Imported {len(songs)} songs")
                
                for song in songs:
                    if song["path"] not in [s["path"] for s in self.all_songs]:
                        self.all_songs.append(song)
                
                self.playlists[name] = {
                    "songs": songs,
                    "created": "imported",
                    "persistent": True
                }
                self.save_playlists()
                self.refresh_playlist_sidebar()
                
                QMessageBox.information(None, "Import Complete", 
                                      f"Downloaded and imported {len(songs)} songs into playlist '{name}'!")
            else:
                dialog.set_status(f"✗ Failed: {error_msg}")
                QMessageBox.critical(None, "Download Failed", 
                                   f"Failed to download from Spotify:\n\n{error_msg}")
            
            dialog.enable_close()
            thread.quit()
            thread.wait()
            
            self.active_downloads = [d for d in self.active_downloads if d['thread'] != thread]
        
        worker.finished.connect(on_finished)
        thread.started.connect(worker.run)
        
        thread.start()
    
    def import_spotify_to_playlist(self, playlist_name):
        """Import songs from Spotify URL into an existing playlist"""
        url, ok = QInputDialog.getText(self, "Import from Spotify", 
                                       f"Enter Spotify URL to add to '{playlist_name}':")
        
        if not ok or not url:
            return
        
        if not ("spotify.com" in url or "spotify:" in url):
            QMessageBox.warning(self, "Invalid URL", "Please enter a valid Spotify URL.")
            return
        
        try:
            subprocess.run([sys.executable, "-m", "spotdl", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            QMessageBox.critical(self, "spotdl Not Found", 
                               "spotdl is not installed. Please use the main 'Import from Spotify' option first to install it.")
            return
        
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
                capture_output=True, text=True, check=True, timeout=10
            )
            outdated = json.loads(result.stdout)
            spotdl_outdated = any(pkg["name"].lower() == "spotdl" for pkg in outdated)
            
            if spotdl_outdated:
                update_dialog = DownloadDialog(None)
                update_dialog.setWindowTitle("Updating spotdl")
                update_dialog.set_status("Updating spotdl to latest version...")
                update_dialog.show()
                
                def update_thread():
                    try:
                        update_dialog.append_output("spotdl update available, upgrading...\n\n")
                        
                        creation_flags = 0
                        if sys.platform == 'win32':
                            creation_flags = 0x08000000
                        
                        process = subprocess.Popen(
                            [sys.executable, "-m", "pip", "install", "--upgrade", "spotdl"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, universal_newlines=True,
                            creationflags=creation_flags
                        )
                        
                        for line in process.stdout:
                            update_dialog.append_output(line.rstrip())
                        
                        process.wait()
                        
                        if process.returncode == 0:
                            update_dialog.set_status("Update complete!")
                            update_dialog.append_output("\n✓ spotdl updated successfully!\n")
                        else:
                            update_dialog.set_status("Update failed!")
                            update_dialog.append_output("\n✗ Update failed, continuing with current version.\n")
                        
                        update_dialog.enable_close()
                    except Exception as e:
                        update_dialog.set_status("Update failed!")
                        update_dialog.append_output(f"\n✗ Error: {e}\n")
                        update_dialog.enable_close()
                
                thread = threading.Thread(target=update_thread, daemon=True)
                thread.start()
                update_dialog.exec()
        except Exception:
            pass 
        
        if playlist_name in self.playlists and self.playlists[playlist_name]["songs"]:
            first_song_dir = Path(self.playlists[playlist_name]["songs"][0]["path"]).parent
            download_dir = first_song_dir
        else:
            download_dir = self.music_folder
        
        download_dir.mkdir(exist_ok=True)
        
        dialog = DownloadDialog(None)
        dialog.show()
        
        worker = DownloadWorker(url, download_dir)
        thread = QThread()
        worker.moveToThread(thread)
        
        download_data = {
            'worker': worker,
            'thread': thread,
            'dialog': dialog,
            'name': playlist_name
        }
        self.active_downloads.append(download_data)
        
        worker.output.connect(dialog.append_output)
        worker.status.connect(dialog.set_status)
        worker.progress.connect(lambda min_v, max_v: dialog.set_progress_range(min_v, max_v))
        
        def on_finished(success, error_msg, songs):
            if success:
                dialog.set_status(f"✓ Complete! Imported {len(songs)} songs")
                
                existing_paths = {song["path"] for song in self.playlists[playlist_name]["songs"]}
                added_count = 0
                
                for song in songs:
                    if song["path"] not in [s["path"] for s in self.all_songs]:
                        self.all_songs.append(song)
                    
                    if song["path"] not in existing_paths:
                        self.playlists[playlist_name]["songs"].append(song)
                        added_count += 1
                
                self.save_playlists()
                
                if self.current_playlist_name == playlist_name:
                    self.display_songs(self.playlists[playlist_name]["songs"])
                
                QMessageBox.information(None, "Import Complete", 
                                      f"Added {added_count} new songs to playlist '{playlist_name}'!\n"
                                      f"Skipped {len(songs) - added_count} duplicates.")
            else:
                dialog.set_status(f"✗ Failed: {error_msg}")
                QMessageBox.critical(None, "Download Failed", 
                                   f"Failed to download from Spotify:\n\n{error_msg}")
            
            dialog.enable_close()
            thread.quit()
            thread.wait()
            
            self.active_downloads = [d for d in self.active_downloads if d['thread'] != thread]
        
        worker.finished.connect(on_finished)
        thread.started.connect(worker.run)
        
        thread.start()
    
    def playlist_drag_enter(self, event):
        """Handle drag enter event for playlist list"""
        if event.mimeData().hasFormat("application/x-song-index"):
            event.acceptProposedAction()
    
    def playlist_drop(self, event):
        """Handle drop event on playlist list"""
        if not event.mimeData().hasFormat("application/x-song-index"):
            return
        
        item = self.playlist_list.itemAt(event.position().toPoint())
        if not item:
            return
        
        playlist_name = item.text()
        
        song_index = int(event.mimeData().data("application/x-song-index").data().decode())
        if song_index < 0 or song_index >= len(self.current_playlist):
            return
        
        song = self.current_playlist[song_index]
        
        self.add_song_to_playlist(playlist_name, song)
        event.acceptProposedAction()
    
    def on_songs_reordered(self):
        """Handle when songs are reordered via drag and drop"""
        if not self.current_playlist_name or self.current_playlist_name not in self.playlists:
            return
        
        playlist = self.playlists[self.current_playlist_name]
        
        new_order = []
        for i in range(self.song_list.count()):
            item = self.song_list.item(i)
            original_index = item.data(Qt.ItemDataRole.UserRole)
            if original_index < len(self.current_playlist):
                new_order.append(self.current_playlist[original_index])
        
        playlist["songs"] = new_order
        self.current_playlist = new_order
        self.save_playlists()
        
        for i in range(self.song_list.count()):
            item = self.song_list.item(i)
            item.setData(Qt.ItemDataRole.UserRole, i)
    
    def show_playlist_context_menu(self, position: QPoint):
        """Show context menu for playlist"""
        item = self.playlist_list.itemAt(position)
        if not item:
            return
        
        playlist_name = item.text()
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #282828;
                color: #ffffff;
                border: 1px solid #3e3e3e;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 20px;
            }
            QMenu::item:selected {
                background-color: #3e3e3e;
            }
        """)
        
        if not self.playlists[playlist_name].get("persistent", False):
            delete_action = QAction("Delete Playlist", self)
            delete_action.triggered.connect(lambda: self.delete_playlist(playlist_name))
            menu.addAction(delete_action)
        
        rename_action = QAction("Rename Playlist", self)
        rename_action.triggered.connect(lambda: self.rename_playlist(playlist_name))
        menu.addAction(rename_action)
        
        menu.addSeparator()
        
        import_action = QAction("Import Files...", self)
        import_action.triggered.connect(lambda: self.import_files_to_playlist(playlist_name))
        menu.addAction(import_action)
        
        import_spotify_action = QAction("Import from Spotify...", self)
        import_spotify_action.triggered.connect(lambda: self.import_spotify_to_playlist(playlist_name))
        menu.addAction(import_spotify_action)
        
        menu.exec(self.playlist_list.mapToGlobal(position))
    
    def delete_playlist(self, name):
        """Delete a playlist"""
        reply = QMessageBox.question(self, "Delete Playlist", 
                                     f"Are you sure you want to delete '{name}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            del self.playlists[name]
            self.save_playlists()
            self.refresh_playlist_sidebar()
            
            if self.current_playlist_name == name:
                self.view_label.setText("Your Library")
                self.display_songs(self.all_songs)
    
    def rename_playlist(self, old_name):
        """Rename a playlist"""
        new_name, ok = QInputDialog.getText(self, "Rename Playlist", 
                                            "New name:", text=old_name)
        
        if ok and new_name and new_name != old_name:
            if new_name in self.playlists:
                QMessageBox.warning(self, "Playlist Exists", 
                                   f"A playlist named '{new_name}' already exists.")
                return
            
            self.playlists[new_name] = self.playlists.pop(old_name)
            self.save_playlists()
            self.refresh_playlist_sidebar()
            
            if self.current_playlist_name == old_name:
                self.current_playlist_name = new_name
                self.view_label.setText(new_name)
    
    def show_song_context_menu(self, position: QPoint):
        """Show context menu for song"""
        item = self.song_list.itemAt(position)
        if not item:
            return
        
        index = item.data(Qt.ItemDataRole.UserRole)
        song = self.current_playlist[index]
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #282828;
                color: #ffffff;
                border: 1px solid #3e3e3e;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 20px;
            }
            QMenu::item:selected {
                background-color: #3e3e3e;
            }
            QMenu::separator {
                height: 1px;
                background: #3e3e3e;
                margin: 5px 0;
            }
        """)
        
        play_action = QAction("Play", self)
        play_action.triggered.connect(lambda: self.play_song(index))
        menu.addAction(play_action)
        
        play_next_action = QAction("Play Next", self)
        play_next_action.triggered.connect(lambda: self.add_to_queue(index, next=True))
        menu.addAction(play_next_action)
        
        add_queue_action = QAction("Add to Queue", self)
        add_queue_action.triggered.connect(lambda: self.add_to_queue(index))
        menu.addAction(add_queue_action)
        
        menu.addSeparator()
        
        add_to_menu = QMenu("Add to Playlist", self)
        add_to_menu.setStyleSheet(menu.styleSheet())
        
        for playlist_name in sorted(self.playlists.keys()):
            action = QAction(playlist_name, self)
            action.triggered.connect(lambda checked, name=playlist_name, s=song: self.add_song_to_playlist(name, s))
            add_to_menu.addAction(action)
        
        menu.addMenu(add_to_menu)
        
        if self.current_playlist_name and self.current_playlist_name in self.playlists:
            menu.addSeparator()
            remove_action = QAction("Remove from Playlist", self)
            remove_action.triggered.connect(lambda: self.remove_song_from_playlist(index))
            menu.addAction(remove_action)
        
        menu.addSeparator()
        
        lyrics_action = QAction("Show Lyrics", self)
        lyrics_action.triggered.connect(self.toggle_lyrics)
        menu.addAction(lyrics_action)
        
        translation_action = QAction("Translation Settings", self)
        translation_action.triggered.connect(self.open_translation_settings)
        menu.addAction(translation_action)
        
        menu.addSeparator()
        
        server_action = QAction("Sync to Server", self)
        server_action.triggered.connect(self.sync_to_server)
        menu.addAction(server_action)
        
        server_settings_action = QAction("Server Settings", self)
        server_settings_action.triggered.connect(self.open_server_settings)
        menu.addAction(server_settings_action)
        
        menu.addSeparator()
        
        info_action = QAction("Song Info", self)
        info_action.triggered.connect(lambda: self.show_song_info(song))
        menu.addAction(info_action)
        
        menu.exec(self.song_list.mapToGlobal(position))
    
    def add_to_queue(self, index, next=False):
        """Add song to play queue"""
        if next:
            self.queue.insert(0, index)
            QMessageBox.information(self, "Added to Queue", "Song will play next!")
        else:
            self.queue.append(index)
            QMessageBox.information(self, "Added to Queue", f"Song added to queue ({len(self.queue)} songs)")
    
    def show_song_info(self, song):
        """Show detailed song information"""
        info = f"""
            <b>Title:</b> {song['title']}<br>
            <b>Artist:</b> {song['artist']}<br>
            <b>Album:</b> {song['album']}<br>
            <b>Duration:</b> {self.format_time(song['duration'])}<br>
            <b>File:</b> {song['filename']}<br>
            <b>Path:</b> {song['path']}
        """
        dialog = SongInfoDialog(info, self)
        dialog.exec()
    
    def add_song_to_playlist(self, playlist_name, song):
        """Add a song to a playlist"""
        if song not in self.playlists[playlist_name]["songs"]:
            self.playlists[playlist_name]["songs"].append(song)
            self.save_playlists()
            QMessageBox.information(self, "Added", f"Added to '{playlist_name}'")
        else:
            QMessageBox.information(self, "Already in Playlist", f"Song already in '{playlist_name}'")
    
    def import_files_to_playlist(self, playlist_name):
        """Import local MP3 files into an existing playlist"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select MP3 Files to Import",
            str(self.music_folder),
            "MP3 Files (*.mp3);;All Files (*.*)"
        )
        
        if not files:
            return
        
        added_count = 0
        duplicate_count = 0
        error_files = []
        
        existing_paths = {song["path"] for song in self.playlists[playlist_name]["songs"]}
        
        for file_path in files:
            try:
                if file_path in existing_paths:
                    duplicate_count += 1
                    print(f"Skipped duplicate: {file_path}")
                    continue
                
                audio = MP3(file_path)
                duration = int(audio.info.length)
                
                title = Path(file_path).stem
                artist = "Unknown Artist"
                album = "Unknown Album"
                album_art = None
                
                if hasattr(audio, 'tags') and audio.tags:
                    if 'TIT2' in audio.tags:
                        title = str(audio.tags['TIT2'])
                    if 'TPE1' in audio.tags:
                        artist = str(audio.tags['TPE1'])
                    if 'TALB' in audio.tags:
                        album = str(audio.tags['TALB'])
                    
                    for tag in audio.tags.values():
                        if isinstance(tag, APIC):
                            album_art = tag.data
                            break
                
                song = {
                    "path": file_path,
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "duration": duration,
                    "album_art": album_art
                }
                
                self.playlists[playlist_name]["songs"].append(song)
                added_count += 1
                print(f"Added: {title} - {artist}")
                    
            except Exception as e:
                error_msg = f"{Path(file_path).name}: {str(e)}"
                error_files.append(error_msg)
                print(f"Error importing {file_path}: {e}")
                import traceback
                traceback.print_exc()
        
        if added_count > 0:
            self.save_playlists()
            
            if self.current_playlist_name == playlist_name:
                self.display_songs(self.playlists[playlist_name]["songs"])
        
        message = f"Import complete!\n\nAdded: {added_count}\nDuplicates skipped: {duplicate_count}"
        
        if error_files:
            message += f"\nErrors: {len(error_files)}\n\n"
            message += "\n".join(error_files[:10])
            if len(error_files) > 10:
                message += f"\n... and {len(error_files) - 10} more errors"
        
        QMessageBox.information(self, "Import Files", message)
    
    def remove_song_from_playlist(self, index):
        """Remove a song from current playlist"""
        if not self.current_playlist_name or self.current_playlist_name not in self.playlists:
            return
        
        playlist = self.playlists[self.current_playlist_name]
        
        song = self.current_playlist[index]
        playlist["songs"].remove(song)
        self.save_playlists()
        
        self.display_songs(playlist["songs"])
        self.current_playlist_name = self.current_playlist_name
    
    def fuzzy_match(self, str1, str2):
        """Simple fuzzy matching for song names"""
        str1 = str1.lower().strip()
        str2 = str2.lower().strip()
        
        for char in ['-', '_', '(', ')', '[', ']', '.mp3', ',']:
            str1 = str1.replace(char, ' ')
            str2 = str2.replace(char, ' ')
        
        words1 = set(str1.split())
        words2 = set(str2.split())
        
        if not words1 or not words2:
            return False
        
        matches = len(words1.intersection(words2))
        return matches / max(len(words1), len(words2)) > 0.4
    
    def display_songs(self, songs):
        """Display songs in the list"""
        self.current_playlist = songs
        self.song_list.clear()
        
        for i, song in enumerate(songs):
            item = QListWidgetItem()
            
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(12)
            
            art_label = QLabel()
            art_label.setFixedSize(48, 48)
            
            if song.get("album_art"):
                pixmap = QPixmap()
                pixmap.loadFromData(song["album_art"])
                art_label.setPixmap(pixmap.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, 
                                                  Qt.TransformationMode.SmoothTransformation))
            else:
                art_label.setStyleSheet("background-color: #282828; border-radius: 4px;")
            
            layout.addWidget(art_label)
            
            info_layout = QVBoxLayout()
            info_layout.setSpacing(2)
            
            title_layout = QHBoxLayout()
            title_layout.setSpacing(8)
            
            track_num = QLabel(f"{i + 1:02d}")
            track_num.setStyleSheet("color: #b3b3b3; font-size: 12px; min-width: 25px;")
            title_layout.addWidget(track_num)
            
            title_label = QLabel(song["title"])
            title_label.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: 500;")
            title_layout.addWidget(title_label)
            title_layout.addStretch()
            
            info_layout.addLayout(title_layout)
            
            subtitle_label = QLabel(f"{song['artist']}  •  {self.format_time(song['duration'])}")
            subtitle_label.setStyleSheet("color: #b3b3b3; font-size: 12px;")
            info_layout.addWidget(subtitle_label)
            
            layout.addLayout(info_layout, 1)
            
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, i)
            
            self.song_list.addItem(item)
            self.song_list.setItemWidget(item, widget)
    
    def on_song_item_double_clicked(self, item):
        """Play song when double-clicked from list"""
        index = item.data(Qt.ItemDataRole.UserRole)
        self.play_song(index)
    
    def play_song(self, index):
        """Play a specific song from current playlist"""
        if 0 <= index < len(self.current_playlist):
            self.current_index = index
            song = self.current_playlist[index]
            
            self.player.setSource(QUrl.fromLocalFile(song["path"]))
            self.player.play()
            self.is_playing = True
            self.play_btn.setIcon(self.icons['pause'])
            
            self.track_title.setText(song["title"])
            self.track_artist.setText(song["artist"])
            
            if song.get("album_art"):
                pixmap = QPixmap()
                pixmap.loadFromData(song["album_art"])
                self.album_art.setPixmap(pixmap.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))
            else:
                self.album_art.clear()
                self.album_art.setStyleSheet("background-color: #282828; border-radius: 4px;")
            
            self.load_lyrics(song["path"])
            
            self.play_history.append(index)
            if len(self.play_history) > 50:
                self.play_history.pop(0)
            
            if 0 <= index < self.song_list.count():
                self.song_list.setCurrentRow(index)
    
    def toggle_play(self):
        """Toggle play/pause"""
        if self.current_index < 0 and self.current_playlist:
            self.play_song(0)
        elif self.is_playing:
            self.player.pause()
            self.is_playing = False
            self.play_btn.setIcon(self.icons['play'])
        else:
            self.player.play()
            self.is_playing = True
            self.play_btn.setIcon(self.icons['pause'])
    
    def play_next(self):
        """Play next song"""
        if not self.current_playlist:
            return
        
        if self.queue:
            next_index = self.queue.pop(0)
            self.play_song(next_index)
        elif self.is_shuffle:
            next_index = random.randint(0, len(self.current_playlist) - 1)
            self.play_song(next_index)
        else:
            next_index = (self.current_index + 1) % len(self.current_playlist)
            self.play_song(next_index)
    
    def play_previous(self):
        """Play previous song"""
        if not self.current_playlist:
            return
        
        if self.is_shuffle and len(self.play_history) > 1:
            self.play_history.pop()
            prev_index = self.play_history[-1]
            self.play_history.pop()
            self.play_song(prev_index)
        else:
            prev_index = (self.current_index - 1) % len(self.current_playlist)
            self.play_song(prev_index)
    
    def toggle_shuffle(self):
        """Toggle shuffle mode"""
        self.is_shuffle = not self.is_shuffle
        self.update_shuffle_button()
    
    def update_shuffle_button(self):
        """Update shuffle button appearance"""
        if self.is_shuffle:
            self.shuffle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #282828;
                    color: #1DB954;
                    border: none;
                    border-radius: 18px;
                }
                QPushButton:hover {
                    background-color: #3e3e3e;
                }
            """)
        else:
            self.shuffle_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #b3b3b3;
                    border: none;
                    border-radius: 18px;
                }
                QPushButton:hover {
                    color: #ffffff;
                    background-color: #282828;
                }
                QPushButton:pressed {
                    background-color: #3e3e3e;
                }
            """)
    
    def toggle_repeat(self):
        """Cycle through repeat modes"""
        self.repeat_mode = (self.repeat_mode + 1) % 3
        self.update_repeat_button()
    
    def toggle_lyrics(self):
        """Toggle lyrics panel visibility"""
        self.lyrics_visible = not self.lyrics_visible
        self.lyrics_panel.setVisible(self.lyrics_visible)
        
        if self.lyrics_visible:
            microphone_svg = '''<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>'''
            self.lyrics_btn.setIcon(self.svg_to_icon(microphone_svg, 18, "#1DB954"))
            self.lyrics_btn.setStyleSheet("""
                QPushButton {
                    background-color: #282828;
                    border: none;
                    border-radius: 16px;
                }
                QPushButton:hover {
                    background-color: #3e3e3e;
                }
            """)
        else:
            self.lyrics_btn.setIcon(self.icons['microphone'])
            self.lyrics_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #b3b3b3;
                    border: none;
                    border-radius: 16px;
                }
                QPushButton:hover {
                    color: #ffffff;
                    background-color: #282828;
                }
                QPushButton:pressed {
                    background-color: #3e3e3e;
                }
            """)
    
    def update_repeat_button(self):
        """Update repeat button icon and appearance"""
        if self.repeat_mode == 0:
            self.repeat_btn.setIcon(self.icons['repeat'])
            self.repeat_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #b3b3b3;
                    border: none;
                    border-radius: 18px;
                }
                QPushButton:hover {
                    color: #ffffff;
                    background-color: #282828;
                }
                QPushButton:pressed {
                    background-color: #3e3e3e;
                }
            """)
        elif self.repeat_mode == 1:
            self.repeat_btn.setIcon(self.icons['repeat'])
            self.repeat_btn.setStyleSheet("""
                QPushButton {
                    background-color: #282828;
                    color: #1DB954;
                    border: none;
                    border-radius: 18px;
                }
                QPushButton:hover {
                    background-color: #3e3e3e;
                }
            """)
        else:
            self.repeat_btn.setIcon(self.icons['repeat_one'])
            self.repeat_btn.setStyleSheet("""
                QPushButton {
                    background-color: #282828;
                    color: #1DB954;
                    border: none;
                    border-radius: 18px;
                }
                QPushButton:hover {
                    background-color: #3e3e3e;
                }
            """)
    
    def on_media_status_changed(self, status):
        """Handle when media finishes"""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.repeat_mode == 2:
                self.play_song(self.current_index)
            elif self.repeat_mode == 1 or self.is_shuffle:
                self.play_next()
            elif self.current_index < len(self.current_playlist) - 1:
                self.play_next()
            else:
                self.is_playing = False
                self.play_btn.setIcon(self.icons['play'])
    
    def update_position(self, position):
        """Update progress bar position"""
        if not self.progress_slider.isSliderDown():
            self.progress_slider.setValue(position)
        self.time_label.setText(self.format_time(position // 1000))
    
    def update_duration(self, duration):
        """Update progress bar maximum"""
        self.progress_slider.setRange(0, duration)
        self.duration_label.setText(self.format_time(duration // 1000))
    
    def on_seek(self, position):
        """Handle seeking"""
        self.player.setPosition(position)
    
    def on_volume_changed(self, value):
        """Handle volume change"""
        volume = value / 100.0
        self.audio_output.setVolume(volume)
        self.save_settings()
    
    def load_lyrics(self, file_path):
        """Load and display lyrics from MP3 file or LRC file"""
        try:
            self.synced_lyrics = []
            self.current_lyric_index = -1
            lyrics = ""
            
            lrc_path = Path(file_path).with_suffix('.lrc')
            if lrc_path.exists():
                print(f"Found LRC file: {lrc_path}")
                lyrics = lrc_path.read_text(encoding='utf-8')
                if self.parse_lrc(lyrics):
                    print(f"Parsed {len(self.synced_lyrics)} synced lyrics lines")
                    self.original_synced_lyrics = self.synced_lyrics.copy()
                    self.translate_lyrics()
                    self.display_synced_lyrics()
                    return
            
            audio = MP3(file_path)
            if hasattr(audio, 'tags') and audio.tags:
                uslt_frames = audio.tags.getall('USLT')
                if uslt_frames:
                    lyrics = uslt_frames[0].text
                    if '[' in lyrics and ']' in lyrics and ':' in lyrics:
                        if self.parse_lrc(lyrics):
                            print(f"Parsed {len(self.synced_lyrics)} synced lyrics from USLT tags")
                            self.original_synced_lyrics = self.synced_lyrics.copy()
                            self.translate_lyrics()
                            self.display_synced_lyrics()
                            return
                
                if not lyrics:
                    for key in audio.tags.keys():
                        if 'lyric' in key.lower():
                            try:
                                tag_value = audio.tags.get(key)
                                if tag_value and hasattr(tag_value, 'text'):
                                    lyrics = '\n'.join(tag_value.text) if isinstance(tag_value.text, list) else str(tag_value.text)
                                    print(f"Found lyrics in tag: {key}")
                                    break
                            except:
                                pass
                
                if not lyrics:
                    sylt_frames = audio.tags.getall('SYLT')
                    if sylt_frames:
                        for text, timestamp in sylt_frames[0].text:
                            self.synced_lyrics.append((timestamp, text))
                        if self.synced_lyrics:
                            print(f"Found {len(self.synced_lyrics)} SYLT lyrics")
                            self.original_synced_lyrics = self.synced_lyrics.copy()
                            self.translate_lyrics()
                            self.display_synced_lyrics()
                            return
            
            if lyrics:
                self.current_lyrics = lyrics
                self.original_lyrics = lyrics
                self.translate_lyrics()
                formatted_lyrics = self.current_lyrics.replace('\n\n', '<br><br>').replace('\n', '<br>')
                translation_note = f' - Translated to {self.translation_language.upper()}' if self.translation_enabled else ''
                self.lyrics_panel.setHtml(f'<div style="text-align: center; color: #b3b3b3; line-height: 1.8;">{formatted_lyrics}<br><br><span style="color: #666666; font-size: 12px; font-style: italic;">Add a .lrc file with the same name for synced lyrics{translation_note}</span></div>')
                print("Displaying unsynced lyrics")
            else:
                self.current_lyrics = ""
                self.lyrics_panel.setHtml('<div style="text-align: center; color: #666666; font-style: italic;">No lyrics available for this track.<br><br>Add a .lrc file with the same name for synced lyrics.</div>')
                
        except Exception as e:
            print(f"Error loading lyrics: {e}")
            import traceback
            traceback.print_exc()
            self.current_lyrics = ""
            self.synced_lyrics = []
            self.lyrics_panel.setHtml('<div style="text-align: center; color: #666666; font-style: italic;">Could not load lyrics.</div>')
    
    def parse_lrc(self, lrc_text):
        """Parse LRC format lyrics"""
        import re
        self.synced_lyrics = []
        
        pattern = r'\[(\d+):(\d+\.?\d*)\](.*)'
        
        for line in lrc_text.split('\n'):
            match = re.match(pattern, line)
            if match:
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                text = match.group(3).strip()
                timestamp_ms = int((minutes * 60 + seconds) * 1000)
                if text:
                    self.synced_lyrics.append((timestamp_ms, text))
        
        self.synced_lyrics.sort(key=lambda x: x[0])
        return len(self.synced_lyrics) > 0
    
    def display_synced_lyrics(self):
        """Display synchronized lyrics with initial styling"""
        if not self.synced_lyrics:
            return
        
        html = '<div style="text-align: center; line-height: 2.5;">\n'
        for i, (_, text) in enumerate(self.synced_lyrics):
            html += f'<p id="lyric_{i}" style="color: #666666; margin: 10px 0; font-size: 15px;">{text}</p>\n'
        html += '</div>'
        
        self.lyrics_panel.setHtml(html)
    
    def update_lyrics_highlight(self, position_ms):
        """Update highlighted lyric line based on playback position"""
        if not self.synced_lyrics or not self.lyrics_visible:
            return
        
        current_index = -1
        for i, (timestamp, _) in enumerate(self.synced_lyrics):
            if timestamp <= position_ms:
                current_index = i
            else:
                break
        
        if current_index != self.current_lyric_index and current_index >= 0:
            self.current_lyric_index = current_index
            print(f"Highlighting lyric {current_index} at {position_ms}ms")
            
            html = '<div style="text-align: center; line-height: 2.5;">\n'
            for i, (_, text) in enumerate(self.synced_lyrics):
                if i == current_index:
                    html += f'<p id="lyric_{i}" style="color: #ffffff; font-weight: bold; font-size: 17px; margin: 10px 0; text-shadow: 0 0 10px rgba(29, 185, 84, 0.5);">{text}</p>\n'
                elif abs(i - current_index) <= 1:
                    html += f'<p id="lyric_{i}" style="color: #999999; margin: 10px 0; font-size: 15px;">{text}</p>\n'
                else:
                    html += f'<p id="lyric_{i}" style="color: #666666; margin: 10px 0; font-size: 15px;">{text}</p>\n'
            html += '</div>'
            
            self.lyrics_panel.setHtml(html)
            
            if current_index > 2:
                cursor = self.lyrics_panel.textCursor()
                scroll_position = int((current_index / len(self.synced_lyrics)) * self.lyrics_panel.verticalScrollBar().maximum())
                self.lyrics_panel.verticalScrollBar().setValue(scroll_position)
    
    def on_search(self, text):
        """Filter songs based on search"""
        if not text:
            self.display_songs(self.all_songs)
            return
        
        text = text.lower()
        filtered = [s for s in self.all_songs 
                   if text in s["title"].lower() or 
                      text in s["artist"].lower() or 
                      text in s["album"].lower()]
        self.display_songs(filtered)
    
    def on_playlist_selected(self, item):
        """Load selected playlist"""
        playlist_name = item.text()
        if playlist_name in self.playlists:
            self.current_playlist_name = playlist_name
            self.view_label.setText(playlist_name)
            songs = self.playlists[playlist_name]["songs"]
            self.display_songs(songs)
    
    def switch_view(self, view):
        """Switch between different views"""
        if view == "library":
            self.current_playlist_name = None
            self.view_label.setText("Your Library")
            self.display_songs(self.all_songs)
        elif view == "home":
            self.current_playlist_name = None
            self.view_label.setText("Home")
        elif view == "search":
            self.search_input.setFocus()
    
    def format_time(self, seconds):
        """Format seconds to MM:SS"""
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}:{secs:02d}"
    
    def translate_lyrics(self):
        if not self.translation_enabled:
            return
        
        try:
            worker = TranslationWorker(
                self.synced_lyrics.copy() if self.synced_lyrics else [],
                self.current_lyrics,
                self.translation_language
            )
            thread = QThread()
            worker.moveToThread(thread)
            
            worker.finished.connect(lambda synced, unsyncced: self.on_translation_complete(synced, unsyncced, thread, worker))
            thread.started.connect(worker.run)
            thread.start()
            
            if not hasattr(self, 'translation_threads'):
                self.translation_threads = []
            self.translation_threads.append((thread, worker))
        except Exception as e:
            print(f"Failed to start translation: {e}")
            import traceback
            traceback.print_exc()
    
    def on_translation_complete(self, translated_synced, translated_unsynced, thread, worker):
        try:
            if translated_synced:
                self.synced_lyrics = translated_synced
                self.display_synced_lyrics()
            elif translated_unsynced:
                self.current_lyrics = translated_unsynced
                formatted_lyrics = self.current_lyrics.replace('\n\n', '<br><br>').replace('\n', '<br>')
                self.lyrics_panel.setHtml(f'<div style="text-align: center; color: #b3b3b3; line-height: 1.8;">{formatted_lyrics}<br><br><span style="color: #666666; font-size: 12px; font-style: italic;">Translated to {self.translation_language}</span></div>')
            
            thread.quit()
            thread.wait()
            
            if hasattr(self, 'translation_threads'):
                self.translation_threads = [(t, w) for t, w in self.translation_threads if t != thread]
        except Exception as e:
            print(f"Translation complete error: {e}")
            import traceback
            traceback.print_exc()
    
    def toggle_translation(self):
        """Toggle lyrics translation"""
        self.translation_enabled = not self.translation_enabled
        self.save_settings()
        
        if self.translation_enabled:
            if self.current_index >= 0 and self.current_index < len(self.current_playlist):
                file_path = self.current_playlist[self.current_index]["path"]
                self.load_lyrics(file_path)
        else:
            self.synced_lyrics = self.original_synced_lyrics.copy()
            self.current_lyrics = self.original_lyrics
            if self.synced_lyrics:
                self.display_synced_lyrics()
            elif self.current_lyrics:
                formatted_lyrics = self.current_lyrics.replace('\n\n', '<br><br>').replace('\n', '<br>')
                self.lyrics_panel.setHtml(f'<div style="text-align: center; color: #b3b3b3; line-height: 1.8;">{formatted_lyrics}<br><br><span style="color: #666666; font-size: 12px; font-style: italic;">Add a .lrc file with the same name for synced lyrics</span></div>')
    
    def open_translation_settings(self):
        """Open translation settings dialog"""
        from PyQt6.QtWidgets import QComboBox, QCheckBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Translation Settings")
        dialog.setMinimumWidth(400)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #181818;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
            }
            QComboBox {
                background-color: #282828;
                color: #ffffff;
                border: 1px solid #3e3e3e;
                border-radius: 4px;
                padding: 8px;
                font-size: 14px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #ffffff;
            }
            QCheckBox {
                color: #ffffff;
                font-size: 14px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #3e3e3e;
                border-radius: 3px;
                background-color: #282828;
            }
            QCheckBox::indicator:checked {
                background-color: #1DB954;
                border-color: #1DB954;
            }
            QPushButton {
                background-color: #1DB954;
                color: #000000;
                border: none;
                border-radius: 20px;
                padding: 12px 32px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1ed760;
            }
        """)
        
        layout = QVBoxLayout()
        
        enable_check = QCheckBox("Enable Lyrics Translation")
        enable_check.setChecked(self.translation_enabled)
        layout.addWidget(enable_check)
        
        layout.addSpacing(10)
        
        lang_label = QLabel("Target Language:")
        layout.addWidget(lang_label)
        
        lang_combo = QComboBox()
        languages = {
            "English": "en",
            "Spanish": "es",
            "French": "fr",
            "German": "de",
            "Italian": "it",
            "Portuguese": "pt",
            "Russian": "ru",
            "Japanese": "ja",
            "Korean": "ko",
            "Chinese": "zh",
            "Arabic": "ar",
            "Dutch": "nl",
            "Polish": "pl",
            "Swedish": "sv",
            "Danish": "da",
            "Finnish": "fi",
            "Greek": "el",
            "Czech": "cs",
            "Romanian": "ro",
            "Bulgarian": "bg",
            "Hungarian": "hu",
            "Turkish": "tr",
            "Indonesian": "id"
        }
        
        for name, code in languages.items():
            lang_combo.addItem(name, code)
            if code == self.translation_language:
                lang_combo.setCurrentText(name)
        
        layout.addWidget(lang_combo)
        
        layout.addSpacing(20)
        
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: self.save_translation_settings(
            enable_check.isChecked(),
            lang_combo.currentData(),
            dialog
        ))
        layout.addWidget(save_btn)
        
        dialog.setLayout(layout)
        dialog.exec()
    
    def open_server_settings(self):
        """Open server sync settings dialog"""
        from PyQt6.QtWidgets import QCheckBox, QSpinBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Server Sync Settings")
        dialog.setMinimumWidth(500)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #181818;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
            }
            QLineEdit, QSpinBox {
                background-color: #282828;
                color: #ffffff;
                border: 1px solid #3e3e3e;
                border-radius: 4px;
                padding: 8px;
                font-size: 14px;
            }
            QCheckBox {
                color: #ffffff;
                font-size: 14px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #3e3e3e;
                border-radius: 3px;
                background-color: #282828;
            }
            QCheckBox::indicator:checked {
                background-color: #1DB954;
                border-color: #1DB954;
            }
            QPushButton {
                background-color: #1DB954;
                color: #000000;
                border: none;
                border-radius: 20px;
                padding: 12px 32px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1ed760;
            }
        """)
        
        layout = QVBoxLayout()
        
        url_label = QLabel("Server URL (e.g., https://your-domain.com:8443):")
        layout.addWidget(url_label)
        
        url_input = QLineEdit()
        url_input.setText(getattr(self, 'server_url', ''))
        url_input.setPlaceholderText("https://your-server.com:8443")
        layout.addWidget(url_input)
        
        layout.addSpacing(10)
        
        username_label = QLabel("Username:")
        layout.addWidget(username_label)
        
        username_input = QLineEdit()
        username_input.setText(getattr(self, 'server_username', ''))
        layout.addWidget(username_input)
        
        layout.addSpacing(10)
        
        password_label = QLabel("Password:")
        layout.addWidget(password_label)
        
        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        password_input.setText(getattr(self, 'server_password', ''))
        layout.addWidget(password_input)
        
        layout.addSpacing(20)
        
        auto_sync_check = QCheckBox("Enable Automatic Background Sync")
        auto_sync_check.setChecked(getattr(self, 'auto_sync_enabled', False))
        layout.addWidget(auto_sync_check)
        
        layout.addSpacing(10)
        
        interval_label = QLabel("Sync Interval (minutes):")
        layout.addWidget(interval_label)
        
        interval_spin = QSpinBox()
        interval_spin.setMinimum(1)
        interval_spin.setMaximum(1440) 
        interval_spin.setValue(getattr(self, 'auto_sync_interval', 300000) // 60000)
        layout.addWidget(interval_spin)
        
        layout.addSpacing(20)
        
        button_layout = QHBoxLayout()
        
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(lambda: self.test_server_connection(
            url_input.text(), username_input.text(), password_input.text()
        ))
        button_layout.addWidget(test_btn)
        
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: self.save_server_settings(
            url_input.text(), username_input.text(), password_input.text(), 
            auto_sync_check.isChecked(), interval_spin.value(), dialog
        ))
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
        
        dialog.setLayout(layout)
        dialog.exec()
    
    def test_server_connection(self, url, username, password):
        """Test connection to server"""
        if not url or not username or not password:
            QMessageBox.warning(self, "Error", "Please fill in all fields")
            return
        
        try:
            from server_sync import ServerSync
            sync = ServerSync(url, username, password)
            if sync.login():
                QMessageBox.information(self, "Success", "Connection successful!")
            else:
                QMessageBox.warning(self, "Error", "Login failed. Check credentials.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Connection failed: {e}")
    
    def save_server_settings(self, url, username, password, auto_sync, interval_minutes, dialog):
        """Save server settings"""
        self.server_url = url
        self.server_username = username
        self.server_password = password
        self.auto_sync_enabled = auto_sync
        self.auto_sync_interval = interval_minutes * 60000  
        self.save_settings()
        
        self.auto_sync_timer.stop()
        if self.auto_sync_enabled and self.server_url:
            self.auto_sync_timer.start(self.auto_sync_interval)
            self.last_playlists_hash = self.get_playlists_hash()
        
        dialog.accept()
        QMessageBox.information(self, "Saved", "Server settings saved!")
    
    def sync_to_server(self):
        """Sync playlists and music to server"""
        if not getattr(self, 'server_url', '') or not getattr(self, 'server_username', ''):
            result = QMessageBox.question(
                self, "Server Not Configured",
                "Server sync is not configured. Would you like to set it up now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if result == QMessageBox.StandardButton.Yes:
                self.open_server_settings()
                if not getattr(self, 'server_url', '') or not getattr(self, 'server_username', ''):
                    return
            else:
                return
        
        self.save_playlists()
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Syncing to Server")
        dialog.setModal(True)
        dialog.setMinimumSize(600, 400)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #181818;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
            }
            QProgressBar {
                border: 2px solid #282828;
                border-radius: 5px;
                text-align: center;
                background-color: #282828;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #1DB954;
            }
            QTextEdit {
                background-color: #282828;
                color: #ffffff;
                border: 1px solid #3e3e3e;
                border-radius: 4px;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        
        status_label = QLabel("Starting sync...")
        status_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(status_label)
        
        progress = QProgressBar()
        progress.setValue(0)
        layout.addWidget(progress)
        
        console_label = QLabel("Sync Log:")
        layout.addWidget(console_label)
        
        console = QTextEdit()
        console.setReadOnly(True)
        layout.addWidget(console)
        
        self._sync_cancelled = False
        
        def on_dialog_rejected():
            self._sync_cancelled = True
        
        dialog.rejected.connect(on_dialog_rejected)
        
        dialog.show()
        QApplication.processEvents()
        
        try:
            from server_sync import ServerSync
            
            console.append("Connecting to server...")
            QApplication.processEvents()
            
            if self._sync_cancelled:
                console.append("Cancelled by user")
                return
            
            sync = ServerSync(self.server_url, self.server_username, self.server_password)
            
            if not sync.login():
                console.append("❌ Login failed!")
                status_label.setText("Sync Failed")
                return
            
            console.append("✓ Connected successfully\n")
            QApplication.processEvents()
            
            if self._sync_cancelled:
                console.append("Cancelled by user")
                return
            
            console.append("Uploading playlists...")
            QApplication.processEvents()
            
            if not sync.sync_playlists(self.playlists_file):
                console.append("❌ Playlist upload failed!")
                status_label.setText("Sync Failed")
                return
            
            console.append("✓ Playlists uploaded\n")
            QApplication.processEvents()
            
            if self._sync_cancelled:
                console.append("Cancelled by user")
                return
            
            console.append("Syncing music files...")
            status_label.setText("Syncing music files...")
            QApplication.processEvents()
            
            def update_progress(current, total, filename):
                if self._sync_cancelled:
                    return False 
                if current == 0:
                    console.append(filename)
                else:
                    progress.setValue(int((current / total) * 100))
                    console.append(f"[{current}/{total}] {filename}")
                QApplication.processEvents()
                return True
            
            success, fail, skip, deleted = sync.sync_all_music(
                self.playlists, 
                self.playlists_file.parent,
                update_progress
            )
            
            if not self._sync_cancelled:
                progress.setValue(100)
                status_label.setText("Sync Complete!")
                console.append(f"\n✓ Sync complete!")
                console.append(f"  Uploaded: {success}")
                console.append(f"  Skipped: {skip}")
                console.append(f"  Deleted: {deleted}")
                console.append(f"  Failed: {fail}")
                
                msg = f"Sync complete!\n\nUploaded: {success}\nSkipped: {skip}"
                if deleted > 0:
                    msg += f"\nDeleted: {deleted}"
                if fail > 0:
                    msg += f"\nFailed: {fail}"
                QMessageBox.information(self, "Success", msg)
            
        except Exception as e:
            console.append(f"\n❌ Error: {e}")
            status_label.setText("Sync Failed")
            QMessageBox.critical(self, "Error", f"Sync failed: {e}")
        finally:
            self._sync_cancelled = False
            if dialog and not dialog.isHidden():
                dialog.close()
    
    def get_playlists_hash(self):
        """Get hash of current playlists for change detection"""
        try:
            if self.playlists_file.exists():
                with open(self.playlists_file, 'rb') as f:
                    return hashlib.sha256(f.read()).hexdigest()
        except:
            pass
        return None
    
    def auto_sync_check(self):
        """Check if playlists changed and sync in background"""
        if not self.auto_sync_enabled or not self.server_url:
            return
        
        current_hash = self.get_playlists_hash()
        if current_hash and current_hash != self.last_playlists_hash:
            self.last_playlists_hash = current_hash
            self.auto_sync_background()
    
    def auto_sync_background(self):
        """Perform background sync without UI dialogs - only show errors"""
        try:
            self.save_playlists()
            
            from server_sync import ServerSync
            sync = ServerSync(self.server_url, self.server_username, self.server_password)
            
            if not sync.login():
                QMessageBox.critical(self, "Auto-Sync Error", "Failed to login to server")
                return
            
            if not sync.sync_playlists(self.playlists_file):
                QMessageBox.critical(self, "Auto-Sync Error", "Failed to upload playlists")
                return
            
            success, fail, skip, deleted = sync.sync_all_music(
                self.playlists,
                self.playlists_file.parent,
                None 
            )
            
            if fail > 0:
                QMessageBox.warning(self, "Auto-Sync Warning", f"Background sync completed with {fail} failed file(s)")
            
        except Exception as e:
            QMessageBox.critical(self, "Auto-Sync Error", f"Background sync failed: {e}")
    
    def save_translation_settings(self, enabled, language, dialog):
        """Save translation settings and apply them"""
        needs_reload = (enabled != self.translation_enabled or 
                       language != self.translation_language)
        
        self.translation_enabled = enabled
        self.translation_language = language
        self.save_settings()
        
        if needs_reload and self.current_index >= 0:
            file_path = self.current_playlist[self.current_index]["path"]
            self.load_lyrics(file_path)
        
        dialog.accept()
    
    def update_ui(self):
        """Periodic UI updates"""
        if self.synced_lyrics and self.is_playing:
            position_ms = self.player.position()
            self.update_lyrics_highlight(position_ms)
    
    def load_settings(self):
        """Load saved settings"""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    volume = settings.get('volume', 0.7)
                    self.audio_output.setVolume(volume)
                    self.volume_slider.setValue(int(volume * 100))
                    if 'window_geometry' in settings:
                        geom = settings['window_geometry']
                        self.setGeometry(geom['x'], geom['y'], geom['width'], geom['height'])
                    self.is_shuffle = settings.get('shuffle', False)
                    self.repeat_mode = settings.get('repeat_mode', 0)
                    self.translation_language = settings.get('translation_language', 'en')
                    self.translation_enabled = settings.get('translation_enabled', False)
                    self.server_url = settings.get('server_url', '')
                    self.server_username = settings.get('server_username', '')
                    self.server_password = settings.get('server_password', '')
                    self.auto_sync_enabled = settings.get('auto_sync_enabled', False)
                    self.auto_sync_interval = settings.get('auto_sync_interval', 300000)
                    print(f"[DEBUG] Loaded settings: server_url={self.server_url}, auto_sync={self.auto_sync_enabled}")
            except Exception as e:
                print(f"[ERROR] Failed to load settings: {e}")
                import traceback
                traceback.print_exc()
    
    def save_settings(self):
        """Save settings"""
        geom = self.geometry()
        settings = {
            'volume': self.audio_output.volume(),
            'window_geometry': {
                'x': geom.x(),
                'y': geom.y(),
                'width': geom.width(),
                'height': geom.height()
            },
            'shuffle': self.is_shuffle,
            'repeat_mode': self.repeat_mode,
            'translation_language': self.translation_language,
            'translation_enabled': self.translation_enabled,
            'server_url': getattr(self, 'server_url', ''),
            'server_username': getattr(self, 'server_username', ''),
            'server_password': getattr(self, 'server_password', ''),
            'auto_sync_enabled': getattr(self, 'auto_sync_enabled', False),
            'auto_sync_interval': getattr(self, 'auto_sync_interval', 300000),
        }
        with open(self.settings_file, 'w') as f:
            json.dump(settings, f, indent=2)
    
    def closeEvent(self, event):
        """Handle window close"""
        self.save_settings()
        self.save_playlists()
        
        for download_data in self.active_downloads:
            thread = download_data['thread']
            worker = download_data['worker']
            dialog = download_data['dialog']
            
            worker.stop()
            
            thread.quit()
            thread.wait(2000)
            
            dialog.close()
        
        event.accept()


def main():
    os.environ["QT_LOGGING_RULES"] = "qt.text.font.db=false"
    
    app = QApplication(sys.argv)
    app.setApplicationName("LocalStream")
    
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    player = MusicPlayer()
    player.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

