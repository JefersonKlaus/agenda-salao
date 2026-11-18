import threading

import pytest

from agenda.erros import ConflitoHorario, ErroValidacao, NaoEncontrado
from conftest import DONO, OUTRO, pedido


def test_criar_listar_e_ordenar(agenda):
    for nome in ("Unha", "babosa", "Corte"):
        agenda.criar(DONO, "servico", {"nome": nome, "duracao_min": 30, "preco_centavos": 100})
    assert [s.nome for s in agenda.listar(DONO, "servico")] == ["babosa", "Corte", "Unha"]


def test_cada_salao_so_ve_os_proprios_dados(agenda, salao):
    corte, _, ana = salao
    assert agenda.listar(OUTRO, "servico") == [] and agenda.listar(OUTRO, "profissional") == []
    with pytest.raises(NaoEncontrado):
        agenda.atualizar(OUTRO, "servico", corte.id, {"nome": "X", "duracao_min": 30, "preco_centavos": 1})
    with pytest.raises(NaoEncontrado):
        agenda.remover(OUTRO, "profissional", ana.id)
    agenda.agendar(DONO, pedido(corte, ana))
    assert agenda.agenda_do_dia(OUTRO, "2026-11-17") == []


def test_salao_nao_agenda_com_servico_de_outro(agenda, salao):
    corte, _, ana = salao
    with pytest.raises(NaoEncontrado):
        agenda.agendar(OUTRO, pedido(corte, ana))


def test_atualizar_mantem_o_id(agenda, salao):
    corte = salao[0]
    novo = agenda.atualizar(DONO, "servico", corte.id, {"nome": "Corte novo", "duracao_min": 45, "preco_centavos": 9000})
    assert novo.id == corte.id and agenda.listar(DONO, "servico")[0].nome in ("Corte novo", "Unha")


def test_profissional_so_aceita_servicos_que_existem(agenda, salao):
    with pytest.raises(ErroValidacao):
        agenda.criar(DONO, "profissional", {"nome": "Bia", "servicos": ["deadbeef"]})


def test_remover_servico_tira_ele_das_profissionais(agenda, salao):
    corte, unha, ana = salao
    agenda.remover(DONO, "servico", corte.id)
    assert agenda.listar(DONO, "profissional")[0].servicos == (unha.id,)
    with pytest.raises(NaoEncontrado):
        agenda.remover(DONO, "servico", corte.id)


def test_limite_de_itens(agenda, monkeypatch):
    monkeypatch.setitem(__import__("agenda.agenda", fromlist=["x"]).LIMITES, "servico", 2)
    for i in range(2):
        agenda.criar(DONO, "servico", {"nome": f"S{i}", "duracao_min": 30, "preco_centavos": 1})
    with pytest.raises(ErroValidacao):
        agenda.criar(DONO, "servico", {"nome": "S3", "duracao_min": 30, "preco_centavos": 1})


def test_agendar_guarda_copia_dos_dados_do_servico(agenda, salao):
    corte, _, ana = salao
    ag = agenda.agendar(DONO, pedido(corte, ana))
    assert (ag.servico_nome, ag.preco_centavos, ag.duracao_min) == ("Corte", 8000, 60)
    assert ag.cliente_telefone == "11988887777" and ag.id.startswith("2026-11-17_1000_")
    agenda.atualizar(DONO, "servico", corte.id, {"nome": "Outro", "duracao_min": 30, "preco_centavos": 1})
    assert agenda.agenda_do_dia(DONO, "2026-11-17")[0].servico_nome == "Corte"      # histórico intacto


def test_horarios_vizinhos_sao_aceitos_e_choque_e_recusado(agenda, salao):
    corte, unha, ana = salao
    agenda.agendar(DONO, pedido(corte, ana, "10:00"))                  # 10:00-11:00
    agenda.agendar(DONO, pedido(corte, ana, "11:00"))                  # encosta: pode
    agenda.agendar(DONO, pedido(corte, ana, "09:00"))                  # 09:00-10:00: pode
    for inicio in ("09:30", "10:00", "10:30", "10:45"):
        with pytest.raises(ErroValidacao, match="ocupado"):
            agenda.agendar(DONO, pedido(unha, ana, inicio))


def test_duas_profissionais_podem_atender_no_mesmo_horario(agenda, salao):
    corte, unha, ana = salao
    bia = agenda.criar(DONO, "profissional", {"nome": "Bia", "servicos": [corte.id]})
    agenda.agendar(DONO, pedido(corte, ana))
    agenda.agendar(DONO, pedido(corte, bia))
    assert len(agenda.agenda_do_dia(DONO, "2026-11-17")) == 2


