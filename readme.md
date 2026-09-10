# FaceID Attendance

A classroom attendance system for teachers. **Take one photo of the class, the app
identifies each student and marks them present, and the whole term's attendance
exports as a formatted Excel workbook.**

College minor project: Python + Flask + face_recognition (dlib) + SQLite + openpyxl.

---

## How it works

```
  Enrolment                 Attendance                    Reporting
  ---------                 ----------                    ---------
  1 photo per student       teacher photographs class     Excel workbook
        |                             |                        |
   detect 1 face              detect all faces           4 sheets:
        |                             |                   - Summary (%)
   128-D encoding             128-D encoding each         - Register grid
        |                             |                   - Detailed records
   store in SQLite  ------->  compare to enrolled         - Session log
                              (Euclidean distance)
                                      |
                            TEACHER REVIEWS & CONFIRMS
                                      |
                              saved as one session
```

A face match is only a **suggestion** until the teacher confirms it. Nothing is
written to the attendance table until Confirm is pressed, and every mark records
whether it came from the model (`face`) or from a human correction (`manual`).
That audit trail is what makes the output defensible.

---

## Features

- **One photo, whole class** - detects and identifies every face in a group photo
- **Teacher-in-the-loop review** - per-student Present/Absent toggles before saving
- **Honest confidence** - the real distance-derived score, never a fixed number
- **Low-confidence flagging** - near-threshold matches are surfaced, not silently accepted
- **Duplicate resolution** - if two faces match one student, only the closest wins
- **Sessions, not just days** - class + date + period is unique, so multiple lectures a day work
- **Real roll numbers** - stored identifiers, not generated display strings
- **Full Excel export** - 4 formatted sheets with a 75% defaulter rule
- **Correct after the fact** - any past session can be edited from its detail page
- **Privacy by default** - face photos and the database are git-ignored

---

## Excel report contents

| Sheet | What's in it |
|---|---|
| **Summary** | One row per student: sessions held, present, absent, percentage, defaulter flag |
| **Attendance Grid** | Classic register: students down, sessions across, `P` / `A` / `L` per cell |
| **Detailed Records** | Every individual mark with confidence and whether a teacher overrode it |
| **Session Log** | Each session: date, period, teacher, faces detected, present/absent counts |

---

## Setup

```bash
git clone https://github.com/Omgupta78/minor-project.git
cd minor-project

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

> **Note on dlib:** `face_recognition` needs `dlib`, which compiles from source.
> On Windows install `cmake` first, or use a prebuilt wheel if the build fails.
> On Debian/Ubuntu: `sudo apt install build-essential cmake python3-dev`.

Initialise the database and start the app:

```bash
python -c "import db; db.init_db()"
python app.py
```

Open <http://127.0.0.1:5000>.

### Migrating an existing `faces/` folder

If you already have images named `Name.jpg` in `faces/`:

```bash
python migrate_to_db.py --class "CSE 3rd Year A" --subject DBMS
```

### Verifying the build

```bash
python selftest.py      # data layer + Excel builder, no camera needed
python rendertest.py    # renders every template against real data
```

---

## Usage

1. **Students > New Class** - create the class you teach
2. **Students > Add Student** - roll number, name, one clear front-facing photo
   (rejected if no face is found, so nobody is enrolled with unusable data)
3. **Take Attendance** - pick class, date and period, then upload or capture the class photo
4. **Identify Students** - boxes are drawn on the photo and the roster fills in
5. **Review** - fix any mistakes with the Present/Absent toggles
6. **Confirm & Save** - the session is written to the database
7. **Records > Download Excel Report** - the full workbook

---

## Configuration

All optional, set as environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | dev value | Flask session signing key - **set this in production** |
| `ATTENDANCE_DB` | `instance/attendance.db` | SQLite database path |
| `FACES_DIR` | `faces` | Where enrolment photos are stored |
| `MATCH_DISTANCE` | `0.50` | Distance at or below which a face auto-matches (lower = stricter) |
| `REVIEW_DISTANCE` | `0.60` | Between this and `MATCH_DISTANCE`, the match is flagged for review |
| `FACE_MODEL` | `hog` | `hog` (fast, CPU) or `cnn` (accurate, needs GPU) |
| `FACE_UPSAMPLE` | `1` | Raise to `2` to find smaller back-row faces (slower) |
| `MAX_EDGE` | `1600` | Class photos are downscaled to this longest edge before detection |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Bind address |
| `FLASK_DEBUG` | off | Never enable on a shared network |

### Tuning for back-row students

In order of effect: get closer or use a higher-resolution camera, raise `MAX_EDGE`
to `2200`, set `FACE_UPSAMPLE=2`, or take two photos (front half, back half) as two
periods.

---

## Project structure

```
app.py               Flask routes only - no recognition or SQL logic
db.py                SQLite schema and every query, one place
recognition.py       Face detection, encoding, matching, duplicate resolution
excel_report.py      The 4-sheet openpyxl workbook builder
migrate_to_db.py     One-time importer for a legacy faces/ folder
build_css.py         Regenerates static/app.css from the templates
doctor.py            Reports whether this copy is the multi-photo build
selftest.py          Smoke test for the data + report layers
rendertest.py        Renders every template against real data
multitest.py         Multi-photo merge checks
run.sh / run.bat     One-command launchers (venv, install, open browser)
templates/           Jinja templates (no CDN, works offline)
static/app.css       Generated stylesheet
static/icons.js      Inline SVG icon set
faces/               Enrolment photos (git-ignored)
instance/            SQLite database (git-ignored)
```

---

## Database schema

```
classes     id, name, subject                        UNIQUE(name, subject)
students    id, roll_no, name, class_id, encoding    UNIQUE(roll_no)
sessions    id, class_id, date, period, taken_by     UNIQUE(class_id, date, period)
attendance  id, session_id, student_id, status,      UNIQUE(session_id, student_id)
            confidence, method
