# Agenda do Salão

Appointment book for beauty salons, serverless on AWS. The salon registers services and
professionals, sets its hours and books clients on a calendar, with no double bookings.

The app's screens are in Brazilian Portuguese; code and docs are in English.

## Run it locally

Needs Python 3.12+ (and Node 22 for the frontend checks). Or open the folder in the dev container
/ Codespaces, which installs everything.

```bash
python dev.py setup             # once: creates .venv/ and downloads Chromium
python dev.py serve             # http://127.0.0.1:8765  as the manager
python dev.py serve employee --professional Ana   # as Ana's employee login: agenda, services, her absences
python dev.py serve --connection off   # start with no internet: the site loads, every API call fails
```

While it runs, type `off` or `on` + Enter in its terminal to drop or restore the connection:
browse online, type `off`, and the agenda keeps showing what was downloaded.

No AWS, no login, no configuration. It opens with demo data, so it looks like a salon in use:
18 services, 22 professionals and 12 logins (enough for a few pages, and names with accents to
try the search), each with her own hours and commission, a busy agenda from last week to two weeks ahead
and a few absences ([local/seed.py](local/seed.py), always dated around today). Add `--empty` to
start like a brand-new salon. Data lives in memory and is gone when you stop the server.

## Run the tests

```bash
python dev.py test    # backend tests + calendar unit tests + JS syntax (seconds)
python dev.py e2e     # browser test in a real Chromium
python dev.py all     # both: what CI runs
```

| Tests | Where |
|---|---|
| Backend (rules, API, DynamoDB format) | `local/tests/` (pytest) |
| Calendar math | `frontend/tests/` (`node --test`) |
| Whole app in a browser | `local/e2e.py` (Playwright) |

## Architecture

```
Browser ──► CloudFront ──► S3                 the site (HTML/CSS/JS, no build)
   │
   └──► API Gateway ──► one Lambda per action ──► DynamoDB
        (checks the Cognito login)
```

```
frontend/   the site                         deployed to S3
backend/    the Lambdas                      deployed to AWS Lambda
infra/      Terraform for everything in AWS
local/      local server, in-memory database, tests   never deployed
dev.py      the commands above
```

### Frontend

Plain JavaScript modules, no framework, no build step.

```
frontend/
  index.html, style.css
  js/app.js          menu and login screen
  js/api.js          every call to the backend
  js/auth.js         Cognito login (tokens), role: manager or employee
  js/config.js       where the API is (written by the deploy; empty in the repo)
  js/calendar.js     date/time math for the calendar views
  js/screens/        one file per screen: agenda, catalog (services, professionals), settings
```

The frontend doesn't know whether the backend is AWS or local: it calls `CONFIG.apiUrl`.
The deploy writes a `config.js` with the real API; the local server returns its own `config.js`
pointing at itself, with `skipLogin: true`.

### Backend

One Lambda per business action, hexagonal: each Lambda has its use case and its HTTP adapter;
everything else lives in a shared core, copied into every Lambda's zip.

```
backend/
  core/agenda_core/
    domain/          entities and rules, pure Python
    ports.py         what use cases need: Repository, Clock
    application.py   rules shared by several use cases
    adapters/        DynamoDB, clock, API Gateway input (login, role, errors)
  lambdas/<action>/  book_appointment, list_services, get_finance, ... (20)
    use_case.py      the action (only domain + ports, never AWS)
    handler.py       API Gateway event -> use case -> HTTP response
    lambda.json      {"route": "POST /appointments", "database": "write"}
```

To add an action, create a folder with these three files. Terraform reads every `lambda.json` and
creates the function, the route and the logs. Lambdas marked `"read"` can only read the table.

Rules worth knowing:

- The salon id comes from the login token, never from the request.
- No double booking: an appointment and its 15-minute "locks" are written in one transaction.
- All times are Brasília time (UTC-3), whatever the server's time zone.
- Commission: per professional and per service, % of the price or a fixed amount. Like the price, it
  is copied into each appointment when booked: changing it later does not change the past.
- Logins: the salon's own account (created by the *Create salon user* workflow) is the manager. The
  manager creates the others in **Acessos** (or "Criar acesso" in Profissionais): Cognito writes the
  salon (`custom:salon`) and, for a service provider, her professional (`custom:professional_id`) in
  the login, immutable; the group (`manager` / `employee`) says what it may do.
- An employee sees only the Agenda and Serviços, books nothing, and registers or removes only her
  own absences. Everything else answers 403. The manager may also book in the past.
- Data in DynamoDB keeps Portuguese field names (`nome`, `SALAO#`...) for compatibility; only
  `adapters/dynamo_repository.py` knows them.

### Local

`local/server.py` serves `frontend/` and plays API Gateway: `local/api_gateway.py` reads the same
`lambda.json` files and calls the same Lambdas, with `local/memory_repository.py` instead of
DynamoDB. It only listens on 127.0.0.1.

## Deploy

Everything goes through GitHub Actions, with no terminal: a push runs every test (Python, JS and the
browser test), then Terraform creates or updates all of AWS (Lambdas, API, Cognito, table, site),
then the site is published. Two environments, each in its own AWS account:

| Environment | Deploys when |
|---|---|
| `dev` | every push to the `dev` branch |
| `prod` | every push to `main` (a merged PR); also by hand: Actions → *Deploy production* → *Run workflow*, typing `producao` |

```
push ──► tests (CI) ──► terraform plan ──► check the plan ──► terraform apply ──► publish the site
```

The deploy **refuses a plan that would delete or recreate the Cognito user pool or the DynamoDB
table** (every login and all the data): that stops it before anything is applied. To require an
approval before each production deploy, set *Required reviewers* on the `producao` Environment.

### One-time setup

1. **In each AWS account:** create an IAM policy from [`docs/iam-deploy-policy.json`](docs/iam-deploy-policy.json)
   (it only touches `agenda-salao-*` resources), a user without console access with that policy,
   and an access key for it.
2. **On GitHub** (Settings → Environments), create `dev` and `producao`, each with:
   - secrets `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
   - variables `AWS_ACCOUNT_ID` (the deploy stops if the key is from another account) and `AWS_REGION`
3. **First deploy:** create the `dev` branch. The site's address shows up in the Actions run summary.
4. Recommended for `producao`: *Required reviewers* (you approve each deploy) and *Deployment
   branches* = only `main`.

### Create a salon login

Actions → *Create salon user* → choose the environment and type the e-mail. Cognito e-mails a
temporary password. There is no open sign-up.

If a deploy fails for a missing permission, the error names it: add it to
`docs/iam-deploy-policy.json` and update the policy in AWS.

## Security and cost

- Encrypted table with continuous backups; deletion protection in `prod`.
- API Gateway rate-limits requests. The site may only talk to itself, Cognito and the API (CSP).
- Rotate the deploy access keys from time to time.
- Pay-per-use: close to zero with no traffic.
