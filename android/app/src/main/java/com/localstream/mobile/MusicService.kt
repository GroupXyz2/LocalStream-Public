package com.localstream.mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.core.app.NotificationCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer

class MusicService : Service() {
    
    private val binder = MusicBinder()
    private var player: ExoPlayer? = null
    private var playlist = listOf<Song>()
    private var currentIndex = 0
    private var isShuffleEnabled = false
    private var repeatMode = Player.REPEAT_MODE_OFF // OFF, ONE, ALL
    private var shuffledPlaylist = listOf<Int>()
    private var mediaSession: MediaSessionCompat? = null
    private var loudnessEnhancer: android.media.audiofx.LoudnessEnhancer? = null
    private var currentVolumeMultiplier: Float = 1.5f
    private var onSongChangeListener: (() -> Unit)? = null
    private val trackLoudnessCache = mutableMapOf<String, Float>()
    private val targetLoudness = -14.0f
    
    companion object {
        private const val NOTIFICATION_ID = 1
        private const val CHANNEL_ID = "music_playback"
        private const val ACTION_PLAY_PAUSE = "action_play_pause"
        private const val ACTION_NEXT = "action_next"
        private const val ACTION_PREVIOUS = "action_previous"
    }
    
    inner class MusicBinder : Binder() {
        fun getService(): MusicService = this@MusicService
    }
    
    override fun onCreate() {
        super.onCreate()
        
        createNotificationChannel()
        setupMediaSession()
        
        player = ExoPlayer.Builder(this).build()
        
        // Initialize audio session for effects
        player?.let { exoPlayer ->
            try {
                val audioSessionId = exoPlayer.audioSessionId
                loudnessEnhancer = android.media.audiofx.LoudnessEnhancer(audioSessionId).apply {
                    enabled = true
                }
                android.util.Log.d("MusicService", "LoudnessEnhancer initialized with session: $audioSessionId")
            } catch (e: Exception) {
                android.util.Log.e("MusicService", "Failed to initialize LoudnessEnhancer", e)
            }
        }
        
        player?.addListener(object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) {
                updateNotification()
                if (state == Player.STATE_ENDED) {
                    if (repeatMode == Player.REPEAT_MODE_ONE) {
                        player?.seekTo(0)
                        player?.play()
                    } else {
                        playNext()
                    }
                }
            }
            
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                updateNotification()
                updatePlaybackState()
                onSongChangeListener?.invoke()
            }
            
