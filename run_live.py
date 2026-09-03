"""
run_live.py — Face Recognition Attendance System, configurable source.

Same real-time loop as main.py, but you choose the video source:
  * no args                 -> webcam 0  (identical to running main.py)
  * -s 0 / -s 1             -> webcam by index
  * -s path\to\clip.mp4     -> a video file as the "camera"
  * --max-frames N          -> stop after N frames (useful for video files)

Python 3.12+ / Windows notes are in README-run.md. Requires:
  pip install -r requirements.txt
"""
import argparse
import csv
import os
from datetime import datetime

import cv2
import numpy as np
import face_recognition

# ---------------------------------------------------------------- settings

FACES_FOLDER = "faces"
ATTENDANCE_FOLDER = "attendance"
MATCH_DISTANCE = 0.5          # same threshold as main.py
DOWNSCALE = 0.25              # same as main.py
FONT = cv2.FONT_HERSHEY_SIMPLEX

# ------------------------------------------------------- load known faces


def load_known_faces(faces_folder: str):
    """Load one encoding per face image in the folder (same as main.py)."""
    known_encodings, known_names = [], []

    for filename in sorted(os.listdir(faces_folder)):
        if not filename.lower().endswith((".jpeg", ".png", ".jpg", ".webp")):
            continue

        name = os.path.splitext(filename)[0]
        try:
            image = face_recognition.load_image_file(os.path.join(faces_folder, filename))
            encodings = face_recognition.face_encodings(image)
        except Exception as exc:
            print(f"error loading image: {name} -> {exc}")
            continue

        if not encodings:
            print(f"no face found in image {name} — skip (use a clear, front-facing photo)")
            continue

        known_encodings.append(encodings[0])
        known_names.append(name)
        print(f"loaded image: {name}")

    if not known_names:
        print("no faces loaded — put face images in the 'faces' folder and retry")
        raise SystemExit(1)
    return known_encodings, known_names


# ------------------------------------------------------------- attendance


def open_attendance_csv(attendance_folder: str):
    """Open today's CSV. Appends if it already exists (so re-runs don't
    wipe earlier marks), otherwise creates it with a header."""
    os.makedirs(attendance_folder, exist_ok=True)
    current_date = datetime.now().strftime("%y-%m-%d")
    path = os.path.join(attendance_folder, f"{current_date}.csv")

    exists = os.path.isfile(path)
    handle = open(path, "a", newline="")
    writer = csv.writer(handle)
    if not exists:
        writer.writerow(["Name", "Time"])
    print(f"attendance file: {path} (appending)" if exists else f"attendance file: {path} (new)")
    return handle, writer


# ------------------------------------------------------------------ main


def probe_display():
    """Return a show(frame) callable. If this build of OpenCV has no GUI
    backend (server/no display), run headless instead of crashing on imshow."""
    try:
        cv2.imshow("probe", np.zeros((10, 10, 3), np.uint8))
        cv2.waitKey(1)
        cv2.destroyAllWindows()
        return lambda frame: (cv2.imshow("Face attendance system", frame),
                              cv2.waitKey(1) & 0xFF)
    except cv2.error:
        print("no display available — running headless (frames processed, no window,"
              " attendance still written)")
        return lambda _frame: -1


def open_source(source: str):
    if source.isdigit():
        cap = cv2.VideoCapture(int(source))
        print(f"webcam started: index {source} (press q to quit)")
    else:
        cap = cv2.VideoCapture(source)
        print(f"video source started: {source} (use --max-frames to stop)")
    return cap


def main() -> None:
    parser = argparse.ArgumentParser(description="Face recognition attendance system")
    parser.add_argument("-s", "--source", default="0",
                        help="camera index (0 = default webcam) or path to a video file")
    parser.add_argument("--max-frames", type=int, default=0,
                        help="stop after N frames (0 = run until 'q' / end of video)")
    args = parser.parse_args()

    known_encodings, known_names = load_known_faces(FACES_FOLDER)

    # Names that have NOT yet been marked today (same logic as main.py).
    unmarked = known_names.copy()

    f, writer = open_attendance_csv(ATTENDANCE_FOLDER)

    cap = open_source(args.source)
    show = probe_display()
    frame_count = 0

    try:
        while True:
            success, frame = cap.read()
            if not success:
                print("no more frames — ending")
                break

            frame_count += 1
            if args.max_frames and frame_count >= args.max_frames:
                print(f"reached --max-frames {args.max_frames} — ending")
                break

            small = cv2.resize(frame, (0, 0), fx=DOWNSCALE, fy=DOWNSCALE)
            rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

            face_locations = face_recognition.face_locations(rgb_small)
            face_encodings = face_recognition.face_encodings(rgb_small, face_locations)

            for face_encoding, face_location in zip(face_encodings, face_locations):
                distances = face_recognition.face_distance(known_encodings, face_encoding)
                best_idx = int(np.argmin(distances))
                name = "Unknown"
                if distances[best_idx] < MATCH_DISTANCE:
                    name = known_names[best_idx]

                # Mark attendance once per person, per session (same as main.py).
                if name in unmarked:
                    unmarked.remove(name)
                    current_time = datetime.now().strftime("%H:%M:%S")
                    writer.writerow([name, current_time])
                    f.flush()
                    print(f"attendance marked: {name} at {current_time}")

                # Scale the box back up and draw (same look as main.py).
                top, right, bottom, left = face_location
                top, right, bottom, left = top * 4, right * 4, bottom * 4, left * 4
                cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
                cv2.rectangle(frame, (left, bottom - 35), (right, bottom), (0, 255, 0), cv2.FILLED)
                cv2.putText(frame, name, (left + 6, bottom - 6), FONT, 0.8, (255, 255, 255), 1)

            if show(frame) == ord("q"):
                break
    finally:
        cap.release()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass  # headless builds have no window manager
        f.close()

    print(f"\nfinished — processed {frame_count} frames, attendance saved")
    print("Program terminated successfully.")


if __name__ == "__main__":
    main()
