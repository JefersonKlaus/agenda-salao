"""Ponto de entrada da Lambda. Só liga as peças: banco, relógio e roteador."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .agenda import Agenda
from .http import tratar
from .repositorio_dynamo import RepositorioDynamo

# Brasília é UTC-3 o ano todo (sem horário de verão desde 2019). Evita depender de tzdata.
FUSO = timezone(timedelta(hours=-3))
_agenda = None


def _obter_agenda() -> Agenda:
    global _agenda
    if _agenda is None:             # criado uma vez por ambiente de execução e reaproveitado
        import boto3                # já vem na Lambda; importado aqui para os testes não exigirem
        repo = RepositorioDynamo(boto3.client("dynamodb"), os.environ["TABELA"])
        _agenda = Agenda(repo, lambda: datetime.now(FUSO).replace(tzinfo=None))
    return _agenda


def lambda_handler(evento: dict[str, Any], contexto: Any) -> dict[str, Any]:
    return tratar(evento, _obter_agenda())
