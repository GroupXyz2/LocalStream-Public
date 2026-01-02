package com.localstream.mobile

import android.content.ComponentName
import android.content.Intent
import android.content.ServiceConnection
import android.content.res.Configuration
import android.os.Bundle
import android.os.IBinder
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.localstream.mobile.databinding.ActivityPlayerBinding

class PlayerActivity : AppCompatActivity() {
    
    private lateinit var binding: ActivityPlayerBinding
    private var musicService: MusicService? = null
    private var bound = false
    private val songs = mutableListOf<Song>()
    private lateinit var adapter: SongAdapter
    private var playlistName: String = ""
    private var updateProgressRunnable: Runnable? = null
    private val handler = android.os.Handler(android.os.Looper.getMainLooper())
    
    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
            val binder = service as MusicService.MusicBinder
            musicService = binder.getService()
            bound = true
            musicService?.setPlaylist(songs)
            
            musicService?.getPlayer()?.let { player ->
                binding.videoPlayerView.player = player
            }
            
            musicService?.setOnSongChangeListener {
                runOnUiThread {
                    updateNowPlaying()
                    updateVideoVisibility()
                }
            }
            
            val volume = musicService?.getVolume() ?: 1.5f
            binding.volumeSlider.progress = (volume * 100).toInt()
            binding.volumeText.text = "${(volume * 100).toInt()}%"
            updateShuffleButton(musicService?.isShuffleEnabled() ?: false)
            updateRepeatButton(musicService?.getRepeatMode() ?: androidx.media3.common.Player.REPEAT_MODE_OFF)
        }
        
        override fun onServiceDisconnected(name: ComponentName?) {
            bound = false
        }
    }
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        try {
            binding = ActivityPlayerBinding.inflate(layoutInflater)
            setContentView(binding.root)
            
            playlistName = intent.getStringExtra("playlist_name") ?: ""
            android.util.Log.d("PlayerActivity", "Opening playlist: $playlistName")
            title = playlistName
            
            setupRecyclerView()
            setupControls()
            loadSongs()
            
            Intent(this, MusicService::class.java).also { intent ->
                bindService(intent, connection, BIND_AUTO_CREATE)
            }
        } catch (e: Exception) {
            android.util.Log.e("PlayerActivity", "Error in onCreate", e)
            android.widget.Toast.makeText(this, "Error: ${e.message}", android.widget.Toast.LENGTH_LONG).show()
            finish()
        }
    }
    
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        updateVideoVisibility()
    }
    
    private fun setupRecyclerView() {
        adapter = SongAdapter(songs) { song, position ->
            musicService?.playSong(position)
            // Delay to allow player state to update
            handler.postDelayed({
                updateNowPlaying()
            }, 100)
        }
        binding.songRecyclerView.layoutManager = LinearLayoutManager(this)
        binding.songRecyclerView.adapter = adapter
    }
    
    private fun setupControls() {
        // Progress bar - seek forward/backward in track
        binding.progressBar.max = 1000
        binding.progressBar.setOnSeekBarChangeListener(object : android.widget.SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: android.widget.SeekBar?, progress: Int, fromUser: Boolean) {
                if (fromUser) {
                    // Show time preview while dragging
                    val duration = musicService?.getDuration() ?: 0L
                    val newPosition = (duration * progress / 1000).toLong()
                    binding.currentTime.text = formatTime(newPosition)
                }
            }
            override fun onStartTrackingTouch(seekBar: android.widget.SeekBar?) {
                // Pause progress updates while user is dragging
                stopProgressUpdates()
            }
            override fun onStopTrackingTouch(seekBar: android.widget.SeekBar?) {
                // Seek to the new position when user releases
                val duration = musicService?.getDuration() ?: 0L
                val newPosition = (duration * seekBar!!.progress / 1000).toLong()
                musicService?.seekTo(newPosition)
                // Resume progress updates
                startProgressUpdates()
            }
        })
        
        // Volume control
        binding.volumeSlider.max = 200
        binding.volumeSlider.progress = 150
        binding.volumeSlider.setOnSeekBarChangeListener(object : android.widget.SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: android.widget.SeekBar?, progress: Int, fromUser: Boolean) {
                if (fromUser) {
                    // Convert percentage to volume (100% = 1.0, 200% = 2.0)
                    val volume = progress / 100f
                    musicService?.setVolume(volume)
                    binding.volumeText.text = "$progress%"
                }
            }
            override fun onStartTrackingTouch(seekBar: android.widget.SeekBar?) {}
            override fun onStopTrackingTouch(seekBar: android.widget.SeekBar?) {}
        })
        
        // Play/Pause button
        binding.playButton.setOnClickListener {
            musicService?.togglePlayPause()
            updatePlayButton()
        }
        
        // Next/Previous buttons
        binding.nextButton.setOnClickListener {
            musicService?.playNext()
            updateNowPlaying()
        }
        
        binding.previousButton.setOnClickListener {
            musicService?.playPrevious()
            updateNowPlaying()
        }
        
        // Shuffle button
        binding.shuffleButton.setOnClickListener {
            val isShuffleOn = musicService?.toggleShuffle() ?: false
            updateShuffleButton(isShuffleOn)
        }
        
        // Repeat button
        binding.repeatButton.setOnClickListener {
            val repeatMode = musicService?.cycleRepeatMode() ?: androidx.media3.common.Player.REPEAT_MODE_OFF
            updateRepeatButton(repeatMode)
        }
    }
    
    private fun updatePlayButton() {
        val isPlaying = musicService?.isPlaying() ?: false
        binding.playButton.setImageResource(
            if (isPlaying) android.R.drawable.ic_media_pause
            else android.R.drawable.ic_media_play
        )
    }
    
    private fun updateNowPlaying() {
        val song = musicService?.getCurrentSong()
        if (song != null) {
            binding.currentSongTitle.text = song.title
            binding.currentSongArtist.text = song.artist
            binding.currentSongTitle.isSelected = true // Enable marquee
            
            // Load album art from file
            loadAlbumArt(song.url)
            
            // Start progress updates
            startProgressUpdates()
        } else {
            binding.currentSongTitle.text = "No song playing"
            binding.currentSongArtist.text = ""
            binding.albumArt.setImageResource(android.R.drawable.ic_menu_gallery)
            stopProgressUpdates()
        }
        updatePlayButton()
    }
    
    private fun startProgressUpdates() {
        stopProgressUpdates()
        updateProgressRunnable = object : Runnable {
            override fun run() {
                updateProgress()
                handler.postDelayed(this, 500) // Update every 500ms
            }
        }
        handler.post(updateProgressRunnable!!)
    }
    
    private fun stopProgressUpdates() {
        updateProgressRunnable?.let { handler.removeCallbacks(it) }
    }
    
    private fun updateProgress() {
        val currentPosition = musicService?.getCurrentPosition() ?: 0L
        val duration = musicService?.getDuration() ?: 0L
        
        if (duration > 0) {
            val progress = ((currentPosition * 1000) / duration).toInt()
            binding.progressBar.progress = progress
            
            binding.currentTime.text = formatTime(currentPosition)
            binding.totalTime.text = formatTime(duration)
        }
    }
    
    private fun formatTime(millis: Long): String {
        val seconds = (millis / 1000).toInt()
        val minutes = seconds / 60
        val secs = seconds % 60
        return String.format("%d:%02d", minutes, secs)
    }
    
    private fun loadAlbumArt(fileUrl: String) {
        try {
            val filePath = fileUrl.removePrefix("file://")
            val retriever = android.media.MediaMetadataRetriever()
            retriever.setDataSource(filePath)
            val art = retriever.embeddedPicture
            if (art != null) {
                val bitmap = android.graphics.BitmapFactory.decodeByteArray(art, 0, art.size)
                binding.albumArt.setImageBitmap(bitmap)
            } else {
                binding.albumArt.setImageResource(android.R.drawable.ic_menu_gallery)
            }
            retriever.release()
        } catch (e: Exception) {
            android.util.Log.e("PlayerActivity", "Error loading album art", e)
            binding.albumArt.setImageResource(android.R.drawable.ic_menu_gallery)
        }
    }
    
    private fun updateShuffleButton(isEnabled: Boolean) {
        binding.shuffleButton.alpha = if (isEnabled) 1.0f else 0.5f
    }
    
    private fun updateVideoVisibility() {
        val currentSong = musicService?.getCurrentSong()
        val isVideo = currentSong?.url?.endsWith(".mp4", ignoreCase = true) == true
        val isLandscape = resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
        
        if (isVideo) {
            binding.videoPlayerView.visibility = View.VISIBLE
            binding.songRecyclerView.visibility = View.GONE
            
            if (isLandscape) {
                enterFullscreen()
            } else {
                exitFullscreen()
            }
        } else {
            binding.videoPlayerView.visibility = View.GONE
            binding.songRecyclerView.visibility = View.VISIBLE
            exitFullscreen()
        }
    }
    
    private fun enterFullscreen() {
        supportActionBar?.hide()
        binding.nowPlayingContainer?.visibility = View.GONE
        binding.controlsContainer?.visibility = View.GONE
        
        val windowInsetsController = WindowCompat.getInsetsController(window, window.decorView)
        windowInsetsController.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        windowInsetsController.hide(WindowInsetsCompat.Type.systemBars())
    }
    
    private fun exitFullscreen() {
        supportActionBar?.show()
        binding.nowPlayingContainer?.visibility = View.VISIBLE
        binding.controlsContainer?.visibility = View.VISIBLE
        
        val windowInsetsController = WindowCompat.getInsetsController(window, window.decorView)
        windowInsetsController.show(WindowInsetsCompat.Type.systemBars())
    }
    
    private fun updateRepeatButton(repeatMode: Int) {
        when (repeatMode) {
            androidx.media3.common.Player.REPEAT_MODE_OFF -> {
                binding.repeatButton.alpha = 0.5f
                binding.repeatButton.setImageResource(android.R.drawable.ic_menu_rotate)
            }
            androidx.media3.common.Player.REPEAT_MODE_ALL -> {
                binding.repeatButton.alpha = 1.0f
                binding.repeatButton.setImageResource(android.R.drawable.ic_menu_rotate)
            }
            androidx.media3.common.Player.REPEAT_MODE_ONE -> {
                binding.repeatButton.alpha = 1.0f
                binding.repeatButton.setImageResource(android.R.drawable.ic_menu_revert)
            }
        }
    }
    
    private fun loadSongs() {
        try {
            android.util.Log.d("PlayerActivity", "Loading songs for playlist: $playlistName")
            val playlist = PlaylistManager.getPlaylist(this, playlistName)
            if (playlist != null) {
                android.util.Log.d("PlayerActivity", "Found ${playlist.songs.size} songs")
                songs.clear()
                songs.addAll(playlist.songs)
                adapter.notifyDataSetChanged()
            } else {
                android.util.Log.w("PlayerActivity", "Playlist not found: $playlistName")
            }
        } catch (e: Exception) {
            android.util.Log.e("PlayerActivity", "Error loading songs", e)
        }
    }
    
    override fun onDestroy() {
        super.onDestroy()
        stopProgressUpdates()
        if (bound) {
            unbindService(connection)
        }
    }
}

