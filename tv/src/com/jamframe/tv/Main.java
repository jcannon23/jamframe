package com.jamframe.tv;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.webkit.WebView;
import android.widget.TextView;

/** The screen: one room's JamFrame page, edge to edge. Opened by Watch when music starts, or by hand. */
public class Main extends Activity {
    static volatile Main showing;   // the open screen, if any
    boolean closing;                // Watch is closing it, as opposed to someone pressing Home or Back
    WebView web;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        configure(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        configure(intent);
    }

    /** Takes the watcher's address and the room when the installer passes them, then shows the page. */
    void configure(Intent intent) {
        SharedPreferences prefs = getSharedPreferences("jamframe", MODE_PRIVATE);
        if (intent.hasExtra("server") && intent.hasExtra("room")) {
            prefs.edit().putString("server", intent.getStringExtra("server"))
                    .putString("room", intent.getStringExtra("room")).apply();
        }
        Watch.start(this);
        String url = Watch.url(prefs, "/");
        if (url == null) {
            TextView note = new TextView(this);
            note.setText("JamFrame is not set up on this TV yet.\nRun scripts/install-tv.sh from the computer.");
            note.setTextSize(22);
            note.setTextColor(Color.LTGRAY);
            note.setGravity(Gravity.CENTER);
            setContentView(note);
            return;
        }
        web = new WebView(this);
        web.setBackgroundColor(Color.BLACK);
        web.getSettings().setJavaScriptEnabled(true);   // our own page, from the watcher on the home network
        web.loadUrl(url);
        setContentView(web);
        web.setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        showing = this;
    }

    void close() {
        closing = true;
        finishAndRemoveTask();
    }

    @Override
    protected void onStop() {
        super.onStop();
        if (!closing && showing == this) {
            Watch.dismissed = true;     // someone left it: stay away until the music stops and starts again
            finishAndRemoveTask();
        }
    }

    @Override
    protected void onDestroy() {
        if (showing == this) showing = null;
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
