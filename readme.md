# Face Recognition Attendance System

A real-time face recognition based attendance system built using Python, OpenCV, and the `face_recognition` library. The application automatically detects and recognizes registered individuals through a webcam feed and records their attendance in a CSV file with timestamps.

## Features

* Real-time face detection using webcam input
* Automatic face recognition using facial embeddings
* Dynamic loading of registered users from a folder
* Attendance recorded only once per session
* Automatic CSV attendance generation with date and time
* Face bounding boxes and name labels displayed on live video
* Supports multiple registered users without code changes
* Easy to extend with databases, dashboards, or APIs

---

## How It Works

1. The system loads all face images from the `faces/` directory.
2. A facial encoding (numerical representation of the face) is generated for each registered person.
3. The webcam continuously captures video frames.
4. Faces detected in each frame are converted into encodings.
5. Encodings are compared against the registered users.
6. If a match is found:

   * The person's name is displayed.
   * Attendance is marked.
   * The entry is stored in a CSV file with the current timestamp.
7. Duplicate attendance entries are prevented within the same session.

---

## Project Structure

```text
Face_recog_system/
│
├── main.py
├── requirements.txt
│
├── faces/
│   ├── Rakesh.jpg
│   ├── Ravi.jpg
│   └── Sukesh.jpg
│
├── attendance/
│   └── 25-06-15.csv
│
└── README.md
```

---

## Technologies Used

### Backend

* Python 3.12+
* OpenCV
* face_recognition
* NumPy

### Data Storage

* CSV

### Computer Vision

* dlib
* Face Embeddings
* Real-time Video Processing

---

## Installation

### Clone Repository

```bash
git clone https://github.com/yourusername/face-recognition-attendance-system.git

cd face-recognition-attendance-system
```

### Create Virtual Environment

```bash
python -m venv .venv
```

### Activate Environment

Windows:

```bash
.\.venv\Scripts\activate
```

Linux / macOS:

```bash
source .venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Adding New Users

Simply place a clear image of the person's face inside the `faces/` folder.

Example:

```text
faces/
├── Rakesh.jpg
├── Ravi.jpg
├── Sukesh.jpg
```

## Running the Project

```bash
python main.py
```

Press:

```text
q
```

to exit the application.

---

## Example Attendance Output

```csv
Name,Time
Rakesh,14:05:11
Ravi,14:07:32
Sukesh,14:10:19
```

---

## Challenges Solved

* Real-time face recognition
* Face embedding generation
* Duplicate attendance prevention
* Automatic user registration through folder scanning
* Webcam integration with OpenCV
* Attendance persistence through CSV logging

---

## Future Improvements

* SQLite/PostgreSQL database integration
* Attendance dashboard
* Confidence score display
* Unknown face alerts
* Multiple images per user
* Liveness detection (anti-spoofing)
* REST API using FastAPI
* Cloud deployment
* Mobile application integration

---

## Learning Outcomes

This project helped develop practical skills in:

* Python Programming
* Computer Vision
* OpenCV
* Face Recognition Systems
* Real-time Video Processing
* File Handling
* Data Persistence
* NumPy
* Debugging and Dependency Management
