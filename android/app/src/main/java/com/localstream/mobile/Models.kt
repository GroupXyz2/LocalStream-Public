package com.localstream.mobile

data class Playlist(
    val name: String,
    val songs: List<Song>
)

data class Song(
    val title: String,
    val artist: String,
    val album: String,
    val duration: Int,
    val url: String
)
