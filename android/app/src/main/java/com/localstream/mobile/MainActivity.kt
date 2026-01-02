package com.localstream.mobile

import android.content.ComponentName
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.IBinder
import android.view.LayoutInflater
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.floatingactionbutton.FloatingActionButton
import com.localstream.mobile.databinding.ActivityMainBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {
    
    private lateinit var binding: ActivityMainBinding
    private var musicService: MusicService? = null
    private var bound = false
    private val playlists = mutableListOf<Playlist>()
    private lateinit var adapter: PlaylistAdapter
    
    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
            val binder = service as MusicService.MusicBinder
            musicService = binder.getService()
            bound = true
        }
        
        override fun onServiceDisconnected(name: ComponentName?) {
            bound = false
        }
    }
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        
        setupRecyclerView()
        setupSyncButton()
        
        // Auto-sync on app start
        syncFromServer()
        
        Intent(this, MusicService::class.java).also { intent ->
            bindService(intent, connection, BIND_AUTO_CREATE)
        }
    }
    
    private fun setupRecyclerView() {
        adapter = PlaylistAdapter(playlists) { playlist ->
            openPlaylist(playlist)
        }
        binding.playlistRecyclerView.layoutManager = LinearLayoutManager(this)
        binding.playlistRecyclerView.adapter = adapter
    }
    
    private fun setupSyncButton() {
        binding.syncButton.setOnClickListener {
            syncFromServer()
        }
    }
    
    private fun loadPlaylists() {
        CoroutineScope(Dispatchers.IO).launch {
            val loadedPlaylists = PlaylistManager.loadPlaylists(this@MainActivity)
            withContext(Dispatchers.Main) {
                playlists.clear()
                playlists.addAll(loadedPlaylists)
                adapter.notifyDataSetChanged()
                
                // Show/hide empty message
                if (playlists.isEmpty()) {
                    binding.emptyText.visibility = View.VISIBLE
                    binding.playlistRecyclerView.visibility = View.GONE
                } else {
                    binding.emptyText.visibility = View.GONE
                    binding.playlistRecyclerView.visibility = View.VISIBLE
                }
            }
        }
    }
    
    private fun syncFromServer() {
        binding.syncButton.isEnabled = false
        CoroutineScope(Dispatchers.IO).launch {
            android.util.Log.d("MainActivity", "Starting sync...")
            val result = ServerSync.syncPlaylists(this@MainActivity)
            android.util.Log.d("MainActivity", "Sync result: ${result.success} - ${result.message}")
            
            // Always load playlists, even if sync failed
            loadPlaylists()
            
            withContext(Dispatchers.Main) {
                binding.syncButton.isEnabled = true
                if (result.success) {
                    android.widget.Toast.makeText(
                        this@MainActivity,
                        "Sync completed successfully",
                        android.widget.Toast.LENGTH_SHORT
                    ).show()
                } else {
                    android.widget.Toast.makeText(
                        this@MainActivity,
                        "⚠️ ${result.message}",
                        android.widget.Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }
    
    private fun openPlaylist(playlist: Playlist) {
        val intent = Intent(this, PlayerActivity::class.java)
        intent.putExtra("playlist_name", playlist.name)
        startActivity(intent)
    }
    
    override fun onCreateOptionsMenu(menu: Menu?): Boolean {
        menuInflater.inflate(R.menu.menu_main, menu)
        return true
    }
    
    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_settings -> {
                val intent = Intent(this, SettingsActivity::class.java)
                startActivity(intent)
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }
    
    override fun onDestroy() {
        super.onDestroy()
        if (bound) {
            unbindService(connection)
        }
    }
}

class PlaylistAdapter(
    private val playlists: List<Playlist>,
    private val onClick: (Playlist) -> Unit
) : RecyclerView.Adapter<PlaylistAdapter.ViewHolder>() {
    
    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val nameText: TextView = view.findViewById(R.id.playlistName)
        val countText: TextView = view.findViewById(R.id.songCount)
    }
    
    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_playlist, parent, false)
        return ViewHolder(view)
    }
    
    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val playlist = playlists[position]
        holder.nameText.text = playlist.name
        holder.countText.text = "${playlist.songs.size} songs"
        holder.itemView.setOnClickListener { onClick(playlist) }
    }
    
    override fun getItemCount() = playlists.size
}
