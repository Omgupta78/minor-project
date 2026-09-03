"""Render preview frames exactly as run_live.py draws them (green box + name
label), one per recognized person, and stitch them into a single preview image."""
import cv2, os, numpy as np, face_recognition

FACES_FOLDER = "faces"
MATCH_DISTANCE = 0.5
DOWNSCALE = 0.25
FONT = cv2.FONT_HERSHEY_SIMPLEX
W, H = 640, 480

# --- load known faces (same as the app) ---
known_encodings, known_names = [], []
for fn in sorted(os.listdir(FACES_FOLDER)):
    if not fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        continue
    img = face_recognition.load_image_file(os.path.join(FACES_FOLDER, fn))
    enc = face_recognition.face_encodings(img)
    if enc:
        known_encodings.append(enc[0])
        known_names.append(os.path.splitext(fn)[0])

# --- build one framed, annotated frame per face photo ---
panels = []
for fn in sorted(os.listdir(FACES_FOLDER)):
    if not fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        continue
    src = cv2.imread(os.path.join(FACES_FOLDER, fn))
    h, w = src.shape[:2]
    scale = min(W / w, H / h) * 0.95
    big = cv2.resize(src, (int(w * scale), int(h * scale)))
    frame = np.zeros((H, W, 3), np.uint8)
    bh, bw = big.shape[:2]
    y0, x0 = (H - bh) // 2, (W - bw) // 2
    frame[y0:y0 + bh, x0:x0 + bw] = big

    small = cv2.resize(frame, (0, 0), fx=DOWNSCALE, fy=DOWNSCALE)
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    locs = face_recognition.face_locations(rgb)
    encs = face_recognition.face_encodings(rgb, locs)

    for enc, loc in zip(encs, locs):
        d = face_recognition.face_distance(known_encodings, enc)
        i = int(np.argmin(d))
        name = known_names[i] if d[i] < MATCH_DISTANCE else "Unknown"
        top, right, bottom, left = [v * 4 for v in loc]
        cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
        cv2.rectangle(frame, (left, bottom - 35), (right, bottom), (0, 255, 0), cv2.FILLED)
        cv2.putText(frame, name, (left + 6, bottom - 6), FONT, 0.8, (255, 255, 255), 1)
    panels.append(frame)

grid = cv2.hconcat(panels)
cv2.imwrite("preview.png", grid)
print("wrote preview.png", grid.shape)
