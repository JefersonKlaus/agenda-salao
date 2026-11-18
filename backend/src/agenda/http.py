"""Traduz o evento do API Gateway (HTTP API v2) em chamadas à Agenda e devolve a resposta JSON."""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Callable

from .agenda import Agenda
from .erros import ErroDeNegocio, ErroValidacao

log = logging.getLogger(__name__)
MAX_CORPO = 10_000                      # bytes: nenhum cadastro precisa de mais que isso
_ID = r"([0-9a-f]{8})"
_ID_AG = r"([0-9a-f_-]{15,40})"


def _tipo(nome: str) -> Callable:
    """Rotas /servicos e /profissionais compartilham o mesmo código."""
    def listar(a, d, c): return [i.para_dict() for i in a.listar(d, nome)]
    def criar(a, d, c): return 201, a.criar(d, nome, c["corpo"]).para_dict()
    def atualizar(a, d, c): return a.atualizar(d, nome, c["id"], c["corpo"]).para_dict()
    def remover(a, d, c): return 204, a.remover(d, nome, c["id"])
    return listar, criar, atualizar, remover


def _rotas() -> list[tuple[str, re.Pattern, Callable]]:
    tabela = []
    for caminho, nome in (("servicos", "servico"), ("profissionais", "profissional")):
        listar, criar, atualizar, remover = _tipo(nome)
        tabela += [("GET", f"/{caminho}", listar), ("POST", f"/{caminho}", criar),
                   ("PUT", f"/{caminho}/{_ID}", atualizar), ("DELETE", f"/{caminho}/{_ID}", remover)]
    tabela += [
        ("GET", "/configuracao", lambda a, d, c: a.configuracao(d).para_dict()),
        ("PUT", "/configuracao", lambda a, d, c: a.salvar_configuracao(d, c["corpo"]).para_dict()),
        ("GET", "/agendamentos", lambda a, d, c: [x.para_dict() for x in a.agenda_do_dia(d, c["q"].get("data"))]),
        ("POST", "/agendamentos", lambda a, d, c: (201, a.agendar(d, c["corpo"]).para_dict())),
        ("DELETE", f"/agendamentos/{_ID_AG}", lambda a, d, c: (204, a.cancelar(d, c["id"]))),
        ("GET", "/disponibilidade", lambda a, d, c: a.disponibilidade(
            d, c["q"].get("data"), c["q"].get("servico_id"), c["q"].get("profissional_id"))),
    ]
    return [(m, re.compile(f"^{p}$"), f) for m, p, f in tabela]


ROTAS = _rotas()


def _resposta(status: int, corpo: Any = None) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": "" if corpo is None else json.dumps(corpo, ensure_ascii=False)}


def _dono(evento: dict[str, Any]) -> str:
    """Id do salão = `sub` do token já verificado pelo API Gateway. Nunca vem do corpo."""
    try:
        sub = evento["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        sub = None
    if not isinstance(sub, str) or not sub:
        raise PermissionError
    return sub


def _corpo(evento: dict[str, Any]) -> dict[str, Any]:
    bruto = evento.get("body") or ""
    if evento.get("isBase64Encoded"):
        bruto = base64.b64decode(bruto).decode("utf-8", "replace")
    if not bruto:
        return {}
    if len(bruto) > MAX_CORPO:
        raise ErroValidacao("corpo grande demais")
    try:
        dados = json.loads(bruto)
    except ValueError:
        raise ErroValidacao("corpo não é um JSON válido") from None
    if not isinstance(dados, dict):
        raise ErroValidacao("o corpo deve ser um objeto JSON")
    return dados


def tratar(evento: dict[str, Any], agenda: Agenda) -> dict[str, Any]:
    try:
        dono = _dono(evento)
        metodo = evento["requestContext"]["http"]["method"]
        caminho = evento.get("rawPath", "").rstrip("/") or "/"
        existe = False
        for m, padrao, funcao in ROTAS:
            achou = padrao.match(caminho)
            if not achou:
                continue
            existe = True
            if m != metodo:
                continue
            contexto = {"corpo": _corpo(evento) if metodo in ("POST", "PUT") else {},
                        "q": evento.get("queryStringParameters") or {},
                        "id": achou.group(1) if achou.groups() else None}
            resultado = funcao(agenda, dono, contexto)
            if isinstance(resultado, tuple):
                status, corpo = resultado
                return _resposta(status, None if status == 204 else corpo)   # 204 não leva corpo
            return _resposta(200, resultado)
        return _resposta(405 if existe else 404, {"erro": "rota não encontrada"})
    except PermissionError:
        return _resposta(401, {"erro": "não autenticado"})
    except ErroDeNegocio as erro:
        return _resposta(erro.status, {"erro": str(erro)})
    except Exception:
        log.exception("erro inesperado")
        return _resposta(500, {"erro": "erro interno, tente de novo"})
