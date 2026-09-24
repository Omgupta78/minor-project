# Deploying FaceID Attendance for real teachers

This file covers putting the app somewhere teachers can actually use it, and
the things that are easy to get wrong and only discovered weeks later, when
the attendance history has already been lost.

Read the section that matches how you want to run it.

---

## Which model should you choose?

There are two honest options, and they are not equally good.

### 1. One instance per school (recommended)

Each school, college or department runs its own copy. Teachers at that school
register accounts on it; each teacher sees only their own classes.

* The school keeps physical control of its students' photographs.
* No cross-border transfer of biometric data.
* A breach is limited to one school.
* The admin sets `ALLOW_SIGNUP=0` after their staff have registered, so the
  address stops accepting strangers.

### 2. One global server for every teacher in the world

Technically the app supports it: accounts are isolated, so teacher A cannot
see teacher B's classes, students, sessions, photographs or Excel exports.

Legally, this is a different project. Whoever operates that server becomes the
controller of biometric data belonging to children in many countries at once:

* **EU/UK (GDPR Art. 9):** face templates are special-category data. You need
  an explicit lawful basis, a DPIA, a retention policy, and a named
  representative.
* **Illinois (BIPA):** written consent before collection, a published
  retention schedule, and statutory damages per person if you get it wrong.
* **India (DPDP Act 2023):** verifiable parental consent for anyone under 18,
  and no tracking or behavioural monitoring of children.
* Several other states and countries have equivalent rules.

None of that is code. It is consent forms, a privacy notice, a retention
policy, and someone legally accountable. Do not put a public signup page for
student face data on the internet for a college project.

**Recommendation:** ship option 1. It is what a school can actually adopt.

---

## Before you deploy anything

1. **Set `SECRET_KEY`.** Without it the app generates a random key at startup
   and prints a warning, which means every restart logs all teachers out.

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. **Point the data at persistent storage.** `ATTENDANCE_DB` and `FACES_DIR`
   must live on a disk that survives a redeploy. On most platforms the app
   directory does not.

3. **Keep HTTPS on.** `COOKIE_SECURE=1` means the login cookie is only sent
   over HTTPS. On plain http the login will appear to "not work" because the
   browser silently drops the cookie: that is the setting, not a bug. Use
   `COOKIE_SECURE=0` only for local testing.

4. **Close signup when you are done.** `ALLOW_SIGNUP=0`. The first account is
   always allowed even when signup is closed, so a fresh server is never
   locked out.

5. **Take a backup.** `attendance.db` plus `faces/` is the entire system.
   `sqlite3 attendance.db ".backup backup.db"` is safe to run while the app
   is serving.

---

## Option A: Docker (works anywhere)

```bash
docker build -t faceid-attendance .          # ~2 min: dlib-bin is a pre-built wheel
docker volume create faceid-data

docker run -d --name faceid \
  -p 8000:8000 \
  -v faceid-data:/data \
  -e SECRET_KEY="paste-the-generated-key" \
  -e ALLOW_SIGNUP=1 \
  -e COOKIE_SECURE=0 \
  faceid-attendance
```

Open <http://localhost:8000>, create the first account, then
`docker exec` or your platform's dashboard to flip `ALLOW_SIGNUP=0`.

Set `COOKIE_SECURE=1` as soon as there is a real domain with TLS in front.

The long build is dlib compiling from source. It is cached after the first
build unless `requirements.txt` changes.

---

## Option B: Render.com blueprint

`render.yaml` in this repo describes the whole service, including the 5 GB
persistent disk mounted at `/data`.

1. Push this repository to GitHub.
2. Render dashboard: **New -> Blueprint**, select the repository.
3. Accept the plan (the free tier cannot attach a disk, so data would be
   erased on each deploy; `starter` is the cheapest plan that can).
4. Render generates `SECRET_KEY` itself and keeps it across deploys.
5. Register the first account, then set `ALLOW_SIGNUP=0` in the dashboard.

Railway and Fly.io work the same way: Docker image, a volume, and the
environment variables from `.env.example`.

---

## Option C: A college server or any VPS

```bash
sudo apt install -y python3-venv build-essential cmake libopenblas-dev
git clone <your-repo-url> /srv/faceid && cd /srv/faceid
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt              # dlib-bin is a pre-built wheel; fast

export SECRET_KEY="paste-the-generated-key"
export ATTENDANCE_DB=/srv/faceid-data/attendance.db
export FACES_DIR=/srv/faceid-data/faces
gunicorn --config gunicorn.conf.py app:app
```

A systemd unit so it starts on boot and restarts after a crash:

```ini
# /etc/systemd/system/faceid.service
[Unit]
Description=FaceID Attendance
After=network.target

[Service]
User=faceid
WorkingDirectory=/srv/faceid
EnvironmentFile=/srv/faceid/.env
ExecStart=/srv/faceid/.venv/bin/gunicorn --config gunicorn.conf.py app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now faceid
```

Put nginx or Caddy in front for TLS. Caddy is two lines and gets a
certificate automatically:

```
attendance.yourschool.edu {
    reverse_proxy 127.0.0.1:8000
}
```

Raise the upload limit in whichever proxy you choose, or multi-photo scans
will fail with a 413 before they reach the app:

```nginx
client_max_body_size 64M;
proxy_read_timeout 300s;
```

---

## Option D: No server at all (the simplest thing that works)

For one teacher or one department, skip hosting. Run it on the teacher's own
laptop with `run.bat` (Windows) or `run.sh` (macOS/Linux). Everything stays
on that machine, there is nothing to secure, nothing to pay for, and no
privacy paperwork beyond the school's own consent form.

This is genuinely the right answer for most schools.

---

## Showing it to someone: a temporary public link

For a demo, a review or a submission you often want a URL a marker can open,
without setting up hosting. Two ways, in order of how long the link needs to
last.

### A Cloudflare quick tunnel (minutes, dies when you close it)

Run the app as usual, then point a tunnel at it from **the same machine**:

```bash
# 1. start the app (leave this terminal running)
./run.sh

# 2. in a second terminal, install cloudflared and open a tunnel
#    macOS:    brew install cloudflared
#    Windows:  winget install --id Cloudflare.cloudflared
#    Linux:    see https://github.com/cloudflare/cloudflared/releases
cloudflared tunnel --url http://127.0.0.1:5000
```

It prints a `https://<random-words>.trycloudflare.com` URL. That is your link.
It works until you press Ctrl+C, and the address is different every time.

The tunnel needs **outbound TCP and UDP on port 7844** to Cloudflare's edge.
College and office networks often block it; if the tunnel reports "HTTP/2
connection is blocked or unreachable", that is what happened, and no flag will
work around it. Use a phone hotspot, or deploy to Render below.

### Harden it first

A quick tunnel is the public internet, not a private demo. Before you share
the URL, restart the app with:

```bash
export SECRET_KEY="$(cat instance/secret_key)"
export PRODUCTION=1 ALLOW_SIGNUP=0 COOKIE_SECURE=1 HOST=127.0.0.1 PORT=8000
gunicorn --config gunicorn.conf.py wsgi:app
```

and point the tunnel at port 8000 instead. That gives you the production
server rather than Flask's development one, a session cookie that only travels
over HTTPS, and **registration closed**, so a stranger who finds the URL
cannot create an account. Create your own account first, while
`ALLOW_SIGNUP=1`, then close it.

**Do not put real students' photographs behind a quick tunnel.** Enrolment
photos are biometric data. For a demo, enrol yourself and a few friends who
have agreed to it, and delete them afterwards. A link anyone can open is not
where a class's faces belong, however short-lived it is.

### Render (a link that survives, free)

`render.yaml` in this repository is a Render blueprint. New → Blueprint, point
it at your fork, and Render builds the Dockerfile and gives you a permanent
`https://<name>.onrender.com` address with HTTPS. Set `ALLOW_SIGNUP=0` in the
dashboard once you have created your account.

The free plan sleeps after inactivity, so the first request after a pause
takes about a minute, and its disk is ephemeral -- **students and attendance
are wiped on every redeploy**. That is fine for showing the app works and
wrong for a real class; see the persistent-disk note under Option B.

## Upgrading an existing installation

The accounts release changes the schema: classes gain an owner, and roll
numbers become unique per class instead of globally. `db.init_db()` performs
the migration automatically at startup and prints each step:

```
  migrated: classes: added teacher_id, scoped UNIQUE per teacher
  migrated: students: roll_no now unique per class, not globally
```

Classes that existed before the upgrade have no owner. The **first account
created after upgrading adopts them**, so sign up as the teacher who owns
that data first. Back up `attendance.db` before the first start, as always.

---

## A teacher forgot their password

There is no email server, so there is no reset link. Recovery is done on the
machine holding the database:

```bash
python reset_password.py --list                    # which accounts exist
python reset_password.py --email you@college.edu   # prompts for a new one
```

Old passwords cannot be recovered -- they are stored as PBKDF2 hashes, which
is the point. The tool sets a new one. It grants no access that whoever runs
it does not already have, since the database file is sitting right there.

If the account was deactivated, add `--activate`.

## Operating checklist

| Task | Command or setting |
| --- | --- |
| Health check | `GET /healthz` returns `{"ok": true}` |
| Backup | `sqlite3 attendance.db ".backup /backups/$(date +%F).db"` plus `faces/` |
| Close registration | `ALLOW_SIGNUP=0` |
| Verify the build | `python doctor.py` |
| Run the test suite | `python selftest.py && python authtest.py && python smalltest.py` |
| Measure accuracy | `python accuracy.py` on your own class photos |
| Rotate a password | Any teacher can `POST /account/password` from the app |

---

## What this app still does not do

Worth saying out loud before anyone relies on it:

* **No liveness detection.** A printed photograph or a phone screen held up to
  the camera will be accepted. Attendance should be taken by the teacher
  photographing the room, not by students photographing themselves.
* **No audit log.** Manual overrides are saved, but not who made them or when.
* **Recognition is not perfect.** Expect to correct a few students per class,
  especially back rows and poor light. The review screen exists for that
  reason; confirm it before saving.
* **One password per teacher, no reset by email.** No mail is sent anywhere.
  An admin restores access directly in the database.
* **SQLite.** Fine for a school. Not for thousands of concurrent teachers.