```

The two `UNIQUE` constraints on `sessions` and `attendance` are what make re-running
a scan idempotent instead of duplicating rows.

---

## Privacy and limitations

Be honest about these in your report - they earn marks rather than losing them.

- **Face data is biometric personal data.** Photos and the database are git-ignored
  and never leave the machine. Get consent from the class before enrolling anyone.
- **No liveness detection.** A student could hold up a printed photo of a friend.
  Real deployments need anti-spoofing; this build relies on the teacher watching the room.
- **Accuracy depends on the photo.** Poor light, motion blur, profile angles, masks and
  distant faces all reduce detection. This is why the teacher confirms every session.
- **Demographic bias.** dlib's model has documented uneven accuracy across skin tones
  and ages. The teacher-review step is the mitigation.
- **No authentication yet.** Anyone who can reach the URL can take attendance.
  Keep it on `127.0.0.1` until login is added.

---

## Roadmap

- [ ] Teacher login (Flask-Login) and per-teacher class ownership
- [ ] Liveness / anti-spoofing check
- [ ] Attendance trend charts on the dashboard
- [ ] PDF export alongside Excel
- [ ] Accuracy evaluation table (precision/recall on a labelled test set) for the report

---

## Multi-photo attendance sessions

One wide photo of a classroom rarely works: the back row is too small to encode,
someone always turns away, and cropping for resolution loses the edges of the
room. So a session accepts **several photos** and merges them into one roster.

**How to use it**

1. Pick the class, date and period as usual.
2. Upload up to 8 photos at once (or drag them in, or keep pressing **Capture**
   in the camera modal). A good pattern is left half / right half / back row.
3. Press **Identify students**. Every photo is scanned, then results are merged.
4. The thumbnail strip shows how many faces were found in each photo. Click a
   thumbnail to see its boxes; click “photo 2” next to a student to jump to the
   shot they were recognised in.
5. Review, correct, and confirm. Only then is anything written to the database.

**How merging works**

- Each photo is scanned independently, and duplicate boxes *within* a photo are
  resolved there (two boxes cannot be the same student in one frame).
- Across photos, every student is credited with their **single best sighting**
  (lowest face distance). Other sightings are tagged `repeat` and shown in blue.
- A student is therefore **counted once**, no matter how many photos they appear
  in — attendance totals cannot be inflated by uploading more pictures.
- Because only the best sighting is kept, adding a photo can only ever *raise* a
  student's confidence, never lower it. A blurry extra shot is harmless.
- Students seen only at `review` confidence stay unchecked and are flagged for
  the teacher rather than being auto-marked present.

**Box colours**

| Colour | Meaning |
| --- | --- |
| Green | Identified confidently |
| Amber | Recognised but below threshold — confirm manually |
| Blue | Same student, already counted from a better photo |
| Grey | Duplicate box within one photo |
| Red | Face detected but not matched to any enrolled student |

**Limits and config**

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAX_PHOTOS_PER_SCAN` | `8` | Photos accepted per scan request |
| `MAX_UPLOAD_MB` | `64` | Total size of one upload batch |

