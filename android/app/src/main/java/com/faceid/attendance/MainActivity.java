package com.faceid.attendance;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

/**
 * The app is a window onto the attendance server, not a copy of it.
 *
 * Face recognition is dlib, which does not run on a phone, so the recognising
 * happens on the server and this carries the teacher's camera and their taps to
 * it. That makes the interesting work here the four things a bare WebView gets
 * wrong, each of which silently breaks a real feature:
 *
 *   1. file chooser  -- without onShowFileChooser, tapping "choose a photo"
 *                       does nothing at all, so no photo can ever be uploaded;
 *   2. camera        -- two separate paths, and over plain http only the
 *                       second one exists. getUserMedia needs a secure
 *                       context, which http://192.168.x.x is not, so the page
 *                       falls back to a file input marked `capture` -- and a
 *                       WebView ignores `capture` unless onShowFileChooser
 *                       launches the camera itself (see startCapture). The
 *                       live path, used when the server is on https, needs
 *                       onPermissionRequest to grant it AND Android to have
 *                       granted CAMERA to the app;
 *   3. downloads     -- the Excel export is a normal download, which a WebView
 *                       ignores unless a DownloadListener hands it on;
 *   4. back button   -- otherwise it closes the app from the first page in
 *                       instead of going back.
 */
public class MainActivity extends Activity {

    public static final String PREFS = "faceid";
    public static final String KEY_SERVER = "server_url";

    private static final int REQ_CAMERA = 101;         // getUserMedia asked for it
    private static final int REQ_FILE = 102;           // pick a file
    private static final int REQ_CAPTURE = 103;        // take a photo now
    private static final int REQ_CAPTURE_PERM = 104;   // CAMERA, so we can

