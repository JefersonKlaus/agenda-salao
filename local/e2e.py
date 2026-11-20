"""Opens the frontend in a real Chromium, talking to the real API (in-memory database).
Run:  python local/e2e.py

Two passes: `run()` goes through the login screen with a simulated Cognito (like the deployed app);
`run_without_login()` checks the local server's default mode, which has no login at all.

The texts used in the selectors ("Entrar", "Salvar", ...) are the app's labels, which are in Portuguese."""
import json
import re
import threading
from datetime import date, timedelta

from playwright.sync_api import expect, sync_playwright

import server as local_server
from agenda_core.adapters.clock import salon_now    # importable once the server has set up the path
from agenda_core.domain.models import Professional, Service

SALON_TIME_ZONE = "America/Sao_Paulo"           # the browser runs where the salon is, like its devices


def cognito(route):
    """First access requires a new password, like a user created by the administrator."""
    target = route.request.headers["x-amz-target"].split(".")[-1]
    body = json.loads(route.request.post_data)
    if target == "InitiateAuth" and body["AuthParameters"].get("PASSWORD") == "wrong":
        return route.fulfill(status=400, content_type="application/x-amz-json-1.1",
                             body=json.dumps({"__type": "NotAuthorizedException"}))
    if target == "InitiateAuth":
        response = {"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": "session-1"}
    else:
        response = {"AuthenticationResult": {"IdToken": "token-salon-1", "ExpiresIn": 3600, "RefreshToken": "r"}}
    route.fulfill(status=200, content_type="application/x-amz-json-1.1", body=json.dumps(response))


