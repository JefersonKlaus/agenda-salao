"""Modelos e validação. Horários são do salão, sem fuso: data "AAAA-MM-DD" e hora "HH:MM"."""
from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Mapping, Optional

from .erros import ErroValidacao

PASSO = 15                          # minutos entre um horário e o próximo
DURACAO_MIN, DURACAO_MAX = 15, 480
PRECO_MAX = 1_000_000               # R$ 10.000,00 em centavos
_RE_HORA = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_ID = re.compile(r"^[0-9a-f]{8}$")
ID_AGENDAMENTO = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}_[0-9a-f]{8}$")


def novo_id() -> str:
    return uuid.uuid4().hex[:8]


def ler_data(valor: Any) -> date:
    if not isinstance(valor, str) or not _RE_DATA.match(valor):
        raise ErroValidacao("data inválida: use AAAA-MM-DD")
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ErroValidacao("essa data não existe") from None


def ler_hora(valor: Any) -> int:
    """'09:30' -> 570 (minutos desde a meia-noite)."""
    achado = _RE_HORA.match(valor) if isinstance(valor, str) else None
    if not achado:
        raise ErroValidacao("hora inválida: use HH:MM")
    return int(achado.group(1)) * 60 + int(achado.group(2))


def formatar_hora(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _texto(dados: Mapping[str, Any], campo: str, maximo: int = 80, obrigatorio: bool = True) -> str:
    valor = dados.get(campo)
    if valor is None and not obrigatorio:
        return ""
    if not isinstance(valor, str) or (obrigatorio and not valor.strip()):
        raise ErroValidacao(f"{campo}: preencha este campo")
    limpo = " ".join(valor.split())
    if len(limpo) > maximo:
        raise ErroValidacao(f"{campo}: no máximo {maximo} caracteres")
    return limpo


def _inteiro(dados: Mapping[str, Any], campo: str, minimo: int, maximo: int) -> int:
    valor = dados.get(campo)
    if isinstance(valor, bool) or not isinstance(valor, int) or not minimo <= valor <= maximo:
        raise ErroValidacao(f"{campo}: informe um número inteiro de {minimo} a {maximo}")
    return valor


@dataclass(frozen=True)
class Servico:
    id: str
    nome: str
    duracao_min: int
    preco_centavos: int

    @classmethod
    def de_dados(cls, dados: Mapping[str, Any], id: Optional[str] = None) -> "Servico":
        duracao = _inteiro(dados, "duracao_min", DURACAO_MIN, DURACAO_MAX)
        if duracao % PASSO:
            raise ErroValidacao(f"duracao_min: use múltiplos de {PASSO} minutos")
        return cls(id or novo_id(), _texto(dados, "nome"), duracao,
                   _inteiro(dados, "preco_centavos", 0, PRECO_MAX))

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def de_dict(cls, d: Mapping[str, Any]) -> "Servico":
        return cls(d["id"], d["nome"], d["duracao_min"], d["preco_centavos"])


@dataclass(frozen=True)
class Profissional:
    id: str
    nome: str
    servicos: tuple[str, ...]       # ids dos serviços que ela faz

    @classmethod
    def de_dados(cls, dados: Mapping[str, Any], id: Optional[str] = None) -> "Profissional":
        ids = dados.get("servicos", [])
        if not isinstance(ids, list) or len(ids) > 100 or not all(
                isinstance(i, str) and _RE_ID.match(i) for i in ids):
            raise ErroValidacao("servicos: envie uma lista de ids de serviço")
        return cls(id or novo_id(), _texto(dados, "nome"), tuple(dict.fromkeys(ids)))

    def para_dict(self) -> dict[str, Any]:
        return {"id": self.id, "nome": self.nome, "servicos": list(self.servicos)}

    @classmethod
    def de_dict(cls, d: Mapping[str, Any]) -> "Profissional":
        return cls(d["id"], d["nome"], tuple(d["servicos"]))


@dataclass(frozen=True)
class Configuracao:
    dias_abertos: tuple[int, ...] = (0, 1, 2, 3, 4, 5)   # 0 = segunda ... 6 = domingo
    abre: str = "09:00"
    fecha: str = "19:00"

    @classmethod
    def de_dados(cls, dados: Mapping[str, Any]) -> "Configuracao":
        dias = dados.get("dias_abertos")
        if not isinstance(dias, list) or not dias or not all(
                isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in dias):
            raise ErroValidacao("dias_abertos: lista de 0 (segunda) a 6 (domingo)")
        abre, fecha = ler_hora(dados.get("abre")), ler_hora(dados.get("fecha"))
        if abre % PASSO or fecha % PASSO:
            raise ErroValidacao(f"os horários devem ser múltiplos de {PASSO} minutos")
        if fecha - abre < PASSO:
            raise ErroValidacao("o salão precisa fechar depois de abrir")
        return cls(tuple(sorted(set(dias))), formatar_hora(abre), formatar_hora(fecha))

    def para_dict(self) -> dict[str, Any]:
        return {"dias_abertos": list(self.dias_abertos), "abre": self.abre, "fecha": self.fecha}

    @classmethod
    def de_dict(cls, d: Mapping[str, Any]) -> "Configuracao":
        return cls(tuple(d["dias_abertos"]), d["abre"], d["fecha"])


@dataclass(frozen=True)
class Agendamento:
    id: str
    data: str
    inicio: str
    duracao_min: int
    profissional_id: str
    profissional_nome: str
    servico_id: str
    servico_nome: str
    preco_centavos: int
    cliente_nome: str
    cliente_telefone: str

    @property
    def inicio_min(self) -> int:
        return ler_hora(self.inicio)

    @property
    def fim_min(self) -> int:
        return self.inicio_min + self.duracao_min

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def de_dict(cls, d: Mapping[str, Any]) -> "Agendamento":
        return cls(**{campo: d[campo] for campo in cls.__dataclass_fields__})


def ler_cliente(dados: Mapping[str, Any]) -> tuple[str, str]:
    """Nome e telefone (só dígitos, com DDD). O telefone é opcional."""
    nome = _texto(dados, "cliente_nome")
    telefone = re.sub(r"\D", "", _texto(dados, "cliente_telefone", 20, obrigatorio=False))
    if telefone and len(telefone) not in (10, 11):
        raise ErroValidacao("cliente_telefone: use DDD + número")
    return nome, telefone


MODELOS = {"servico": Servico, "profissional": Profissional}
