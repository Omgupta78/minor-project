import os
import face_recognition
import cv2
import numpy as np 
import csv
from datetime import datetime


faces_folder = "faces"
attendance_folder = "attendance"

os.makedirs(attendance_folder, exist_ok=True)

known_face_encodings = []
known_face_names = []

for filename in os.listdir(faces_folder):

    if not filename.lower().endswith(
        (".jpeg", ".png", ".jpg", ".webp")
    ):
        continue

    image_path = os.path.join(faces_folder, filename)
    image_name = os.path.splitext(filename)[0]

    try:
        image = face_recognition.load_image_file(image_path)
        encodings = face_recognition.face_encodings(image)

        if len(encodings) == 0:
            print(f"no face found in image {image_name}")
            continue

        encoding = encodings[0]

        known_face_encodings.append(encoding)
        known_face_names.append(image_name)

        print(f"loaded image : {image_name}")
        

    except Exception as e:
        
        print(f"error loading image : {image_name} {e}")

print("\nfinished loading faces")

if len(known_face_names) == 0:
    print("no faces found")
    exit()


# //////////////////////////////////////

students = known_face_names.copy()

current_date = datetime.now().strftime(
    "%y-%m-%d"
)

attendance_file = os.path.join(
    attendance_folder,
    f"{current_date}.csv"
)

f = open(attendance_file, "w", newline = "")

writer = csv.writer(f)

writer.writerow(
    ["Name", "Time"]
)

# ///////////////////////////////////////////

video_capture = cv2.VideoCapture(0)

print("\nwebcam started")
print("\npress q to quit\n")

while True:

    success, frame = video_capture.read()

    if not success:
        continue

    small_frame = cv2.resize(frame, (0,0), fx = 0.25, fy = 0.25)

    rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

    face_locations = face_recognition.face_locations(rgb_small_frame)

    face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

    for face_encoding, face_location in zip(face_encodings, face_locations):

        name = "Unknown"

        face_distances = face_recognition.face_distance(known_face_encodings, face_encoding)

        best_match_idx = np.argmin(face_distances)

        if face_distances[best_match_idx] < 0.5:
            name = known_face_names[best_match_idx]

        # /////////////////////////////

        if name in students:
            students.remove(name)

            current_time = datetime.now().strftime("%H:%M:%S")
            writer.writerow([name, current_time])

            print(f"attendace marked \n name : {name} at {current_time}")



        top, right, bottom, left = (
            face_location
        )

        # Scale coordinates back.

        top *= 4
        right *= 4
        bottom *= 4
        left *= 4

        # Face box.

        cv2.rectangle(
            frame,
            (left, top),
            (right, bottom),
            (0, 255, 0),
            2
        )

        # Name background.

        cv2.rectangle(
            frame,
            (left, bottom - 35),
            (right, bottom),
            (0, 255, 0),
            cv2.FILLED
        )

        # Name text.

        cv2.putText(
            frame,
            name,
            (left + 6, bottom - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            1
        )

    cv2.imshow("Face attendace system", frame)

    if cv2.waitKey(1) & 0xFF == ord("q") :         
        break


video_capture.release()

cv2.destroyAllWindows()

f.close()

print("\nProgram terminated successfully.")