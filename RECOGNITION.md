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

| stage | serial | now |
|-------|-------:|----:|
| decode | 0.2 s | 0.2 s |
| detection (tiled, full resolution) | 9.7 s | **3.8 s** — 4 threads |
| encoding 120 faces | 25 s | **5.0 s** — 4 processes |
| **whole scan** | **36 s** | **8.0 s** |

Measured end to end through `POST /api/scan` with 119 students enrolled:
**9.0 s on the first scan, 8.0 s on every scan after it** (the first pays for
starting the encoding pool). Three photos of the same room, which is the
coverage this document recommends: **23 s**, against 51 s before.

Nothing was traded away for it. Same 121 faces found, same 100 students
identified, zero misidentifications — see *What the speed did not cost* below.

### Detection is threaded; encoding cannot be

These two look like the same problem and are not. Getting them the same way
round is the difference between a 2x speedup and a segfault in a classroom.

**Encoding needs separate processes.** Threads do not merely fail to help,
they crash: `face_encodings` called concurrently segfaults the interpreter
once enough faces are in flight. 16 jobs over 2 threads survived every time;
118 jobs over 4 threads died 3 times out of 3.

**Detection is threaded**, because dlib releases the GIL inside the HOG
search — 9.7 s to 3.8 s on four cores, with no process to start and no 12 MP
image to pickle. Two things had to be true first, and each one fails in its
own quiet way:

1. **Every thread needs its own `dlib.get_frontal_face_detector()`.**
   `face_recognition` keeps one at module scope and shares it with every
   caller. Calling that shared object from four threads segfaulted 11 runs out
   of 12. Per-thread detectors: 8 out of 8, and every run since.

2. **Every tile must be copied contiguous first.** A tile is a slice view into
   the big photo, and dlib reads one of those wrongly when several threads do
   it at once. It returned **153 boxes instead of 197** — reproducibly, and
   every box it dropped was a ~36 px back-row face. No crash, no warning, just
   the quiet disappearance of exactly the students this project exists to
   find. `np.ascontiguousarray` per tile costs 4 MB and restores the count to
   the serial result exactly.

`halltest.py` pins both, and asserts the threaded path searches the same tiles
as the serial one. `DETECT_THREADS=1` turns threading off if you ever need to.

The first measurement taken here claimed 3.91x and was simply the one run in
twelve that survived. A benchmark that crashes eleven times is not a
benchmark; if you re-measure this, check the exit code.

### The encoding pool is kept warm

It used to be built and torn down for every photo, which threw away the ~2.4 s
its four workers spend importing dlib and loading models. It is now created
once and reused: 7.8 s cold against 6.4 s warm for the same work, and a
teacher scanning three photos pays the startup once instead of three times.
It is rebuilt automatically if a worker ever dies.

`SCAN_WORKERS` controls the pool:

* `0` (default) — automatic: up to four workers when there are at least
  `PARALLEL_MIN_FACES` (24) faces and more than one CPU.
* `1` — never parallelise. **Set this on a 512 MB host**: each worker loads
  its own copy of the dlib models, about 250 MB resident.
* `N` — exactly N workers.

The pool uses the `forkserver` start method, not plain `fork`, because
Gunicorn runs threaded workers by default and forking a threaded process can
deadlock in the child. Starting it costs about 2.4 s, paid once per server
process rather than once per photo. If the platform refuses to start processes
the scan falls back to serial and says so in the log rather than failing.

One sharp edge, handled rather than documented away: `forkserver` and `spawn`
both **re-execute the program's `__main__` module in every worker**. That is
harmless for `app.py`, `wsgi.py` and Gunicorn, which all guard their entry
point, but a plain script without `if __name__ == "__main__":` has its whole
body re-run once per worker — measured at 259 s against 18 s for a caller that
enrolled students at import time. `recognition.main_module_is_guarded()`
checks for that guard and quietly falls back to serial encoding when it is
missing, so the worst case is slow rather than baffling. If you write your own
script that scans photos, guard its entry point and you keep the speedup.

### What the speed did not cost

Every change above was checked against ground truth on the 120-student hall
before it was kept.

Threaded detection returns **exactly** the boxes serial detection returns —
not "about the same", the identical set, verified five runs out of five. That
is the whole reason for the contiguous copy in point 2 above; without it the
counts quietly diverged.

The one change that did alter results is `SMALL_FACE_JITTERS`, dropped from 2
to 1:

| | scan | found | auto-accepted | sent to review | wrong names |
|---|---:|---:|---:|---:|---:|
| `SMALL_FACE_JITTERS=1` | 8.0 s | 100/120 | 90 | 10 | **0** |
| `SMALL_FACE_JITTERS=2` | 10.9 s | 100/120 | 97 | 3 | **0** |

The same 100 students, and no misidentification either way. Averaging two
jittered passes pulls distances in slightly, so seven more faces clear the
auto-accept band instead of landing in review.

One pass is the default because it is 28% faster and **exactly repeatable** —
dlib only applies its random transform when asked for more than one pass, so
rescanning a photo now returns an identical register. Two passes wobbled
between 97 and 101 auto-accepts across nine runs of the same photograph.

The cost is real and it is seven extra confirmation taps on a full hall. Set
`SMALL_FACE_JITTERS=2` to buy them back for three seconds.

### A note on the match threshold

A sweep with 30 of the 120 students held out of the gallery — so any name
given to one of them is a false positive — suggests `MATCH_DISTANCE` has some
headroom above the current 0.52: recall kept climbing to 0.54 without adding a
false positive beyond the one already present at 0.48.

It has **not** been changed. That is one random split of one synthetic room,
and a threshold that decides whether an absent student is marked present is
not something to move on a single sample. `calibrate.py` exists for this and
enforces a zero-false-positive policy; run it against a real labelled class
before touching the default.

### What a hall needs from the host

* **2 or more CPU cores and 2 GB RAM** for a 120-student room at a sensible
  speed. Both detection and encoding scale with cores, so this is the single
  thing most worth spending on: one core works, at roughly 36 s per photo,
  against 8 s on four.
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
