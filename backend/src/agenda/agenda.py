"""Casos de uso da agenda. Recebem o `dono` (id do salão) já validado pelo login."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping

from .dominio import (ID_AGENDAMENTO, MODELOS, Agendamento, Configuracao, Profissional, ler_cliente,
                      ler_data, ler_hora, novo_id)
from .erros import ErroValidacao, NaoEncontrado
from .horarios import cabe_no_expediente, choca, horarios_livres, ja_passou, ocupacao

LIMITES = {"servico": 200, "profissional": 50}
ROTULOS = {"servico": "serviço", "profissional": "profissional"}


class Agenda:
    def __init__(self, repo: Any, agora: Callable[[], datetime]) -> None:
        self.repo, self.agora = repo, agora

    # ------------------------------------------------------------ serviços e profissionais
    def listar(self, dono: str, tipo: str) -> list[Any]:
        return sorted(self.repo.listar(dono, tipo), key=lambda i: i.nome.lower())

    def criar(self, dono: str, tipo: str, dados: Mapping[str, Any]) -> Any:
        if len(self.repo.listar(dono, tipo)) >= LIMITES[tipo]:
            raise ErroValidacao(f"limite de {LIMITES[tipo]} itens atingido")
        item = MODELOS[tipo].de_dados(dados)
        self._conferir_servicos(dono, item)
        self.repo.salvar(dono, tipo, item)
        return item

    def atualizar(self, dono: str, tipo: str, id: str, dados: Mapping[str, Any]) -> Any:
        self._obter(dono, tipo, id)
        item = MODELOS[tipo].de_dados(dados, id=id)
        self._conferir_servicos(dono, item)
        self.repo.salvar(dono, tipo, item)
        return item

    def remover(self, dono: str, tipo: str, id: str) -> None:
        self._obter(dono, tipo, id)
        self.repo.excluir(dono, tipo, id)
        if tipo == "servico":           # ninguém mais "faz" um serviço que não existe
            for prof in self.repo.listar(dono, "profissional"):
                if id in prof.servicos:
                    self.repo.salvar(dono, "profissional", Profissional(
                        prof.id, prof.nome, tuple(s for s in prof.servicos if s != id)))

    def _obter(self, dono: str, tipo: str, id: str) -> Any:
        item = self.repo.obter(dono, tipo, id)
        if item is None:
            raise NaoEncontrado(f"{ROTULOS[tipo]} não encontrado")
        return item

    def _conferir_servicos(self, dono: str, item: Any) -> None:
        if isinstance(item, Profissional):
            existentes = {s.id for s in self.repo.listar(dono, "servico")}
            if not set(item.servicos) <= existentes:
                raise ErroValidacao("servicos: há serviço que não existe")

    # ------------------------------------------------------------ expediente
    def configuracao(self, dono: str) -> Configuracao:
        return self.repo.obter_configuracao(dono) or Configuracao()

    def salvar_configuracao(self, dono: str, dados: Mapping[str, Any]) -> Configuracao:
        config = Configuracao.de_dados(dados)
        self.repo.salvar_configuracao(dono, config)
        return config

    # ------------------------------------------------------------ agendamentos
    def disponibilidade(self, dono: str, data: str, servico_id: str, profissional_id: str) -> list[str]:
        dia = ler_data(data)
        servico, prof = self._servico_e_profissional(dono, servico_id, profissional_id)
        ocupados = ocupacao(self.repo.agendamentos_do_dia(dono, data), prof.id)
        return horarios_livres(self.configuracao(dono), dia, servico.duracao_min, ocupados, self.agora())

    def agenda_do_dia(self, dono: str, data: str) -> list[Agendamento]:
        ler_data(data)
        return sorted(self.repo.agendamentos_do_dia(dono, data), key=lambda a: (a.inicio, a.profissional_nome))

    def agendar(self, dono: str, dados: Mapping[str, Any]) -> Agendamento:
        dia, inicio = ler_data(dados.get("data")), ler_hora(dados.get("inicio"))
        cliente_nome, telefone = ler_cliente(dados)
        servico, prof = self._servico_e_profissional(dono, dados.get("servico_id"),
                                                     dados.get("profissional_id"))
        if ja_passou(dia, inicio, self.agora()):
            raise ErroValidacao("esse horário já passou")
        if not cabe_no_expediente(self.configuracao(dono), dia, inicio, servico.duracao_min):
            raise ErroValidacao("esse horário está fora do expediente do salão")
        data = dia.isoformat()
        ocupados = ocupacao(self.repo.agendamentos_do_dia(dono, data), prof.id)
        if choca(inicio, inicio + servico.duracao_min, ocupados):
            raise ErroValidacao("esse horário já está ocupado")   # a trava no banco cobre a corrida
        ag = Agendamento(f"{data}_{inicio // 60:02d}{inicio % 60:02d}_{novo_id()}", data,
                         dados["inicio"], servico.duracao_min, prof.id, prof.nome, servico.id,
                         servico.nome, servico.preco_centavos, cliente_nome, telefone)
        self.repo.criar_agendamento(dono, ag)
        return ag

    def cancelar(self, dono: str, id: str) -> Agendamento:
        if not isinstance(id, str) or not ID_AGENDAMENTO.match(id):
            raise NaoEncontrado("agendamento não encontrado")
        ag = self.repo.cancelar_agendamento(dono, id)
        if ag is None:
            raise NaoEncontrado("agendamento não encontrado")
        return ag

    def _servico_e_profissional(self, dono: str, servico_id: Any, profissional_id: Any):
        servico = self._obter(dono, "servico", servico_id if isinstance(servico_id, str) else "")
        prof = self._obter(dono, "profissional", profissional_id if isinstance(profissional_id, str) else "")
        if servico.id not in prof.servicos:
            raise ErroValidacao("essa profissional não faz esse serviço")
        return servico, prof
