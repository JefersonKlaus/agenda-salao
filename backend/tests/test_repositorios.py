"""Contrato dos repositórios, sem passar pelas checagens da Agenda: aqui só a trava conta."""
import pytest

from agenda.dominio import Agendamento, Configuracao, Profissional, Servico
from agenda.erros import ConflitoHorario
from agenda.repositorio_dynamo import RepositorioDynamo
from conftest import DONO, OUTRO, DynamoFalso, ErroFalso


def ag(id, inicio="10:00", duracao=60, prof="p1", data="2026-11-17"):
    return Agendamento(id, data, inicio, duracao, prof, "Ana", "s1", "Corte", 100, "Maria", "")


def test_trava_impede_choque_mesmo_sem_checagem_previa(repo):
    repo.criar_agendamento(DONO, ag("2026-11-17_1000_aaaaaaaa"))
    for inicio, duracao in (("10:00", 60), ("10:30", 30), ("09:30", 45), ("10:45", 15)):
        with pytest.raises(ConflitoHorario):
            repo.criar_agendamento(DONO, ag("2026-11-17_9999_bbbbbbbb", inicio, duracao))
    assert len(repo.agendamentos_do_dia(DONO, "2026-11-17")) == 1


def test_conflito_nao_deixa_travas_pela_metade(repo):
    repo.criar_agendamento(DONO, ag("2026-11-17_1000_aaaaaaaa", "10:00", 60))
    with pytest.raises(ConflitoHorario):
        repo.criar_agendamento(DONO, ag("2026-11-17_0930_bbbbbbbb", "09:30", 60))   # bate às 10:00
    repo.criar_agendamento(DONO, ag("2026-11-17_0900_cccccccc", "09:00", 60))       # 09:30 não ficou preso


def test_encostar_nao_e_conflito_e_outro_dono_ou_profissional_nao_interfere(repo):
    repo.criar_agendamento(DONO, ag("2026-11-17_1000_aaaaaaaa"))
    repo.criar_agendamento(DONO, ag("2026-11-17_1100_bbbbbbbb", "11:00"))
    repo.criar_agendamento(DONO, ag("2026-11-17_1000_cccccccc", prof="p2"))
    repo.criar_agendamento(OUTRO, ag("2026-11-17_1000_dddddddd"))
    repo.criar_agendamento(DONO, ag("2026-11-18_1000_eeeeeeee", data="2026-11-18"))
    assert len(repo.agendamentos_do_dia(DONO, "2026-11-17")) == 3


def test_cancelar_libera_as_travas_e_nao_cancela_duas_vezes(repo):
    repo.criar_agendamento(DONO, ag("2026-11-17_1000_aaaaaaaa"))
    assert repo.cancelar_agendamento(DONO, "2026-11-17_1000_aaaaaaaa").id == "2026-11-17_1000_aaaaaaaa"
    assert repo.cancelar_agendamento(DONO, "2026-11-17_1000_aaaaaaaa") is None
    repo.criar_agendamento(DONO, ag("2026-11-17_1000_bbbbbbbb"))


def test_salvar_obter_listar_excluir(repo):
    servico = Servico("aaaaaaaa", "Corte", 60, 8000)
    prof = Profissional("bbbbbbbb", "Ana", ("aaaaaaaa",))
    repo.salvar(DONO, "servico", servico)
    repo.salvar(DONO, "profissional", prof)
    assert repo.obter(DONO, "servico", "aaaaaaaa") == servico
    assert repo.listar(DONO, "profissional") == [prof]
    assert repo.listar(OUTRO, "servico") == [] and repo.obter(OUTRO, "servico", "aaaaaaaa") is None
    repo.excluir(DONO, "servico", "aaaaaaaa")
    repo.excluir(DONO, "servico", "aaaaaaaa")                       # excluir de novo não quebra
    assert repo.listar(DONO, "servico") == [] and len(repo.listar(DONO, "profissional")) == 1


def test_configuracao_vazia_e_salva(repo):
    assert repo.obter_configuracao(DONO) is None
    config = Configuracao((1, 2), "08:00", "12:00")
    repo.salvar_configuracao(DONO, config)
    assert repo.obter_configuracao(DONO) == config and repo.obter_configuracao(OUTRO) is None


# ---------------------------------------------------------------- só o DynamoDB

def test_listar_junta_todas_as_paginas():
    repo = RepositorioDynamo(DynamoFalso(pagina=2), "t")
    for i in range(7):
        repo.salvar(DONO, "servico", Servico(f"{i:08x}", f"S{i}", 30, 100))
    assert len(repo.listar(DONO, "servico")) == 7


def test_prefixo_do_dia_nao_pega_outro_dia():
    repo = RepositorioDynamo(DynamoFalso(), "t")
    repo.criar_agendamento(DONO, ag("2026-11-17_1000_aaaaaaaa"))
    repo.criar_agendamento(DONO, ag("2026-11-18_1000_bbbbbbbb", data="2026-11-18"))
    assert [a.id for a in repo.agendamentos_do_dia(DONO, "2026-11-18")] == ["2026-11-18_1000_bbbbbbbb"]


def test_transacao_tem_um_put_por_bloco_com_condicao():
    banco = DynamoFalso()
    RepositorioDynamo(banco, "t").criar_agendamento(DONO, ag("2026-11-17_1000_aaaaaaaa", duracao=60))
    operacoes = banco.chamadas[0]
    assert len(operacoes) == 1 + 4                                   # o agendamento + 4 blocos de 15 min
    assert all(op["Put"]["ConditionExpression"] == "attribute_not_exists(PK)" for op in operacoes)
    assert all(op["Put"]["Item"]["PK"] == {"S": f"SALAO#{DONO}"} for op in operacoes)


def test_so_condicao_falsa_vira_conflito():
    class Banco(DynamoFalso):
        def __init__(self, erro):
            super().__init__()
            self.erro = erro

        def transact_write_items(self, TransactItems):
            raise self.erro

    for erro in (ErroFalso("TransactionCanceledException", ["None", "TransactionConflict"]),
                 ErroFalso("ProvisionedThroughputExceededException"), RuntimeError("boom")):
        with pytest.raises(type(erro)):
            RepositorioDynamo(Banco(erro), "t").criar_agendamento(DONO, ag("2026-11-17_1000_aaaaaaaa"))
    conflito = ErroFalso("TransactionCanceledException", ["None", "ConditionalCheckFailed"])
    with pytest.raises(ConflitoHorario):
        RepositorioDynamo(Banco(conflito), "t").criar_agendamento(DONO, ag("2026-11-17_1000_aaaaaaaa"))
