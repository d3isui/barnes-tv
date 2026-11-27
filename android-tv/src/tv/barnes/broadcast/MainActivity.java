package tv.barnes.broadcast;

import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.graphics.Bitmap;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.URL;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Barnes TV for Google TV / Android TV.
 *
 * Finds the Barnes Television Broadcasting System server on the local network (or takes a typed address), then
 * shows its TV page full screen. The TV page does the playing; this app passes the remote's buttons to it:
 * D-pad up/down = channel, OK = guide, left = last channel, right = info, CH+/CH- (TV remotes), Back = close/exit.
 */
public class MainActivity extends Activity {
    static final int PORT = 8420;
    static final int NAVY = 0xFF0B1020, PANEL = 0xFF18234A, GOLD = 0xFFFFD23F, SUB = 0xFFBFDBFE;

    final Handler ui = new Handler(Looper.getMainLooper());
    SharedPreferences prefs;
    WebView web;
    String server;
    TextView status;
    LinearLayout foundList;
    EditText addressBox;
    volatile int scanId = 0;
    final Map<String, String> found = Collections.synchronizedMap(new LinkedHashMap<String, String>());

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        prefs = getSharedPreferences("barnes", MODE_PRIVATE);
        server = prefs.getString("server", null);
        if (server != null) showTv(server);
        else showSetup(null);
    }

    // ------------------------------------------------------------------ setup screen
    int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    TextView text(String s, float size, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(size);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setGravity(Gravity.CENTER_HORIZONTAL);
        return t;
    }

    Button button(String label) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setTextSize(20);
        b.setTextColor(Color.WHITE);
        b.setFocusable(true);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(PANEL);
        bg.setCornerRadius(dp(10));
        b.setBackground(bg);
        b.setPadding(dp(24), dp(12), dp(24), dp(12));
        b.setOnFocusChangeListener(new View.OnFocusChangeListener() {
            public void onFocusChange(View v, boolean has) {
                GradientDrawable d = new GradientDrawable();
                d.setColor(has ? GOLD : PANEL);
                d.setCornerRadius(dp(10));
                v.setBackground(d);
                ((Button) v).setTextColor(has ? 0xFF1A1400 : Color.WHITE);
            }
        });
        return b;
    }

    LinearLayout.LayoutParams gap(int top) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.gravity = Gravity.CENTER_HORIZONTAL;
        lp.topMargin = dp(top);
        return lp;
    }

    void showSetup(String message) {
        if (web != null) {
            web.destroy();
            web = null;
        }
        found.clear();
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(NAVY);
        scroll.setFillViewport(true);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setPadding(dp(48), dp(32), dp(48), dp(32));
        scroll.addView(box, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        String name = brand();
        box.addView(text(name.toUpperCase(), 44, GOLD, true));
        box.addView(text("Barnes TV".equals(name) ? "Television Broadcasting System" : "Live TV", 18, SUB, false));
        status = text(message != null ? message : "Looking for your " + brand() + " server on this network…", 20, Color.WHITE, false);
        box.addView(status, gap(28));
        foundList = new LinearLayout(this);
        foundList.setOrientation(LinearLayout.VERTICAL);
        foundList.setGravity(Gravity.CENTER_HORIZONTAL);
        box.addView(foundList, gap(16));

        Button again = button("Search again");
        again.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                startScan();
            }
        });
        box.addView(again, gap(16));

        box.addView(text("Or type the address of the computer running it:", 16, SUB, false), gap(28));
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER);
        addressBox = new EditText(this);
        addressBox.setHint("192.168.1.20");
        addressBox.setHintTextColor(0xFF6B7AA8);
        addressBox.setTextColor(Color.WHITE);
        addressBox.setTextSize(22);
        addressBox.setSingleLine(true);
        addressBox.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        addressBox.setImeOptions(EditorInfo.IME_ACTION_GO);
        addressBox.setMinWidth(dp(320));
        String saved = prefs.getString("server", null);
        if (saved != null) addressBox.setText(Uri.parse(saved).getHost() + (Uri.parse(saved).getPort() != PORT ? ":" + Uri.parse(saved).getPort() : ""));
        Button go = button("Connect");
        go.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                connectTyped();
            }
        });
        addressBox.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            public boolean onEditorAction(TextView v, int id, KeyEvent e) {
                connectTyped();
                return true;
            }
        });
        row.addView(addressBox);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.leftMargin = dp(12);
        row.addView(go, lp);
        box.addView(row, gap(8));
        box.addView(text("The address is shown in the admin page under Connect to Jellyfin.", 14, 0xFF94A3D6, false), gap(10));
        setContentView(scroll);
        again.requestFocus();
        startScan();
    }

    void connectTyped() {
        String s = addressBox.getText().toString().trim();
        if (s.isEmpty()) return;
        if (!s.startsWith("http")) s = "http://" + s;
        Uri u = Uri.parse(s);
        final String base = "http://" + u.getHost() + ":" + (u.getPort() > 0 ? u.getPort() : PORT);
        status.setText("Checking " + base + " …");
        new Thread(new Runnable() {
            public void run() {
                final String name = probe(base, 4000);
                ui.post(new Runnable() {
                    public void run() {
                        if (name != null) connect(base);
                        else status.setText("No " + brand() + " server answered at " + base + ". Check the address and that it's running.");
                    }
                });
            }
        }).start();
    }

    // ------------------------------------------------------------------ finding the server
    static String probe(String base, int timeout) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(base + "/api/tvapp/hello").openConnection();
            c.setConnectTimeout(timeout);
            c.setReadTimeout(timeout * 2);
            if (c.getResponseCode() != 200) return null;
            InputStream in = c.getInputStream();
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0 && out.size() < 65536) out.write(buf, 0, n);
            String body = out.toString("UTF-8");
            if (!body.contains("barnes-tv")) return null;
            Matcher m = Pattern.compile("\"name\"\\s*:\\s*\"([^\"]*)\"").matcher(body);
            return m.find() ? m.group(1) : appName;
        } catch (Exception e) {
            return null;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    static List<String> subnets() {
        List<String> out = new ArrayList<String>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InetAddress a : Collections.list(ni.getInetAddresses())) {
                    if (a instanceof Inet4Address && a.isSiteLocalAddress()) {
                        String ip = a.getHostAddress();
                        String prefix = ip.substring(0, ip.lastIndexOf('.') + 1);
                        if (!out.contains(prefix)) out.add(prefix);
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return out;
    }

    void startScan() {
        final int my = ++scanId;
        found.clear();
        if (foundList != null) foundList.removeAllViews();
        if (status != null) status.setText("Looking for your " + brand() + " server on this network…");
        new Thread(new Runnable() {
            public void run() {
                List<String> nets = subnets();
                ExecutorService pool = Executors.newFixedThreadPool(48);
                final String saved = prefs.getString("server", null);
                if (saved != null) {
                    pool.submit(new Runnable() {
                        public void run() {
                            String name = probe(saved, 1500);
                            if (name != null) addFound(my, saved, name);
                        }
                    });
                }
                for (String net : nets) {
                    for (int i = 1; i < 255; i++) {
                        final String base = "http://" + net + i + ":" + PORT;
                        pool.submit(new Runnable() {
                            public void run() {
                                if (scanId != my) return;
                                String name = probe(base, 700);
                                if (name != null) addFound(my, base, name);
                            }
                        });
                    }
                }
                pool.shutdown();
                try {
                    pool.awaitTermination(40, TimeUnit.SECONDS);
                } catch (InterruptedException ignored) {
                }
                ui.post(new Runnable() {
                    public void run() {
                        if (scanId != my || web != null) return;
                        if (found.isEmpty()) {
                            status.setText("No " + brand() + " server found on this network. Make sure it's running, then search "
                                    + "again, or type its address below.");
                        } else if (found.size() == 1) {
                            connect(found.keySet().iterator().next());
                        } else {
                            status.setText("Pick your " + brand() + " server:");
                        }
                    }
                });
            }
        }).start();
    }

    void addFound(final int my, final String base, final String name) {
        if (found.containsKey(base)) return;
        found.put(base, name);
        ui.post(new Runnable() {
            public void run() {
                if (scanId != my || foundList == null || web != null) return;
                Button b = button("📺  " + name + "   (" + Uri.parse(base).getHost() + ")");
                b.setOnClickListener(new View.OnClickListener() {
                    public void onClick(View v) {
                        connect(base);
                    }
                });
                foundList.addView(b, gap(8));
                if (foundList.getChildCount() == 1) b.requestFocus();
            }
        });
    }

    void connect(String base) {
        scanId++;
        prefs.edit().putString("server", base).apply();
        showTv(base);
    }

    // ------------------------------------------------------------------ the TV
    void showTv(final String base) {
        server = base;
        if (web != null) web.destroy();
        web = new WebView(this);
        web.setBackgroundColor(Color.BLACK);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setUserAgentString(s.getUserAgentString() + " BarnesTVApp/1.0");
        web.setFocusable(true);
        web.setFocusableInTouchMode(true);
        web.addJavascriptInterface(new Bridge(), "BarnesApp");
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public Bitmap getDefaultVideoPoster() {     // no grey "play" placeholder while a channel loads
                return Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888);
            }
        });
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return false;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (Build.VERSION.SDK_INT >= 21 && req.isForMainFrame()) lost(base);
            }

            @SuppressWarnings("deprecation")
            @Override
            public void onReceivedError(WebView view, int code, String desc, String failingUrl) {
                if (failingUrl != null && failingUrl.startsWith(base + "/tv")) lost(base);
            }
        });
        setContentView(web);
        web.requestFocus();
        web.loadUrl(base + "/tv?app=1");
    }

    void lost(final String base) {
        ui.post(new Runnable() {
            public void run() {
                showSetup("Can't reach the " + brand() + " server at " + Uri.parse(base).getHost()
                        + ". Is the computer on and the server running? Looking again…");
            }
        });
    }

    class Bridge {
        @JavascriptInterface
        public void changeServer() {
            ui.post(new Runnable() {
                public void run() {
                    showSetup("Pick a " + brand() + " server, or type an address.");
                }
            });
        }

        @JavascriptInterface
        public void exit() {
            ui.post(new Runnable() {
                public void run() {
                    finish();
                }
            });
        }

        @JavascriptInterface
        public String version() {
            return "1.0";
        }
    }

    /** The app's name as installed (set by the branding kit when the app is built). */
    static String appName = "Barnes TV";

    String brand() {
        try {
            appName = getApplicationInfo().loadLabel(getPackageManager()).toString();
        } catch (Exception e) {
            // keep the last known name
        }
        return appName;
    }

    void js(String code) {
        if (web != null) web.evaluateJavascript(code, null);
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        if (web == null) return super.dispatchKeyEvent(e);
        String key = null;
        switch (e.getKeyCode()) {
            case KeyEvent.KEYCODE_CHANNEL_UP:
            case KeyEvent.KEYCODE_PAGE_UP:
            case KeyEvent.KEYCODE_MEDIA_NEXT:
                key = "chup";
                break;
            case KeyEvent.KEYCODE_CHANNEL_DOWN:
            case KeyEvent.KEYCODE_PAGE_DOWN:
            case KeyEvent.KEYCODE_MEDIA_PREVIOUS:
                key = "chdown";
                break;
            case KeyEvent.KEYCODE_GUIDE:
            case KeyEvent.KEYCODE_MENU:
            case KeyEvent.KEYCODE_TV_INPUT:
                key = "guide";
                break;
            case KeyEvent.KEYCODE_INFO:
            case KeyEvent.KEYCODE_CAPTIONS:
                key = "info";
                break;
            case KeyEvent.KEYCODE_LAST_CHANNEL:
                key = "last";
                break;
            case KeyEvent.KEYCODE_BACK:
                if (e.getAction() == KeyEvent.ACTION_UP) {
                    web.evaluateJavascript("(window.tvBack && tvBack()) ? 'y' : 'n'", new ValueCallback<String>() {
                        public void onReceiveValue(String v) {
                            if (v == null || !v.contains("y")) finish();
                        }
                    });
                }
                return true;
            default:
                return super.dispatchKeyEvent(e);
        }
        if (e.getAction() == KeyEvent.ACTION_DOWN) js("window.tvKey && tvKey('" + key + "')");
        return true;
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (web != null) web.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
    }

    @Override
    protected void onStop() {
        super.onStop();
        js("window.tvSuspend && tvSuspend()");      // stop streaming while the app is in the background
    }

    @Override
    protected void onRestart() {
        super.onRestart();
        js("window.tvResume && tvResume()");
    }

    @Override
    protected void onDestroy() {
        scanId++;
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
