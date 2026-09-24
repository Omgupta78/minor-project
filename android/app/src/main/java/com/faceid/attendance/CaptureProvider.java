package com.faceid.attendance;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.IOException;

/**
 * Somewhere for the camera app to put the class photo.
 *
 * A camera started with ACTION_IMAGE_CAPTURE writes the full-resolution image
 * to a uri you hand it, and since Android 7 handing it a file:// path throws
 * FileUriExposedException. The usual answer is AndroidX's FileProvider, but
 * this app deliberately carries no dependencies, so here is the part of it
 * that is actually needed: one directory inside our own cache, served over
 * content://.
 *
 * Nothing else can reach it. The provider is not exported, the camera is given
 * a one-shot grant for a single uri, and the directory is emptied on launch --
 * a class photo of 120 students is several megabytes and there is no reason to
 * keep yesterday's.
 */
public class CaptureProvider extends ContentProvider {

    public static final String AUTHORITY = "com.faceid.attendance.captures";
    private static final String DIR = "captures";

    private static File directory(Context context) {
        return new File(context.getCacheDir(), DIR);
    }

    /** A fresh uri for the camera to write into. */
    public static Uri newImageUri(Context context) throws IOException {
        File dir = directory(context);
        if (!dir.isDirectory() && !dir.mkdirs()) {
            throw new IOException("cannot create " + dir);
        }
        File file = File.createTempFile("capture-", ".jpg", dir);
        return new Uri.Builder()
                .scheme("content").authority(AUTHORITY)
                .appendPath(file.getName())
                .build();
    }

    /** Drop everything taken earlier. Called once, when the app starts. */
    public static void clear(Context context) {
        File[] old = directory(context).listFiles();
        if (old == null) return;
        for (File file : old) {
            // Best effort: a file the camera still holds open will go next time.
            file.delete();
        }
    }

    /**
     * The uri's path names one file directly inside our capture directory.
     *
     * Only the last segment is used and it is checked afterwards against the
     * directory's canonical path, so "../../databases/webview.db" resolves
     * somewhere we refuse rather than somewhere we serve.
     */
    private File resolve(Uri uri) throws FileNotFoundException {
        Context context = getContext();
        String name = uri.getLastPathSegment();
        if (context == null || name == null || name.isEmpty()) {
            throw new FileNotFoundException(String.valueOf(uri));
        }
        File dir = directory(context);
        File file = new File(dir, name);
        try {
            if (!file.getCanonicalPath().startsWith(dir.getCanonicalPath() + File.separator)) {
                throw new FileNotFoundException(String.valueOf(uri));
            }
        } catch (IOException e) {
            throw new FileNotFoundException(String.valueOf(uri));
        }
        return file;
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        return ParcelFileDescriptor.open(resolve(uri), ParcelFileDescriptor.parseMode(mode));
    }

    /** Camera apps ask for the name and size before writing. */
    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] args, String sort) {
        File file;
        try {
            file = resolve(uri);
        } catch (FileNotFoundException e) {
            return null;
        }
        String[] columns = projection != null ? projection
                : new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        MatrixCursor cursor = new MatrixCursor(columns, 1);
        MatrixCursor.RowBuilder row = cursor.newRow();
        for (String column : columns) {
            if (OpenableColumns.DISPLAY_NAME.equals(column)) row.add(file.getName());
            else if (OpenableColumns.SIZE.equals(column)) row.add(file.length());
            else row.add(null);
        }
        return cursor;
    }

    @Override
    public String getType(Uri uri) {
        return "image/jpeg";
    }

    @Override
    public int delete(Uri uri, String selection, String[] args) {
        try {
            return resolve(uri).delete() ? 1 : 0;
        } catch (FileNotFoundException e) {
            return 0;
        }
    }

    // The camera writes through openFile; it never inserts or updates.
    @Override
    public Uri insert(Uri uri, ContentValues values) {
        throw new UnsupportedOperationException("read and write only");
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] args) {
        throw new UnsupportedOperationException("read and write only");
    }
}
