from datetime import date, datetime

import pytest

from agenda.dominio import Configuracao
from agenda.horarios import (cabe_no_expediente, chaves_das_travas, choca, horarios_livres,
                             ja_passou)

CONFIG = Configuracao(dias_abertos=(0, 1, 2, 3, 4, 5), abre="09:00", fecha="12:00")
SEGUNDA, DOMINGO = date(2026, 11, 16), date(2026, 11, 22)


@pytest.mark.parametrize("a, b, esperado", [
    ((600, 660), (630, 690), True),     # sobrepõe no meio
    ((600, 660), (660, 720), False),    # encostam: o fim de um é o início do outro
    ((600, 660), (540, 600), False),
    ((600, 660), (600, 660), True),     # iguais
    ((600, 720), (630, 660), True),     # um dentro do outro
    ((630, 660), (600, 720), True),
])
def test_choque_de_intervalos(a, b, esperado):
    assert choca(a[0], a[1], [b]) is esperado


def test_horarios_livres_sem_nada_ocupado():
    horas = horarios_livres(CONFIG, SEGUNDA, 60, [])
    assert horas[0] == "09:00" and horas[-1] == "11:00" and len(horas) == 9


def test_atendimento_nao_pode_passar_do_fechamento():
    assert horarios_livres(CONFIG, SEGUNDA, 180, []) == ["09:00"]
    assert horarios_livres(CONFIG, SEGUNDA, 195, []) == []


def test_horarios_ocupados_somem_e_os_vizinhos_continuam():
    horas = horarios_livres(CONFIG, SEGUNDA, 60, [(600, 660)])        # ocupado 10:00-11:00
    assert "10:00" not in horas and "09:30" not in horas and "10:30" not in horas
    assert "09:00" in horas and "11:00" in horas


def test_dia_fechado_nao_tem_horarios():
    assert horarios_livres(CONFIG, DOMINGO, 30, []) == []


def test_horarios_do_passado_somem_so_no_dia_de_hoje():
    agora = datetime(2026, 11, 16, 10, 20)
    horas = horarios_livres(CONFIG, SEGUNDA, 30, [], agora)
    assert horas[0] == "10:30"
    assert horarios_livres(CONFIG, date(2026, 11, 17), 30, [], agora)[0] == "09:00"
    assert horarios_livres(CONFIG, date(2026, 11, 15), 30, [], agora) == []


def test_ja_passou():
    agora = datetime(2026, 11, 16, 10, 0)
    assert ja_passou(SEGUNDA, 600, agora) and not ja_passou(SEGUNDA, 615, agora)
    assert ja_passou(date(2026, 11, 15), 1000, agora) and not ja_passou(date(2026, 11, 17), 0, agora)
    assert not ja_passou(SEGUNDA, 0, None)


def test_cabe_no_expediente():
    assert cabe_no_expediente(CONFIG, SEGUNDA, 540, 180)
    assert not cabe_no_expediente(CONFIG, SEGUNDA, 540, 195)       # passa do fechamento
    assert not cabe_no_expediente(CONFIG, SEGUNDA, 525, 30)        # antes de abrir
    assert not cabe_no_expediente(CONFIG, SEGUNDA, 545, 30)        # fora do passo de 15 min
    assert not cabe_no_expediente(CONFIG, DOMINGO, 600, 30)


def test_travas_cobrem_cada_bloco_sem_o_fim():
    assert chaves_das_travas("p", "2026-11-17", 600, 45) == [
        "p#2026-11-17#1000", "p#2026-11-17#1015", "p#2026-11-17#1030"]
    # 10:00-10:30 e 10:30-11:00 não compartilham nenhuma trava
    assert not set(chaves_das_travas("p", "d", 600, 30)) & set(chaves_das_travas("p", "d", 630, 30))
