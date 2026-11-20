"""Local server to try the frontend without AWS: serves the site and the API (the SAME code as the
Lambdas, one per action, routed like API Gateway) with an in-memory database, and NO login (no Cognito): every request is the same salon.

    python local/server.py [manager|employee] [--port 8765]

The role plays the part of the user's Cognito group (default: manager). The manager adds services
and professionals and configures the salon; the employee only works with the agenda.

Data lives in memory and is lost when the server stops. It only listens on 127.0.0.1: never expose
it, since it has no authentication. The deployed app is not affected: there, API Gateway still
requires a valid Cognito token for every request.

`start(require_login=True)` is used by local/e2e.py to test the login screen: the site then logs in
through Cognito (which the test simulates) and the server accepts the simulated tokens."""
import argparse
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_gateway import dispatch                    # noqa: E402  (also puts the backend on the path)
from agenda_core.adapters.clock import salon_now    # noqa: E402
from agenda_core.ports import Dependencies          # noqa: E402
from memory_repository import MemoryRepository     # noqa: E402

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
        url = urlparse(self.path)
        event = {"rawPath": url.path[len("/api"):], "requestContext": {"http": {"method": self.command}},
                 "queryStringParameters": {k: v[0] for k, v in parse_qs(url.query).items()} or None,
                 "body": self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()}
        owner = self._owner()
        if owner:
            claims = {"sub": owner, "cognito:groups": f"[{self.server.role}]"}   # as API Gateway sends it
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
        return f'export const CONFIG = {{region:"",clientId:"",apiUrl:"{api_url}",skipLogin:true,role:"{self.server.role}"}};'

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


def start(port=8765, require_login=False, role="manager"):
    """A server with its own empty in-memory database. Call `serve_forever()` on it.
    `role` is the Cognito group every request is treated as coming from."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    server = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    server.require_login = require_login
    server.role = role
    server.deps = Dependencies(MemoryRepository(), salon_now)  # Brasília time, like the Lambdas (not the machine's)
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("role", nargs="?", choices=ROLES, default="manager",
                        help="the Cognito group to simulate (default: manager)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(f"http://127.0.0.1:{args.port}  (in-memory data, no login, as {args.role}; Ctrl+C to stop)")
    try:
        start(args.port, role=args.role).serve_forever()
    except KeyboardInterrupt:
        pass
