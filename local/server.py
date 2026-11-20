"""Local server to try the frontend without AWS: serves the site and the API (the SAME code as the
Lambdas, one per action, routed like API Gateway) with an in-memory database, and NO login (no Cognito): every request is the same salon.

    python local/server.py [manager|employee] [--port 8765] [--empty] [--connection on|off]

It starts with demo data (local/seed.py): services, professionals, a busy agenda around today and a
few absences. `--empty` starts with nothing registered, like a new salon.

`--connection off` simulates having no internet: the site still loads, but every API call has its
connection dropped without an answer, which the browser sees exactly as being offline (fetch fails).
While it runs, type `off` or `on` + Enter in this terminal to drop or restore the connection, without
restarting (and without losing the data): browse online, type `off`, and see what the page does.

The role plays the part of the user's Cognito group (default: manager). The manager does everything;
the employee sees the agenda and the services, and registers or removes only her own absences. With
`employee --professional Ana` she is Ana's login (the demo data has logins for Ana and Bia); with no
--professional she is a login that does not attend clients (a receptionist): she cannot add absences.

Data lives in memory and is lost when the server stops. It only listens on 127.0.0.1: never expose
it, since it has no authentication. The deployed app is not affected: there, API Gateway still
requires a valid Cognito token for every request.

`start(require_login=True)` is used by local/e2e.py to test the login screen: the site then logs in
through Cognito (which the test simulates) and the server accepts the simulated tokens."""
import argparse
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_gateway import dispatch                    # noqa: E402  (also puts the backend on the path)
from agenda_core.adapters.clock import salon_now    # noqa: E402
from agenda_core.ports import Dependencies          # noqa: E402
from memory_identity import MemoryIdentity          # noqa: E402
from memory_repository import MemoryRepository     # noqa: E402
from seed import seed as load_demo_data             # noqa: E402

LOCAL_OWNER = "local-salon"                         # the salon every request belongs to without login
# Same as CloudFront's (infra/frontend.tf): if the site breaks with it, the test catches it before deploy.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self' https://cognito-idp.sa-east-1.amazonaws.com; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'")
CONTENT_TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml"}


class RequestHandler(BaseHTTPRequestHandler):
    def _owner(self):
        """Plays the part of API Gateway's JWT authorizer: decides which salon the request is from."""
        if not self.server.require_login:
            return LOCAL_OWNER
        authorization = self.headers.get("Authorization", "")
        return authorization[len("Bearer token-"):] if authorization.startswith("Bearer token-") else None

    def _api(self):
        if not self.server.online:             # --connection off: drop it, like a network that is down
            self.close_connection = True
            return
        url = urlparse(self.path)
        event = {"rawPath": url.path[len("/api"):], "requestContext": {"http": {"method": self.command}},
                 "queryStringParameters": {k: v[0] for k, v in parse_qs(url.query).items()} or None,
                 "body": self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()}
        owner = self._owner()
        if owner:
            claims = {"sub": owner, "cognito:groups": f"[{self.server.role}]"}   # as API Gateway sends it
            if self.server.role == "employee":     # a login the manager created: the salon is written in it
                claims["custom:salon"] = owner
                if self.server.professional_id:
                    claims["custom:professional_id"] = self.server.professional_id
            event["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}
        response = dispatch(event, self.server.deps)
        body = response["body"].encode()
        self.send_response(response["statusCode"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _config(self):
        api_url = f"http://{self.headers['Host']}/api"
        if self.server.require_login:
            return f'export const CONFIG = {{region:"sa-east-1",clientId:"local",apiUrl:"{api_url}"}};'
        return f'export const CONFIG = {{region:"",clientId:"",apiUrl:"{api_url}",skipLogin:true}};'

    def _static(self):
        path = urlparse(self.path).path.lstrip("/") or "index.html"
        file = (ROOT / "frontend" / path).resolve()
        if path == "js/config.js":
            body = self._config().encode()
        elif (ROOT / "frontend").resolve() in file.parents and file.is_file():
            body = file.read_bytes()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(file.suffix, "text/plain") + "; charset=utf-8")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cache-Control", "no-store")       # edits to the frontend show up on reload
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._api() if self.path.startswith("/api") else self._static()

    do_POST = do_PUT = do_DELETE = _api

    def log_message(self, *args):
        pass


ROLES = ("manager", "employee")


CONNECTIONS = ("on", "off")


class LocalServer(ThreadingHTTPServer):
    # On Windows, "reuse address" lets a second server take a port that is already in use, and the
    # requests then go to the other one. Here a busy port is an error instead ("address already in use").
    allow_reuse_address = os.name != "nt"


def start(port=8765, require_login=False, role="manager", demo_data=False, connection="on", professional=None):
    """A server with its own in-memory database, empty unless `demo_data`. Call `serve_forever()` on it.
    `role` is the Cognito group every request is treated as coming from; `professional` (a name), which
    professional an employee's login is (`server.professional_id` can also be set). `connection="off"`: the API
    never answers (simulated offline); `server.online` can also be switched while it runs."""
    if connection not in CONNECTIONS:
        raise ValueError(f"connection must be one of {CONNECTIONS}")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    server = LocalServer(("127.0.0.1", port), RequestHandler)    # port 0: any free one (the tests)
    server.require_login = require_login
    server.role = role
    server.online = connection == "on"
    # Brasília time, like the Lambdas (not the machine's); logins kept in memory, as Cognito would
    server.deps = Dependencies(MemoryRepository(), salon_now, MemoryIdentity())
    if demo_data:
        load_demo_data(server.deps, LOCAL_OWNER, salon_now().date())
    server.professional_id = None
    if professional:
        found = [p for p in server.deps.repo.list_items(LOCAL_OWNER, "professional") if p.name.lower() == professional.lower()]
        if not found:
            raise ValueError(f"no professional named {professional!r}")
        server.professional_id = found[0].id
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("role", nargs="?", choices=ROLES, default="manager",
                        help="the Cognito group to simulate (default: manager)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--professional", help="employee only: which professional she is (e.g. Ana)")
    parser.add_argument("--empty", action="store_true", help="start with no data, like a new salon")
    parser.add_argument("--connection", choices=CONNECTIONS, default="on",
                        help="off = simulate no internet: the site loads, the API never answers (default: on)")
    args = parser.parse_args()
    data = "empty" if args.empty else "demo data"
    offline = ", OFFLINE: the API does not answer" if args.connection == "off" else ""
    print(f"http://127.0.0.1:{args.port}  (in memory, {data}, no login, as {args.role}{offline}; Ctrl+C to stop)")
    print("Type 'off' or 'on' + Enter to drop or restore the connection (simulates the internet going down).")
    server = start(args.port, role=args.role, demo_data=not args.empty, connection=args.connection,
                   professional=args.professional if args.role == "employee" else None)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        while True:
            try:
                command = input().strip().lower()
            except EOFError:                   # no terminal to type in (started in the background): just serve
                while True:
                    time.sleep(3600)
            if command in CONNECTIONS:
                server.online = command == "on"
                print("connection ON: the API answers" if server.online else "connection OFF: the API does not answer")
            elif command:
                print("type 'off' or 'on'")
    except KeyboardInterrupt:
        server.shutdown()
