package com.jamframe.tv;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Starts watching again after the TV restarts. */
public class Boot extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) Watch.start(context);
    }
}
