import pytest

from agenda.dominio import (Agendamento, Configuracao, Profissional, Servico, formatar_hora,
                            ler_cliente, ler_data, ler_hora)
from agenda.erros import ErroValidacao


@pytest.mark.parametrize("texto, minutos", [("00:00", 0), ("09:30", 570), ("23:59", 1439)])
def test_hora_ida_e_volta(texto, minutos):
    assert ler_hora(texto) == minutos
    assert formatar_hora(minutos) == texto


@pytest.mark.parametrize("ruim", ["9:30", "24:00", "10:60", "", None, 930, "10:00:00", "ab:cd"])
def test_hora_invalida(ruim):
    with pytest.raises(ErroValidacao):
        ler_hora(ruim)


@pytest.mark.parametrize("ruim", ["2026-02-30", "26-01-01", "2026/01/01", None, 20260101, "2026-1-1"])
def test_data_invalida(ruim):
    with pytest.raises(ErroValidacao):
        ler_data(ruim)


def test_servico_valido_limpa_espacos():
    s = Servico.de_dados({"nome": "  Corte   feminino ", "duracao_min": 45, "preco_centavos": 0})
    assert s.nome == "Corte feminino" and len(s.id) == 8
    assert Servico.de_dict(s.para_dict()) == s


@pytest.mark.parametrize("campo, valor", [
    ("nome", ""), ("nome", "   "), ("nome", "x" * 81), ("nome", 5),
    ("duracao_min", 20), ("duracao_min", 0), ("duracao_min", 495), ("duracao_min", True),
    ("duracao_min", "30"), ("duracao_min", 30.0),
    ("preco_centavos", -1), ("preco_centavos", 1_000_001), ("preco_centavos", 10.5),
])
def test_servico_recusa_dados_ruins(campo, valor):
    dados = {"nome": "Corte", "duracao_min": 30, "preco_centavos": 100, campo: valor}
    with pytest.raises(ErroValidacao):
        Servico.de_dados(dados)


def test_servico_sem_campo_obrigatorio():
    with pytest.raises(ErroValidacao):
        Servico.de_dados({"nome": "Corte"})


def test_profissional_remove_repetidos_e_valida_ids():
    p = Profissional.de_dados({"nome": "Ana", "servicos": ["aaaaaaaa", "aaaaaaaa", "bbbbbbbb"]})
    assert p.servicos == ("aaaaaaaa", "bbbbbbbb")
    assert Profissional.de_dict(p.para_dict()) == p
    for ruim in ("aaaaaaaa", [1], ["curto"], ["../etc"], ["a" * 8] * 101, None):
        with pytest.raises(ErroValidacao):
            Profissional.de_dados({"nome": "Ana", "servicos": ruim})


def test_configuracao_padrao_e_validacao():
    c = Configuracao.de_dados({"dias_abertos": [5, 1, 1], "abre": "08:00", "fecha": "18:30"})
    assert c.dias_abertos == (1, 5) and Configuracao.de_dict(c.para_dict()) == c
    ruins = [{"dias_abertos": [], "abre": "08:00", "fecha": "18:00"},
             {"dias_abertos": [7], "abre": "08:00", "fecha": "18:00"},
             {"dias_abertos": [True], "abre": "08:00", "fecha": "18:00"},
             {"dias_abertos": [1], "abre": "18:00", "fecha": "08:00"},
             {"dias_abertos": [1], "abre": "08:10", "fecha": "18:00"},
             {"dias_abertos": [1], "abre": "08:00", "fecha": "08:00"}]
    for dados in ruins:
        with pytest.raises(ErroValidacao):
            Configuracao.de_dados(dados)


@pytest.mark.parametrize("entrada, telefone", [
    ("(11) 98888-7777", "11988887777"), ("1133334444", "1133334444"), ("", ""), (None, "")])
def test_cliente_telefone(entrada, telefone):
    assert ler_cliente({"cliente_nome": "Maria", "cliente_telefone": entrada}) == ("Maria", telefone)


def test_cliente_recusa_telefone_curto_e_nome_vazio():
    with pytest.raises(ErroValidacao):
        ler_cliente({"cliente_nome": "Maria", "cliente_telefone": "9999"})
    with pytest.raises(ErroValidacao):
        ler_cliente({"cliente_nome": " ", "cliente_telefone": ""})


def test_agendamento_calcula_fim():
    a = Agendamento("2026-11-17_1000_aaaaaaaa", "2026-11-17", "10:00", 90, "p", "Ana", "s",
                    "Corte", 100, "Maria", "")
    assert (a.inicio_min, a.fim_min) == (600, 690)
    assert Agendamento.de_dict(a.para_dict()) == a
