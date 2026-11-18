package io.github.yakovashgar27.docmind;

import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.Settings;
import android.provider.DocumentsContract;
import android.provider.MediaStore;
import android.provider.OpenableColumns;
import android.util.Base64;
import android.webkit.JavascriptInterface;

import androidx.core.content.FileProvider;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Set;

/**
 * JavaScript ↔ Android bridge, exposed as window.DocMindNative. Only metadata and file streams the user
 * granted ever cross it; files are read by the page through /native/file/... and encrypted there.
 */
public class NativeBridge {
    private static final int MAX_FOLDER_FILES = 60_000;
    private static final int MAX_DEPTH = 14;
    private final MainActivity act;
    private final SharedPreferences prefs;
    private final Set<String> allowed = new HashSet<>();
    private String pendingFolderKind;

    NativeBridge(MainActivity act) {
        this.act = act;
        this.prefs = act.getSharedPreferences("docmind_native", 0);
    }

    // ---- helpers --------------------------------------------------------------------------
    void allow(Uri u) { synchronized (allowed) { allowed.add(u.toString()); } }
    boolean isAllowed(Uri u) { synchronized (allowed) { return allowed.contains(u.toString()); } }

    void emit(String event, String json) {
        final String js = "window.__docmindNative && window.__docmindNative(" + JSONObject.quote(event) + "," + json + ")";
        act.runOnUiThread(() -> act.web.evaluateJavascript(js, null));
    }

    private JSONArray folders() {
        try { return new JSONArray(prefs.getString("folders", "[]")); } catch (Exception e) { return new JSONArray(); }
    }

    private boolean assetExists(String path) {
        try { act.getAssets().open(path).close(); return true; } catch (Exception e) { return false; }
    }

    // ---- info & permissions ----------------------------------------------------------------
    @JavascriptInterface
    public String info() {
        try {
            JSONObject o = new JSONObject();
            o.put("platform", "android");
            o.put("sdk", Build.VERSION.SDK_INT);
            o.put("media", act.hasMediaPermission());
            o.put("allFiles", hasAllFiles());
            o.put("folders", folders());
            o.put("bundledOcr", assetExists("www/vendor/tesseract/tesseract.min.js"));
            return o.toString();
        } catch (Exception e) { return "{}"; }
    }

    @JavascriptInterface
    public void requestMedia() { act.runOnUiThread(act::requestMediaPermission); }

    static boolean hasAllFiles() {
        return Build.VERSION.SDK_INT >= 30 ? Environment.isExternalStorageManager() : false;
    }

