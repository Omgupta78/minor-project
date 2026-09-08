"""
Face Recognition Attendance System — Flask Web App
Teacher uploads a group photo → AI identifies students → Excel export
"""

import os
import csv
import base64
import io
from datetime import datetime
from pathlib import Path

import numpy as np
import face_recognition
import cv2
from flask import Flask, jsonify, render_template, request, send_file
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
FACES_FOLDER     = "faces"
ATTENDANCE_FOLDER = "attendance"
UPLOAD_FOLDER    = "uploads"
MATCH_DISTANCE   = 0.50        # lower = stricter

os.makedirs(ATTENDANCE_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024   # 16 MB max upload

# ─────────────────────────────────────────────
# Load known faces at startup
# ─────────────────────────────────────────────
known_encodings: list = []
known_names: list[str] = []

def load_known_faces() -> None:
    global known_encodings, known_names
    known_encodings, known_names = [], []
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    for fpath in Path(FACES_FOLDER).iterdir():
        if fpath.suffix.lower() not in exts:
            continue
        try:
            img = face_recognition.load_image_file(str(fpath))
            encs = face_recognition.face_encodings(img)
            if encs:
                known_encodings.append(encs[0])
                known_names.append(fpath.stem)
                print(f"  [faces] loaded: {fpath.stem}")
            else:
                print(f"  [faces] no face in: {fpath.name}")
        except Exception as e:
            print(f"  [faces] error loading {fpath.name}: {e}")
    print(f"[startup] {len(known_names)} known face(s): {known_names}")

load_known_faces()

# ─────────────────────────────────────────────
# Attendance helpers
# ─────────────────────────────────────────────
def today_csv() -> str:
    date_str = datetime.now().strftime("%y-%m-%d")
    return os.path.join(ATTENDANCE_FOLDER, f"{date_str}.csv")

def already_marked_today() -> set[str]:
    path = today_csv()
    if not os.path.exists(path):
        return set()
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return {row["Name"] for row in reader}

def mark_attendance(names: list[str]) -> list[dict]:
    """Mark names as present. Returns list of {name, time, already_marked}."""
    marked_set = already_marked_today()
    path = today_csv()
    new_file = not os.path.exists(path)
    results = []

    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["Name", "Time"])
        for name in names:
            now = datetime.now().strftime("%H:%M:%S")
            already = name in marked_set
            if not already:
                writer.writerow([name, now])
                marked_set.add(name)
            results.append({"name": name, "time": now, "already": already})
    return results

# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", students=known_names, active_page="dashboard")

@app.route("/students_page")
def students_page():
    return render_template("students_page.html", students=known_names, active_page="students")

@app.route("/add-student", methods=["POST"])
def add_student():
    if "student_photo" not in request.files or not request.form.get("student_name"):
        return jsonify({"error": "Missing name or photo"}), 400
    
    file = request.files["student_photo"]
    name = request.form["student_name"].strip()
    
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
        
    save_path = os.path.join(FACES_FOLDER, f"{name}.jpg")
    
    # Convert image (supports HEIC thanks to pillow-heif) to RGB JPG
    import pillow_heif
    from PIL import Image
    try:
        # Check if it's HEIC first
        if file.filename.lower().endswith(('.heic', '.heif')):
            heif_file = pillow_heif.read_heif(file)
            image = Image.frombytes(
                heif_file.mode, 
                heif_file.size, 
                heif_file.data,
                "raw",
                heif_file.mode,
                heif_file.stride,
            )
        else:
            image = Image.open(file)
            
        # Convert to RGB to ensure jpeg save works
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
            
        image.save(save_path, "JPEG")
    except Exception as e:
        return jsonify({"error": f"Failed to process image: {str(e)}"}), 400
    
    # Reload faces to include the new one
    load_known_faces()
    
    from flask import redirect
    return redirect("/students_page")

@app.route("/records")
def records():
    csv_files = []
    for csv_path in sorted(Path(ATTENDANCE_FOLDER).glob("*.csv"), reverse=True):
        count = 0
        with open(csv_path, newline="") as f:
            count = sum(1 for row in f) - 1 # Subtract header
        csv_files.append({
            "filename": csv_path.name,
            "date_str": csv_path.stem,
            "count": max(0, count)
        })
    return render_template("records.html", students=known_names, csv_files=csv_files, active_page="records")

@app.route("/students")
def students():
    return jsonify({"students": known_names, "total": len(known_names)})

