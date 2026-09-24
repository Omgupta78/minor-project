"""
roster_import.py - enrol a whole class at once from a folder, a zip or a CSV.

Adding 120 students one form at a time is not a workflow, it is a punishment.
A school already has the roster somewhere: a shared drive of photographs, a
spreadsheet the office keeps, a folder the class teacher assembled. This reads
that as it is, rather than asking anyone to rename 360 files by hand.

Three layouts are understood, and the right one is detected automatically.

  1. A CSV manifest (recommended - see IMPORT.md for why)

        students.csv
        photos/CS-001-a.jpg ...

     roll_no,name,photo
     CS-001,Ravi Kumar,photos/CS-001-a.jpg
     CS-001,Ravi Kumar,photos/CS-001-b.jpg

     Several rows per student add several reference photos. A `photos` column
     holding a semicolon-separated list works too.

  2. One folder per student

        CS-001 Ravi Kumar/front.jpg, left.jpg, right.jpg
        CS-002 Priya Singh/1.jpg

  3. Flat files in one folder

        CS-001_Ravi_Kumar.jpg
        CS-001_Ravi_Kumar_2.jpg
        CS-002_Priya_Singh.jpg

Nothing here imports Flask, so the whole thing is testable without a web
server (importtest.py), and the CLI (import_students.py) and the web route
share one implementation rather than two that drift apart.
"""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

import recognition

# Names a manifest may go by, in the order they are looked for.
MANIFEST_NAMES = (
    "students.csv",
    "roster.csv",
    "manifest.csv",
    "students.tsv",
    "roster.tsv",
)

# Column headings accepted for each field, lower-cased and stripped of spaces
# and underscores. A spreadsheet exported from Sheets or Excel rarely uses the
# exact words a programmer would pick, so accept the obvious variations rather
# than rejecting the file.
ROLL_HEADINGS = {
    "rollno", "roll", "rollnumber", "rollnum", "enrollmentno", "enrolmentno",
    "enrollment", "registrationno", "regno", "admissionno", "studentid", "id",
    "usn", "prn",
}
NAME_HEADINGS = {"name", "studentname", "fullname", "student"}
PHOTO_HEADINGS = {"photo", "photos", "image", "images", "file", "filename", "picture"}

# Files a Drive or macOS download drops in that are not student photos.
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "icon\r"}
JUNK_PREFIXES = ("._", "~$")

# Filenames a camera or a messaging app produces. They carry no roll number and
# no name, so importing them would create students called "2831" and "20240412"
# that nobody can ever match. Flagged, never guessed at.
CAMERA_PATTERNS = re.compile(
    r"^(img|dsc|dscn|pxl|p|photo|image|screenshot|scaled|whatsapp|fb|received)[ _-]",
    re.IGNORECASE,
)

MAX_ROLL_LEN = 40
MAX_NAME_LEN = 120
# A zip that expands to more than this is refused rather than filling the disk.
MAX_UNPACKED_BYTES = int(os.environ.get("IMPORT_MAX_UNPACKED_MB", "2048")) * 1024 * 1024
MAX_MEMBERS = int(os.environ.get("IMPORT_MAX_FILES", "5000"))


class ImportError_(Exception):
    """A problem that stops the whole import, with a message for the teacher."""


@dataclass
class Candidate:
    """One student the importer believes it found."""

    roll_no: str
    name: str
    photos: list[Path] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.problems and bool(self.photos)


@dataclass
class Plan:
    """What an import would do, before it does any of it."""

    root: Path
    layout: str = "unknown"
    students: list[Candidate] = field(default_factory=list)
    ignored: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def usable(self) -> list[Candidate]:
        return [s for s in self.students if s.usable]

    @property
    def rejected(self) -> list[Candidate]:
        return [s for s in self.students if not s.usable]

    @property
    def photo_count(self) -> int:
        return sum(len(s.photos) for s in self.students)


@dataclass
class Result:
    """What an import actually did."""

    added: int = 0
    updated: int = 0
    failed: int = 0
    photos_used: int = 0
    photos_rejected: int = 0
    messages: list[str] = field(default_factory=list)


# ----------------------------------------------------------------- unpacking
def _is_junk(name: str) -> bool:
    lowered = name.lower()
    return lowered in JUNK_NAMES or name.startswith(JUNK_PREFIXES)