def run():
    tomorrow = (salon_now().date() + timedelta(days=1)).isoformat()
    server = local_server.start(8765, require_login=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("dialog", lambda d: d.accept())
        page.route("https://cognito-idp.sa-east-1.amazonaws.com/", cognito)
        page.goto("http://127.0.0.1:8765/")

        # login: wrong password, then first access with a new password
        page.fill("#l-email", "owner@salon.com")
        page.fill("#l-password", "wrong")
        page.click("text=Entrar")
        expect(page.locator(".toast.error")).to_contain_text("incorretos")
        page.fill("#l-password", "Strong-Password-1")
        page.click("text=Entrar")
        expect(page.locator("text=Primeiro acesso")).to_be_visible()
        page.fill("#l-password", "Another-Password-9")
        page.click("text=Definir senha")
        expect(page.locator("#menu button")).to_have_count(4)

        # service with a malicious name: it must show up as text, without running anything
        page.click("nav >> text=Serviços")
        page.click("text=Adicionar")
        page.fill("#c-name", "<img src=x onerror=window.__xss=1>Haircut")
        page.select_option("#c-duration", "60")
        page.fill("#c-price", "80,50")
        page.click("text=Salvar")
        expect(page.locator(".card strong")).to_have_text("<img src=x onerror=window.__xss=1>Haircut")
        assert page.evaluate("window.__xss") is None

        # an invalid price is not sent
        page.click("text=Adicionar")
        page.fill("#c-name", "Blow-dry")
        page.fill("#c-price", "abc")
        page.click("text=Salvar")
        expect(page.locator(".toast.error", has_text="Preço inválido")).to_be_visible()
        page.fill("#c-price", "50,00")
        page.click("text=Salvar")

        # disable a service: it stays listed, marked, and is not offered for new appointments
        blow_dry = page.locator(".card", has_text="Blow-dry")
        blow_dry.locator("text=Desativar").click()
        expect(blow_dry.locator(".badge")).to_have_text("Desativado")
        expect(blow_dry.locator("button", has_text="Ativar")).to_be_visible()

        # the salon's window (Configurações): open every day, 09:00-19:00
        page.click("nav >> text=Configurações")
        expect(page.locator("h1")).to_have_text("Configurações")
        expect(page.locator("input[type=checkbox]")).to_have_count(7)      # wait for the screen before .all()
        for checkbox in page.locator("input[type=checkbox]").all():
            checkbox.check()
        page.click("text=Salvar")
        expect(page.locator(".toast", has_text="funcionamento salvo")).to_be_visible()

        # Ana, Bia and Carla work 10:00-14:00; Carla does not work tomorrow's weekday
        tomorrow_weekday = date.fromisoformat(tomorrow).weekday()
        page.click("nav >> text=Profissionais")
        for name in ("Ana", "Bia", "Carla"):
            page.click("text=Adicionar")
            page.fill("#c-name", name)
            page.locator("input[type=checkbox]").first.check()          # the first checkbox is the service
            for day, row in enumerate(page.locator(".work-row").all()):
                works = not (name == "Carla" and day == tomorrow_weekday)
                row.locator("input[type=checkbox]").set_checked(works)
                if works:
                    row.locator("input[type=time]").first.fill("10:00")
                    row.locator("input[type=time]").last.fill("14:00")
            if name == "Carla":                                         # outside the salon's window: refused
                day_row = page.locator(".work-row").nth((tomorrow_weekday + 1) % 7)
                day_row.locator("input[type=time]").first.fill("08:00")
                page.click("text=Salvar")
                expect(page.locator(".toast.error", has_text="fora do horário do salão (09:00–19:00)")).to_be_visible()
                day_row.locator("input[type=time]").first.fill("10:00")
            page.click("text=Salvar")
            expect(page.locator(".card", has_text=name)).to_contain_text("10:00–14:00")
        expect(page.locator(".card", has_text="Ana")).to_contain_text("Seg a Dom 10:00–14:00")

        # the agenda opens in the week view; tomorrow's day view only has who works tomorrow
        page.click("nav >> text=Agenda")
        expect(page.locator(".segmented button[aria-pressed=true]")).to_have_text("Semana")
        expect(page.locator(".cal-filter .pill")).to_have_text(["Todas", "Ana", "Bia", "Carla"])
        page.click(".segmented >> text=Dia")
        page.click("[aria-label='Próximo dia']")
        expect(page.locator(".tg-person")).to_have_text(["Ana", "Bia"])         # not Carla
        ana_column = page.locator(".tg-col[data-professional]").nth(0)
        bia_column = page.locator(".tg-col[data-professional]").nth(1)
        expect(ana_column.locator(".tg-off")).to_have_count(2)             # 09:00-10:00 and 14:00-19:00

        # book Ana at 10:00 from the "Novo agendamento" button (the disabled service is not offered)
        page.click("text=Novo agendamento")
        expect(page.locator("#f-date")).to_have_value(tomorrow)
        expect(page.locator("#f-service option")).to_have_count(2)         # "Escolha..." + the active one
        page.select_option("#f-service", index=1)
        page.select_option("#f-professional", label="Ana")
        expect(page.locator(".slots button").first).to_have_text("10:00")    # her hours, not the salon's 09:00
        page.click(".slots button:text-is('10:00')")
        page.fill("#f-name", "Maria")
        page.fill("#f-phone", "(11) 98888-7777")
        page.click("button:text-is('Agendar')")
        expect(ana_column.locator(".tg-event")).to_contain_text("10:00 Maria")
        expect(page.locator("dialog")).to_have_count(0)

        # click Bia's empty 12:00 spot: books with her; 10:00 is free for her even though Ana is busy
        bia_column.click(position={"x": 40, "y": 3 * 48 + 6})              # grid starts at 09:00, 48 px per hour
        page.select_option("#f-service", index=1)
        expect(page.locator("#f-professional option:checked")).to_have_text("Bia")
        expect(page.locator(".slots button[aria-pressed=true]")).to_have_text("12:00")
        times = page.locator(".slots button").all_inner_texts()
        assert "10:00" in times and "09:00" not in times and "13:15" not in times, times
        page.fill("#f-name", "Joana")
        page.click("button:text-is('Agendar')")
        expect(bia_column.locator(".tg-event")).to_contain_text("12:00 Joana")

        # Ana's empty 11:00 spot: the taken and overlapping times are not offered
        ana_column.click(position={"x": 40, "y": 2 * 48 + 6})
        page.select_option("#f-service", index=1)
        expect(page.locator("#f-professional option:checked")).to_have_text("Ana")
        expect(page.locator(".slots button[aria-pressed=true]")).to_have_text("11:00")
        times = page.locator(".slots button").all_inner_texts()
        for absent in ("10:00", "10:30", "09:00", "13:15"):
            assert absent not in times, (absent, times)
        assert "13:00" in times, times
        page.fill("#f-name", "Luana")
        page.click("button:text-is('Agendar')")
        expect(page.locator(".tg-event")).to_have_count(3)

        # Bia is sick tomorrow: her 12:00 appointment is flagged, to be given to someone else
        page.click(".cal-controls >> text=Ausência")
        page.select_option("#o-professional", label="Bia")
        expect(page.locator("#o-first")).to_have_value(tomorrow)
        page.fill("#o-reason", "Doente")
        page.click("text=Salvar ausência")
        expect(page.locator(".toast.error", has_text="1 agendamento(s)")).to_be_visible()
        expect(bia_column.locator(".tg-event.conflict")).to_contain_text("12:00 Joana")
        expect(page.locator(".tg-allday .away-chip")).to_contain_text("Ausente · Doente")

        # give Joana's appointment to Ana (free at 12:00): Bia, away all day with nothing left, disappears
        bia_column.locator(".tg-event").click()
        expect(page.locator("dialog .warning")).to_contain_text("ausente")
        page.select_option("#a-professional", label="Ana")
        page.click("dialog button:text-is('Trocar')")
        expect(page.locator(".toast", has_text="passado para Ana")).to_be_visible()
        expect(page.locator(".tg-person")).to_have_text(["Ana"])
        expect(page.locator(".away-line")).to_contain_text("Bia · Doente")          # said above the grid
        expect(page.locator(".tg-event")).to_have_count(3)
        expect(page.locator(".tg-event.conflict")).to_have_count(0)

        # the filter: only Ana's agenda, then everybody again
        page.click(".cal-filter >> text=Ana")
        expect(page.locator(".tg-col")).to_have_count(1)
        expect(page.locator(".tg-event")).to_have_count(3)
        page.click(".cal-filter >> text=Todas")

        # week view: the absence is in the all-day strip; tomorrow is free while Ana works
        page.click(".segmented >> text=Semana")
        expect(page.locator(".tg-col")).to_have_count(7)
        expect(page.locator(".tg-event")).to_have_count(3)
        expect(page.locator(f".tg-col[data-date='{tomorrow}'] .tg-off")).to_have_count(2)
        chip = page.locator(".tg-allday .away-chip", has_text="Bia ausente")
        expect(chip).to_contain_text("Doente")

        # removing the absence brings Bia back
        chip.click()
        page.click("dialog >> text=Remover ausência")
        expect(page.locator(".away-chip")).to_have_count(0)
        page.click(".segmented >> text=Dia")
        expect(page.locator(".tg-person")).to_have_text(["Ana", "Bia"])
        page.click(".segmented >> text=Semana")

        # month view: same appointments, tomorrow not marked closed
        page.click(".segmented >> text=Mês")
        expect(page.locator(".mv-chip")).to_have_count(3)
        expect(page.locator(f".mv-cell[data-date='{tomorrow}']")).not_to_have_class(re.compile("closed"))

        # open an appointment and cancel it: it frees the slot
        page.locator(".mv-chip", has_text="10:00 Maria").click()
        expect(page.locator("dialog")).to_contain_text("11988887777")
        page.click("dialog >> text=Cancelar agendamento")
        expect(page.locator(".mv-chip")).to_have_count(2)
        expect(page.locator(".mv-chip")).to_have_text(["11:00 Luana", "12:00 Joana"])   # name hidden on phones

        # phone-sized screen: the menu is a drawer behind the ☰ button
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator("#menu-toggle")).to_be_visible()
        expect(page.locator("#sidebar")).not_to_be_visible()
        page.click("#menu-toggle")
        expect(page.locator("#sidebar")).to_be_visible()
        expect(page.locator("#menu-toggle")).to_have_attribute("aria-expanded", "true")
        page.click("nav >> text=Serviços")
        expect(page.locator("#sidebar")).not_to_be_visible()             # choosing a page closes it
        expect(page.locator("h1")).to_have_text("Serviços")
        page.click("#menu-toggle")
        page.keyboard.press("Escape")
        expect(page.locator("#sidebar")).not_to_be_visible()

        # log out (from the drawer) and go back to the login screen
        page.click("#menu-toggle")
        page.click("#logout")
        expect(page.locator("#l-email")).to_be_visible()
        browser.close()
    server.shutdown()
    # the only network errors allowed are the two 400s triggered on purpose: the wrong password and
    # Carla's hours outside the salon's window
    assert len(errors) == 2 and all("400" in e for e in errors), errors
    print("e2e ok: login, catalog, disabled service, salon window, work hours, XSS, day/week/month views, "
          "columns of who works, filter, booking, conflict, absence, change professional, cancellation, "
          "mobile sidebar, logout")


