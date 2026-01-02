package com.localstream.mobile

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

class SettingsActivity : AppCompatActivity() {
    
    private lateinit var serverUrlEdit: EditText
    private lateinit var usernameEdit: EditText
    private lateinit var passwordEdit: EditText
    private lateinit var saveButton: Button
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)
        
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.title = "Settings"
        
        serverUrlEdit = findViewById(R.id.serverUrlEdit)
        usernameEdit = findViewById(R.id.usernameEdit)
        passwordEdit = findViewById(R.id.passwordEdit)
        saveButton = findViewById(R.id.saveButton)
        
        loadSettings()
        
        saveButton.setOnClickListener {
            saveSettings()
        }
    }
    
    private fun loadSettings() {
        val prefs = getSharedPreferences("app_settings", MODE_PRIVATE)
        serverUrlEdit.setText(prefs.getString("server_url", ""))
        usernameEdit.setText(prefs.getString("username", ""))
        passwordEdit.setText(prefs.getString("password", ""))
    }
    
    private fun saveSettings() {
        val serverUrl = serverUrlEdit.text.toString().trim()
        val username = usernameEdit.text.toString().trim()
        val password = passwordEdit.text.toString().trim()
        
        if (serverUrl.isEmpty()) {
            Toast.makeText(this, "Server URL is required", Toast.LENGTH_SHORT).show()
            return
        }
        
        if (username.isEmpty()) {
            Toast.makeText(this, "Username is required", Toast.LENGTH_SHORT).show()
            return
        }
        
        if (password.isEmpty()) {
            Toast.makeText(this, "Password is required", Toast.LENGTH_SHORT).show()
            return
        }
        
        val prefs = getSharedPreferences("app_settings", MODE_PRIVATE)
        prefs.edit().apply {
            putString("server_url", serverUrl)
            putString("username", username)
            putString("password", password)
            apply()
        }
        
        Toast.makeText(this, "Settings saved successfully", Toast.LENGTH_SHORT).show()
        finish()
    }
    
    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }
}