def unpack(source: os.PathLike | str, workdir: os.PathLike | str) -> Path:
    """Return a directory holding the roster, extracting a zip if needed.

    A zip is what Google Drive hands you when you download a folder, so it is
    the format most teachers will actually arrive with.

    Extraction is done member by member rather than with extractall, because
    a zip can name its members '../../etc/passwd' (zip slip) and extractall
    will happily write there. Everything outside the destination is refused,
    as are symlinks, and the total expanded size is capped so a small
    malicious file cannot fill the disk.
    """
    source = Path(source)
    if source.is_dir():
        return source
    if not source.exists():
        raise ImportError_(f"There is nothing at {source}.")
    if source.suffix.lower() != ".zip":
        raise ImportError_(
            f"{source.name} is neither a folder nor a .zip file. "
            "Download the Drive folder as a zip, or point at a folder."
        )

    destination = Path(workdir) / "unpacked"
    destination.mkdir(parents=True, exist_ok=True)
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise ImportError_(f"{source.name} is not a readable zip file.") from exc

    with archive:
        members = archive.infolist()
        if len(members) > MAX_MEMBERS:
            raise ImportError_(
                f"That zip holds {len(members)} files; the limit is {MAX_MEMBERS}."
            )
        total = sum(m.file_size for m in members)
        if total > MAX_UNPACKED_BYTES:
            raise ImportError_(
                f"That zip expands to {total // 1048576} MB; the limit is "
                f"{MAX_UNPACKED_BYTES // 1048576} MB."
            )
        root = destination.resolve()
        for member in members:
            if member.is_dir():
                continue
            # 0xA000 is the symlink bit in the external attributes of a zip
            # made on Unix. A symlink could point anywhere once followed.
            if (member.external_attr >> 16) & 0xF000 == 0xA000:
                continue
            name = member.filename.replace("\\", "/")
            if _is_junk(Path(name).name):
                continue
            target = (destination / name).resolve()
            if not target.is_relative_to(root):
                raise ImportError_(
                    f"That zip tries to write outside the folder ({member.filename}). "
                    "Refusing to extract it."
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)

    # Drive wraps the folder you downloaded in one more folder. If that is all
    # there is, step into it so the layout detection sees the real thing.
    entries = [p for p in destination.iterdir() if not _is_junk(p.name)]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return destination


# -------------------------------------------------------------- name parsing
def clean_text(value: Optional[str]) -> str:
    """Trim, collapse whitespace, and normalise unicode.

    Names arrive from spreadsheets full of non-breaking spaces and from macOS
    filenames in NFD, where 'é' is two code points. Normalising to NFC means
    the same student typed two ways compares equal.
    """
    text = unicodedata.normalize("NFC", str(value or ""))
    text = text.replace(" ", " ").replace("​", "")
    return re.sub(r"\s+", " ", text).strip()


def strip_photo_index(stem: str) -> str:
    """Drop a trailing photo number: 'CS-001_Ravi_Kumar_2' -> 'CS-001_Ravi_Kumar'.

    Only a *trailing* group of digits after a separator is removed, so a name
    that genuinely ends in a number keeps it as long as it is not separated.
    """
    return re.sub(r"[ _-]+\d{1,3}$", "", stem).strip(" _-")


def split_label(text: str) -> tuple[str, str]:
    """Split 'CS-001 Ravi Kumar' or 'CS-001_Ravi_Kumar' into (roll, name).

    The split is on the FIRST underscore or space only. Roll numbers routinely
    contain hyphens (CS-001, 21-CSE-014), so hyphens are never separators --
    splitting on them would turn CS-001 into roll 'CS' and name '001'.
    """
    cleaned = clean_text(text)
    match = re.match(r"^\s*([^\s_]+)[\s_]+(.*)$", cleaned)
    if not match:
        return cleaned, ""
    roll, name = match.group(1), match.group(2)
    return roll.strip(), clean_text(name.replace("_", " "))


def image_files(folder: Path) -> list[Path]:
    """Every readable image directly inside a folder, in a stable order."""
    out = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or _is_junk(path.name):
            continue
        if path.suffix.lower() in recognition.IMAGE_EXTS:
            out.append(path)
    return out


# ------------------------------------------------------------------ manifest
def find_manifest(root: Path) -> Optional[Path]:
    lowered = {p.name.lower(): p for p in root.iterdir() if p.is_file()}
    for name in MANIFEST_NAMES:
        if name in lowered:
            return lowered[name]
    return None


def _heading_key(text: str) -> str:
    return re.sub(r"[\s_.\-]+", "", str(text or "")).strip().lower()