    /** Opens the system screen where the user can allow "All files access" for DocMind. */
    @JavascriptInterface
    public void requestAllFiles() {
        act.runOnUiThread(() -> {
            if (Build.VERSION.SDK_INT < 30) { act.requestMediaPermission(); return; }
            try {
                act.startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                        Uri.parse("package:" + act.getPackageName())));
            } catch (Exception e) {
                act.startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
            }
        });
    }

    static String mimeOf(String path) {
        String p = path.toLowerCase();
        if (p.endsWith(".pdf")) return "application/pdf";
        if (p.endsWith(".jpg") || p.endsWith(".jpeg")) return "image/jpeg";
        if (p.endsWith(".png")) return "image/png";
        if (p.endsWith(".webp")) return "image/webp";
        if (p.endsWith(".heic") || p.endsWith(".heif")) return "image/heic";
        if (p.endsWith(".docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
        if (p.endsWith(".doc")) return "application/msword";
        return null;
    }

    /**
     * Full scan of ALL shared storage (needs "All files access"): the whole internal storage and any memory card,
     * every folder and any age. Only places that never hold documents are skipped (app caches, thumbnails, music,
     * ringtones, voice notes, stickers, videos).
     */
    private void scanFileSystem(JSONArray out, long sinceMs) throws Exception {
        Set<String> seen = new HashSet<>();
        Set<String> roots = new HashSet<>();
        roots.add(Environment.getExternalStorageDirectory().getCanonicalPath());
        File[] vols = new File("/storage").listFiles();               // memory cards / USB drives
        if (vols != null) for (File v : vols) {
            String n = v.getName();
            if (n.equals("emulated") || n.equals("self") || !v.canRead()) continue;
            roots.add(v.getCanonicalPath());
        }
        for (String r : roots) walkFs(new File(r), 0, out, sinceMs, seen);
    }

    private static boolean skipDir(File dir, String n) {
        String p = dir.getAbsolutePath().toLowerCase();
        if (p.endsWith("/android/data") || p.endsWith("/android/obb")) return true;         // other apps' private data
        return n.contains("sticker") || n.contains("voice") || n.contains("audio") || n.contains("video") || n.contains("gif")
                || n.equals("thumbnails") || n.equals("cache") || n.equals(".cache") || n.equals("music") || n.equals("ringtones")
                || n.equals("notifications") || n.equals("alarms") || n.equals("podcasts") || n.equals("audiobooks")
                || n.equals("recordings") || n.equals("movies") || n.equals("lost.dir") || n.equals("backups") || n.equals("databases");
    }

    private void walkFs(File dir, int depth, JSONArray out, long sinceMs, Set<String> seen) throws Exception {
        if (depth > MAX_DEPTH || out.length() > MAX_FOLDER_FILES || dir == null || !dir.isDirectory()) return;
        File[] list = dir.listFiles();
        if (list == null) return;
        for (File f : list) {
            String name = f.getName();
            if (name.startsWith(".")) continue;
            if (f.isDirectory()) {
                if (skipDir(f, name.toLowerCase())) continue;
                walkFs(f, depth + 1, out, sinceMs, seen);
                continue;
            }
            String mime = mimeOf(name);
            if (mime == null) continue;
            long size = f.length(), modified = f.lastModified();
            boolean isImage = mime.startsWith("image/");
            if (size < 10_000 || size > 25_000_000) continue;
            if (isImage && modified <= sinceMs) continue; // sinceMs is 0 by default: every photo, any age
            String path = f.getCanonicalPath();
            if (!seen.add(path)) continue;
            Uri u = Uri.fromFile(f);
            String lower = path.toLowerCase();
            JSONObject o = new JSONObject();
            o.put("uri", u.toString());
            o.put("name", name);
            o.put("size", size);
            o.put("mime", mime);
            o.put("modified", modified);
            o.put("source", lower.contains("whatsapp") ? "whatsapp" : lower.contains("telegram") ? "telegram" : lower.contains("/download") ? "downloads"
                    : (lower.contains("/dcim") || lower.contains("/pictures")) ? "gallery" : "folder");
            out.put(o);
            allow(u);
        }
    }

    // ---- user-granted folders (Storage Access Framework) ----------------------------------------
    @JavascriptInterface
    public void addFolder(String kind) {
        pendingFolderKind = kind;
        act.runOnUiThread(() -> {
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
            String hint = "whatsapp".equals(kind) ? "primary:Android/media/com.whatsapp/WhatsApp/Media"
                    : "downloads".equals(kind) ? "primary:Download" : null;
            if (hint != null) {
                i.putExtra(DocumentsContract.EXTRA_INITIAL_URI,
                        DocumentsContract.buildDocumentUri("com.android.externalstorage.documents", hint));
            }
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
            try { act.startActivityForResult(i, MainActivity.REQ_TREE); } catch (Exception e) { emit("folder", "{\"ok\":false}"); }
        });
    }

    void onTreeResult(Uri tree) {
        try {
            if (tree == null) { emit("folder", "{\"ok\":false}"); return; }
            act.getContentResolver().takePersistableUriPermission(tree, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            JSONArray list = folders();
            JSONArray next = new JSONArray();
            for (int i = 0; i < list.length(); i++) if (!list.getJSONObject(i).getString("uri").equals(tree.toString())) next.put(list.get(i));
            JSONObject f = new JSONObject();
            f.put("uri", tree.toString());
            f.put("kind", pendingFolderKind == null ? "folder" : pendingFolderKind);
            String id = DocumentsContract.getTreeDocumentId(tree);
            f.put("label", id.contains(":") ? id.substring(id.indexOf(':') + 1) : id);
            next.put(f);
            prefs.edit().putString("folders", next.toString()).apply();
            emit("folder", "{\"ok\":true}");
        } catch (Exception e) {
            emit("folder", "{\"ok\":false}");
        }
    }

    @JavascriptInterface
    public void removeFolder(String uri) {
        try {
            act.getContentResolver().releasePersistableUriPermission(Uri.parse(uri), Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (Exception ignored) { }
        JSONArray list = folders(), next = new JSONArray();
        try {
            for (int i = 0; i < list.length(); i++) if (!list.getJSONObject(i).getString("uri").equals(uri)) next.put(list.get(i));
        } catch (Exception ignored) { }
        prefs.edit().putString("folders", next.toString()).apply();
    }

    // ---- background scanning (foreground service + wake lock) -----------------------------------
    @JavascriptInterface
    public void bgStart() {
        act.runOnUiThread(() -> {
            act.askNotificationPermission();
            ScanService.start(act.getApplicationContext());
            act.keepAliveInBackground(true);
        });
    }

    @JavascriptInterface
    public void bgUpdate(int stage, int done, int total, int docs) {
        ScanService.update(act.getApplicationContext(), stage, done, total, docs);
    }

    @JavascriptInterface
    public void bgStop() {
        act.runOnUiThread(() -> {
            ScanService.stop(act.getApplicationContext());
            act.keepAliveInBackground(false);
        });
    }

    // ---- scanning -----------------------------------------------------------------------------
    /** Lists candidate documents (metadata only). Result arrives as event "scan". */
    @JavascriptInterface
    public void scan(final double sinceMs, final int maxImages) {
        new Thread(() -> {
            JSONArray out = new JSONArray();
            try {
                if (hasAllFiles()) scanFileSystem(out, (long) sinceMs);
                else if (act.hasMediaPermission()) scanImages(out, (long) sinceMs, maxImages);
                JSONArray fs = folders();
                for (int i = 0; i < fs.length(); i++) {
                    JSONObject f = fs.getJSONObject(i);
                    Uri tree = Uri.parse(f.getString("uri"));
                    String root = DocumentsContract.getTreeDocumentId(tree);
                    walk(tree, root, f.getString("kind"), 0, out, (long) sinceMs);
                }
            } catch (Exception e) {
                emit("scan", "{\"error\":" + JSONObject.quote(String.valueOf(e.getMessage())) + ",\"items\":" + out + "}");
                return;
            }
            emit("scan", "{\"items\":" + out + "}");
        }, "docmind-scan").start();
    }

    private void scanImages(JSONArray out, long sinceMs, int max) throws Exception {
        ContentResolver cr = act.getContentResolver();
        String[] proj = {MediaStore.Images.Media._ID, MediaStore.Images.Media.DISPLAY_NAME, MediaStore.Images.Media.SIZE,
                MediaStore.Images.Media.MIME_TYPE, MediaStore.Images.Media.DATE_MODIFIED, MediaStore.Images.Media.BUCKET_DISPLAY_NAME};
        String sel = MediaStore.Images.Media.DATE_MODIFIED + " > ?";
        String[] args = {String.valueOf(sinceMs / 1000)};
        try (Cursor c = cr.query(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, proj, sel, args,
                MediaStore.Images.Media.DATE_MODIFIED + " DESC")) {
            if (c == null) return;
            int n = 0;
            while (c.moveToNext() && n < max) {
                long id = c.getLong(0);
                long size = c.getLong(2);
                if (size < 20_000 || size > 25_000_000) continue; // icons / huge files are not documents
                Uri u = ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id);
                String bucket = c.getString(5) == null ? "" : c.getString(5);
                JSONObject o = new JSONObject();
                o.put("uri", u.toString());
                o.put("name", c.getString(1));
                o.put("size", size);
                o.put("mime", c.getString(3));
                o.put("modified", c.getLong(4) * 1000);
                o.put("source", bucket.toLowerCase().contains("whatsapp") ? "whatsapp" : "gallery");
                out.put(o);
                allow(u);
                n++;
            }
        }
    }

    private void walk(Uri tree, String docId, String kind, int depth, JSONArray out, long sinceMs) throws Exception {
        if (depth > MAX_DEPTH || out.length() > MAX_FOLDER_FILES) return;
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, docId);
        String[] proj = {DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE, DocumentsContract.Document.COLUMN_SIZE,
                DocumentsContract.Document.COLUMN_LAST_MODIFIED};
        try (Cursor c = act.getContentResolver().query(children, proj, null, null, null)) {
            if (c == null) return;
            while (c.moveToNext()) {
                String id = c.getString(0), name = c.getString(1), mime = c.getString(2);
                if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)) {
                    if (name != null && (name.startsWith(".") || name.equalsIgnoreCase("Sent") && depth > 2)) continue;
                    walk(tree, id, kind, depth + 1, out, sinceMs);
                    continue;
                }
                if (mime == null || mimeOf(name == null ? "" : name) == null && !(mime.equals("application/pdf") || mime.startsWith("image/"))) continue;
                long size = c.isNull(3) ? 0 : c.getLong(3);
                long modified = c.isNull(4) ? 0 : c.getLong(4);
                if (size < 10_000 || size > 25_000_000 || modified <= sinceMs) continue;
                Uri u = DocumentsContract.buildDocumentUriUsingTree(tree, id);
                JSONObject o = new JSONObject();
                o.put("uri", u.toString());
                o.put("name", name);
                o.put("size", size);
                o.put("mime", mime);
                o.put("modified", modified);
                o.put("source", kind.equals("whatsapp") ? "whatsapp" : kind.equals("downloads") ? "downloads" : "folder");
                out.put(o);
                allow(u);
            }
        }
    }

    // ---- "Share → DocMind" inbox -----------------------------------------------------------------
    @JavascriptInterface
    public String takeShared() {
        JSONArray out = new JSONArray();
        synchronized (act.sharedInbox) {
            for (Uri u : act.sharedInbox) {
                try {
                    JSONObject o = new JSONObject();
                    o.put("uri", u.toString());
                    String name = "document";
                    long size = 0;
                    try (Cursor c = act.getContentResolver().query(u, new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}, null, null, null)) {
                        if (c != null && c.moveToFirst()) { name = c.getString(0); size = c.getLong(1); }
                    } catch (Exception ignored) { }
                    o.put("name", name);
                    o.put("size", size);
                    o.put("mime", act.getContentResolver().getType(u));
                    out.put(o);
                } catch (Exception ignored) { }
            }
            act.sharedInbox.clear();
        }
        return out.toString();
    }

    // ---- saving and sharing files -------------------------------------------------------------------
    @JavascriptInterface
    public String saveFile(String name, String mime, String b64) {
        try {
            byte[] bytes = Base64.decode(b64, Base64.DEFAULT);
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues v = new ContentValues();
                v.put(MediaStore.MediaColumns.DISPLAY_NAME, safe(name));
                v.put(MediaStore.MediaColumns.MIME_TYPE, mime);
                v.put(MediaStore.MediaColumns.RELATIVE_PATH, "Download/DocMind");
                Uri u = act.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (u == null) return "error";
                try (OutputStream os = act.getContentResolver().openOutputStream(u)) { os.write(bytes); }
                return "saved";
            }
            shareBytes(new String[]{name}, new String[]{mime}, new byte[][]{bytes});
            return "shared";
        } catch (Exception e) {
            return "error";
        }
    }

    @JavascriptInterface
    public String shareFiles(String json) {
        try {
            JSONArray a = new JSONArray(json);
            String[] names = new String[a.length()], mimes = new String[a.length()];
            byte[][] data = new byte[a.length()][];
            for (int i = 0; i < a.length(); i++) {
                JSONObject o = a.getJSONObject(i);
                names[i] = o.getString("name");
                mimes[i] = o.optString("mime", "application/octet-stream");
                data[i] = Base64.decode(o.getString("b64"), Base64.DEFAULT);
            }
            shareBytes(names, mimes, data);
            return "ok";
        } catch (Exception e) {
            return "error";
        }
    }

    private void shareBytes(String[] names, String[] mimes, byte[][] data) throws Exception {
        File dir = new File(act.getCacheDir(), "share");
        File[] old = dir.listFiles();
        if (old != null) for (File f : old) f.delete(); // never keep decrypted copies around
        dir.mkdirs();
        ArrayList<Uri> uris = new ArrayList<>();
        for (int i = 0; i < names.length; i++) {
            File f = new File(dir, safe(names[i]));
            try (FileOutputStream fos = new FileOutputStream(f)) { fos.write(data[i]); }
            uris.add(FileProvider.getUriForFile(act, act.getPackageName() + ".files", f));
        }
        Intent send = new Intent(uris.size() == 1 ? Intent.ACTION_SEND : Intent.ACTION_SEND_MULTIPLE);
        send.setType(names.length == 1 ? mimes[0] : "*/*");
        if (uris.size() == 1) send.putExtra(Intent.EXTRA_STREAM, uris.get(0));
        else send.putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris);
        send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        act.runOnUiThread(() -> act.startActivity(Intent.createChooser(send, null)));
    }

    private static String safe(String n) {
        String s = n == null ? "document" : n.replaceAll("[\\\\/:*?\"<>|\\x00-\\x1f]", "_").trim();
        return s.isEmpty() ? "document" : s;
    }
}