def run_without_login():
    """The local server's default mode: no Cognito and no login screen, straight to the agenda."""
    server = local_server.start(8766)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors, outside_requests = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("request", lambda r: r.url.startswith("http://127.0.0.1:8766/") or outside_requests.append(r.url))
        page.goto("http://127.0.0.1:8766/")

        expect(page.locator(".segmented button[aria-pressed=true]")).to_have_text("Semana")
        expect(page.locator("#l-email")).to_have_count(0)
        expect(page.locator("#local-mode")).to_have_text("Modo local, sem login (gerente)")
        expect(page.locator("#logout")).to_have_count(0)

        page.click("nav >> text=Serviços")
        page.click("text=Adicionar")
        page.fill("#c-name", "Corte")
        page.fill("#c-price", "80,00")
        page.click("text=Salvar")
        page.click("nav >> text=Configurações")                         # the salon: every day, all day
        expect(page.locator("input[type=checkbox]")).to_have_count(7)      # wait for the screen before .all()
        for checkbox in page.locator("input[type=checkbox]").all():
            checkbox.check()
        page.fill("#s-opens", "00:00")
        page.fill("#s-closes", "23:45")
        page.click("text=Salvar")
        expect(page.locator(".toast", has_text="funcionamento salvo")).to_be_visible()
        page.click("nav >> text=Profissionais")
        page.click("text=Adicionar")
        page.fill("#c-name", "Ana")
        page.locator("input[type=checkbox]").first.check()
        for row in page.locator(".work-row").all():                     # works every day, all day
            row.locator("input[type=checkbox]").check()
            row.locator("input[type=time]").first.fill("00:00")
            row.locator("input[type=time]").last.fill("23:45")
        page.click("text=Salvar")
        expect(page.locator(".card", has_text="Ana")).to_be_visible()

        # The server uses the salon's clock (Brasília), not the machine's: today's first free time is the
        # next quarter hour after the current Brasília time. (A UTC machine once made it 3 hours later.)
        def next_free_now():
            now = salon_now()
            first = ((now.hour * 60 + now.minute) // 15 + 1) * 15
            return f"{first // 60:02d}:{first % 60:02d}" if first + 60 <= 23 * 60 + 45 else None
        expected = next_free_now()
        times = page.evaluate("""async (day) => {
            const get = (path) => fetch("/api" + path).then((r) => r.json());
            const [[service], [professional]] = await Promise.all([get("/services"), get("/professionals")]);
            return get(`/availability?date=${day}&service_id=${service.id}&professional_id=${professional.id}`);
        }""", salon_now().date().isoformat())
        if expected and next_free_now():                                # skipped in the last hour of the day
            assert times[0] in (expected, next_free_now()), (times[:3], expected)

        def open_tomorrow():                                            # day view: works on any day of the week
            page.click(".segmented >> text=Dia")
            page.click("[aria-label='Próximo dia']")

        page.click("nav >> text=Agenda")
        open_tomorrow()
        page.click("text=Novo agendamento")
        page.select_option("#f-service", index=1)
        page.select_option("#f-professional", index=1)
        page.click(".slots button:text-is('10:00')")
        page.fill("#f-name", "Maria")
        page.click("button:text-is('Agendar')")
        expect(page.locator(".tg-event")).to_contain_text("10:00 Maria")

        page.reload()                                                   # data stays while the server runs
        open_tomorrow()
        expect(page.locator(".tg-event")).to_contain_text("10:00 Maria")
        browser.close()
    server.shutdown()
    assert not errors, errors
    assert not outside_requests, outside_requests                      # nothing went to Cognito (or anywhere)
    print("e2e ok (local server without login): opens the agenda directly, saves and books in memory")


def run_now_marker():
    """The red "now" line with the time: Brasília time (even on a device in another time zone), keeps
    moving while the agenda is open, and moves to the next day after midnight. Uses a fake clock."""
    server = local_server.start(8767)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id="Asia/Tokyo")              # far from Brasília on purpose
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.clock.install(time="2026-11-18T13:07:00Z")                  # Wednesday 10:07 in Brasília
        page.goto("http://127.0.0.1:8767/")
        label, line = page.locator(".tg-now-label"), page.locator(".tg-now")
        top = lambda: float(line.evaluate("el => el.style.top").removesuffix("px"))   # noqa: E731

        expect(label).to_have_text("10:07")                              # not Tokyo's 22:07, not UTC's 13:07
        expect(page.locator(".tg-col[data-date='2026-11-18'] .tg-now")).to_have_count(1)
        assert top() == (10 * 60 + 7 - 9 * 60) * 48 / 60, top()            # grid starts at 09:00, 48 px per hour

        page.clock.fast_forward("05:00")                                 # five minutes later
        expect(label).to_have_text("10:12")
        assert top() == (10 * 60 + 12 - 9 * 60) * 48 / 60, top()

        page.clock.fast_forward("13:53:00")                              # 00:05 on Thursday, in Brasília
        expect(page.locator(".tg-day-head.today .tg-date")).to_have_text("19")
        expect(page.locator(".tg-col[data-date='2026-11-19'] .tg-now")).to_have_count(1)
        expect(line).to_be_hidden()                                      # 00:05 is above the 09:00-19:00 grid
        expect(label).to_be_hidden()
        browser.close()
    server.shutdown()
    assert not errors, errors
    print("e2e ok (now marker): Brasília time on a Tokyo device, moves every tick, follows midnight")


