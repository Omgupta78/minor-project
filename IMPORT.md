# Importing a whole class

Enrolling 120 students one form at a time is not a workflow. The app reads a
folder of photographs — the kind a department already keeps on a shared drive —
and enrols everybody in one go. Adding a single student by hand still works
exactly as before; this is an extra route in, not a replacement.

- **In the app:** Students → **Import a class**
- **From a terminal:** `python import_students.py <folder or zip> --class "CSE 3rd Year A"`

Use the terminal for the first big import. Encoding a reference photo takes
about a second, so 120 students with three photos each is roughly six minutes.
The web page runs the same import as a background job with a progress bar, but
a terminal cannot time out at all.

---

## Which format should I use?

**Use a CSV manifest if you can. Use folder-per-student if you want zero
setup.** Both work; they fail differently.

| | Folder per student | Flat filenames | CSV manifest |
|---|---|---|---|
| Setup | none | none | export one sheet |
| Names with commas, accents, apostrophes | risky on some systems | risky | **safe** |
| Roll numbers with `/` or leading zeros | loses them | loses them | **keeps them** |
| Several photos per student | **natural** | needs `_2` suffixes | **natural** |
| Renaming 360 files | not needed | needed | not needed |
| Fixing a typo later | rename a folder | rename files | edit one cell |
| Auditable, diffable, reviewable | no | no | **yes** |

The manifest wins because **the filenames stop carrying meaning**. Photos can
be called `IMG_2831.jpg` and it does not matter — the spreadsheet says who is
who. That also means the office can maintain the roster in Google Sheets and
re-export whenever it changes, which is the closest thing to a real student
database you will get without building one.

---

## Format 1 — CSV manifest (recommended)

Put a file called `students.csv` beside the photos:

```
CSE-3A/
  students.csv
  photos/
    ravi-front.jpg
    ravi-left.jpg
    priya.jpg
```

```csv
roll_no,name,photo
CS-001,Ravi Kumar,photos/ravi-front.jpg
CS-001,Ravi Kumar,photos/ravi-left.jpg
CS-002,"Singh, Priya",photos/priya.jpg
```

- **One row per photo.** Repeat the roll number to add more photos to the same
  student. Or use one row per student with a `photos` column holding a
  semicolon-separated list: `photos/a.jpg;photos/b.jpg`.
- **Quote any value containing a comma.** Google Sheets and Excel do this for
  you when you export as CSV.
- **The file may also be called** `roster.csv`, `manifest.csv`, `students.tsv`
  or `roster.tsv`.
- **Column headings are matched loosely,** ignoring case, spaces and
  underscores. All of these are understood:
  - roll: `roll_no`, `Roll No`, `Roll Number`, `Enrollment No`, `Registration No`,
    `Reg No`, `Admission No`, `Student ID`, `USN`, `PRN`, `id`
  - name: `name`, `Student Name`, `Full Name`, `student`
  - photo: `photo`, `photos`, `image`, `images`, `file`, `filename`, `picture`
- **Extra columns are ignored,** so your existing sheet with section, email and
  phone columns can be exported as-is.
- **If there is no photo column,** photos are matched by filename instead: any
  image whose name starts with the roll number belongs to that student.

### Making one in Google Sheets

1. Columns `roll_no`, `name`, `photo`.
2. File → Download → **Comma-separated values (.csv)**.
3. Put the downloaded file in the folder with the photos, named `students.csv`.

---

## Format 2 — one folder per student

```
CSE 3rd Year A/
  CS-001 Ravi Kumar/
    front.jpg
    left.jpg
    right.jpg
  CS-002 Priya Singh/
    1.jpg
    2.jpg
```

The folder is named `<roll> <name>`. **The filenames inside do not matter** —
photos straight off a phone are fine. One extra level of nesting is allowed
(`CS-001 Ravi Kumar/photos/front.jpg`), which is what happens when somebody
tidies up.

---

## Format 3 — all photos in one folder

```
CSE 3rd Year A/
  CS-001_Ravi_Kumar.jpg
  CS-001_Ravi_Kumar_2.jpg
  CS-001_Ravi_Kumar_3.jpg
  CS-002_Priya_Singh.jpg
```

Roll number, then an underscore, then the name. A **trailing `_2`, `-3` or
` 4` is a photo number**, not part of the name, so the three files above are
one student with three photos.

---

## The naming rules, precisely

These apply to folder names and to filenames.

