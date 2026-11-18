"""Regras de horário: expediente, passado e choque entre atendimentos. Funções puras."""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

from .dominio import PASSO, Agendamento, Configuracao, formatar_hora, ler_hora


def ocupacao(agendamentos: Iterable[Agendamento], profissional_id: str) -> list[tuple[int, int]]:
    """Intervalos [início, fim) já tomados por uma profissional."""
    return [(a.inicio_min, a.fim_min) for a in agendamentos if a.profissional_id == profissional_id]


def choca(inicio: int, fim: int, ocupados: Iterable[tuple[int, int]]) -> bool:
    """Dois intervalos se sobrepõem se um começa antes de o outro terminar. Encostar não conta."""
    return any(inicio < o_fim and o_inicio < fim for o_inicio, o_fim in ocupados)


def ja_passou(dia: date, inicio: int, agora: Optional[datetime]) -> bool:
    if agora is None:
        return False
    if dia != agora.date():
        return dia < agora.date()
    return inicio <= agora.hour * 60 + agora.minute


def cabe_no_expediente(config: Configuracao, dia: date, inicio: int, duracao: int) -> bool:
    return (dia.weekday() in config.dias_abertos and inicio % PASSO == 0
            and ler_hora(config.abre) <= inicio and inicio + duracao <= ler_hora(config.fecha))


def horarios_livres(config: Configuracao, dia: date, duracao: int,
                    ocupados: list[tuple[int, int]], agora: Optional[datetime] = None) -> list[str]:
    """Horários de início possíveis para um atendimento de `duracao` minutos."""
    if dia.weekday() not in config.dias_abertos:
        return []
    ultimo = ler_hora(config.fecha) - duracao
    return [formatar_hora(inicio) for inicio in range(ler_hora(config.abre), ultimo + 1, PASSO)
            if not choca(inicio, inicio + duracao, ocupados) and not ja_passou(dia, inicio, agora)]


def chaves_das_travas(profissional_id: str, data: str, inicio: int, duracao: int) -> list[str]:
    """Uma chave por bloco de 15 min. Quem consegue criar todas as chaves ganha o horário:
    é isso que impede duas reservas simultâneas no mesmo horário."""
    return [f"{profissional_id}#{data}#{bloco // 60:02d}{bloco % 60:02d}"
            for bloco in range(inicio, inicio + duracao, PASSO)]