def run_layout():
    """Empty screens show a picture and how to start; lists and forms fill the width between their
    limits (760 px at most) instead of shrinking to their content; the agenda uses all the width."""
    server = local_server.start(8768)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    width_of = "el => Math.round(el.getBoundingClientRect().width)"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto("http://127.0.0.1:8768/")
        expect(page.locator(".tg")).to_be_visible()
        content_width = 1440 - 240                                        # the screen minus the sidebar

        # the agenda fills everything next to the sidebar (minus main's 16 px padding on each side)
        assert page.locator(".tg").evaluate(width_of) == content_width - 32

        def empty_state(screen, heading):
            page.click(f"nav >> text={screen}")
            card = page.locator(".empty-state")
            expect(card.locator("h2")).to_have_text(heading)
            expect(page.locator("main .row button")).to_have_count(0)     # the card's button is the way to start
            image = card.locator("img")
            expect(image).to_be_visible()
            assert image.evaluate("img => img.complete && img.naturalWidth > 0"), "the picture did not load"
            assert card.evaluate(width_of) == 760 - 32, card.evaluate(width_of)
            return card

        card = empty_state("Profissionais", "Nenhuma profissional cadastrada")
        expect(card).to_contain_text("cadastre os serviços primeiro")     # no services yet: a hint
        empty_state("Serviços", "Nenhum serviço cadastrado").locator("button").click()

        # the form is as wide as the page allows, even with only three short fields
        expect(page.locator("#c-name")).to_be_visible()
        assert page.locator(".card").evaluate(width_of) == 760 - 32
        page.fill("#c-name", "Corte")
        page.fill("#c-price", "80,00")
        page.click("text=Salvar")
        listed = page.locator(".card", has_text="Corte")                   # wait for the list, not the old form
        expect(listed.locator(".actions")).to_be_visible()
        expect(page.locator(".empty-state")).to_have_count(0)
        assert listed.evaluate(width_of) == 760 - 32
        expect(page.locator("main .row button", has_text="Adicionar")).to_be_visible()

        page.click("nav >> text=Profissionais")
        expect(page.locator(".empty-state")).not_to_contain_text("cadastre os serviços primeiro")

        # a wide screen: the agenda grows with it, the other pages stop at 760 px
        page.set_viewport_size({"width": 1920, "height": 900})
        page.click("nav >> text=Agenda")
        expect(page.locator(".tg")).to_be_visible()
        assert page.locator(".tg").evaluate(width_of) == 1920 - 240 - 32
        page.click("nav >> text=Serviços")
        expect(page.locator(".card")).to_have_count(1)
        assert page.locator(".card").evaluate(width_of) == 760 - 32

        # a phone: everything is as wide as the screen
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator(".card")).to_have_count(1)
        assert page.locator(".card").evaluate(width_of) == 390 - 32
        browser.close()
    server.shutdown()
    assert not errors, errors
    print("e2e ok (layout): empty screens with a picture, cards 760 px at most and full width on phones, full-width agenda")


