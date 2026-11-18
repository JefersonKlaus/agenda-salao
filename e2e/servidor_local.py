"""Servidor de desenvolvimento: serve o frontend e a API usando o MESMO código da Lambda,
com banco em memória. Serve para testar tudo sem AWS:  python e2e/servidor_local.py"""
import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend" / "src"))

from agenda.agenda import Agenda                    # noqa: E402
from agenda.http import tratar                      # noqa: E402
from agenda.repositorio_memoria import RepositorioMemoria  # noqa: E402

AGENDA = Agenda(RepositorioMemoria(), datetime.now)
# Igual ao do CloudFront (infra/frontend.tf): se o site quebrar com ele, o teste acusa antes do deploy.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self' https://cognito-idp.sa-east-1.amazonaws.com; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'")
TIPOS = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}


class Manipulador(BaseHTTPRequestHandler):
    def _api(self):
        url = urlparse(self.path)
        autorizacao = self.headers.get("Authorization", "")
        evento = {"rawPath": url.path[len("/api"):], "requestContext": {"http": {"method": self.command}},
                  "queryStringParameters": {k: v[0] for k, v in parse_qs(url.query).items()} or None,
                  "body": self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()}
        if autorizacao.startswith("Bearer token-"):     # imita o autorizador JWT do API Gateway
            evento["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": autorizacao[13:]}}}
        resposta = tratar(evento, AGENDA)
        corpo = resposta["body"].encode()
        self.send_response(resposta["statusCode"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _estatico(self):
        caminho = urlparse(self.path).path.lstrip("/") or "index.html"
        arquivo = (RAIZ / "frontend" / caminho).resolve()
        if caminho == "js/config.js":
            corpo = ('export const CONFIG = {regiao:"sa-east-1",clienteId:"local",'
                     f'apiUrl:"http://{self.headers["Host"]}/api"}};').encode()
        elif (RAIZ / "frontend").resolve() in arquivo.parents and arquivo.is_file():
            corpo = arquivo.read_bytes()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", TIPOS.get(arquivo.suffix, "text/plain") + "; charset=utf-8")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        self._api() if self.path.startswith("/api") else self._estatico()

    do_POST = do_PUT = do_DELETE = _api

    def log_message(self, *args):
        pass


def iniciar(porta=8765):
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Manipulador)
    return servidor


if __name__ == "__main__":
    print("http://127.0.0.1:8765  (o login precisa do Cognito: veja e2e/teste_e2e.py)")
    iniciar().serve_forever()
