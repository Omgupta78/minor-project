# Recognition at hall scale

Everything below was measured, not estimated. The defaults in
`recognition.py` are what they are because of these numbers, and
`hallbench.py` re-runs the measurement so you can repeat it on your own room.

## The benchmark

A 4000x3000 photograph (12 MP, what a phone produces) of 120 students in six
rows of twenty. Row distances 4 m to 15 m, which for a ~70 degree lens puts a
16 cm face at 114 px in the front row and 30 px in the back row:

```
face_px = image_width * 0.16 / (2 * distance * tan(35 deg))
```

The faces are 120 different real people, each enrolled from one photograph and
seated in the room from a different photograph, so no student is ever matched
against the same image they were enrolled from.

What this benchmark does model: face size against distance, which is the whole
question for the back row. What it does not model: a single shared lighting
setup, real motion blur, students turned away from the camera, or occlusion by
the person in front. Treat the numbers as an upper bound on a real room and
re-run `hallbench.py` on your own photograph before quoting them.

Reproduce it with any labelled folder (one sub-folder per student, two or more
photos in each — the layout `accuracy.py` already uses):

```
python hallbench.py --compose testset --rows 6 --per-row 20
```

## How far back it works

One enrolment photo per student, current defaults:

| row | distance | face width | detected | identified |
|-----|----------|-----------:|---------:|-----------:|
| 1   | 4.0 m    | 114 px     | 20/20    | 19/20      |
| 2   | 6.2 m    | 74 px      | 20/20    | 20/20      |
| 3   | 8.4 m    | 54 px      | 20/20    | 19/20      |
| 4   | 10.6 m   | 43 px      | 20/20    | 18/20      |
| 5   | 12.8 m   | 36 px      | 19/20    | 14/20      |
| 6   | 15.0 m   | 30 px      | 17/20    | 12/20      |
| all |          |            | 116/120  | 102/120    |

**Detection is not the problem.** 97% of the room is found, and everything
down to a 43 px face is found every time. What runs out is pixels to encode:
below about 45 px a face is detected but cannot be told apart from the other
119 students. That is why the scan reports `faces_too_small` and the dashboard
says so in words — no threshold recovers information that was never captured.

The practical consequence, and the single most useful thing to tell a teacher:

> If the back rows come back unknown, take a second photo of the back of the
> room. The scan merges up to eight photos and keeps each student's best
> sighting, so extra photos can only help.

Halving the distance doubles the face width, which by the table above moves a
row from ~60% identified to ~100%.

## Why the thresholds changed

With 120 students enrolled the gallery is dense: the nearest *wrong* student
sits much closer than it does with a class of ten. Measured on the same photo,
with 100 students enrolled and 20 of the seated students deliberately held out
of the gallery so they act as strangers:

| `SMALL_FACE_PENALTY` | correctly identified | strangers wrongly named |
|---------------------:|---------------------:|------------------------:|
| 0.04 (old default)   | 67 / 97              | 0                       |
| 0.02                 | 77 / 97              | 0                       |
| 0.00 (new default)   | 82 / 97              | 0                       |

| `MATCH_DISTANCE` | correctly identified | strangers wrongly named |
|-----------------:|---------------------:|------------------------:|
| 0.50             | 82 / 97              | 0                       |
| 0.52 (new)       | 85 / 97              | 0                       |
| 0.54             | 88 / 97              | 1                       |
| 0.56             | 90 / 97              | 1                       |

The small-face penalty was written to stop a noisy enlarged face being
accepted. In a hall nearly every face is enlarged, so it only ever rejected
correct matches — it bought no precision at all. It now defaults to 0 and
remains available if your own calibration shows otherwise.

`MATCH_DISTANCE` moved 0.50 → 0.52. 0.54 is where a stranger starts borrowing
a name, so that is the ceiling, not a target. `MATCH_MARGIN` stays at 0.06:
relaxing it gained little and is the guard that stops two similar students
swapping identities.

**Run `calibrate.py` on your own students before trusting any of this.**
Precision is the constraint that matters — marking an absent student present
is worse than asking a teacher to confirm one face.

## Enrolment photos per student

Same photo, same thresholds, varying only how many reference photos each
student was enrolled from:

| reference photos | auto-matched |
|-----------------:|-------------:|
| 1                | 69 / 120     |
| 3                | 78 / 120     |

Three photos — front on, turned slightly left, slightly right — is the
cheapest accuracy available. The students page flags anyone enrolled from a
single photo, and the scan says so too.