def read_manifest(path: Path, root: Path) -> tuple[list[Candidate], list[tuple[str, str]]]:
    """Read a CSV/TSV manifest into candidates, keeping row order."""
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    # utf-8-sig: Excel writes a byte-order mark that would otherwise become
    # part of the first column heading and stop it being recognised.
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ImportError_(f"{path.name} is empty.")

    columns = {_heading_key(h): h for h in reader.fieldnames if h}
    roll_col = next((columns[k] for k in columns if k in ROLL_HEADINGS), None)
    name_col = next((columns[k] for k in columns if k in NAME_HEADINGS), None)
    photo_col = next((columns[k] for k in columns if k in PHOTO_HEADINGS), None)
    if roll_col is None or name_col is None:
        raise ImportError_(
            f"{path.name} needs a roll-number column and a name column. "
            f"Found: {', '.join(reader.fieldnames)}. "
            "Name them 'roll_no' and 'name'."
        )

    by_roll: dict[str, Candidate] = {}
    order: list[str] = []
    ignored: list[tuple[str, str]] = []

    for line_no, row in enumerate(reader, start=2):
        roll = clean_text(row.get(roll_col))
        name = clean_text(row.get(name_col))
        if not roll and not name:
            continue  # a blank row at the end of a spreadsheet
        key = roll.casefold()
        if key not in by_roll:
            by_roll[key] = Candidate(roll_no=roll, name=name)
            order.append(key)
        candidate = by_roll[key]
        if name and candidate.name and name != candidate.name:
            candidate.problems.append(
                f"row {line_no}: roll {roll} is given two names "
                f"('{candidate.name}' and '{name}')"
            )
        candidate.name = candidate.name or name

        if photo_col:
            listed = [p for p in re.split(r"[;|]", row.get(photo_col) or "") if p.strip()]
        else:
            listed = []
        if not listed and not photo_col:
            # No photo column: fall back to files named after the roll number.
            listed = []
        for entry in listed:
            resolved = _resolve_photo(root, entry.strip())
            if resolved is None:
                ignored.append((entry.strip(), f"row {line_no}: no such file"))
            else:
                candidate.photos.append(resolved)

    candidates = [by_roll[k] for k in order]
    if not photo_col:
        # Photos are matched by filename instead: CS-001*.jpg anywhere below root.
        lookup = _index_by_roll(root)
        for candidate in candidates:
            candidate.photos = lookup.get(candidate.roll_no.casefold(), [])
    return candidates, ignored


def _resolve_photo(root: Path, entry: str) -> Optional[Path]:
    """Find a photo named by a manifest row, without escaping the folder."""
    entry = entry.replace("\\", "/").lstrip("/")
    candidate = (root / entry).resolve()
    if not candidate.is_relative_to(root.resolve()):
        return None
    if candidate.is_file():
        return candidate
    # The manifest may name the file alone while it sits in a sub-folder.
    matches = [p for p in root.rglob(Path(entry).name) if p.is_file()]
    return matches[0] if matches else None


