"""Repositório em memória: usado nos testes e para rodar sem AWS."""
from __future__ import annotations

import threading
from typing import Any, Optional

from .dominio import MODELOS, Agendamento, Configuracao
from .erros import ConflitoHorario
from .horarios import chaves_das_travas


class RepositorioMemoria:
    def __init__(self) -> None:
        self._dados: dict[str, dict[str, Any]] = {}
        self._tranca = threading.Lock()     # imita a atomicidade da transação do DynamoDB

    def _salao(self, dono: str) -> dict[str, Any]:
        return self._dados.setdefault(dono, {"servico": {}, "profissional": {}, "agendamentos": {},
                                            "travas": set(), "configuracao": None})

    def listar(self, dono: str, tipo: str) -> list[Any]:
        return list(self._salao(dono)[tipo].values())

    def obter(self, dono: str, tipo: str, id: str) -> Optional[Any]:
        return self._salao(dono)[tipo].get(id)

    def salvar(self, dono: str, tipo: str, item: Any) -> None:
        self._salao(dono)[tipo][item.id] = MODELOS[tipo].de_dict(item.para_dict())

    def excluir(self, dono: str, tipo: str, id: str) -> None:
        self._salao(dono)[tipo].pop(id, None)

    def obter_configuracao(self, dono: str) -> Optional[Configuracao]:
        return self._salao(dono)["configuracao"]

    def salvar_configuracao(self, dono: str, config: Configuracao) -> None:
        self._salao(dono)["configuracao"] = config

    def agendamentos_do_dia(self, dono: str, data: str) -> list[Agendamento]:
        return [a for a in self._salao(dono)["agendamentos"].values() if a.data == data]

    def obter_agendamento(self, dono: str, id: str) -> Optional[Agendamento]:
        return self._salao(dono)["agendamentos"].get(id)

    def criar_agendamento(self, dono: str, ag: Agendamento) -> None:
        chaves = chaves_das_travas(ag.profissional_id, ag.data, ag.inicio_min, ag.duracao_min)
        with self._tranca:
            salao = self._salao(dono)
            if ag.id in salao["agendamentos"] or any(c in salao["travas"] for c in chaves):
                raise ConflitoHorario("esse horário acabou de ser ocupado")
            salao["agendamentos"][ag.id] = ag
            salao["travas"].update(chaves)

    def cancelar_agendamento(self, dono: str, id: str) -> Optional[Agendamento]:
        with self._tranca:
            salao = self._salao(dono)
            ag = salao["agendamentos"].pop(id, None)
            if ag:
                salao["travas"].difference_update(
                    chaves_das_travas(ag.profissional_id, ag.data, ag.inicio_min, ag.duracao_min))
            return ag