class SongAdapter(
    private val songs: List<Song>,
    private val onClick: (Song, Int) -> Unit
) : RecyclerView.Adapter<SongAdapter.ViewHolder>() {
    
    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val titleText: TextView = view.findViewById(R.id.songTitle)
        val artistText: TextView = view.findViewById(R.id.songArtist)
        val albumArtImage: android.widget.ImageView = view.findViewById(R.id.songAlbumArt)
    }
    
    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_song, parent, false)
        return ViewHolder(view)
    }
    
    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val song = songs[position]
        holder.titleText.text = song.title
        holder.artistText.text = song.artist
        holder.itemView.setOnClickListener { onClick(song, position) }
        
        // Load album art
        loadAlbumArtForItem(song.url, holder.albumArtImage)
    }
    
    private fun loadAlbumArtForItem(fileUrl: String, imageView: android.widget.ImageView) {
        try {
            val filePath = fileUrl.removePrefix("file://")
            val retriever = android.media.MediaMetadataRetriever()
            retriever.setDataSource(filePath)
            val art = retriever.embeddedPicture
            if (art != null) {
                val bitmap = android.graphics.BitmapFactory.decodeByteArray(art, 0, art.size)
                imageView.setImageBitmap(bitmap)
            } else {
                imageView.setImageResource(android.R.drawable.ic_menu_gallery)
            }
            retriever.release()
        } catch (e: Exception) {
            imageView.setImageResource(android.R.drawable.ic_menu_gallery)
        }
    }
    
    override fun getItemCount() = songs.size
}
