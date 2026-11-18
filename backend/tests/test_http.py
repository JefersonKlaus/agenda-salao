import base64
import json

import pytest

from agenda.agenda import Agenda
from agenda.http import MAX_CORPO, tratar
from agenda.repositorio_memoria import RepositorioMemoria
from conftest import AGORA


def chamar(agenda, metodo, caminho, corpo=None, query=None, dono="dono-a", base64_=False):
    evento = {"rawPath": caminho, "requestContext": {"http": {"method": metodo}},
              "queryStringParameters": query}
    if dono:
        evento["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": dono}}}
    if corpo is not None:
        texto = corpo if isinstance(corpo, str) else json.dumps(corpo)
        evento["body"] = base64.b64encode(texto.encode()).decode() if base64_ else texto
        evento["isBase64Encoded"] = base64_
    resposta = tratar(evento, agenda)
    return resposta["statusCode"], json.loads(resposta["body"]) if resposta["body"] else None


@pytest.fixture
def api():
    return Agenda(RepositorioMemoria(), lambda: AGORA)


def montar(api):
    _, corte = chamar(api, "POST", "/servicos", {"nome": "Corte", "duracao_min": 60, "preco_centavos": 8000})
    _, ana = chamar(api, "POST", "/profissionais", {"nome": "Ana", "servicos": [corte["id"]]})
    return corte, ana


def test_fluxo_completo(api):
    corte, ana = montar(api)
    assert chamar(api, "GET", "/servicos")[1][0]["nome"] == "Corte"
    status, horas = chamar(api, "GET", "/disponibilidade",
                           query={"data": "2026-11-17", "servico_id": corte["id"], "profissional_id": ana["id"]})
    assert status == 200 and horas[0] == "09:00"
    pedido = {"data": "2026-11-17", "inicio": "10:00", "servico_id": corte["id"],
              "profissional_id": ana["id"], "cliente_nome": "Maria", "cliente_telefone": ""}
    status, ag = chamar(api, "POST", "/agendamentos", pedido)
    assert status == 201 and ag["servico_nome"] == "Corte"
    assert chamar(api, "POST", "/agendamentos", pedido)[0] == 400
    assert len(chamar(api, "GET", "/agendamentos", query={"data": "2026-11-17"})[1]) == 1
    assert chamar(api, "DELETE", f"/agendamentos/{ag['id']}") == (204, None)
    assert chamar(api, "DELETE", f"/agendamentos/{ag['id']}")[0] == 404
    assert chamar(api, "PUT", "/configuracao", {"dias_abertos": [1], "abre": "08:00", "fecha": "12:00"})[0] == 200
    assert chamar(api, "GET", "/configuracao")[1]["abre"] == "08:00"


def test_sem_login_e_401_e_nao_toca_no_banco(api):
    assert chamar(api, "GET", "/servicos", dono=None)[0] == 401
    assert chamar(api, "GET", "/servicos", dono="")[0] == 401
    assert chamar(api, "POST", "/servicos", {"nome": "x"}, dono=None)[0] == 401


def test_o_dono_vem_do_token_e_nao_do_corpo(api):
    chamar(api, "POST", "/servicos", {"nome": "Corte", "duracao_min": 30, "preco_centavos": 1,
                                      "dono": "dono-b", "PK": "SALAO#dono-b"})
    assert chamar(api, "GET", "/servicos", dono="dono-b")[1] == []
    assert len(chamar(api, "GET", "/servicos", dono="dono-a")[1]) == 1


def test_atualizar_e_remover_servico(api):
    corte, _ = montar(api)
    status, novo = chamar(api, "PUT", f"/servicos/{corte['id']}", {"nome": "Novo", "duracao_min": 30, "preco_centavos": 5})
    assert status == 200 and novo["nome"] == "Novo"
    assert chamar(api, "DELETE", f"/servicos/{corte['id']}") == (204, None)
    assert chamar(api, "DELETE", f"/servicos/{corte['id']}")[0] == 404


@pytest.mark.parametrize("metodo, caminho, esperado", [
    ("GET", "/nada", 404), ("PATCH", "/servicos", 405), ("GET", "/servicos/xyz", 404),
    ("GET", "/servicos/", 200), ("DELETE", "/servicos/ZZZZZZZZ", 404),
    ("GET", "/agendamentos", 400),                                # falta ?data=
])
def test_rotas_estranhas(api, metodo, caminho, esperado):
    assert chamar(api, metodo, caminho)[0] == esperado


@pytest.mark.parametrize("corpo", ["{quebrado", "[1, 2]", '"texto"', "x" * (MAX_CORPO + 1)])
def test_corpo_ruim_vira_400(api, corpo):
    assert chamar(api, "POST", "/servicos", corpo)[0] == 400


def test_corpo_em_base64(api):
    status, _ = chamar(api, "POST", "/servicos", {"nome": "Corte", "duracao_min": 30, "preco_centavos": 1},
                       base64_=True)
    assert status == 201


def test_erro_inesperado_nao_vaza_detalhes(api, caplog):
    class Quebrado(RepositorioMemoria):
        def listar(self, dono, tipo):
            raise RuntimeError("senha-do-banco")
    status, corpo = chamar(Agenda(Quebrado(), lambda: AGORA), "GET", "/servicos")
    assert status == 500 and "senha" not in json.dumps(corpo)
    assert "senha-do-banco" in caplog.text                        # fica só no log