def run_as_employee():
    """`local/server.py employee`: sees the agenda and the catalog, but cannot change the catalog or the salon."""
    server = local_server.start(8769, role="employee")
    service = Service.from_input({"name": "Corte", "duration_min": 60, "price_cents": 8000})
    server.deps.repo.save("local-salon", "service", service)
    server.deps.repo.save("local-salon", "professional", Professional.from_input({"name": "Ana", "services": [service.id]}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:8769/")

        expect(page.locator("#local-mode")).to_have_text("Modo local, sem login (funcionária)")
        expect(page.locator("nav button")).to_have_text(["Agenda", "Serviços", "Profissionais"])
        for screen, name in (("Serviços", "Corte"), ("Profissionais", "Ana")):
            page.click(f"nav >> text={screen}")
            expect(page.locator(".card", has_text=name)).to_be_visible()
            expect(page.locator("main button")).to_have_count(0)        # no Adicionar / Editar / Excluir
        status = page.evaluate("""() => fetch("/api/services", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: "Cor", duration_min: 60, price_cents: 1 }) }).then((r) => r.status)""")
        assert status == 403, status                                    # the API refuses it too
        browser.close()
    server.shutdown()
    assert not errors, errors
    print("e2e ok (employee): no Configurações, read-only catalog, API answers 403")


if __name__ == "__main__":
    run()
    run_without_login()
    run_as_employee()
    run_now_marker()
    run_layout()