@app.route("/attendance-today")
def attendance_today():
    path = today_csv()
    rows = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    return jsonify({"records": rows, "date": datetime.now().strftime("%Y-%m-%d")})

@app.route("/take-attendance", methods=["POST"])
def take_attendance():
    # Accept either file upload or base64 data-URL
    img_array = None

    if "photo" in request.files:
        f = request.files["photo"]
        data = f.read()
        img_array = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

    elif request.is_json and "image" in request.json:
        # Base64 data URL: "data:image/jpeg;base64,..."
        b64 = request.json["image"].split(",", 1)[-1]
        data = base64.b64decode(b64)
        img_array = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

    if img_array is None:
        return jsonify({"error": "No image provided"}), 400

    # Convert BGR → RGB for face_recognition
    rgb = cv2.cvtColor(img_array, cv2.COLOR_BGR2RGB)

    # Downscale for speed (0.5×)
    scale = 0.5
    small = cv2.resize(rgb, (0, 0), fx=scale, fy=scale)

    locations  = face_recognition.face_locations(small)
    encodings  = face_recognition.face_encodings(small, locations)

    recognized, unknown = [], []

    for enc, loc in zip(encodings, locations):
        if known_encodings:
            distances  = face_recognition.face_distance(known_encodings, enc)
            best_idx   = int(np.argmin(distances))
            best_dist  = float(distances[best_idx])
            if best_dist <= MATCH_DISTANCE:
                recognized.append(known_names[best_idx])
            else:
                unknown.append("Unknown")
        else:
            unknown.append("Unknown")

    # Remove duplicates but keep order
    seen = set()
    unique_recognized = []
    for n in recognized:
        if n not in seen:
            seen.add(n)
            unique_recognized.append(n)

    # Mark attendance
    results = mark_attendance(unique_recognized)

    # Build bounding-box data (scaled back up)
    boxes = []
    for i, (top, right, bottom, left) in enumerate(locations):
        top    = int(top    / scale)
        right  = int(right  / scale)
        bottom = int(bottom / scale)
        left   = int(left   / scale)
        name = recognized[i] if i < len(recognized) else "Unknown"
        boxes.append({"top": top, "right": right, "bottom": bottom, "left": left, "name": name})

    return jsonify({
        "recognized": unique_recognized,
        "unknown_count": len(unknown),
        "total_faces": len(locations),
        "results": results,
        "boxes": boxes,
    })

@app.route("/reload-faces", methods=["POST"])
def reload_faces():
    load_known_faces()
    return jsonify({"status": "ok", "students": known_names})

@app.route("/static/faces/<path:filename>")
def serve_face(filename):
    from flask import send_from_directory
    return send_from_directory(FACES_FOLDER, filename)

@app.route("/download-excel")
def download_excel():
    """Build an Excel workbook from all attendance CSVs and send it."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)   # remove default sheet

    # Styles
    hdr_fill   = PatternFill("solid", fgColor="1B4332")
    hdr_font   = Font(bold=True, color="FFFFFF", size=11)
    alt_fill   = PatternFill("solid", fgColor="D8F3DC")
    center     = Alignment(horizontal="center", vertical="center")
    thin       = Side(style="thin", color="CCCCCC")
    border     = Border(left=thin, right=thin, top=thin, bottom=thin)

    csv_files = sorted(Path(ATTENDANCE_FOLDER).glob("*.csv"))
    if not csv_files:
        # Return empty workbook with info sheet
        ws = wb.create_sheet("No Records")
        ws["A1"] = "No attendance records found."
    else:
        for csv_path in csv_files:
            sheet_name = csv_path.stem  # e.g. "26-09-06"
            ws = wb.create_sheet(title=sheet_name)

            rows_data = []
            with open(csv_path, newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    rows_data.append(row)

            for r_idx, row in enumerate(rows_data, start=1):
                for c_idx, val in enumerate(row, start=1):
                    cell = ws.cell(row=r_idx, column=c_idx, value=val)
                    cell.border = border
                    cell.alignment = center
                    if r_idx == 1:
                        cell.fill = hdr_fill
                        cell.font = hdr_font
                    elif r_idx % 2 == 0:
                        cell.fill = alt_fill

            # Auto-fit columns
            for col in ws.columns:
                max_len = max((len(str(c.value or "")) for c in col), default=10)
                ws.column_dimensions[get_column_letter(col[0].column)].width = max_len + 4

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"attendance_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("\n[*] Face Attendance System starting...")
    print("    Open http://localhost:5000 in your browser\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
