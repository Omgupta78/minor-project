"""Build a test clip from the reference face photos so the recognizer has
something to run against when no webcam is available. Each face is upscaled
onto a 640x480 canvas and held for a number of frames."""
import cv2, os

FACES = "faces"
OUT = "test_faces.mp4"
W, H = 640, 480
HOLD = 40  # frames per face

writer = cv2.VideoWriter(OUT, cv2.VideoWriter_fourcc(*"mp4v"), 20, (W, H))

for fn in sorted(os.listdir(FACES)):
    if not fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        continue
    img = cv2.imread(os.path.join(FACES, fn))
    if img is None:
        continue
    # Upscale so the face is large in the frame, keep aspect, fit within canvas.
    h, w = img.shape[:2]
    scale = min(W / w, H / h) * 0.95
    big = cv2.resize(img, (int(w * scale), int(h * scale)))
    canvas = cv2.imread(os.path.join(FACES, fn)) * 0  # not used; placeholder
    canvas = (0 * cv2.resize(img, (W, H)))            # black WxH
    bh, bw = big.shape[:2]
    y0, x0 = (H - bh) // 2, (W - bw) // 2
    canvas[y0:y0 + bh, x0:x0 + bw] = big
    for _ in range(HOLD):
        writer.write(canvas)
    print(f"added {fn} ({HOLD} frames)")

writer.release()
print(f"wrote {OUT}")