def _index_by_roll(root: Path) -> dict[str, list[Path]]:
    """Group every image under root by the roll number its filename starts with."""
    grouped: dict[str, list[Path]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _is_junk(path.name):
            continue
        if path.suffix.lower() not in recognition.IMAGE_EXTS:
            continue
        roll, _name = split_label(strip_photo_index(path.stem))
        grouped.setdefault(roll.casefold(), []).append(path)
    return grouped


# ------------------------------------------------------------ folder layouts
def read_folders(root: Path) -> tuple[list[Candidate], list[tuple[str, str]]]:
    """One sub-folder per student, named '<roll> <name>'."""
    candidates: list[Candidate] = []
    ignored: list[tuple[str, str]] = []
    for folder in sorted(
        (p for p in root.iterdir() if p.is_dir() and not _is_junk(p.name)),
        key=lambda p: p.name.lower(),
    ):
        photos = image_files(folder)
        # One level of nesting is common when people tidy up ("CS-001/photos").
        if not photos:
            for inner in sorted(p for p in folder.iterdir() if p.is_dir()):
                photos.extend(image_files(inner))
        roll, name = split_label(folder.name)
        candidate = Candidate(roll_no=roll, name=name, photos=photos)
        if not photos:
            candidate.problems.append("the folder holds no readable image")
        candidates.append(candidate)
    for path in sorted(root.iterdir()):
        if path.is_file() and path.suffix.lower() in recognition.IMAGE_EXTS:
            ignored.append((path.name, "loose image outside any student folder"))
    return candidates, ignored


def read_flat(root: Path) -> tuple[list[Candidate], list[tuple[str, str]]]:
    """All photos in one folder, named '<roll>_<name>[_n].jpg'."""
    by_roll: dict[str, Candidate] = {}
    order: list[str] = []
    ignored: list[tuple[str, str]] = []
    for path in image_files(root):
        roll, name = split_label(strip_photo_index(path.stem))
        if not roll:
            ignored.append((path.name, "no roll number in the filename"))
            continue
        key = roll.casefold()
        if key not in by_roll:
            by_roll[key] = Candidate(roll_no=roll, name=name)
            order.append(key)
        candidate = by_roll[key]
        candidate.name = candidate.name or name
        candidate.photos.append(path)
    return [by_roll[k] for k in order], ignored


# ---------------------------------------------------------------- the plan
def detect_layout(root: Path) -> str:
    if find_manifest(root) is not None:
        return "manifest"
    folders = [p for p in root.iterdir() if p.is_dir() and not _is_junk(p.name)]
    if folders:
        return "folders"
    return "flat"


def build_plan(root: os.PathLike | str) -> Plan:
    """Read a folder into a plan, validating but changing nothing."""
    root = Path(root)
    if not root.is_dir():
        raise ImportError_(f"{root} is not a folder.")

    plan = Plan(root=root, layout=detect_layout(root))
    if plan.layout == "manifest":
        manifest = find_manifest(root)
        plan.students, plan.ignored = read_manifest(manifest, root)
        plan.notes.append(f"read the roster from {manifest.name}")
    elif plan.layout == "folders":
        plan.students, plan.ignored = read_folders(root)
        plan.notes.append("read one folder per student")
    else:
        plan.students, plan.ignored = read_flat(root)
        plan.notes.append("read photos named <roll>_<name>.jpg")

    validate(plan)
    return plan


def validate(plan: Plan) -> Plan:
    """Attach a problem to every candidate that cannot be enrolled as read."""
    seen: dict[str, str] = {}
    for candidate in plan.students:
        roll = candidate.roll_no
        if not roll:
            candidate.problems.append("no roll number could be read")
        elif len(roll) > MAX_ROLL_LEN:
            candidate.problems.append(f"the roll number is longer than {MAX_ROLL_LEN} characters")
        if not candidate.name:
            candidate.problems.append(
                "no name could be read - name the folder or file '<roll> <name>'"
            )
        elif not any(ch.isalpha() for ch in candidate.name):
            # 'IMG_2831.jpg' parses to roll 'IMG', name '2831'. A real name has
            # letters in it, so this is a camera filename, not a student.
            candidate.problems.append(
                f"'{candidate.roll_no} {candidate.name}' has no name in it - "
                "this looks like a camera filename, so it was not imported"
            )
        elif CAMERA_PATTERNS.match(f"{candidate.roll_no} "):
            candidate.problems.append(
                f"'{candidate.roll_no}' looks like a camera filename prefix, "
                "not a roll number - rename the file '<roll> <name>.jpg'"
            )
        elif len(candidate.name) > MAX_NAME_LEN:
            candidate.name = candidate.name[:MAX_NAME_LEN]
            plan.notes.append(f"{roll}: the name was shortened to {MAX_NAME_LEN} characters")
        if not candidate.photos:
            candidate.problems.append("no photo was found for this student")

        key = roll.casefold()
        if key and key in seen and seen[key] != roll:
            candidate.problems.append(
                f"the roll number clashes with '{seen[key]}' (they differ only in case)"
            )
        seen.setdefault(key, roll)
    return plan


# ------------------------------------------------------------------ enrolling
def safe_filename(roll_no: str, name: str, index: int) -> str:
    """A filesystem-safe, collision-free name for a stored reference photo."""
    def slug(text: str) -> str:
        cleaned = unicodedata.normalize("NFKD", text)
        cleaned = cleaned.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^A-Za-z0-9_-]+", "_", cleaned).strip("_")[:40] or "student"

    suffix = "" if index == 1 else f"_{index}"
    return f"{slug(roll_no)}_{slug(name)}{suffix}.jpg"


def store_photo(source: Path, target: Path) -> None:
    """Re-encode a reference photo to JPEG, honouring the EXIF rotation flag.

    Everything is normalised on the way in, exactly as the single-student form
    does it, so the rest of the app never meets a HEIC or a sideways photo.
    """
    from PIL import Image, ImageOps

    recognition.register_heif()
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail((1200, 1200))
        image.convert("RGB").save(target, "JPEG", quality=90)