## The bug this benchmark found

The numbers above were first measured by calling `load_image()` directly. Run
through the actual `/api/scan` route, the same photograph produced **7 faces
instead of 121**, and 0 on the next call in the same worker.

The cause: a scan decodes the upload with `decode_image_bytes()`, which used
OpenCV first. **When `cv2.imdecode` is the first image decode to run in a
process, dlib's HOG detector is crippled for the life of that process.**
Decoding anything with Pillow first avoids it completely — importing Pillow is
not enough, it has to actually decode something. `cv2.resize` is harmless, and
so is importing OpenCV; only being the first decoder matters.

Enrolment goes through Pillow (`face_recognition.load_image_file`), so
enrolment always looked perfect. Only scanning was affected, and only the
small faces survived, so it presented as "the back of the room doesn't work"
rather than as a decoder bug.

`decode_image_bytes()` now tries Pillow first and keeps OpenCV as a fallback.
Pillow also reads HEIC through pillow-heif, which OpenCV cannot read at all,
so it is the better primary decoder anyway. `decodetest.py` asserts the two
paths detect the same faces, which is the check that was missing.

Through the real HTTP route, after the fix: **121 faces, 94 of 119 students
auto-marked present, 18.5 s.**

## Speed

120 faces in one 12 MP photo, 4-core x86:

| stage | serial | 4 worker processes |
|-------|-------:|-------------------:|
| detection (tiled, full resolution) | 9.0 s | 9.0 s |
| encoding 120 faces | 27.1 s | 7.4 s |
| **whole scan** | **36 s** | **18 s** |

Measured end to end through `POST /api/scan` with 119 students enrolled:
**18.5 s**, which matches the component timings above.

dlib holds the GIL, so threads are worthless here — measured 1.02x on four
threads. Only separate processes help. `SCAN_WORKERS` controls this:

* `0` (default) — automatic: up to four workers when there are at least
  `PARALLEL_MIN_FACES` (24) faces and more than one CPU.
* `1` — never parallelise. **Set this on a 512 MB host**: each worker loads
  its own copy of the dlib models, about 250 MB resident.
* `N` — exactly N workers.

The pool uses the `forkserver` start method, not plain `fork`, because
Gunicorn runs threaded workers by default and forking a threaded process can
deadlock in the child. Starting it costs about 1.4 s, which a hall photo
repays several times over. If the platform refuses to start processes the scan
falls back to serial and says so in the log rather than failing.

One sharp edge, handled rather than documented away: `forkserver` and `spawn`
both **re-execute the program's `__main__` module in every worker**. That is
harmless for `app.py`, `wsgi.py` and Gunicorn, which all guard their entry
point, but a plain script without `if __name__ == "__main__":` has its whole
body re-run once per worker — measured at 259 s against 18 s for a caller that
enrolled students at import time. `recognition.main_module_is_guarded()`
checks for that guard and quietly falls back to serial encoding when it is
missing, so the worst case is slow rather than baffling. If you write your own
script that scans photos, guard its entry point and you keep the speedup.

### What a hall needs from the host

* **2 or more CPU cores and 2 GB RAM** for a 120-student room at a sensible
  speed. One core works, at roughly 36 s per photo.
* `GUNICORN_TIMEOUT` of at least 300 (already the default in
  `gunicorn.conf.py`) so a multi-photo scan is never killed mid-request.
* `WEB_CONCURRENCY=1`, so the scan's worker processes get the cores rather
  than competing with other Gunicorn workers for them.
* A 0.1-CPU / 512 MB free tier will technically run but a hall photo takes
  minutes. Use it for a demo, not a real class.

## Things that were tried and did not work

Measured, and rejected — recorded here so nobody spends the afternoon again:

| change | result |
|--------|--------|
| `MAX_UPSCALE` 4 → 8, `UPSCALE_FACE_PX` 150 → 170 | no change (median distance 0.430 → 0.432) |
| `SMALL_FACE_JITTERS` 2 → 4 | no change, 2x slower |
| `SMALL_FACE_JITTERS` 2 → 1 | 2 fewer students, 2x faster |
| `FACE_UPSAMPLE` 1 → 2 (whole image) | +1 face found, detection 9 s → 37 s |
| CNN detector on the back rows | 24/40 against HOG's 39/40, and 15x slower |
| threads instead of processes | 1.02x — dlib holds the GIL |

The encoding pipeline is already extracting close to everything dlib can get
from a 30 px face. More pixels on the face is the only real lever.