    private WebView web;
    private ValueCallback<Uri[]> pendingFiles;
    private WebChromeClient.FileChooserParams pendingChooser;
    private PermissionRequest pendingCamera;
    private Uri captureUri;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);

        String server = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_SERVER, null);
        if (server == null || server.trim().isEmpty()) {
            startActivity(new Intent(this, SetupActivity.class));
            finish();
            return;
        }

        web = new WebView(this);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);            // the review screen keeps state here
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setMediaPlaybackRequiresUserGesture(false);   // or the camera never starts
        s.setAllowFileAccess(false);                    // no reason to read the disk
        s.setAllowContentAccess(false);
        CookieManager.getInstance().setAcceptCookie(true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri uri = r.getUrl();
                String host = Uri.parse(currentServer()).getHost();
                // Anything on the attendance server stays in the app; anything
                // else is somebody else's website and belongs in a browser.
                if (host != null && host.equalsIgnoreCase(uri.getHost())) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (Exception ignored) { }
                return true;
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r != null && !r.isForMainFrame()) return;
                showUnreachable();
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (pendingFiles != null) pendingFiles.onReceiveValue(null);
                pendingFiles = callback;
                pendingChooser = params;

                // createIntent() builds a document picker and drops `capture`
                // on the floor, so the page's "take a photo now" input would
                // open a file browser instead of the camera. Only this side
                // can tell the difference.
                if (params.isCaptureEnabled() && hasCamera()) {
                    if (checkSelfPermission(Manifest.permission.CAMERA)
                            != PackageManager.PERMISSION_GRANTED) {
                        requestPermissions(new String[]{Manifest.permission.CAMERA},
                                REQ_CAPTURE_PERM);
                        return true;   // picked up again in onRequestPermissionsResult
                    }
                    if (startCapture()) return true;
                }
                return startBrowse();
            }

            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(() -> {
                    pendingCamera = request;
                    if (checkSelfPermission(Manifest.permission.CAMERA)
                            == PackageManager.PERMISSION_GRANTED) {
                        grantCamera();
                    } else {
                        requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
                    }
                });
            }
        });

        // The Excel report is a plain download; hand it to the system.
        web.setDownloadListener((url, agent, disposition, mime, size) -> {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
            } catch (Exception e) {
                Toast.makeText(this, "No app can open that download", Toast.LENGTH_LONG).show();
            }
        });

        // A class photo is several megabytes and is uploaded the moment it is
        // taken; nothing needs yesterday's still sitting in the cache.
        CaptureProvider.clear(this);

        if (state != null) web.restoreState(state);
        else web.loadUrl(server);
    }

    private String currentServer() {
        return getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_SERVER, "");
    }

    private boolean hasCamera() {
        return getPackageManager().hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY);
    }

    /** Open the camera, writing full resolution into a file we own. */
    private boolean startCapture() {
        try {
            captureUri = CaptureProvider.newImageUri(this);
            Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            intent.putExtra(MediaStore.EXTRA_OUTPUT, captureUri);
            // A uri in an extra is not covered by the grant flags -- those
            // reach the intent's data and its clip data only. Without this
            // line the camera is handed a uri it may not write to, and the
            // photo comes back empty on a good many phones.
            intent.setClipData(ClipData.newRawUri("", captureUri));
            intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                    | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            if (intent.resolveActivity(getPackageManager()) == null) return false;
            startActivityForResult(intent, REQ_CAPTURE);
            return true;
        } catch (Exception e) {
            captureUri = null;
            return false;
        }
    }

    /** The ordinary "choose a file" path, and what everything else falls back to. */
    private boolean startBrowse() {
        try {
            Intent intent = pendingChooser != null
                    ? pendingChooser.createIntent()
                    : new Intent(Intent.ACTION_GET_CONTENT).setType("image/*");
            startActivityForResult(intent, REQ_FILE);
            return true;
        } catch (Exception e) {
            finishChooser(null);
            return false;
        }
    }

    /**
     * Answer the page, exactly once.
     *
     * Null means the teacher cancelled. Skipping it altogether leaves the file
     * input wedged and it never opens again, which looks like the button has
     * stopped working.
     */
    private void finishChooser(Uri[] result) {
        if (pendingFiles != null) pendingFiles.onReceiveValue(result);
        pendingFiles = null;
        pendingChooser = null;
    }

    private void grantCamera() {
        if (pendingCamera == null) return;
        pendingCamera.grant(pendingCamera.getResources());
        pendingCamera = null;
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        boolean granted = results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED;

        if (code == REQ_CAPTURE_PERM) {
            // Refusing the camera should not strand the teacher: the gallery
            // still has whatever they photographed with the camera app.
            if (!granted || !startCapture()) startBrowse();
            return;
        }
        if (code != REQ_CAMERA) {
            super.onRequestPermissionsResult(code, perms, results);
            return;
        }
        if (granted) {
            grantCamera();
        } else {
            if (pendingCamera != null) pendingCamera.deny();
            pendingCamera = null;
            Toast.makeText(this,
                    "Camera permission refused. You can still choose a photo from the gallery.",
                    Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onActivityResult(int code, int result, Intent data) {
        if (code == REQ_CAPTURE) {
            Uri taken = captureUri;
            captureUri = null;
            // The camera returns no data: the photo went to the uri we gave it.
            boolean ok = result == RESULT_OK && taken != null;
            finishChooser(ok ? new Uri[]{taken} : null);
            return;
        }
        if (code != REQ_FILE) {
            super.onActivityResult(code, result, data);
            return;
        }
        finishChooser(WebChromeClient.FileChooserParams.parseResult(result, data));
    }

    private void showUnreachable() {
        new AlertDialog.Builder(this)
                .setTitle("Cannot reach the server")
                .setMessage("The attendance server at\n\n" + currentServer()
                        + "\n\nis not answering. Check that it is running and that "
                        + "this phone is on the same Wi-Fi network.")
                .setPositiveButton("Try again", (d, w) -> web.reload())
                .setNegativeButton("Change address", (d, w) -> {
                    startActivity(new Intent(this, SetupActivity.class));
                    finish();
                })
                .setCancelable(false)
                .show();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        if (web != null) web.saveState(out);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