def enrol(
    plan: Plan,
    conn,
    class_id: int,
    faces_dir: os.PathLike | str,
    *,
    replace: bool = True,
    max_photos: int = 5,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Result:
    """Enrol every usable candidate. Returns what happened, per student.

    Each photo goes through the same quality gate as a single manual
    enrolment, so a blurry or faceless photo is reported with its reason
    rather than quietly becoming a reference nobody can match against.

    A student whose photos are all rejected is counted as failed and left out
    of the database entirely: a student row with no encoding would be marked
    absent in every session for the rest of the term, which is worse than not
    importing them.

    Each student is committed as they are finished, rather than the whole
    class in one transaction, for two reasons. An import that dies halfway --
    a restart, a bad photo, a full disk -- keeps the students it managed
    instead of losing an hour of encoding. And a write transaction held open
    for the length of the import locks the database against everything else,
    including the progress the teacher is watching.
    """
    import db

    faces_dir = Path(faces_dir)
    faces_dir.mkdir(parents=True, exist_ok=True)
    result = Result()
    todo = plan.usable
    total = len(todo)

    for position, candidate in enumerate(todo, start=1):
        if on_progress:
            on_progress(position, total, candidate.roll_no)

        encodings: list = []
        stored: list[Path] = []
        for index, source in enumerate(candidate.photos[:max_photos], start=1):
            target = faces_dir / safe_filename(candidate.roll_no, candidate.name, index)
            try:
                store_photo(source, target)
            except Exception as exc:
                result.photos_rejected += 1
                result.messages.append(f"{candidate.roll_no}: {source.name} could not be read ({exc})")
                continue
            try:
                encoding, report = recognition.encode_face_checked(target)
            except recognition.RecognitionUnavailable:
                target.unlink(missing_ok=True)
                for path in stored:
                    path.unlink(missing_ok=True)
                raise
            if encoding is None:
                target.unlink(missing_ok=True)
                result.photos_rejected += 1
                result.messages.append(
                    f"{candidate.roll_no}: {source.name} - {report.get('problem')}"
                )
                continue
            encodings.append(encoding)
            stored.append(target)

        if not encodings:
            result.failed += 1
            result.messages.append(
                f"{candidate.roll_no} {candidate.name}: no usable photo, not imported"
            )
            continue

        existing = conn.execute(
            "SELECT id FROM students WHERE roll_no = ? AND class_id IS ?",
            (candidate.roll_no, class_id),
        ).fetchone()

        if existing and not replace:
            for path in stored:
                path.unlink(missing_ok=True)
            result.messages.append(f"{candidate.roll_no}: already enrolled, left alone")
            continue

        if existing:
            student_id = existing["id"]
            superseded = db.student_photo_names(conn, student_id)
            db.update_student(
                conn, student_id, name=candidate.name, class_id=class_id,
                photo_path=stored[0].name, encoding=encodings[0],
            )
            db.clear_student_encodings(conn, student_id)
            result.updated += 1
        else:
            superseded = set()
            student_id = db.create_student(
                conn, candidate.roll_no, candidate.name, class_id,
                stored[0].name, encodings[0],
            )
            result.added += 1

        for encoding, path in zip(encodings[1:], stored[1:]):
            db.add_student_encoding(conn, student_id, encoding, path.name)
        result.photos_used += len(encodings)

        for name in superseded - {p.name for p in stored}:
            (faces_dir / name).unlink(missing_ok=True)

        # Land this student before starting the next one. See the note above.
        conn.commit()

    return result


def describe(plan: Plan) -> str:
    """A short human summary of a plan, for the CLI and the dry run."""
    lines = [
        f"Folder : {plan.root}",
        f"Layout : {plan.layout} ({'; '.join(plan.notes)})",
        f"Found  : {len(plan.usable)} students ready, "
        f"{len(plan.rejected)} with problems, {plan.photo_count} photos",
    ]
    for candidate in plan.usable[:10]:
        lines.append(f"   ok   {candidate.roll_no:<12} {candidate.name:<28} "
                     f"{len(candidate.photos)} photo(s)")
    if len(plan.usable) > 10:
        lines.append(f"   ...  and {len(plan.usable) - 10} more")
    for candidate in plan.rejected:
        label = f"{candidate.roll_no or '?'} {candidate.name}".strip()
        lines.append(f"   skip {label}: {'; '.join(candidate.problems)}")
    for name, why in plan.ignored[:10]:
        lines.append(f"   --   ignored {name}: {why}")
    return "\n".join(lines)
