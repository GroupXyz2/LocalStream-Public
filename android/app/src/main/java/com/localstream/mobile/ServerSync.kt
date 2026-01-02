package com.localstream.mobile

import android.content.Context
import com.google.gson.Gson
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import java.io.File
import java.io.FileOutputStream

object ServerSync {
    
    private val client = OkHttpClient()
    private val gson = Gson()
    private var token: String? = null
    
    private fun getSettings(context: Context): Triple<String, String, String> {
        val prefs = context.getSharedPreferences("app_settings", Context.MODE_PRIVATE)
        val serverUrl = prefs.getString("server_url", "https://downloader.groupxyz.me:8192") ?: "https://downloader.groupxyz.me:8192"
        val username = prefs.getString("username", "") ?: ""
        val password = prefs.getString("password", "") ?: ""
        return Triple(serverUrl, username, password)
    }
    
    private fun login(context: Context): Boolean {
        try {
            val (serverUrl, username, password) = getSettings(context)
            
            if (username.isEmpty() || password.isEmpty()) {
                android.util.Log.w("ServerSync", "Username or password not configured")
                return false
            }
            
            android.util.Log.d("ServerSync", "Attempting login to $serverUrl...")
            val json = """{"username":"$username","password":"$password"}"""
            val requestBody = json.toRequestBody("application/json".toMediaType())
            
            val request = Request.Builder()
                .url("$serverUrl/auth/login")
                .post(requestBody)
                .build()
            
            android.util.Log.d("ServerSync", "Sending login request...")
            val response = client.newCall(request).execute()
            android.util.Log.d("ServerSync", "Login response code: ${response.code}")
            if (response.isSuccessful) {
                val responseBody = response.body?.string() ?: return false
                android.util.Log.d("ServerSync", "Login response: ${responseBody.take(100)}")
                val data = gson.fromJson(responseBody, Map::class.java)
                token = data["access_token"] as? String
                android.util.Log.d("ServerSync", "Token received: ${if (token != null) "YES" else "NO"}")
                return token != null
            } else {
                val errorBody = response.body?.string() ?: "No error body"
                android.util.Log.e("ServerSync", "Login failed: ${response.code} ${response.message}")
                android.util.Log.e("ServerSync", "Error body: $errorBody")
            }
            return false
        } catch (e: Exception) {
            android.util.Log.w("ServerSync", "Login failed (offline?): ${e.message}")
            return false
        }
    }
    
    suspend fun syncPlaylists(context: Context): SyncResult {
        try {
            val (serverUrl, username, password) = getSettings(context)
            
            if (username.isEmpty() || password.isEmpty()) {
                return SyncResult(false, "Please configure server settings")
            }
            
            if (token == null && !login(context)) {
                android.util.Log.w("ServerSync", "Authentication failed - working offline")
                return SyncResult(false, "Authentication failed - working offline")
            }
        
        android.util.Log.d("ServerSync", "Fetching playlists from server...")
        val request = Request.Builder()
            .url("$serverUrl/playlists")
            .header("Authorization", "Bearer $token")
            .build()
        
        val response = client.newCall(request).execute()
        if (response.isSuccessful) {
            val json = response.body?.string() ?: return SyncResult(false, "Empty response")
            android.util.Log.d("ServerSync", "Received playlists: ${json.take(200)}...")
            
            val playlistsFile = File(context.filesDir, "playlists.json")
            playlistsFile.writeText(json)
            android.util.Log.d("ServerSync", "Saved playlists to: ${playlistsFile.absolutePath}")
            
            val playlistsData = gson.fromJson(json, Map::class.java) as Map<String, Map<String, Any>>
            android.util.Log.d("ServerSync", "Found ${playlistsData.size} playlists")
            
            playlistsData.forEach { (playlistName, playlistData) ->
                val songPaths = playlistData["song_paths"] as? List<*> ?: return@forEach
                android.util.Log.d("ServerSync", "Playlist '$playlistName' has ${songPaths.size} songs")
                
                songPaths.forEach { path ->
                    val songPath = path as? String ?: return@forEach
                    android.util.Log.d("ServerSync", "Downloading song: $songPath")
                    downloadSong(context, songPath)
                }
            }
            android.util.Log.d("ServerSync", "Sync completed successfully")
            return SyncResult(true, "Sync completed successfully")
        } else if (response.code == 401) {
            if (login(context)) {
                return syncPlaylists(context)
            } else {
                android.util.Log.w("ServerSync", "Re-authentication failed - working offline")
                return SyncResult(false, "Authentication failed - working offline")
            }
        } else {
            val errorMsg = "Server error ${response.code} - working offline"
            android.util.Log.w("ServerSync", errorMsg)
            return SyncResult(false, errorMsg)
        }
        } catch (e: Exception) {
            android.util.Log.w("ServerSync", "Sync failed (offline?): ${e.message}")
            return SyncResult(false, "Connection failed - working offline")
        }
    }
    
    data class SyncResult(val success: Boolean, val message: String)
    
    private fun downloadSong(context: Context, remotePath: String) {
        if (token == null && !login(context)) {
            return
        }
        
        val (serverUrl, _, _) = getSettings(context)
        val fileName = remotePath.replace("\\", "/").substringAfterLast("/")
        val localFile = File(context.filesDir, "music/$fileName")
        
        if (localFile.exists()) {
            android.util.Log.d("ServerSync", "Song already exists: $fileName")
            return
        }
        
        localFile.parentFile?.mkdirs()
        
        android.util.Log.d("ServerSync", "Downloading: $fileName")
        
        val encodedFileName = java.net.URLEncoder.encode(fileName, "UTF-8").replace("+", "%20")
        val request = Request.Builder()
            .url("$serverUrl/music/$encodedFileName")
            .header("Authorization", "Bearer $token")
            .build()
        
        try {
            android.util.Log.d("ServerSync", "Request URL: $serverUrl/music/$encodedFileName")
            val response = client.newCall(request).execute()
            android.util.Log.d("ServerSync", "Response code: ${response.code}")
            if (response.isSuccessful) {
                val bodyLength = response.body?.contentLength() ?: 0
                android.util.Log.d("ServerSync", "Response body length: $bodyLength bytes")
                response.body?.byteStream()?.use { input ->
                    FileOutputStream(localFile).use { output ->
                        val bytes = input.copyTo(output)
                        android.util.Log.d("ServerSync", "Wrote $bytes bytes to file")
                    }
                }
                android.util.Log.d("ServerSync", "Downloaded successfully: $fileName (${localFile.length()} bytes)")
            } else {
                val errorBody = response.body?.string() ?: "No error body"
                android.util.Log.e("ServerSync", "Failed to download $fileName: ${response.code} ${response.message}")
                android.util.Log.e("ServerSync", "Error body: $errorBody")
            }
        } catch (e: Exception) {
            android.util.Log.e("ServerSync", "Error downloading $fileName: ${e.message}", e)
            e.printStackTrace()
        }
    }
}