| Rule | Example | Result |
|---|---|---|
| The **first space or underscore** separates roll from name | `CS-001 Ravi Kumar` | roll `CS-001`, name `Ravi Kumar` |
| **Hyphens are never separators** | `21-CSE-014 Priya Singh` | roll `21-CSE-014`, name `Priya Singh` |
| Underscores in the name become spaces | `CS-001_Ravi_Kumar` | name `Ravi Kumar` |
| A trailing number is a photo index | `CS-001_Ravi_Kumar_2.jpg` | second photo of `CS-001` |
| Accents and non-English names are kept | `CS-002 Ana María Gómez` | name `Ana María Gómez` |
| A name must contain letters | `IMG_2831.jpg` | **skipped** — reported as a camera filename |

Roll numbers are compared **case-insensitively**. If `CS-001` and `cs-001`
both appear they are reported as a clash rather than silently merged.

---

## Photo requirements

The same quality gate as manual enrolment. A photo that fails is reported with
the reason and skipped; the student is still enrolled from their other photos.

| | Requirement |
|---|---|
| Formats | JPG, JPEG, PNG, WEBP, BMP, **HEIC/HEIF** (iPhone) |
| Face width | at least **80 px** across (`MIN_FACE_PX`) |
| Sharpness | in focus — blurry photos are rejected |
| Lighting | neither very dark nor blown out |
| Faces per photo | one; if there are several the largest is used |
| Orientation | EXIF rotation is applied automatically |
| Stored as | JPEG, at most 1200 px, quality 90 |

**Use three photos per student** — front on, turned slightly left, turned
slightly right. Measured on a 120-student hall photo, going from one reference
photo to three identified seven more students. Up to five are kept
(`MAX_ENROL_PHOTOS`).

A student whose photos are **all** rejected is **not** added to the database.
A student row with no face encoding would be marked absent in every session
for the rest of the term, which is worse than not importing them; they are
listed in the report so you can retake the photo.

---

## Google Drive

The importer does not connect to Drive directly, on purpose. A Drive folder
reachable by link is a folder of children's faces reachable by link, and
biometric data of students is not something to put behind a shareable URL.
Keep the folder private and bring a copy to the app:

### Option A — download the folder (simplest)

1. In Drive, right-click the class folder → **Download**. Drive zips it.
2. In the app: Students → Import a class → **Upload a .zip**.

The zip may have the extra wrapping folder Drive adds; that is handled.

### Option B — Google Drive for Desktop (best if the roster changes)

1. Install Drive for Desktop and let the class folder sync.
2. Run the app on that machine and either
   - Students → Import a class → **Pick a folder**, or
   - `python import_students.py "~/Google Drive/My Drive/CSE 3A" --class "CSE 3rd Year A"`

Re-run it whenever the folder changes. Students already enrolled have their
photos replaced; new students are added. Use `--skip-existing` (or untick
*Replace* on the page) to add only the new ones.

### Option C — a shared network folder

Anything mounted on the machine running the app works the same way as B.
Importing from a server path can be switched off with `ALLOW_PATH_IMPORT=0`,
which you should do on a shared host, where it would otherwise let any teacher
read any folder the process can reach.

---

## Before you import 120 students

1. **Check first.** The page's *Check the folder first* button, or
   `--dry-run` on the command line, reads the folder and reports exactly which
   students were recognised and why any were skipped. It changes nothing.
2. Fix whatever it reports — usually a missing name or a camera filename.
3. Then import.

```
$ python import_students.py roster/ --class "CSE 3rd Year A" --dry-run
Folder : roster
Layout : folders (read one folder per student)
Found  : 12 students ready, 1 with problems, 36 photos
   ok   CS-001       Ravi Kumar                   3 photo(s)
   ...
   skip CS-099 No Photos: the folder holds no readable image
   --   ignored IMG_2831.jpg: loose image outside any student folder
```

---

## What the importer will not do

- It will not invent a roll number or a name. If it cannot read one, the
  student is skipped and reported.
- It will not enrol a student with no usable photo.
- It will not merge two roll numbers that differ only in case.
- It will not extract a zip that writes outside its own folder, or one that
  expands beyond `IMPORT_MAX_UNPACKED_MB` (2048 by default) or
  `IMPORT_MAX_FILES` (5000).
- It will not delete a student who is missing from the folder. Removing
  students is deliberate, one at a time, on the Students page.

## Settings

| Variable | Default | What it does |
|---|---|---|
| `MAX_ENROL_PHOTOS` | 5 | reference photos kept per student |
| `ALLOW_PATH_IMPORT` | 1 | allow importing from a path on the server |
| `IMPORT_DIR` | `instance/imports` | scratch space for an import in progress |
| `IMPORT_MAX_UNPACKED_MB` | 2048 | largest a zip may expand to |
| `IMPORT_MAX_FILES` | 5000 | most files a zip may contain |
| `MIN_FACE_PX` | 80 | smallest acceptable face in an enrolment photo |
