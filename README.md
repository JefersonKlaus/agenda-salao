# Agenda do Salão

Online appointment book for beauty salons, **serverless on AWS**: each salon signs in, registers
its services and professionals (with the days and hours each one works), sets its business hours
and books clients on a Google Calendar–style agenda, with no chance of a double-booked slot.

The app's interface is in Brazilian Portuguese (labels, messages, dates and R$ amounts); the code,
comments and documentation are in English.

```
Browser ──► CloudFront ──► S3 (static site: HTML/CSS/JS, no build step)
    │
    └─► API Gateway (HTTP API, validates the Cognito JWT) ──► Lambda (Python) ──► DynamoDB
```

| Part | Where | Size |
|---|---|---|
| Backend (rules + API) | `backend/src/agenda/` | ~1020 lines |
| Frontend | `frontend/` | ~1360 lines |
| Backend tests | `backend/tests/` | 250 tests |
| Calendar unit tests | `frontend/tests/` | `node --test`, no dependencies |
| Browser test | `e2e/` | a real Chromium |
| Infrastructure | `infra/` (Terraform) | not counted |
| CI/CD | `.github/workflows/` | not counted |

## What the salon sees

The menu is a sidebar: always visible on wide screens, and a drawer behind the ☰ button on phones.
Every login is the salon's manager account (there are no separate logins for the professionals).

