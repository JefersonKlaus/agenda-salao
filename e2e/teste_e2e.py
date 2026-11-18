"""Abre o frontend num Chromium de verdade, conversa com a API de verdade (banco em memória)
e um Cognito simulado. Roda:  python e2e/teste_e2e.py"""
import json
import re
import threading
from datetime import datetime, timedelta

from playwright.sync_api import expect, sync_playwright

import servidor_local


def cognito(rota):
    """Primeiro acesso exige senha nova, como num usuário criado pelo administrador."""
    alvo = rota.request.headers["x-amz-target"].split(".")[-1]
    corpo = json.loads(rota.request.post_data)
    if alvo == "InitiateAuth" and corpo["AuthParameters"].get("PASSWORD") == "errada":
        return rota.fulfill(status=400, content_type="application/x-amz-json-1.1",
                            body=json.dumps({"__type": "NotAuthorizedException"}))
    if alvo == "InitiateAuth":
        resposta = {"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": "sessao-1"}
    else:
        resposta = {"AuthenticationResult": {"IdToken": "token-salao-1", "ExpiresIn": 3600, "RefreshToken": "r"}}
    rota.fulfill(status=200, content_type="application/x-amz-json-1.1", body=json.dumps(resposta))


def rodar():
    servidor_local.LOGIN_SIMULADO = False       # aqui o Cognito falso é o do próprio teste
    servidor = servidor_local.iniciar(8765)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    erros = []
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()
        pagina.on("pageerror", lambda e: erros.append(str(e)))
        pagina.on("console", lambda m: m.type == "error" and erros.append(m.text))
        pagina.on("dialog", lambda d: d.accept())
        pagina.route("https://cognito-idp.sa-east-1.amazonaws.com/", cognito)
        pagina.goto("http://127.0.0.1:8765/")

        # login: senha errada, depois primeiro acesso com senha nova
        pagina.fill("#l-email", "dona@salao.com")
        pagina.fill("#l-senha", "errada")
        pagina.click("text=Entrar")
        expect(pagina.locator(".toast.erro")).to_contain_text("incorretos")
        pagina.fill("#l-senha", "Senha-Forte-1")
        pagina.click("text=Entrar")
        expect(pagina.locator("text=Primeiro acesso")).to_be_visible()
        pagina.fill("#l-senha", "Outra-Senha-9")
        pagina.click("text=Definir senha")
        expect(pagina.locator("#menu button")).to_have_count(4)

        # serviço com nome malicioso: tem que aparecer como texto, sem executar nada
        pagina.click("nav >> text=Serviços")
        pagina.click("text=Adicionar")
        pagina.fill("#c-nome", "<img src=x onerror=window.__xss=1>Corte")
        pagina.select_option("#c-dur", "60")
        pagina.fill("#c-preco", "80,50")
        pagina.click("text=Salvar")
        expect(pagina.locator(".cartao strong")).to_have_text("<img src=x onerror=window.__xss=1>Corte")
        assert pagina.evaluate("window.__xss") is None

        # preço inválido não envia
        pagina.click("text=Adicionar")
        pagina.fill("#c-nome", "Escova")
        pagina.fill("#c-preco", "abc")
        pagina.click("text=Salvar")
        expect(pagina.locator(".toast.erro", has_text="Preço inválido")).to_be_visible()
        pagina.click("text=Voltar")

        pagina.click("nav >> text=Profissionais")
        pagina.click("text=Adicionar")
        pagina.fill("#c-nome", "Ana")
        pagina.locator("input[type=checkbox]").first.check()
        pagina.click("text=Salvar")
        expect(pagina.locator(".cartao")).to_contain_text("Ana")

        # abre todos os dias para o teste não depender do dia da semana
        pagina.click("nav >> text=Horários")
        for caixa in pagina.locator("input[type=checkbox]").all():
            caixa.check()
        pagina.click("text=Salvar")
        expect(pagina.locator(".toast", has_text="funcionamento salvo")).to_be_visible()

        # agendar amanhã às 10:00
        pagina.click("nav >> text=Agenda")
        pagina.click("[aria-label='Próximo dia']")
        pagina.click("text=Novo agendamento")
        pagina.select_option("#f-servico", index=1)
        pagina.select_option("#f-prof", index=1)
        expect(pagina.locator(".horarios button").first).to_have_text("09:00")
        pagina.click(".horarios button:text-is('10:00')")
        pagina.fill("#f-nome", "Maria")
        pagina.fill("#f-tel", "(11) 98888-7777")
        pagina.click("button:text-is('Agendar')")
        expect(pagina.locator(".cartao")).to_contain_text("10:00 – 11:00")
        expect(pagina.locator(".cartao")).to_contain_text("R$")

        # o horário ocupado não é mais oferecido, nem os que invadem o atendimento
        pagina.click("text=Novo agendamento")
        pagina.select_option("#f-servico", index=1)
        pagina.select_option("#f-prof", index=1)
        expect(pagina.locator(".horarios button").first).to_be_visible()
        horas = pagina.locator(".horarios button").all_inner_texts()
        assert "10:00" not in horas and "09:30" not in horas and "11:00" in horas and "09:00" in horas, horas
        pagina.click("text=Fechar")

        # cancelar libera
        pagina.click("button:text-is('Cancelar')")
        expect(pagina.locator("text=Nenhum agendamento")).to_be_visible()

        # sair e voltar ao login
        pagina.click("#sair")
        expect(pagina.locator("#l-email")).to_be_visible()
        navegador.close()
    servidor.shutdown()
    # o único erro de rede permitido é o 400 da senha errada, provocado de propósito no começo
    assert len(erros) == 1 and "400" in erros[0], erros
    print("e2e ok: login, cadastros, XSS, agendamento, conflito, cancelamento, sair")


if __name__ == "__main__":
    rodar()
