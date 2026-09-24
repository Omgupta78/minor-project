package com.faceid.attendance;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Asks once where the attendance server is.
 *
 * The address is not baked into the app on purpose: a laptop's address on the
 * college Wi-Fi changes, and the same build has to work for a laptop on the
 * LAN, a Render deployment and a demo on the marker's own machine. Building a
 * new APK every time an IP changes is not a workflow anybody would accept.
 *
 * The layout is written in code rather than XML because it is one screen of
 * four views, and a layout file would be more moving parts than it saves.
 */
public class SetupActivity extends Activity {

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);

        SharedPreferences prefs = getSharedPreferences(MainActivity.PREFS, MODE_PRIVATE);

        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad * 2, pad, pad);
        root.setGravity(Gravity.CENTER_VERTICAL);

        TextView title = new TextView(this);
        title.setText("Attendance server");
        title.setTextSize(22);
        root.addView(title);

        TextView help = new TextView(this);
        help.setText("Type the address the attendance server is running on.\n\n"
                + "On a laptop on the same Wi-Fi this looks like\n"
                + "http://192.168.1.14:5000\n\n"
                + "Find it by running  ipconfig  (Windows) or  ifconfig  (Mac) on "
                + "the laptop, and use that address rather than 127.0.0.1 -- on the "
                + "phone, 127.0.0.1 means the phone itself.");
        help.setPadding(0, pad / 2, 0, pad);
        root.addView(help);

        final EditText field = new EditText(this);
        field.setHint("http://192.168.1.14:5000");
        field.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        field.setSingleLine(true);
        field.setText(prefs.getString(MainActivity.KEY_SERVER, ""));
        root.addView(field, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        Button save = new Button(this);
        save.setText("Connect");
        save.setOnClickListener(v -> {
            String url = normalise(field.getText().toString());
            if (url == null) {
                Toast.makeText(this,
                        "That does not look like an address. It should start with http.",
                        Toast.LENGTH_LONG).show();
                return;
            }
            prefs.edit().putString(MainActivity.KEY_SERVER, url).apply();
            startActivity(new Intent(this, MainActivity.class));
            finish();
        });
        root.addView(save);

        setContentView(root);
    }

    /**
     * Tidy what was typed, or return null if it cannot be salvaged.
     *
     * People type "192.168.1.14:5000" without a scheme far more often than not,
     * so add one rather than rejecting it and making them guess what is wrong.
     */
    static String normalise(String raw) {
        String url = raw == null ? "" : raw.trim();
        if (url.isEmpty()) return null;
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://" + url;
        }
        while (url.endsWith("/")) url = url.substring(0, url.length() - 1);
        // Must have something after the scheme to be an address at all.
        String rest = url.substring(url.indexOf("//") + 2);
        if (rest.isEmpty() || rest.startsWith(":")) return null;
        return url;
    }
}
