package com.localstream.mobile

import android.content.Context
import com.google.gson.Gson
import java.io.File

object PlaylistManager {
    
    private val gson = Gson()
    
    fun loadPlaylists(context: Context): List<Playlist> {
        val file = File(context.filesDir, "playlists.json")
        android.util.Log.d("PlaylistManager", "Loading playlists from: ${file.absolutePath}")
        android.util.Log.d("PlaylistManager", "File exists: ${file.exists()}")
        
        if (!file.exists()) return emptyList()
        
        try {
            val json = file.readText()
            android.util.Log.d("PlaylistManager", "JSON content: ${json.take(200)}...")
            
            @Suppress("UNCHECKED_CAST")
            val data = gson.fromJson(json, Map::class.java) as Map<String, Map<String, Any>>
            android.util.Log.d("PlaylistManager", "Parsed ${data.size} playlists")
            
            return data.map { (name, playlistData) ->
                android.util.Log.d("PlaylistManager", "Processing playlist: $name")
                // Server stores song_paths array
                val songPaths = (playlistData["song_paths"] as? List<*>)?.mapNotNull { path ->
                    val songPath = path as? String ?: return@mapNotNull null
                    // Extract just the filename from the full path (handles both Windows and Unix paths)
                    val fileName = songPath.replace("\\", "/").split("/").last()
                    val localFile = File(context.filesDir, "music/$fileName")
                    
                    android.util.Log.d("PlaylistManager", "Checking song: $fileName, exists: ${localFile.exists()}")
                    
                    // Only include songs that exist locally
                    if (!localFile.exists()) return@mapNotNull null
                    
                    val localUrl = "file://${localFile.absolutePath}"
                    
                    // Parse song metadata from file name or use defaults
                    // Format: Artist - Title.mp3 or Artist - Title.mp4
                    // Remove both .mp3 and .mp4 extensions
                    val baseName = fileName.removeSuffix(".mp3").removeSuffix(".mp4")
                    val nameParts = baseName.split(" - ", limit = 2)
                    val artist = if (nameParts.size > 1) nameParts[0] else "Unknown"
                    val title = if (nameParts.size > 1) nameParts[1] else baseName
                    
                    Song(
                        title = title,
                        artist = artist,
                        album = "Unknown",
                        duration = 0,
                        url = localUrl
                    )
                } ?: emptyList()
                
                android.util.Log.d("PlaylistManager", "Playlist '$name' has ${songPaths.size} songs")
                Playlist(name, songPaths)
            }.filter { it.songs.isNotEmpty() }
        } catch (e: Exception) {
            android.util.Log.e("PlaylistManager", "Error loading playlists", e)
            e.printStackTrace()
            return emptyList()
        }
    }
    
    fun getPlaylist(context: Context, name: String): Playlist? {
        return loadPlaylists(context).find { it.name == name }
    }
}
