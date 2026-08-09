# Videoflix Backend

REST API for a video streaming platform. Users register, confirm their address by
email and watch videos that are delivered as HLS streams in three resolutions.

Uploaded videos are converted in the background by FFMPEG. Authentication uses JSON
Web Tokens transported exclusively in HttpOnly cookies, so the browser attaches them
automatically and no script can read them.

## Stack

| Component | Version |
|---|---|
| Python | 3.12 |
| Django | 5.2 LTS |
| Django REST Framework | 3.17 |
| PostgreSQL | 18 |
| Redis | 8 |
| FFMPEG | 8.1 |

Background jobs run on Django-RQ with Redis as the broker.

---

## Requirements

- **Docker Desktop**, recent enough to ship Compose as a built-in plugin. Every
  command below uses `docker compose`, not the standalone `docker-compose`.
- A free **[Mailtrap](https://mailtrap.io)** account for the activation and password
  reset emails. The sandbox plan is sufficient.

Python, PostgreSQL, Redis and FFMPEG do **not** have to be installed for the
backend — they live inside the containers. Serving the frontend needs any static
web server; the examples below use Python's built-in one because it is the
shortest route.

---

## Setup

### 1. Clone the repository

```bash
git clone <repository-url>
```

Then change into the directory that was created.

### 2. Create the environment file

The repository contains `.env.template` listing every variable the project reads.
Copy it to `.env`, which is never committed:

```bash
cp .env.template .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.template .env
```

### 3. Generate a secret key

`.env.template` ships with a placeholder. Replace it with a value of your own:

```bash
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Copy the output into `SECRET_KEY` in your `.env`.

### 4. Fill in the remaining values

Open `.env` and set these. Everything else can stay as it is.

| Variable | What to enter |
|---|---|
| `SECRET_KEY` | the value generated in step 3 |
| `DB_NAME` | any database name, for example `videoflix_db` |
| `DB_USER` | any user name, for example `videoflix_user` |
| `DB_PASSWORD` | any password you choose |
| `EMAIL_HOST` | `sandbox.smtp.mailtrap.io` |
| `EMAIL_PORT` | `2525` |
| `EMAIL_HOST_USER` | the user name from your Mailtrap inbox |
| `EMAIL_HOST_PASSWORD` | the password from your Mailtrap inbox |
| `DEFAULT_FROM_EMAIL` | any sender address, for example `noreply@videoflix.local` |

The three database values are read by PostgreSQL itself when its container is
created, so they have to be set **before** the first start.

Mailtrap shows host, port, user name and password in the SMTP settings of your
inbox. Nothing is delivered to real recipients; every message lands in that inbox,
which is exactly what makes it safe to test with.

`DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD` and
`DJANGO_SUPERUSER_EMAIL` can be left at their defaults or changed. The account is
created automatically on the first start.

### 5. Start the containers

```bash
docker compose up --build
```

The first run takes a few minutes: the image is built and FFMPEG is installed. The
startup script then waits for PostgreSQL, collects static files, applies all
migrations, creates the superuser, starts the background worker and finally the web
server.

Startup is complete once both of these have appeared in the log — the first comes
from the job worker, the second from the web server:

```
*** Listening on default...
[INFO] Booting worker with pid: ...
```

Leave the terminal open, or start detached with `docker compose up -d --build`.

### 6. Verify the installation

Open <http://127.0.0.1:8000/api/video/> in a browser. The expected answer is status
**401** with:

```json
{"detail": "Authentication credentials were not provided."}
```

That is correct and is the proof you want: the endpoint requires a login, so Django,
the database and the routing all work. An error page or a refused connection means
something went wrong — see [Troubleshooting](#troubleshooting).

---

## Admin panel

<http://127.0.0.1:8000/admin/>

Log in with the value of `DJANGO_SUPERUSER_USERNAME` (default: `admin`) and
`DJANGO_SUPERUSER_PASSWORD`.

> **Log in with the user name, not the email address.** Accounts created through
> registration store their address in both fields, but the superuser does not — its
> user name is `admin` while its address is something else entirely.

The queue dashboard at <http://127.0.0.1:8000/django-rq/> shows running, finished
and failed conversion jobs.

---

## Adding videos

There is no upload endpoint. Videos enter the platform through the admin panel:

1. Open **Video_app → Videos → Add video**
2. Fill in title, description and category, and choose a video file
   (`.mp4`, `.mov` or `.mkv`)
3. Save

Saving starts four background jobs: one conversion per resolution (480p, 720p,
1080p) plus one that extracts a thumbnail. Progress is visible on the video's change
page, where each resolution appears with its own status. A short clip is converted
within a minute; longer material takes proportionally more time.

The video is playable once **Hls status** reads `ready`, which requires all three
resolutions to have finished.

Two things worth knowing:

- **Do not use `newest` as a category name.** The frontend reserves it for the
  section listing films added within the last five days.
- **A thumbnail you upload yourself is never overwritten.** The generated one is
  used only when the field is left empty.

---

## Using the frontend

The frontend is a separate repository and is served as static files:

```bash
git clone https://github.com/editoraky/videoflix-frontend
cd videoflix-frontend
python -m http.server 5500
```

Any other static web server works as well, as long as it serves on port 5500.

Then open **<http://127.0.0.1:5500>**.

> **Use `127.0.0.1`, never `localhost`.** The frontend calls the backend at a fixed
> address of `http://127.0.0.1:8000`. Opening the page under `localhost` makes every
> request cross-site, because a browser treats the two names as different sites, and
> the authentication cookies are then no longer sent along. The symptom is
> characteristic: login succeeds, and every request afterwards fails with 401.

The registration and password reset emails link back to the frontend, using the
address in `FRONTEND_BASE_URL`. It has to match the address you open the page under,
for the same reason.

---

## Trying the API without the frontend

The full cycle with `curl`. On Windows use Git Bash, since `curl` in Windows
PowerShell is an alias for a different command.

**Register.** The account is created locked and an email is sent:

```bash
curl -X POST http://127.0.0.1:8000/api/register/ \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"YourPassword123!","confirmed_password":"YourPassword123!"}'
```

**Activate.** Open the email in Mailtrap. Its link points at the frontend and carries
two query parameters, `uid` and `token`. Take both values and call:

```bash
curl http://127.0.0.1:8000/api/activate/<uid>/<token>/
```

**Log in.** `-c cookies.txt` stores the two cookies the response sets:

```bash
curl -X POST http://127.0.0.1:8000/api/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"YourPassword123!"}' \
  -c cookies.txt
```

**Read the catalogue.** `-b cookies.txt` sends the cookies back:

```bash
curl -b cookies.txt http://127.0.0.1:8000/api/video/
```

---

## API

All endpoints are prefixed with `/api/`. Authentication is carried by the
`access_token` cookie, which the browser sends automatically; there is no
`Authorization` header.

### Authentication

| Method | Path | Purpose |
|---|---|---|
| POST | `register/` | Create an account. It stays locked until activation. |
| GET | `activate/<uidb64>/<token>/` | Unlock the account from the emailed link. |
| POST | `login/` | Sign in; sets both auth cookies. |
| POST | `logout/` | Sign out; blacklists the refresh token and clears the cookies. |
| POST | `token/refresh/` | Issue a new pair of tokens from the refresh cookie. |
| POST | `password_reset/` | Request a reset email. |
| POST | `password_confirm/<uidb64>/<token>/` | Set a new password from the emailed link. |

`password_reset/` always answers **200**, whether or not the address exists. Any
other behaviour would turn the form into a lookup service for registered accounts.

### Videos

| Method | Path | Purpose |
|---|---|---|
| GET | `video/` | List every video as a flat array. |
| GET | `video/<id>/<resolution>/index.m3u8` | HLS playlist of one resolution. |
| GET | `video/<id>/<resolution>/<segment>` | A single transport stream segment. |

`<resolution>` is one of `480p`, `720p`, `1080p`. All three require a valid
`access_token` cookie and answer **401** without one.

A list entry looks like this:

```json
{
  "id": 1,
  "created_at": "2026-08-08T00:23:38.645103Z",
  "title": "Coral Reef",
  "description": "A short dive.",
  "thumbnail_url": "http://127.0.0.1:8000/media/thumbnails/reef.jpg",
  "category": "Nature"
}
```

---

## Tests

The database has no published port and is unreachable from the host, so the tests
run inside the container:

```bash
docker compose exec web python manage.py test
```

A single module:

```bash
docker compose exec web python manage.py test video_app.tests.test_video_list
```

268 tests cover registration, activation, login, logout, token refresh, password
reset, delivery failures of the mail server, the video models, the admin, the list
endpoint, HLS delivery including path traversal attempts, the conversion services
and the background jobs. Some of them invoke FFMPEG on generated test clips, which
is why a full run takes about half a minute.

---

## Project structure

```
videoflix-backend/
├── core/                     project configuration, root URLs
├── auth_app/                 user model and every authentication endpoint
│   ├── api/                  serializers, views, URLs, cookie authentication
│   └── tests/
├── video_app/                videos, streaming and the conversion pipeline
│   ├── api/                  serializers, views, URLs, path handling
│   ├── services.py           FFMPEG calls
│   ├── tasks.py              background jobs
│   ├── signals.py            enqueues jobs, cleans up deleted videos
│   └── tests/
├── templates/emails/         activation and password reset emails
├── backend.Dockerfile
├── backend.entrypoint.sh
└── docker-compose.yml
```

Uploads and conversion results live in a Docker volume mounted at `/app/media`:

```
media/
├── uploads/videos/           the original uploads, never served publicly
├── thumbnails/               the only publicly reachable media directory
└── videos/<id>/<resolution>/ playlist and segments, served behind authentication
```

---

## Everyday commands

| Task | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop | `docker compose down` |
| Follow the log | `docker compose logs -f web` |
| Django shell | `docker compose exec web python manage.py shell` |
| Apply migrations by hand | `docker compose exec web python manage.py migrate` |
| Recreate after changing `.env` | `docker compose up -d --force-recreate web` |

> `docker compose down -v` additionally deletes the volumes, and with them the
> database, all uploads and every converted video.

---

## Troubleshooting

**`could not translate host name "db"`**
The command ran on the host. PostgreSQL and Redis have no published ports and are
reachable only from inside the container network. Prefix every Django command with
`docker compose exec web`.

**Changing `.env` has no effect**
`env_file` is evaluated when a container is *created*, not when it restarts.
Recreate it: `docker compose up -d --force-recreate web`.

**Port 8000 is already in use**
Another program holds the port. Stop it, or map a different one by changing the
`ports` entry of the `web` service in `docker-compose.yml` to `"8001:8000"`. The
frontend expects port 8000 and would then need adjusting too.

**Login succeeds, every request afterwards returns 401**
The frontend was opened under `localhost` instead of `127.0.0.1`. See
[Using the frontend](#using-the-frontend).

**`exec ./backend.entrypoint.sh: no such file or directory`**
The file was checked out with Windows line endings, so the interpreter named on its
first line cannot be resolved. `.gitattributes` prevents this; should it happen
anyway, convert the file to LF line endings and rebuild the image.

**A video stays on `pending` or `processing`**
Check the worker with `docker compose logs web`, and <http://127.0.0.1:8000/django-rq/>
for failed jobs. A file FFMPEG cannot read ends up as `failed`, with the reason in
the video's **Hls error** field.

**No emails arrive**
Verify `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` against the SMTP credentials of
your Mailtrap inbox. Messages are only ever delivered to that inbox, never to the
recipient's real address.

**The database appears empty after renaming or moving the project folder**
Compose derives volume names from the project name. `COMPOSE_PROJECT_NAME=videoflix`
in `.env` pins it, so this cannot happen; if the entry is missing, the old volumes
are still there under their previous name.
