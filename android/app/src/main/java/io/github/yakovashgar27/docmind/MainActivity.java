package io.github.yakovashgar27.docmind;

import android.Manifest;
import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Base64;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.webkit.WebViewAssetLoader;

import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * DocMind for Android: hosts the phone edition (bundled in assets/www) in a WebView served from a
 * virtual https origin, and adds native abilities through {@link NativeBridge}: finding document photos in
 * the gallery, scanning folders the user grants (Downloads, WhatsApp), receiving "Share → DocMind",
 * saving and sharing files. All documents are still encrypted and stored inside the app only.
 */
public class MainActivity extends Activity {
    static final String ORIGIN = "https://appassets.androidplatform.net";
    static final int REQ_FILE_CHOOSER = 1;
    static final int REQ_TREE = 2;
    static final int REQ_MEDIA_PERMISSION = 3;

    WebView web;
    NativeBridge bridge;
    private ValueCallback<Uri[]> fileCallback;
    final List<Uri> sharedInbox = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        setContentView(web);
        bridge = new NativeBridge(this);

        WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
                .addPathHandler("/app/", new WebViewAssetLoader.AssetsPathHandler(this))
                .addPathHandler("/native/", this::serveNative)
                .build();

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return loader.shouldInterceptRequest(request.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                if (ORIGIN.equals(u.getScheme() + "://" + u.getHost())) return false;
                // External links (official sites, gov.il...) open in the browser.
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) { }
                return true;
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                i.setType("*/*");
                String[] accept = params.getAcceptTypes();
                boolean zip = accept != null && accept.length > 0 && accept[0].contains("zip");
                i.putExtra(Intent.EXTRA_MIME_TYPES, zip ? new String[]{"application/zip"}
                        : new String[]{"application/pdf", "image/*", "text/plain"});
                i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                try {
                    startActivityForResult(i, REQ_FILE_CHOOSER);
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });
        web.addJavascriptInterface(bridge, "DocMindNative");
        collectShared(getIntent());
        web.loadUrl(ORIGIN + "/app/www/index.html");
    }

    /** /native/file/{base64url(content-uri)} streams a granted file to the page (read-only). */
    private WebResourceResponse serveNative(String path) {
        try {
            if (!path.startsWith("file/")) return null;
            String uriStr = new String(Base64.decode(path.substring(5), Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING), "UTF-8");
            Uri uri = Uri.parse(uriStr);
            if (!bridge.isAllowed(uri)) return new WebResourceResponse("text/plain", "utf-8", 403, "Forbidden", null, null);
            InputStream in;
            String mime;
            if ("file".equals(uri.getScheme())) {
                in = new java.io.FileInputStream(new java.io.File(uri.getPath()));
                mime = NativeBridge.mimeOf(uri.getPath());
            } else {
                in = getContentResolver().openInputStream(uri);
                mime = getContentResolver().getType(uri);
            }
            return new WebResourceResponse(mime != null ? mime : "application/octet-stream", null, in);
        } catch (Exception e) {
            return new WebResourceResponse("text/plain", "utf-8", 404, "Not found", null, null);
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (collectShared(intent)) bridge.emit("shared", "{}");
    }

    private boolean collectShared(Intent intent) {
        if (intent == null) return false;
        String action = intent.getAction();
        List<Uri> uris = new ArrayList<>();
        if (Intent.ACTION_SEND.equals(action)) {
            Uri u = intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (u != null) uris.add(u);
        } else if (Intent.ACTION_SEND_MULTIPLE.equals(action)) {
            ArrayList<Uri> list = intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (list != null) uris.addAll(list);
        } else if (Intent.ACTION_VIEW.equals(action) && intent.getData() != null) {
            uris.add(intent.getData());
        }
        ClipData clip = intent.getClipData();
        if (clip != null && uris.isEmpty()) for (int i = 0; i < clip.getItemCount(); i++) {
            Uri u = clip.getItemAt(i).getUri();
            if (u != null) uris.add(u);
        }
        if (uris.isEmpty()) return false;
        synchronized (sharedInbox) {
            sharedInbox.addAll(uris);
            for (Uri u : uris) bridge.allow(u);
        }
        return true;
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_FILE_CHOOSER) {
            Uri[] result = null;
            if (resultCode == RESULT_OK && data != null) {
                if (data.getClipData() != null) {
                    ClipData c = data.getClipData();
                    result = new Uri[c.getItemCount()];
                    for (int i = 0; i < c.getItemCount(); i++) result[i] = c.getItemAt(i).getUri();
                } else if (data.getData() != null) {
                    result = new Uri[]{data.getData()};
                }
            }
            if (fileCallback != null) fileCallback.onReceiveValue(result);
            fileCallback = null;
        } else if (requestCode == REQ_TREE) {
            bridge.onTreeResult(resultCode == RESULT_OK && data != null ? data.getData() : null);
        }
    }

    void requestMediaPermission() {
        String[] p = Build.VERSION.SDK_INT >= 34
                ? new String[]{Manifest.permission.READ_MEDIA_IMAGES, "android.permission.READ_MEDIA_VISUAL_USER_SELECTED"}
                : Build.VERSION.SDK_INT >= 33 ? new String[]{Manifest.permission.READ_MEDIA_IMAGES}
                : new String[]{Manifest.permission.READ_EXTERNAL_STORAGE};
        requestPermissions(p, REQ_MEDIA_PERMISSION);
    }

    boolean hasMediaPermission() {
        String p = Build.VERSION.SDK_INT >= 33 ? Manifest.permission.READ_MEDIA_IMAGES : Manifest.permission.READ_EXTERNAL_STORAGE;
        if (checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED) return true;
        // Android 14+: "Select photos" partial access also lets us read the photos the user picked.
        return Build.VERSION.SDK_INT >= 34
                && checkSelfPermission("android.permission.READ_MEDIA_VISUAL_USER_SELECTED") == PackageManager.PERMISSION_GRANTED;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_MEDIA_PERMISSION) bridge.emit("permission", "{\"media\":" + hasMediaPermission() + "}");
    }

    @Override
    protected void onResume() {
        super.onResume();
        // Returning from Settings after granting "All files access".
        if (bridge != null) bridge.emit("permission", "{\"media\":" + hasMediaPermission() + ",\"allFiles\":" + NativeBridge.hasAllFiles() + "}");
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }
}