Detection is roughly linear in photo count, so 8 large photos on the `hog` model
take noticeably longer than one. If a file is unreadable (HEIC, PDF, corrupt),
it is skipped and named in a warning — the remaining photos are still scanned.

`POST /api/scan` now returns an `images` array (one entry per photo, each with
its own `faces`), aggregate counts (`images_scanned`, `total_faces`, `matched`,
`needs_review`, `unknown`, `repeats`), a `skipped` list, and a `roster` where
each student carries the `confidence` and `photo` number of their best sighting.
The old single-`photo` field is still accepted, so nothing that worked before
breaks.

**Tests:** `python3 multitest.py` covers the merge layer — single-count
guarantees, best-sighting selection, repeat tagging, and empty inputs.

---

## Works with no internet

The UI originally pulled Tailwind and the Material Symbols icon font from CDNs.
That is fine on a laptop with wifi and a disaster in a lab or exam hall: with no
connection the page loads as unstyled black-on-white text with the word
"download" printed inside every button. Everything is now served locally.

| File | Purpose |
| --- | --- |
| `static/app.css` | Generated stylesheet, only the utility classes this app uses |
| `static/icons.css` | Icon sizing and hide-until-ready behaviour |
| `static/icons.js` | Inline SVG icon set, replaces the webfont ligatures |
| `build_css.py` | Regenerates `static/app.css` from the templates |

**After editing any template, regenerate the CSS:**

```bash
python3 build_css.py
```

It scans `templates/*.html`, collects every utility class (including ones built
inside JavaScript strings and Jinja ternaries), and writes CSS for exactly those
— currently ~230 rules in about 12 KB. If a class is used that the generator
does not understand, it is listed in the output so it can be added to the rules
table in `build_css.py`. No node, no npm, no build pipeline.

**Icons.** `static/icons.js` holds a hand-drawn SVG for each icon name used in
the templates and swaps them in on load. A `MutationObserver` catches icons in
markup rendered later by JavaScript (the review roster, the thumbnail strip).
Unknown names fall back to a neutral dot instead of breaking the layout. To add
an icon, add its name and 24x24 path data to the `S` map in that file.

**Fonts.** IBM Plex is no longer fetched from Google Fonts; the stack falls back
to the system UI font. To restore the exact typeface offline, drop the IBM Plex
`.woff2` files into `static/fonts/` and add matching `@font-face` rules.

**Verifying it.** `python3 rendertest.py` renders every template with fixture
data into `/data/render`, then you can screenshot without a network:

```bash
chromium --headless --screenshot=out.png file:///data/render/index.html
```

The harness resolves `url_for('static', ...)` to real relative paths, so a
missing or broken stylesheet shows up in the screenshot rather than passing
quietly.

---

## Quick start (getting to http://127.0.0.1:5000)

**Windows:** double-click `run.bat`
**macOS / Linux:** `./run.sh`

The script creates a `.venv`, installs the dependencies, starts the server and
opens your browser automatically. First run takes a few minutes because of
dlib; later runs start in seconds.

### Manual start

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** (identical to `http://localhost:5000`).

### If dlib will not install

The launcher installs the web dependencies first and the face engine second,
so a dlib failure does not stop the app. It starts, every page works, and the
banner says `Face engine: NOT INSTALLED`; only scanning is disabled, returning
a clear 503 instead of crashing.

| Platform | Fix |
| --- | --- |
| Windows | `pip install dlib-bin` (prebuilt, no compiler), or install Visual Studio Build Tools with "Desktop development with C++" |
| macOS | `xcode-select --install && brew install cmake` |
| Ubuntu | `sudo apt install build-essential cmake python3-dev` |

### Startup options

| Variable | Default | Effect |
| --- | --- | --- |
| `PORT` | `5000` | Change if port 5000 is taken |
| `HOST` | `127.0.0.1` | `0.0.0.0` exposes the app to your LAN |
| `OPEN_BROWSER` | `0` (launchers set `1`) | Auto-open the browser |
| `FLASK_DEBUG` | unset | `1` enables the reloader. Never combine with `HOST=0.0.0.0` |

```bash
PORT=8000 python app.py          # http://127.0.0.1:8000
```

**Demoing from a phone.** `HOST=0.0.0.0 python app.py` makes the app reachable
at your laptop's LAN IP (`ipconfig` / `ifconfig`), for example
`http://192.168.1.7:5000`, so a phone on the same wifi can take the photos.
There is no login yet, so anyone on that network can open it — use it on a
trusted network, and never together with `FLASK_DEBUG=1`, which would expose a
remote code execution console.
