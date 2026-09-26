"""Drive the real page in a browser: does "Use Camera" open the camera?

Reported from a phone on the classroom Wi-Fi: tapping Use Camera offered a
file upload instead of the camera, while the same page on the laptop was
fine. The cause was that the two buttons used different mechanisms -- the
gallery picker was a <label for=...>, which works, and the camera button
called .click() on a hidden file input from script, which makes Android
browsers drop the `capture` attribute and show the ordinary file chooser.

Nothing about that is visible in the HTML source, so this drives a real
Chromium: once as a touch device with no navigator.mediaDevices (a phone on
plain http) and once as a desktop with a mouse.

Needs playwright. CI skips it when the browser is not installed; the rest of
the suite does not depend on it.

The phone case is the one that was broken, so it is checked the way the phone
sees it -- a touch device on a LAN address, where navigator.mediaDevices is
absent and the only way to a camera is the capture input.
"""
import os, sys, tempfile, threading, time
from pathlib import Path

WORK = Path(tempfile.mkdtemp(prefix="camtest-"))
os.environ.update(
    ATTENDANCE_DB=str(WORK / "a.db"), FACES_DIR=str(WORK / "faces"),
    PASSWORD_ROUNDS="1000", COOKIE_SECURE="0", ALLOW_SIGNUP="1",
    SECRET_KEY="camtest-secret-key-that-is-long-enough-ok", PRODUCTION="0",
)
sys.path.insert(0, "/home/user/minor-project")
import app as flask_app

PORT = 5099
threading.Thread(
    target=lambda: flask_app.app.run(host="127.0.0.1", port=PORT, threaded=True),
    daemon=True,
).start()
time.sleep(2)

CHROMIUM = next(
    (str(p) for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")),
    os.environ.get("CHROMIUM_PATH", ""),
)
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright is not installed; skipping the browser checks.")
    raise SystemExit(0)
if not CHROMIUM or not Path(CHROMIUM).exists():
    print("no Chromium available; skipping the browser checks.")
    raise SystemExit(0)

FAILS = []
def check(label, ok, detail=""):
    print(f"  [{'ok  ' if ok else 'FAIL'}] {label}" + (f"  {detail}" if not ok else ""))
    if not ok: FAILS.append(label)

PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True,
         "has_touch": True, "device_scale_factor": 3,
         "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"}
DESKTOP = {"viewport": {"width": 1280, "height": 800}, "has_touch": False}

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=CHROMIUM)
    for name, opts in (("PHONE", PHONE), ("DESKTOP", DESKTOP)):
        ctx = browser.new_context(**opts)
        page = ctx.new_page()
        if name == "PHONE":
            # Over plain http to a LAN address the browser withholds this
            # entirely -- the exact situation reported from the phone.
            page.add_init_script(
                "Object.defineProperty(navigator, 'mediaDevices', "
                "{get: () => undefined, configurable: true});")
        page.goto(f"http://127.0.0.1:{PORT}/signup")
        page.fill("input[name=email]", f"{name.lower()}@example.edu")
        page.fill("input[name=name]", name)
        page.fill("input[name=password]", "password1")
        page.click("button[type=submit], input[type=submit]")
        page.wait_for_load_state("networkidle")

        # The scan card only renders once the teacher has a class.
        ctx.request.post(f"http://127.0.0.1:{PORT}/classes/add",
                         form={"name": f"{name} 3A", "subject": "DBMS"})
        page.goto(f"http://127.0.0.1:{PORT}/")
        page.wait_for_load_state("networkidle")

        print(f"\n{name}")
        if not page.query_selector("#camera-input"):
            print("   (no scan card on this page; url=" + page.url + ")")
        coarse = page.evaluate("matchMedia('(pointer: coarse)').matches")
        live = page.evaluate("!!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)")
        print(f"  pointer:coarse={coarse}  liveCamera={live}")

        label_vis = page.is_visible("#camera-label")
        button_vis = page.is_visible("#camera-button")
        check("exactly one camera control is visible",
              label_vis != button_vis, f"label={label_vis} button={button_vis}")

        if name == "PHONE":
            check("the phone gets the label, not the script button",
                  label_vis and not button_vis)
            target = page.get_attribute("#camera-label", "for")
            check("the label points at the capture input", target == "camera-input", str(target))
            cap = page.get_attribute("#camera-input", "capture")
            acc = page.get_attribute("#camera-input", "accept")
            multi = page.get_attribute("#camera-input", "multiple")
            check("that input asks for the rear camera", cap == "environment", str(cap))
            check("and accepts images", acc == "image/*", str(acc))
            check("and is single-shot (capture overrides multiple anyway)", multi is None)
            # The label must actually reach the input when tapped.
            opened = page.evaluate("""() => new Promise(res => {
                const i = document.getElementById('camera-input');
                i.addEventListener('click', () => res(true), {once: true});
                document.getElementById('camera-label').click();
                setTimeout(() => res(false), 500);
            })""")
            check("tapping the label opens that input", opened)
        else:
            check("the desktop keeps the in-page viewfinder button",
                  button_vis and not label_vis)

        # The gallery picker must stay multi-select on both.
        check("Upload Photos is still multi-select",
              page.get_attribute("#file-input", "multiple") is not None
              and page.get_attribute("#file-input", "capture") is None)
        ctx.close()
    browser.close()

import shutil; shutil.rmtree(WORK, ignore_errors=True)
print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("Camera control behaves correctly on both phone and desktop.")
