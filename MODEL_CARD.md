# Model card: FaceID Attendance recogniser

## Purpose
Suggest which enrolled students appear in teacher-supplied classroom photos.
The output is **not an attendance decision**: the teacher reviews the roster and
confirms it before the database changes.

## Model and pipeline
- Detector/embedding: `face_recognition` / dlib, 128-dimensional embeddings.
- Default detector: CPU HOG. CNN is optional only with a tested GPU deployment.
- Enrolment: up to five reference photos, quality checks for face size, blur and
  exposure, and jitter-averaged embeddings.
- Classroom detection: optional tiled full-resolution pass, small-face crop and
  enlargement, and a rescue pass for low-resolution uploads.
- Decision: nearest embedding must pass an absolute distance threshold and a
  runner-up margin. Ambiguous, distant and unknown faces go to review.
- Multiple photos: each student is counted once using their best sighting.

This is metric learning, not a generative AI model. Adding an LLM would not make
face recognition more accurate.

## Intended use
Teacher-supervised attendance for a consenting class, preferably in a school-
controlled deployment. Not for surveillance, discipline, exam proctoring,
public-space identification or fully automatic decisions.

## Release acceptance policy
A class is production-ready only after `calibrate.py` runs on images never used
for enrolment. The default gate requires at least 30 enrolled test faces, at
least 10 strangers, precision >= 0.98, recall >= 0.80, zero false-positive
suggestions, and no threshold over 0.60.

If no threshold passes, improve references, lighting, framing or camera
position. Do not loosen the threshold until the report turns green.

## Known limitations
- Very small faces contain insufficient identity information.
- Masks, profiles, motion blur, glare and demographic imbalance reduce accuracy.
- A still photo gives no liveness evidence; printed-photo attacks are not prevented.
- Results apply only to the tested class, camera and environment.

## Human controls
Every session requires review and explicit confirmation. Unknown and ambiguous
faces carry no student ID into attendance. Manual corrections are stored as
manual rather than model-derived marks.
