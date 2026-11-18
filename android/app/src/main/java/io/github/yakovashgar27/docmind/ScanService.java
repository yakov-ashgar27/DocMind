package io.github.yakovashgar27.docmind;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

/**
 * Keeps the phone scan running with the screen off or the app in the background: a foreground service
 * (visible, ongoing notification with progress — Android's required, honest way to work in the background)
 * plus a partial wake lock so the CPU doesn't sleep. The indexing itself runs in the app's WebView; this
 * service only keeps the process awake and alive. It stops itself when the scan ends (or after 6 hours).
 */
public class ScanService extends Service {
    static final String CHANNEL = "scan";
    static final int NOTIF_ID = 42;
    static volatile boolean running = false;
    private PowerManager.WakeLock wake;

    static void start(Context c) {
        Intent i = new Intent(c, ScanService.class);
        if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i); else c.startService(i);
    }

    static void stop(Context c) { c.stopService(new Intent(c, ScanService.class)); }

    static void update(Context c, int stage, int done, int total, int docs) {
        if (!running) return;
        NotificationManager nm = (NotificationManager) c.getSystemService(NOTIFICATION_SERVICE);
        if (nm != null) nm.notify(NOTIF_ID, build(c, stage, done, total, docs));
    }

    static Notification build(Context c, int stage, int done, int total, int docs) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = (NotificationManager) c.getSystemService(NOTIFICATION_SERVICE);
            if (nm != null && nm.getNotificationChannel(CHANNEL) == null) {
                NotificationChannel ch = new NotificationChannel(CHANNEL, "סריקת הטלפון", NotificationManager.IMPORTANCE_LOW);
                ch.setDescription("התקדמות סריקת המסמכים בטלפון");
                ch.setShowBadge(false);
                nm.createNotificationChannel(ch);
            }
        }
        Intent open = new Intent(c, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pi = PendingIntent.getActivity(c, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        String title = stage == 2 ? "DocMind קורא צילומי מסמכים" : "DocMind סורק את הטלפון";
        String text = total > 0 ? done + " / " + total + (docs > 0 ? " · " + docs + " מסמכים זוהו" : "") : "מכין רשימת קבצים…";
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, CHANNEL) : new Notification.Builder(c);
        b.setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle(title)
                .setContentText(text)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setContentIntent(pi)
                .setProgress(Math.max(total, 0), Math.max(Math.min(done, total), 0), total <= 0);
        if (Build.VERSION.SDK_INT >= 31) b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        return b.build();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Notification n = build(this, 1, 0, 0, 0);
        if (Build.VERSION.SDK_INT >= 34) startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        else startForeground(NOTIF_ID, n);
        running = true;
        if (wake == null) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            wake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "DocMind:scan");
            wake.setReferenceCounted(false);
        }
        wake.acquire(6 * 60 * 60 * 1000L);        // safety cap: never hold the CPU awake more than 6 hours
        return START_NOT_STICKY;                   // the scan lives in the app; if Android kills it, it resumes on next open
    }

    @Override
    public void onTimeout(int startId) {          // Android 15 daily limit for this service type
        stopSelf();
    }

    @Override
    public void onDestroy() {
        running = false;
        if (wake != null && wake.isHeld()) wake.release();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