            override fun onMediaItemTransition(mediaItem: androidx.media3.common.MediaItem?, reason: Int) {
                // Called when track changes
                onSongChangeListener?.invoke()
            }
        })
    }
    
    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Music Playback",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Shows currently playing music"
                setShowBadge(false)
            }
            val notificationManager = getSystemService(NotificationManager::class.java)
            notificationManager?.createNotificationChannel(channel)
        }
    }
    
    private fun setupMediaSession() {
        mediaSession = MediaSessionCompat(this, "MusicService").apply {
            setCallback(object : MediaSessionCompat.Callback() {
                override fun onPlay() {
                    player?.play()
                }
                
                override fun onPause() {
                    player?.pause()
                }
                
                override fun onSkipToNext() {
                    playNext()
                }
                
                override fun onSkipToPrevious() {
                    playPrevious()
                }
                
                override fun onSeekTo(pos: Long) {
                    seekTo(pos)
                }
            })
            isActive = true
        }
        updatePlaybackState()
    }
    
    private fun updatePlaybackState() {
        val state = if (player?.isPlaying == true) {
            PlaybackStateCompat.STATE_PLAYING
        } else {
            PlaybackStateCompat.STATE_PAUSED
        }
        
        val playbackState = PlaybackStateCompat.Builder()
            .setState(state, player?.currentPosition ?: 0, 1.0f)
            .setActions(
                PlaybackStateCompat.ACTION_PLAY_PAUSE or
                PlaybackStateCompat.ACTION_SKIP_TO_NEXT or
                PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS or
                PlaybackStateCompat.ACTION_SEEK_TO
            )
            .build()
        
        mediaSession?.setPlaybackState(playbackState)
    }
    
    override fun onBind(intent: Intent?): IBinder = binder
    
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_PLAY_PAUSE -> togglePlayPause()
            ACTION_NEXT -> playNext()
            ACTION_PREVIOUS -> playPrevious()
        }
        return START_STICKY
    }
    
    private fun updateNotification() {
        val song = getCurrentSong() ?: return
        
        val notification = buildNotification(song)
        startForeground(NOTIFICATION_ID, notification)
    }
    
    private fun buildNotification(song: Song): Notification {
        val playPauseIntent = Intent(this, MusicService::class.java).apply {
            action = ACTION_PLAY_PAUSE
        }
        val playPausePendingIntent = PendingIntent.getService(
            this, 0, playPauseIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        
        val previousIntent = Intent(this, MusicService::class.java).apply {
            action = ACTION_PREVIOUS
        }
        val previousPendingIntent = PendingIntent.getService(
            this, 1, previousIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        
        val nextIntent = Intent(this, MusicService::class.java).apply {
            action = ACTION_NEXT
        }
        val nextPendingIntent = PendingIntent.getService(
            this, 2, nextIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        
        val contentIntent = Intent(this, PlayerActivity::class.java)
        val contentPendingIntent = PendingIntent.getActivity(
            this, 3, contentIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        
        // Load album art
        var albumArt: android.graphics.Bitmap? = null
        try {
            val filePath = song.url.removePrefix("file://")
            val retriever = android.media.MediaMetadataRetriever()
            retriever.setDataSource(filePath)
            val art = retriever.embeddedPicture
            if (art != null) {
                albumArt = android.graphics.BitmapFactory.decodeByteArray(art, 0, art.size)
            }
            retriever.release()
        } catch (e: Exception) {
            // Ignore
        }
        
        val playPauseIcon = if (player?.isPlaying == true) {
            android.R.drawable.ic_media_pause
        } else {
            android.R.drawable.ic_media_play
        }
        
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(song.title)
            .setContentText(song.artist)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setLargeIcon(albumArt)
            .setContentIntent(contentPendingIntent)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOnlyAlertOnce(true)
            .addAction(android.R.drawable.ic_media_previous, "Previous", previousPendingIntent)
            .addAction(playPauseIcon, "Play/Pause", playPausePendingIntent)
            .addAction(android.R.drawable.ic_media_next, "Next", nextPendingIntent)
            .setStyle(
                androidx.media.app.NotificationCompat.MediaStyle()
                    .setMediaSession(mediaSession?.sessionToken)
                    .setShowActionsInCompactView(0, 1, 2)
            )
            .build()
    }
    
    fun setPlaylist(songs: List<Song>) {
        playlist = songs
        if (isShuffleEnabled) {
            shufflePlaylist()
        }
    }
    
    fun playSong(index: Int) {
        if (index < 0 || index >= playlist.size) return
        currentIndex = index
        val actualIndex = if (isShuffleEnabled && index < shuffledPlaylist.size) {
            shuffledPlaylist[index]
        } else {
            index
        }
        val song = playlist[actualIndex]
        val mediaItem = MediaItem.fromUri(song.url)
        player?.setMediaItem(mediaItem)
        player?.prepare()
        
        applyLoudnessNormalization(song.url)
        
        player?.play()
        updateNotification()
        updatePlaybackState()
    }
    
    fun getCurrentSong(): Song? {
        if (currentIndex < 0 || currentIndex >= playlist.size) return null
        val actualIndex = if (isShuffleEnabled && currentIndex < shuffledPlaylist.size) {
            shuffledPlaylist[currentIndex]
        } else {
            currentIndex
        }
        return playlist.getOrNull(actualIndex)
    }
    
    fun togglePlayPause() {
        player?.let {
            if (it.isPlaying) {
                it.pause()
            } else {
                it.play()
            }
            updateNotification()
            updatePlaybackState()
        }
    }
    
    fun isPlaying(): Boolean = player?.isPlaying ?: false
    
    fun playNext() {
        val nextIndex = when (repeatMode) {
            Player.REPEAT_MODE_ALL -> (currentIndex + 1) % playlist.size
            else -> currentIndex + 1
        }
        if (nextIndex < playlist.size) {
            playSong(nextIndex)
        }
    }
    
    fun playPrevious() {
        if (currentIndex > 0) {
            playSong(currentIndex - 1)
        }
    }
    
    fun setVolume(volume: Float) {
        currentVolumeMultiplier = volume.coerceIn(0f, 2.0f)
        
        if (volume <= 1.0f) {
            // Normal volume range (0-100%)
            player?.volume = volume
            loudnessEnhancer?.setTargetGain(0)
            android.util.Log.d("MusicService", "Volume set to: $volume (normal)")
        } else {
            // Boost range (100-200%)
            player?.volume = 1.0f
            // LoudnessEnhancer gain is in millibels (100 mB = 1 dB)
            // For 200%, we use approximately +6dB gain (600 mB)
            val gainMb = ((volume - 1.0f) * 600).toInt()
            try {
                loudnessEnhancer?.setTargetGain(gainMb)
                android.util.Log.d("MusicService", "Volume boosted to: $volume (gain: ${gainMb}mB)")
            } catch (e: Exception) {
                android.util.Log.e("MusicService", "Failed to set gain", e)
            }
        }
    }
    
    fun getVolume(): Float = currentVolumeMultiplier
    
    private fun applyLoudnessNormalization(fileUrl: String) {
        try {
            val loudness = trackLoudnessCache.getOrPut(fileUrl) {
                analyzeLoudness(fileUrl)
            }
            
            val loudnessDelta = targetLoudness - loudness
            val volumeMultiplier = Math.pow(10.0, (loudnessDelta / 20.0).toDouble()).toFloat()
            val clampedMultiplier = volumeMultiplier.coerceIn(0.5f, 2.0f)
            
            val normalizedVolume = currentVolumeMultiplier * clampedMultiplier
            
            if (normalizedVolume <= 1.0f) {
                player?.volume = normalizedVolume
                loudnessEnhancer?.setTargetGain(0)
            } else {
                player?.volume = 1.0f
                val gainMb = ((normalizedVolume - 1.0f) * 600).toInt()
                loudnessEnhancer?.setTargetGain(gainMb)
            }
            
            android.util.Log.d("MusicService", "Applied normalization: loudness=$loudness, multiplier=$clampedMultiplier")
        } catch (e: Exception) {
            android.util.Log.e("MusicService", "Normalization failed", e)
        }
    }
    
    private fun analyzeLoudness(fileUrl: String): Float {
        return try {
            val extractor = android.media.MediaExtractor()
            extractor.setDataSource(fileUrl, emptyMap())
            
            var totalEnergy = 0.0
            var sampleCount = 0
            
            for (i in 0 until extractor.trackCount) {
                val format = extractor.getTrackFormat(i)
                val mime = format.getString(android.media.MediaFormat.KEY_MIME) ?: ""
                if (mime.startsWith("audio/")) {
                    extractor.selectTrack(i)
                    val buffer = java.nio.ByteBuffer.allocate(256 * 1024)
                    
                    while (sampleCount < 100000) {
                        val sampleSize = extractor.readSampleData(buffer, 0)
                        if (sampleSize < 0) break
                        
                        buffer.rewind()
                        for (j in 0 until minOf(sampleSize / 2, 1000)) {
                            val sample = buffer.short
                            totalEnergy += (sample / 32768.0) * (sample / 32768.0)
                            sampleCount++
                        }
                        
                        extractor.advance()
                        buffer.clear()
                    }
                    break
                }
            }
            
            extractor.release()
            
            if (sampleCount > 0) {
                val rms = Math.sqrt(totalEnergy / sampleCount)
                val loudness = (20 * Math.log10(rms + 1e-10)).toFloat()
                loudness.coerceIn(-60f, 0f)
            } else {
                -20f
            }
        } catch (e: Exception) {
            android.util.Log.e("MusicService", "Loudness analysis failed", e)
            -20f
        }
    }
    
    fun setOnSongChangeListener(listener: () -> Unit) {
        onSongChangeListener = listener
    }
    
    fun toggleShuffle(): Boolean {
        isShuffleEnabled = !isShuffleEnabled
        if (isShuffleEnabled) {
            shufflePlaylist()
        }
        return isShuffleEnabled
    }
    
    fun isShuffleEnabled(): Boolean = isShuffleEnabled
    
    fun cycleRepeatMode(): Int {
        repeatMode = when (repeatMode) {
            Player.REPEAT_MODE_OFF -> Player.REPEAT_MODE_ALL
            Player.REPEAT_MODE_ALL -> Player.REPEAT_MODE_ONE
            else -> Player.REPEAT_MODE_OFF
        }
        return repeatMode
    }
    
    fun getRepeatMode(): Int = repeatMode
    
    fun getCurrentPosition(): Long = player?.currentPosition ?: 0L
    
    fun getDuration(): Long = player?.duration ?: 0L
    
    fun seekTo(position: Long) {
        player?.seekTo(position)
    }
    
    fun getPlayer(): ExoPlayer? = player
    
    private fun shufflePlaylist() {
        shuffledPlaylist = playlist.indices.shuffled()
    }
    
    override fun onDestroy() {
        super.onDestroy()
        loudnessEnhancer?.release()
        mediaSession?.release()
        player?.release()
        player = null
        stopForeground(true)
    }
}