- **Agenda** in three views, like Google Calendar: **day** (one column per professional who works
  that day or has appointments in it, each with her own schedule, so two of them can be booked at the
  same time side by side), **week** (a time grid; appointments that overlap sit side by side) and
  **month** (a grid with the first items of each day and "+N mais"). Each professional has her own
  color; the buttons above the calendar ("Todas", "● Ana", ...) show everybody or a single
  professional and double as the color legend. Hatched areas are times when nobody (or the selected
  professional) can be booked; a red line with the time (Brasília time, whatever the device's time
  zone) marks now, and keeps moving while the agenda is open. Click an empty spot to book at that
  time (in the day view, with that column's professional); click an appointment to see it, cancel it
  or **give it to another professional** (who does that service and is free then).
- **Absences** ("Ausência" button): a professional is away (sick, travelling...) for whole days or
  just some hours, for one or more days, with an optional reason. She gets no new appointments then.
  Absences show as striped "Ausente" blocks (whole days in the "Dia todo" strip; in the day view a
  professional away all day gets no column and is listed under "Ausentes"). Her appointments already
  booked inside an absence are flagged with ⚠ so they can be moved or cancelled. Click an absence to
  remove it.
- **Serviços** (name, duration, price). A service can be **disabled**: it stays listed (and its
  appointments stay on the agenda) but is not offered for new appointments until it is enabled again.
- **Profissionais**: the services each one performs and the **days and hours she works** (one shift
  per weekday), always inside the salon's business hours. Professionals without hours of their own
  (including those saved before this existed) work the whole business hours.
- **Configurações**: the salon's business hours (open days, opening and closing time). They are the
  window every professional works inside: her hours must fit in it, and if it is narrowed later, the
  part of her hours outside it is simply not offered (the professionals list shows a ⚠).

## How it works (what matters)

- **One salon = one Cognito user.** The salon id (the token's `sub`) comes from the token already
  validated by API Gateway, **never from the request body**. Every DynamoDB item carries
  `PK = SALAO#<id>`.
- **No double booking, even with simultaneous clicks.** Each appointment writes, in a single
  transaction, the booking and one "lock" per 15-minute block. If any lock already exists, nothing
  is written and the answer is "slot taken". Appointments that merely touch (10:00–11:00 and
  11:00–12:00) do not conflict.
- Times are Brasília time (UTC-3), in 15-minute steps, whatever the server's time zone (AWS and most
  containers run in UTC; `backend/src/agenda/clock.py` is the one clock the Lambda and the local server use). Open days and opening/closing times are
  configurable. Nothing can be booked in the past, outside the salon's business hours, outside the
  professional's own hours, while she is away, or for a disabled service.
- The API: `/services` (with `active`), `/professionals` (with `work_hours`: a list of
  `{day, start, end}`, day 0 = Monday, or `null` = the whole business hours), `/settings`,
  `/availability?date=&service_id=&professional_id=`, `/appointments` (`?date=` for one day, or
  `?from=&to=` for up to 62 days, used by the week and month views), `PUT
  /appointments/{id}/professional` (changes the professional: one transaction that moves the locks too)
  and `/time-off` (absences: `GET ?from=&to=`, `POST`, `DELETE /time-off/{id}`).
- The appointment stores a **copy** of the service's name, price and duration: changing the price
  later does not alter the history.
- The data already stored in DynamoDB uses Portuguese key prefixes and field names (`SALAO#`,
  `nome`, `preco_centavos`...). They are kept as they are so existing data stays readable; only
  `backend/src/agenda/dynamo_repository.py` knows about them (`STORED_FIELD_NAMES`), and
  `backend/tests/test_repositories.py` pins the format down.

## Development environment

**Easiest: the dev container.** In VS Code with Docker ("Dev Containers" extension) open the folder and
choose *Reopen in Container*, or open the repository in **GitHub Codespaces**. `.devcontainer/` brings
Python 3.12, Node 22 and Terraform, and runs `python dev.py setup` by itself. Then `python dev.py serve`.

**On your own machine** you need Python 3.12+ and Node 22 (Node only for the frontend checks). Then:

```bash
python dev.py setup      # creates .venv/ with the pinned tools (requirements-dev.txt) + Chromium
python dev.py serve      # the site + in-memory API at http://127.0.0.1:8765, no login
python dev.py test       # backend tests, calendar unit tests, JS syntax (quick)
python dev.py e2e        # the browser test, in a real Chromium
python dev.py all        # test + e2e: what CI runs, except Terraform
```

`dev.py` works the same on Windows, macOS and Linux and installs nothing outside `.venv/`. No
environment variables are needed to develop: the local server needs no AWS, and the deployed
configuration (`frontend/js/config.js`) is written by the deploy. `.editorconfig` keeps editors on the
repository's conventions (UTF-8, CRLF line endings, 4 spaces in Python, 2 elsewhere).

The browser test covers login with a password change, the catalog screens, a disabled service, the
salon's window, working hours, the day/week/month views, booking, conflicts, absences, changing the
professional, cancellation, the mobile sidebar, the "now" marker (with a fake clock), the layout (empty
screens with a picture, page widths between 320 and 760 px, full-width agenda), protection
against injected HTML, and the same security policy (CSP) as CloudFront.

`local_server.py` is for trying the frontend: no AWS, no Cognito and **no login**. Every request is
treated as the same salon, and the data lives in memory until the server stops (`--port` changes the
port). It only listens on `127.0.0.1` and must never be exposed. This only affects the local server:
it generates its own `js/config.js` with `skipLogin: true`, while the deployed site's `config.js`
(written by the deploy) never has that flag, and API Gateway still requires a valid token for every
request. The browser test runs the local server with login turned on to cover the login screen.

## Environments and deployment (all through GitHub, no terminal)

There are two environments, **each in a different AWS account**:

| Environment | When it deploys | GitHub Environment | AWS resources |
|---|---|---|---|
| `dev` | **automatically**, on every push to the `dev` branch | `dev` | `agenda-salao-dev-*` |
| `prod` | **only when someone presses the button** (Actions → *Deploy production* → *Run workflow*, on `main`) | `producao` | `agenda-salao-prod-*` |

Flow: work on `dev` (automatic deploy) → open a PR `dev` → `main` (runs CI) → merge →
deploy to production with the button. The production workflow refuses to run outside `main` and
asks you to type `producao` to confirm. Merging into `main` does **not** deploy anything.

### Step 1: an IAM user for GitHub, in each AWS account (AWS console, in the browser)

1. IAM → *Policies* → *Create policy* → **JSON** tab → paste the contents of
   [`docs/iam-deploy-policy.json`](docs/iam-deploy-policy.json) → name it `agenda-salao-deploy`.
   It only allows touching resources whose name starts with `agenda-salao-`.
2. IAM → *Users* → *Create user* → name `github-deploy-agenda-salao`, **without** console access →
   attach the `agenda-salao-deploy` policy.
3. Open the user → *Security credentials* → *Create access key* → use case *Application running
   outside AWS* → copy the **Access key ID** and the **Secret access key** (the secret is only
   shown now).
4. Repeat in both accounts (dev and production). Also write down the **account number** (12 digits,
   in the menu in the top right corner).

### Step 2: Environments on GitHub (Settings → Environments)

Create `dev` and `producao`. In **each one**, add (with that account's values):

| Type | Name | Example | What it is for |
|---|---|---|---|
| **Secret** | `AWS_ACCESS_KEY_ID` | `AKIA...` | key of that account's IAM user |
| **Secret** | `AWS_SECRET_ACCESS_KEY` | `wJalr...` | secret of the IAM user |
| Variable | `AWS_ACCOUNT_ID` | `123456789012` | safety check: if the key belongs to another account, the deploy **stops before publishing** |
| Variable | `AWS_REGION` | `sa-east-1` | region |

That's all. The Terraform state bucket (`agenda-salao-estado-<account>`) is created by the deploy
itself the first time. Recommended for `producao`: *Required reviewers* (you) and *Deployment
branches* = only `main`.

### Step 3: deploy

- **dev:** create the `dev` branch (on GitHub: branches button → type `dev` → *Create branch*).
  Creating it already triggers the first deploy. Follow it under *Actions*; the site's address
  appears in the run summary.
- **production:** *Actions* → *Deploy production* → *Run workflow* (branch `main`) → type `producao`.

### Step 4: create a salon's login (there is no open sign-up, on purpose)

*Actions* → *Create salon user* → *Run workflow* → choose the environment and type the e-mail.
Cognito sends a temporary password by e-mail; on first access the site asks for a new password.
`dev` and `prod` users are separate.

> If a step fails for lack of permission in the IAM policy, the Actions error says which action was
> denied: just add it to `docs/iam-deploy-policy.json` and update the policy in AWS.

## Security and cost

- Encrypted table, with continuous backup (PITR) and deletion protection in `prod`.
- The Lambda can only read/write/delete items in its own table. API Gateway rate-limits requests
  (`rate_limit_per_second`) to contain abuse and cost.
- The site only talks to itself, Cognito and the API (CSP), and cannot be put in an iframe.
- The deploy uses access keys of an IAM user **with only this project's permissions** (policy in
  `docs/`), stored as Environment *secrets* (GitHub hides them in the logs). Keys last until they
  are rotated: **rotate them from time to time** (IAM → user → create a new key → update the
  secret → delete the old one), never put them in a repository file, and protect the `main`
  branch. The safest way, which needs no keys at all, is OIDC (temporary login); you can migrate
  to it later.
- Cost: with no traffic, close to zero (everything is pay-per-use). What may be charged even when
  idle is small: logs and S3 storage.
