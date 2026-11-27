package com.jamframe.tv;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.ResolveInfo;
import android.net.Uri;
import android.os.IBinder;
import android.os.PowerManager;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Asks the watcher every few seconds whether this TV's room has music, and opens or closes the screen.
 * It only ever takes a TV that is free: asleep, on its screensaver, or on the home screen.
 */
public class Watch extends Service implements Runnable {
    static volatile boolean dismissed;   // someone closed the screen during this run of music
    volatile boolean running, dreaming;
    boolean opened;                      // the screen that is up is one we opened
    String front;                        // package of the app in front, as far as usage events have told us
    long checked;                        // usage events are read from here on

    static void start(Context context) {
        context.startForegroundService(new Intent(context, Watch.class));
    }

    /** The watcher's address for this TV's room, e.g. url(prefs, "/state"); null until set up. */
    static String url(SharedPreferences prefs, String path) {
        String server = prefs.getString("server", null), room = prefs.getString("room", null);
        if (server == null || room == null) return null;
        return server.replaceAll("/+$", "") + path + "?room=" + Uri.encode(room) + "&screen=tv";
    }

    final BroadcastReceiver dreams = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            dreaming = Intent.ACTION_DREAMING_STARTED.equals(intent.getAction());
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("watch", "JamFrame", NotificationManager.IMPORTANCE_MIN));
        startForeground(1, new Notification.Builder(this, "watch").setContentTitle("JamFrame")
                .setContentText("Waiting for music").setSmallIcon(android.R.drawable.ic_media_play).build());
        IntentFilter filter = new IntentFilter(Intent.ACTION_DREAMING_STARTED);
        filter.addAction(Intent.ACTION_DREAMING_STOPPED);
        registerReceiver(dreams, filter);
        checked = System.currentTimeMillis() - 12 * 3600 * 1000L;
        running = true;
        new Thread(this, "jamframe").start();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int id) {
        return START_STICKY;
    }

    @Override
    public void run() {
        while (running) {
            try {
                step();
            } catch (Exception e) {
                // watcher off, Wi-Fi blip: the next round tries again
            }
            try {
                Thread.sleep(3000);
            } catch (InterruptedException e) {
                return;
            }
        }
    }

    void step() throws Exception {
        String url = url(getSharedPreferences("jamframe", MODE_PRIVATE), "/state");
        if (url == null) return;
        boolean music = !new JSONObject(get(url)).isNull("art");
        if (!music) dismissed = false;
        Main screen = Main.showing;
        if (music && screen == null && !dismissed && free()) {
            // the screen itself asks to be turned on; this wakes a sleeping TV so that it can
            PowerManager power = getSystemService(PowerManager.class);
            power.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP, "jamframe:show")
                    .acquire(10000);
            startActivity(new Intent(this, Main.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            opened = true;
        } else if (!music && screen != null && opened) {
            opened = false;
            screen.runOnUiThread(screen::close);
        }
    }

    /** Is nobody using the TV? Asleep, on the screensaver, or on the home screen. Not knowing counts as in use. */
    boolean free() {
        if (!getSystemService(PowerManager.class).isInteractive() || dreaming) return true;
        long now = System.currentTimeMillis();
        UsageEvents events = getSystemService(UsageStatsManager.class).queryEvents(checked, now);
        UsageEvents.Event event = new UsageEvents.Event();
        while (events.hasNextEvent()) {
            events.getNextEvent(event);
            if (event.getEventType() == UsageEvents.Event.ACTIVITY_RESUMED) front = event.getPackageName();
        }
        checked = now;
        ResolveInfo home = getPackageManager().resolveActivity(
                new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), 0);
        return front != null && home != null && front.equals(home.activityInfo.packageName);
    }

    static String get(String address) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(address).openConnection();
        c.setConnectTimeout(4000);
        c.setReadTimeout(4000);
        try (InputStream in = c.getInputStream()) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            for (int n; (n = in.read(buffer)) > 0; ) out.write(buffer, 0, n);
            return out.toString("UTF-8");
        } finally {
            c.disconnect();
        }
    }

    @Override
    public void onDestroy() {
        running = false;
        unregisterReceiver(dreams);
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