@pytest.mark.parametrize("extra, trecho", [
    ({"data": "2026-11-16", "inicio": "09:30"}, "já passou"),          # hoje, antes de agora (10:00)
    ({"data": "2026-11-15"}, "já passou"),
    ({"data": "2026-11-22"}, "fora do expediente"),                    # domingo
    ({"inicio": "08:45"}, "fora do expediente"),
    ({"inicio": "18:30"}, "fora do expediente"),                       # 60 min passam das 19:00
    ({"inicio": "10:10"}, "fora do expediente"),                       # fora do passo de 15 min
    ({"inicio": "9h"}, "hora inválida"),
    ({"data": "amanhã"}, "data inválida"),
    ({"cliente_nome": ""}, "cliente_nome"),
    ({"cliente_telefone": "123"}, "DDD"),
])
def test_agendamentos_recusados(agenda, salao, extra, trecho):
    corte, _, ana = salao
    with pytest.raises(ErroValidacao, match=trecho):
        agenda.agendar(DONO, pedido(corte, ana, **extra))


def test_profissional_que_nao_faz_o_servico(agenda, salao):
    corte, unha, ana = salao
    bia = agenda.criar(DONO, "profissional", {"nome": "Bia", "servicos": [unha.id]})
    with pytest.raises(ErroValidacao, match="não faz"):
        agenda.agendar(DONO, pedido(corte, bia))


def test_ids_inventados(agenda, salao):
    corte, _, ana = salao
    with pytest.raises(NaoEncontrado):
        agenda.agendar(DONO, {**pedido(corte, ana), "servico_id": "deadbeef"})
    with pytest.raises(NaoEncontrado):
        agenda.agendar(DONO, {**pedido(corte, ana), "profissional_id": None})


def test_disponibilidade_reflete_os_agendamentos(agenda, salao):
    corte, unha, ana = salao
    antes = agenda.disponibilidade(DONO, "2026-11-17", corte.id, ana.id)
    assert antes[0] == "09:00" and "10:00" in antes
    agenda.agendar(DONO, pedido(corte, ana, "10:00"))
    depois = agenda.disponibilidade(DONO, "2026-11-17", corte.id, ana.id)
    assert "10:00" not in depois and "09:30" not in depois and "11:00" in depois
    assert "09:00" in depois and "09:15" not in depois
    assert agenda.disponibilidade(DONO, "2026-11-22", corte.id, ana.id) == []


def test_configuracao_muda_a_disponibilidade(agenda, salao):
    corte, _, ana = salao
    assert agenda.configuracao(DONO).abre == "09:00"
    agenda.salvar_configuracao(DONO, {"dias_abertos": [1], "abre": "13:00", "fecha": "15:00"})
    assert agenda.disponibilidade(DONO, "2026-11-17", corte.id, ana.id) == ["13:00", "13:15", "13:30", "13:45", "14:00"]
    assert agenda.disponibilidade(DONO, "2026-11-18", corte.id, ana.id) == []
    assert agenda.configuracao(OUTRO).abre == "09:00"                   # outro salão não mudou


def test_cancelar_libera_o_horario(agenda, salao):
    corte, _, ana = salao
    ag = agenda.agendar(DONO, pedido(corte, ana))
    assert agenda.cancelar(DONO, ag.id).id == ag.id
    assert agenda.agenda_do_dia(DONO, "2026-11-17") == []
    agenda.agendar(DONO, pedido(corte, ana))                            # volta a caber
    with pytest.raises(NaoEncontrado):
        agenda.cancelar(DONO, ag.id)


def test_cancelar_de_outro_salao_ou_id_estranho(agenda, salao):
    corte, _, ana = salao
    ag = agenda.agendar(DONO, pedido(corte, ana))
    for dono, id in ((OUTRO, ag.id), (DONO, "../x"), (DONO, ""), (DONO, None), (DONO, "2026-11-17_1000_zzzzzzzz")):
        with pytest.raises(NaoEncontrado):
            agenda.cancelar(dono, id)
    assert len(agenda.agenda_do_dia(DONO, "2026-11-17")) == 1


def test_agenda_do_dia_ordenada_por_hora(agenda, salao):
    corte, unha, ana = salao
    for inicio in ("15:00", "09:00", "11:30"):
        agenda.agendar(DONO, pedido(unha, ana, inicio))
    assert [a.inicio for a in agenda.agenda_do_dia(DONO, "2026-11-17")] == ["09:00", "11:30", "15:00"]


def test_reservas_simultaneas_no_mesmo_horario_so_uma_vence(agenda, salao):
    """Dispara várias reservas ao mesmo tempo para o mesmo horário: exatamente uma passa."""
    corte, _, ana = salao
    resultados = []

    def tentar():
        try:
            agenda.agendar(DONO, pedido(corte, ana, "14:00"))
            resultados.append("ok")
        except (ErroValidacao, ConflitoHorario):
            resultados.append("recusado")

    fios = [threading.Thread(target=tentar) for _ in range(8)]
    [f.start() for f in fios]
    [f.join() for f in fios]
    assert resultados.count("ok") == 1 and len(agenda.agenda_do_dia(DONO, "2026-11-17")) == 1
