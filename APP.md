# Installing it as an app

The same attendance system, two ways of getting it onto a phone: installed
from the browser, or as an `.apk` file you can hand over.

**Face recognition runs on the server, not on the phone.** dlib does not run on
Android, so both routes are a window onto a running server — your laptop on the
classroom Wi-Fi, or a hosted deployment. Neither one works with nothing behind
it, and neither one recognises faces offline. Anything claiming otherwise would
be a different project.

---

## 1. Install from the browser (no file needed)

Start the server, open it on the phone, and install:

| | |
|---|---|
| **Android / Chrome** | A bar offers **Install**. Or menu → *Add to Home Screen*. |
| **iPhone / Safari** | Share → **Add to Home Screen**. Safari never offers this itself. |
| **Desktop Chrome / Edge** | An install icon appears in the address bar. |

It then has its own icon, opens full-screen with no address bar, and appears in
the app switcher like anything else.

### It must be localhost or HTTPS

Browsers only allow installing from a **secure context**. `http://localhost`
counts; `http://192.168.1.14:5000` does **not**. So over plain Wi-Fi to a
laptop, the site works but the install option never appears, which looks like a
bug and is not one.

Two ways round it:

* deploy to Render (see `DEPLOY.md`) — you get HTTPS and it just works;
* use a Cloudflare quick tunnel to get an `https://…trycloudflare.com` address.

Or use the Android app below, which has no such restriction.

### Taking the photo

Over plain http — which is what `http://192.168.1.14:5000` is — the browser
refuses `getUserMedia` outright: live camera access is allowed only from https
or from localhost. So **Use Camera** does not open a viewfinder inside the
page. It opens the phone's own camera app instead, and the photo comes back
into the page when you accept it.

This is the better of the two, not a workaround:

| | In-page viewfinder | Phone's camera app |
|---|---|---|
| Resolution | ~1280×720 | the full sensor, commonly 12MP |
| Back-row face in a hall of 120 | ~16px across | ~60px across |
| Identified? | no — 45px is the floor | yes |

The numbers are from `RECOGNITION.md`. A viewfinder frame simply does not
carry enough pixels for the back of a lecture hall, so the fallback is what you
want even when https is available.

### What it stores

The service worker caches **stylesheets, icons and scripts only** — never a
page, never an API response. On a shared staff phone a cached roster would show
one teacher's class to whoever opened the app next, and stale attendance
presented as current is worse than none. With no connection you get an offline
notice rather than yesterday's register.

---

## 2. The Android app (`.apk`)

A small WebView app: your server's pages, in an app shell, with the four things
a browser tab cannot give you — a launcher icon, no address bar, a camera that
works over plain http, and a remembered server address.

**It is about 77 KB** because it has no dependencies at all: everything it uses
is in Android itself.

### Install it

1. Copy `app-release.apk` to the phone.
2. Open it. Android asks permission to install from this source — allow it.
3. Open **Attendance**. On first run it asks for the server address.

### The server address

**One command does all of it:**

```bash
./run-phone.sh          # Windows: run-phone.bat
```

That is `run.sh` bound to every network instead of this computer only, which is
the difference the phone needs. It prints the address to type:

```
  Attendance server
  ----------------------------------------------------
  On this computer:  http://127.0.0.1:5000

  In the phone app, type this address:

      http://192.168.1.14:5000
```

If it instead says *"Phones CANNOT reach this server"*, the server is bound to
the computer only — stop it and start it again with `HOST=0.0.0.0`.

Type where the attendance server is running, for example:

```
http://192.168.1.14:5000
```

Find it on the laptop with `ipconfig` (Windows) or `ifconfig` (Mac/Linux) and
use the address starting `192.168.` or `10.`.

> **Not `127.0.0.1`.** On the phone that means *the phone*, so nothing answers.
> This is the single commonest reason the app shows "cannot reach the server".

The phone and the laptop must be on the same Wi-Fi, and the server must be
started with `HOST=0.0.0.0` so it accepts connections from other devices:

```bash
HOST=0.0.0.0 PORT=5000 ./run.sh
```

Without `HOST=0.0.0.0` the server only answers itself, and the phone cannot
reach it however correct the address is.

If the address changes, reopen the app: the error offers **Change address**.

### If it still will not connect

In order of how often each one is the cause:

1. **The server is bound to localhost.** It must be started with
   `HOST=0.0.0.0`. Its startup message says which it is.
2. **You typed `127.0.0.1` or `localhost`.** On the phone those mean the
   phone, so nothing answers. Use the `192.168.x.x` address.
3. **The computer's firewall.** Windows blocks incoming connections to Python
   by default and asks once — if you dismissed that prompt, allow Python on
   **private networks** in Windows Defender Firewall.
4. **Different networks.** A phone on mobile data, or on a guest Wi-Fi that
   isolates clients, cannot see the laptop. Both must be on the same Wi-Fi.
5. **College Wi-Fi blocks device-to-device traffic.** Many campus networks do.
   Use a phone hotspot with the laptop joined to it, or deploy to Render.

To test without the app, open `http://192.168.1.14:5000/healthz` in the
phone's browser. If that shows `{"ok": true ...}` the network is fine and the
problem is in the app's address; if it does not, it is one of the five above.

### Build it yourself

**With GitHub, no tools installed.** Actions → *build apk* → *Run workflow*.
When it finishes, download the **faceid-attendance-apk** artifact.

**On your own machine.** Needs a JDK (17+) and the Android SDK; Android Studio
includes both.

```bash
cd android
./gradlew assembleRelease          # Windows: gradlew.bat assembleRelease
```

The file lands at `android/app/build/outputs/apk/release/app-release.apk`.

### About the signature

It is signed with Android's **debug key**, so it installs and runs anywhere and
is fine to hand in or demonstrate. It is *not* suitable for the Play Store,
which requires your own keystore. That is a deliberate choice: a private signing
key does not belong in a public repository.

---

## Which should you use?

| | Browser install | `.apk` |
|---|---|---|
| A file to hand in | no | **yes** |
| Works over plain http to a laptop | **yes** (install prompt needs HTTPS) | **yes** |
| Works on iPhone | **yes** | no |
| Install effort | one tap | allow unknown sources |
| Updates | automatic | rebuild and reinstall |

For a project that has to be submitted, build the APK. For everyday use on a
hosted deployment, the browser install is less to maintain.

---

## The icons

All of them — web, iOS, Android, favicon — are drawn by `make_icons.py`:

```bash
python make_icons.py
```

It writes `static/icons/` and, when the Android project is present, every
launcher density including the adaptive-icon foreground. Change `BRAND` at the
top and re-run rather than editing a binary by hand.
