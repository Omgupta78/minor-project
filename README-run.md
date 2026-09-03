# Getting this app live on your Windows machine

The app = `face_recognition` (dlib-based embeddings) + OpenCV taking frames from a
webcam, writing attendance to `attendance/DD-MM-YY.csv`. Every part of this is
installable on Windows — no cloud, no camera server needed.

Two files here do the work:

- `main.py` — original, hard-coded to webcam 0.
- `run_live.py` — one-line upgrade: same loop, but you can point it at a webcam
  index **or** a video file. Use it as your daily driver.

## 1. One-time setup

You already have Python 3.12.5 and a `.venv` folder, so:

```cmd
cd face-recognition-attendance-system
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

This installs dlib, face_recognition, OpenCV, numpy and CMake. On Python 3.12
Windows there is **no prebuilt dlib wheel**, so pip builds it from source — the
`cmake` package is required for that and gets installed automatically. If the
build dies with a "No CMAKE_CXX_COMPILER" error, install **Visual Studio Build
Tools** → "Desktop development with C++" workload, reopen the terminal, and run
the install again. That's the whole gotcha; everything after that is smooth.

## 2. Run it live

```cmd
.venv\Scripts\activate
python run_live.py                  # webcam 0 — identical behaviour to main.py
python run_live.py -s 1             # second webcam, if you have one
```

Walk in front of the camera; names of people whose photos are in `faces/` get a
green box, their attendance is written to `attendance/26-09-02.csv` with the
timestamp, and each person is marked once per run. `q` quits.

### Video-file mode (for testing without a webcam)

Drop a clip (e.g. a phone video of the faces) next to the script and run:

```cmd
python run_live.py -s my_clip.mp4 --max-frames 700
```

`--max-frames` stops the loop when the clip ends; without it, a file with no
more frames ends the run anyway. Same attendance CSV is produced — if you run
it on a day that already has a CSV, the new marks are **appended**, not
overwritten (this was a bug in the original: it reopened the file in `"w"` mode
and wiped earlier entries).

## 3. If recognition misses or misnames someone

The match threshold is `MATCH_DISTANCE = 0.5` at the top of `run_live.py`
(same value as `main.py`). Lower it (e.g. `0.45`) to be stricter — fewer false
accepts, more misses. The usual real cause of misses is a poor reference
photo: the `faces/` image should be a front-facing, well-lit shot of the face
only. Replacing `Rakesh.jpg`/`Ravi.jpg`/`Sushant.jpg` with better photos is
the single highest-impact fix, and new users are added the same way — drop a
`Name.jpg` in `faces/`, no code changes needed.

## 4. Where attendance lands

`attendance/yy-mm-dd.csv`, one row per session run: `Name,Time`. The file name
uses the same `%y-%m-%d` style as the original (`26-09-02.csv` for 2026-09-02).
