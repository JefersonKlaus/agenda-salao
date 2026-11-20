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


def url_of(server):
    """Each test's server listens on a free port the system picked (start(0)): it never collides with a
    `python dev.py serve` that is running, nor with another test."""
    return f"http://127.0.0.1:{server.server_address[1]}/"


def row_action(page, row, action):
    """A list row's actions are in its "⋮" menu: open it, then choose."""
    row.locator(".kebab").click()
    page.locator(".menu-list:not([hidden]) [role=menuitem]", has_text=action).click()


def row_actions(page, row):
    """The names in a row's "⋮" menu (it is closed again afterwards)."""
    row.locator(".kebab").click()
    names = page.locator(".menu-list:not([hidden]) [role=menuitem]").all_inner_texts()
    page.keyboard.press("Escape")
    return names


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
    server = local_server.start(0, require_login=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("dialog", lambda d: d.accept())
        page.route("https://cognito-idp.sa-east-1.amazonaws.com/", cognito)
        page.goto(url_of(server))

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
        expect(page.locator("#menu button")).to_have_count(5)            # Agenda, Clientes, Serviços, Profissionais, Financeiro

        # service with a malicious name: it must show up as text, without running anything
        page.click("nav >> text=Serviços")
        page.click("text=Adicionar")
        page.fill("#c-name", "<img src=x onerror=window.__xss=1>Haircut")
        page.select_option("#c-duration", "60")
        page.fill("#c-price", "80,50")
        page.click("text=Salvar")
        expect(page.locator(".list-item strong")).to_have_text("<img src=x onerror=window.__xss=1>Haircut")
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
        blow_dry = page.locator(".list-item", has_text="Blow-dry")
        row_action(page, blow_dry, "Desativar")
        expect(blow_dry.locator(".badge")).to_have_text("Desativado")
        assert row_actions(page, blow_dry) == ["Editar", "Ativar", "Excluir"]

        # the salon's hours (Configurações › Funcionamento): open every day, 09:00-19:00 (each day has its own row)
        page.click("nav >> text=Funcionamento")
        expect(page.locator("h1")).to_have_text("Funcionamento do salão")
        expect(page.locator(".work-row")).to_have_count(7)                  # wait for the screen before .all()
        for row in page.locator(".work-row").all():
            row.locator("input[type=checkbox]").check()
            expect(row.locator("input[type=time]").first).to_have_value("09:00")
            expect(row.locator("input[type=time]").last).to_have_value("19:00")
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
            expect(page.locator(".list-item", has_text=name)).to_contain_text("10:00–14:00")
        expect(page.locator(".list-item", has_text="Ana")).to_contain_text("Seg a Dom 10:00–14:00")

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
        # nobody works before 10:00 or after 14:00 while the salon is open: yellow, with a note
        expect(ana_column.locator(".tg-gap")).to_have_count(2)
        expect(ana_column.locator(".tg-gap").first).to_contain_text("Sem profissional atendendo")

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
        page.fill("#f-phone", "(11) 97777-6666")                     # a new client: registered on booking
        expect(page.locator(".client-note")).to_have_text("Cliente nova: é cadastrada ao agendar.")
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
        page.fill("#f-phone", "(11) 95555-4444")
        page.fill("#f-name", "Luana")
        page.click("button:text-is('Agendar')")
        expect(page.locator(".tg-event")).to_have_count(3)

        # Bia is sick tomorrow: her 12:00 appointment is flagged, to be given to someone else
        page.click(".cal-controls >> text=Ausência")
        page.select_option("#o-professional", label="Bia")
        expect(page.locator("#o-first")).to_have_value(tomorrow)
        page.click(".chips >> text=Doença")
        page.fill("#o-reason", "Gripe")
        page.click("text=Salvar ausência")
        expect(page.locator(".toast.error", has_text="1 agendamento(s)")).to_be_visible()
        expect(bia_column.locator(".tg-event.conflict")).to_contain_text("12:00 Joana")
        expect(page.locator(".tg-allday .away-chip")).to_contain_text("Ausente · Doença · Gripe")

        # give Joana's appointment to Ana (free at 12:00): Bia, away all day with nothing left, disappears
        bia_column.locator(".tg-event").click()
        expect(page.locator("dialog .warning")).to_contain_text("ausente")
        page.select_option("#a-professional", label="Ana")
        page.click("dialog button:text-is('Trocar')")
        expect(page.locator(".toast", has_text="passado para Ana")).to_be_visible()
        expect(page.locator(".tg-person")).to_have_text(["Ana"])
        expect(page.locator(".away-line")).to_contain_text("Bia · Doença · Gripe")          # said above the grid
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
        expect(chip).to_contain_text("Doença")

        # removing the absence brings Bia back
        chip.click()
        page.click("dialog >> text=Remover ausência")
        expect(page.locator(".away-chip")).to_have_count(0)
        page.click(".segmented >> text=Dia")
        expect(page.locator(".tg-person")).to_have_text(["Ana", "Bia"])

        # the filter picks one, some or all: each name turns on and off
        page.click(".cal-filter >> text=Bia")
        expect(page.locator(".tg-col")).to_have_count(1)                     # just Bia: her own agenda
        page.click(".cal-filter >> text=Ana")
        expect(page.locator(".tg-person")).to_have_text(["Ana", "Bia"])
        expect(page.locator(".cal-filter .pill[aria-pressed=true]")).to_have_text(["Ana", "Bia"])
        expect(page.locator(".cal-filter")).to_contain_text("2 de 3")
        page.click(".cal-filter >> text=Carla")                               # all three: the same as "Todas"
        expect(page.locator(".cal-filter .pill[aria-pressed=true]")).to_have_text(["Todas"])
        page.click(".cal-filter >> text=Carla")                               # Carla alone: she does not work today
        expect(page.locator(".tg-col")).to_have_count(1)
        page.click(".cal-filter >> text=Todas")
        expect(page.locator(".tg-person")).to_have_text(["Ana", "Bia"])
        page.click(".segmented >> text=Semana")

        # month view: same appointments, tomorrow not marked closed
        page.click(".segmented >> text=Mês")
        expect(page.locator(".mv-chip")).to_have_count(3)
        expect(page.locator(f".mv-cell[data-date='{tomorrow}']")).not_to_have_class(re.compile("closed"))

        # open an appointment and cancel it: it frees the slot
        page.locator(".mv-chip", has_text="10:00 Maria").click()
        expect(page.locator("dialog")).to_contain_text("(11) 98888-7777")      # shown formatted
        page.click("dialog >> text=Cancelar agendamento")
        expect(page.locator(".mv-chip")).to_have_count(2)
        expect(page.locator(".mv-chip")).to_have_text([re.compile("11:00 Luana$"), re.compile("12:00 Joana$")])  # name hidden on phones
        expect(page.locator(".mv-chip .pay.due")).to_have_count(2)        # tomorrow, not paid yet: gray R$

        # phone-sized screen: the menu is a drawer behind the ☰ button
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator("#menu-toggle")).to_be_visible()
        expect(page.locator("#sidebar")).not_to_be_visible()
        page.click("#menu-toggle")
        expect(page.locator("#sidebar")).to_be_visible()
        expect(page.locator("#menu-toggle")).to_have_attribute("aria-expanded", "true")
        page.click("nav >> text=Serviços")
        expect(page.locator("#sidebar")).not_to_be_visible()             # choosing a page closes it
        expect(page.locator("h1")).to_have_text(re.compile(r"^Serviços \(\d+\)$"))   # with how many there are
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
    server = local_server.start(0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors, outside_requests = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("request", lambda r: r.url.startswith(url_of(server)) or outside_requests.append(r.url))
        page.goto(url_of(server))

        expect(page.locator(".segmented button[aria-pressed=true]")).to_have_text("Semana")
        expect(page.locator("#l-email")).to_have_count(0)
        expect(page.locator("#local-mode")).to_have_text("Modo local, sem login (gerente)")
        expect(page.locator("#logout")).to_have_count(0)

        page.click("nav >> text=Serviços")
        page.click("text=Adicionar")
        page.fill("#c-name", "Corte")
        page.fill("#c-price", "80,00")
        page.click("text=Salvar")
        page.click("nav >> text=Funcionamento")                         # the salon: every day, all day
        expect(page.locator(".work-row")).to_have_count(7)                  # wait for the screen before .all()
        for row in page.locator(".work-row").all():
            row.locator("input[type=checkbox]").check()
            row.locator("input[type=time]").first.fill("00:00")
            row.locator("input[type=time]").last.fill("23:45")
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
        expect(page.locator(".list-item", has_text="Ana")).to_be_visible()
        expect(page.locator(".coverage-warning")).to_have_count(0)        # she covers every open hour

        # Ana stops working on Mondays: the salon is open with nobody there, so both screens warn
        row_action(page, page.locator(".list-item", has_text="Ana"), "Editar")
        page.locator(".work-row").first.locator("input[type=checkbox]").uncheck()
        page.click("text=Salvar")
        expect(page.locator(".coverage-warning")).to_contain_text("Segunda: 00:00–23:45")
        page.click("nav >> text=Funcionamento")
        expect(page.locator(".coverage-warning")).to_contain_text("Segunda: 00:00–23:45")
        page.click("nav >> text=Profissionais")                         # she works Mondays again: no warning
        row_action(page, page.locator(".list-item", has_text="Ana"), "Editar")
        page.locator(".work-row").first.locator("input[type=checkbox]").check()   # starts at the salon's hours
        page.click("text=Salvar")
        expect(page.locator(".list-item", has_text="Ana")).to_be_visible()
        expect(page.locator(".coverage-warning")).to_have_count(0)

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
        expect(page.locator("button:text-is('Agendar')")).to_be_disabled()   # the phone is required: her key
        page.fill("#f-phone", "(11) 98888-7777")
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
    moving while the agenda is open, and moves to the next day after midnight. Uses a fake clock.
    As an employee: no click on the grid opens the booking (only the manager books)."""
    server = local_server.start(0, role="employee")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id="Asia/Tokyo")              # far from Brasília on purpose
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.clock.install(time="2026-11-18T13:07:00Z")                  # Wednesday 10:07 in Brasília
        page.goto(url_of(server))
        label, line = page.locator(".tg-now-label"), page.locator(".tg-now")
        top = lambda: float(line.evaluate("el => el.style.top").removesuffix("px"))   # noqa: E731

        expect(label).to_have_text("10:07")                              # not Tokyo's 22:07, not UTC's 13:07
        expect(page.locator(".tg-col[data-date='2026-11-18'] .tg-now")).to_have_count(1)
        assert top() == (10 * 60 + 7 - 9 * 60) * 48 / 60, top()            # grid starts at 09:00, 48 px per hour

        page.clock.fast_forward("05:00")                                 # five minutes later
        expect(label).to_have_text("10:12")
        assert top() == (10 * 60 + 12 - 9 * 60) * 48 / 60, top()

        # what already passed is shaded and does not open the booking; neither does a closed day
        wednesday = page.locator(".tg-col[data-date='2026-11-18']")
        shade = float(wednesday.locator(".tg-past").evaluate("el => el.style.height").removesuffix("px"))
        assert shade == (10 * 60 + 12 - 9 * 60) * 48 / 60, shade           # up to now, following the clock
        expect(page.locator(".tg-col[data-date='2026-11-17'] .tg-past")).to_have_count(1)   # yesterday: all of it
        expect(page.locator(".tg-col[data-date='2026-11-19'] .tg-past")).to_have_count(0)   # tomorrow: none
        wednesday.click(position={"x": 20, "y": 30})                     # 09:30 today: already passed
        page.locator(".tg-col[data-date='2026-11-17']").click(position={"x": 20, "y": 3 * 48 + 6})   # yesterday 12:00
        page.locator(".tg-col[data-date='2026-11-22']").click(position={"x": 20, "y": 3 * 48 + 6})   # Sunday: closed
        expect(page.locator("dialog[open]")).to_have_count(0)
        wednesday.click(position={"x": 20, "y": 3 * 48 + 6})            # 12:00 today: an employee does not book
        expect(page.locator("dialog[open]")).to_have_count(0)

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
    server = local_server.start(0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    width_of = "el => Math.round(el.getBoundingClientRect().width)"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto(url_of(server))
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
        listed = page.locator(".list-item", has_text="Corte")              # wait for the list, not the old form
        expect(listed.locator(".kebab")).to_be_visible()
        expect(page.locator(".empty-state")).to_have_count(0)
        assert page.locator(".list-card").evaluate(width_of) == 760 - 32
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


def run_absences_on_professionals():
    """Profissionais: each card lists her absences, and a vacation can be planned from there."""
    server = local_server.start(0)
    service = Service.from_input({"name": "Corte", "duration_min": 60, "price_cents": 8000})
    server.deps.repo.save("local-salon", "service", service)
    server.deps.repo.save("local-salon", "professional", Professional.from_input({"name": "Bia", "services": [service.id]}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())
        page.goto(url_of(server))
        page.click("nav >> text=Profissionais")
        bia_card = page.locator(".list-item", has_text="Bia")
        expect(bia_card.locator(".absences")).to_contain_text("Sem ausências marcadas.")
        bia_card.locator("text=+ Adicionar ausência").click()
        expect(page.locator("#o-professional option:checked")).to_have_text("Bia")
        vacation_first = (salon_now().date() + timedelta(days=30)).isoformat()
        vacation_last = (salon_now().date() + timedelta(days=44)).isoformat()
        page.click(".chips >> text=Férias")
        page.fill("#o-first", vacation_first)
        page.fill("#o-last", vacation_last)
        page.click("text=Salvar ausência")
        vacation = bia_card.locator(".absences .away-chip")
        expect(vacation).to_have_text(
            f"Férias · {vacation_first[8:]}/{vacation_first[5:7]} – {vacation_last[8:]}/{vacation_last[5:7]}")
        vacation.click()
        page.click("dialog >> text=Remover ausência")
        expect(bia_card.locator(".absences")).to_contain_text("Sem ausências marcadas.")
        browser.close()
    server.shutdown()
    assert not errors, errors
    print("e2e ok (absences on Profissionais): listed on her card, vacation added and removed from there")


def run_long_lists():
    """The demo data (18 services, 22 professionals): pages of 10, a search over every page (not just
    the one shown) and without accents, and the list scrolls inside its box."""
    server = local_server.start(0, demo_data=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE, viewport={"width": 1280, "height": 520})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url_of(server))
        page.click("nav >> text=Serviços")
        expect(page.locator("h1")).to_have_text("Serviços (18)")
        expect(page.locator(".list-item")).to_have_count(10)                   # the first page
        expect(page.locator(".pager")).to_contain_text("1–10 de 18")
        expect(page.locator(".pager-page")).to_have_text("1 de 2")
        expect(page.locator("[aria-label='Página anterior']")).to_be_disabled()
        page.click("[aria-label='Próxima página']")
        expect(page.locator(".list-item")).to_have_count(8)
        expect(page.locator(".pager")).to_contain_text("11–18 de 18")
        expect(page.locator("[aria-label='Próxima página']")).to_be_disabled()
        page.click("[aria-label='Página anterior']")
        expect(page.locator(".list-item")).to_have_count(10)
        box = page.locator(".item-list")
        assert box.evaluate("e => e.scrollHeight > e.clientHeight"), "the list should scroll inside its box"
        expect(page.locator("main .row button", has_text="Adicionar")).to_be_in_viewport()
        page.fill(".list-search", "coloracao")                         # without the accent
        expect(page.locator(".list-item:visible")).to_have_text(re.compile("Coloração"))
        expect(page.locator(".pager")).to_be_hidden()                    # one page: no pager
        page.fill(".list-search", "spa dos pes")                        # found although it is on page 2
        expect(page.locator(".list-item")).to_have_text(re.compile("Spa dos pés"))
        page.fill(".list-search", "xyz")
        expect(page.locator(".list-item:visible")).to_have_count(0)
        expect(page.locator(".list-empty")).to_be_visible()
        page.fill(".list-search", "")
        expect(page.locator(".list-item:visible")).to_have_count(10)

        # professionals: 22 in 3 pages, and found by name from any page
        page.click("nav >> text=Profissionais")
        expect(page.locator("h1")).to_have_text("Profissionais (22)")
        expect(page.locator(".pager-page")).to_have_text("1 de 3")
        page.click("[aria-label='Próxima página']")
        page.click("[aria-label='Próxima página']")
        expect(page.locator(".list-item")).to_have_count(2)                    # 21 and 22
        page.fill(".list-search", "julia")                              # Júlia, without the accent
        expect(page.locator(".list-item")).to_have_count(1)
        expect(page.locator(".list-item strong")).to_contain_text("Júlia Martins")
        page.fill(".list-search", "joao pedro")
        expect(page.locator(".list-item strong")).to_contain_text("João Pedro Alves")
        page.fill(".list-search", "ra")                                 # Carla, Márcia, Rafael, Sabrina, Tânia Araújo...
        expect(page.locator(".pager")).to_be_hidden()
        assert page.locator(".list-item").count() > 3

        # the agenda's filter, with 22 professionals: folded, only "Todas" and the chosen ones stay
        page.click("nav >> text=Agenda")
        pills = page.locator(".cal-filter .pill")
        expect(pills).to_have_count(23)                                  # "Todas" + 22
        page.click(".cal-filter >> text=Júlia Martins")
        page.click(".cal-filter .fold")                                  # "Recolher"
        expect(pills).to_have_text(["Todas", "Júlia Martins"])
        expect(page.locator(".cal-filter .fold")).to_have_text("Mostrar profissionais (22) ▾")
        page.reload()                                                     # remembered on this device
        expect(page.locator(".cal-filter .fold")).to_have_attribute("aria-expanded", "false")
        expect(pills).to_have_count(1)                                   # a reload forgets the choice: "Todas"
        page.click(".cal-filter .fold")
        expect(pills).to_have_count(23)
        browser.close()
    server.shutdown()
    assert not errors, errors
    print("e2e ok (long lists): pages of 10, search over every page and without accents, scrolls in its box")


def run_finance():
    """Financeiro, with the demo data: the month's totals, per professional and per service, and marking
    an appointment that already happened as paid. The manager may also book in the past."""
    server = local_server.start(0, demo_data=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto(url_of(server))
        expect(page.locator("#menu button")).to_have_text(["Agenda", "Clientes", "Serviços", "Profissionais", "Financeiro"])
        expect(page.locator("#settings-group .nav-group-title")).to_have_text("Configurações")   # at the bottom
        expect(page.locator("#settings-menu button")).to_have_text(["Funcionamento", "Acessos"])
        page.click("nav >> text=Financeiro")
        expect(page.locator("h1")).to_have_text("Financeiro")
        expect(page.locator(".totals strong")).to_have_count(3)
        expect(page.locator(".money").first.locator("tbody tr")).to_have_count(22)         # every professional
        pending = page.locator(".overdue li")
        if pending.count() == 0:                                         # early in the month: look at the last one
            page.click("[aria-label='Mês anterior']")
        before = pending.count()
        assert before > 0, "the demo data leaves a few past appointments unpaid"
        pending.first.locator("text=Marcar como pago").click()
        expect(page.locator(".toast", has_text="Pagamento de")).to_be_visible()
        expect(pending).to_have_count(before - 1)

        expect(page.locator(".money").first.locator("thead th").last).to_have_text("Comissão")

        # a commission per service: % for one, a fixed amount for another; it shows on her row
        page.click("nav >> text=Profissionais")
        page.fill(".list-search", "duda")                               # wherever she is in the pages
        row_action(page, page.locator(".list-item", has_text="Duda"), "Editar")
        rows = page.locator(".service-row", has=page.locator("input[type=checkbox]:checked"))
        rows.nth(0).locator("select").select_option("percent")
        rows.nth(0).locator("input[inputmode=decimal]").fill("30")
        rows.nth(1).locator("select").select_option("fixed")
        rows.nth(1).locator("input[inputmode=decimal]").fill("12,50")
        page.click("text=Salvar")
        duda = page.locator(".list-item", has_text="Duda")
        expect(duda).to_contain_text("30%")
        expect(duda).to_contain_text("R$ 12,50")

        # the agenda marks each appointment: ✓ paid, amber R$ happened and not paid, gray R$ still ahead
        page.click("nav >> text=Agenda")
        page.click(".segmented >> text=Semana")
        expect(page.locator(".pay-legend")).to_be_visible()
        page.click("[aria-label='Semana anterior']")                    # all of it already happened
        expect(page.locator(".cal-body.loading")).to_have_count(0)
        expect(page.locator(".tg-event .pay.paid").first).to_be_visible()
        assert page.locator(".tg-event .pay.late").count() > 0, "the demo leaves some past ones unpaid"
        assert page.locator(".tg-event .pay.due").count() == 0
        page.click("text=Hoje")
        page.click("[aria-label='Próxima semana']")                     # all of it still ahead
        expect(page.locator(".cal-body.loading")).to_have_count(0)
        expect(page.locator(".cal-title")).not_to_have_text(re.compile(r"^$"))
        expect(page.locator(".tg-event .pay.late")).to_have_count(0)   # waits for next week's appointments
        expect(page.locator(".tg-event .pay.due").first).to_be_visible()
        assert page.locator(".tg-event .pay.late").count() == 0 and page.locator(".tg-event .pay.paid").count() == 0
        page.click("text=Hoje")

        # the manager opens the booking on a past time (employees cannot: see run_now_marker)
        page.click("nav >> text=Agenda")
        page.click(".segmented >> text=Dia")
        page.click("[aria-label='Dia anterior']")
        free = page.locator(".tg-col").first
        expect(free).to_be_visible()
        expect(page.locator(".cal-body.loading")).to_have_count(0)        # yesterday's appointments are in
        page.evaluate("""() => {                                   // a free, open spot of yesterday's first column
            const col = document.querySelector(".tg-col");
            const top = col.getBoundingClientRect().top;
            for (let y = 2; y < col.clientHeight; y += 12) {
                const el = document.elementFromPoint(col.getBoundingClientRect().left + 8, top + y);
                if (el === col) { window.__freeY = y; return; }
            }
        }""")
        free_y = page.evaluate("window.__freeY")
        if free_y is not None:                                           # yesterday may be Sunday (closed)
            free.click(position={"x": 8, "y": free_y})
            expect(page.locator("dialog[open] h2")).to_have_text("Novo agendamento")
            assert page.locator("#f-date").get_attribute("min") is None   # past dates allowed for her
            page.keyboard.press("Escape")
        browser.close()
    server.shutdown()
    assert not errors, errors
    print("e2e ok (finance): totals, per professional and service, mark paid; the manager books in the past")


def run_offline():
    """No connection (`--connection off`, or the internet dropping): only the agenda works, showing what
    was already downloaded; every change and every other page is blocked until it comes back."""
    server = local_server.start(0, demo_data=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE, viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url_of(server))
        expect(page.locator(".segmented button[aria-pressed=true]")).to_have_text("Semana")
        events = page.locator(".tg-event")
        expect(events.first).to_be_visible()
        this_week = events.count()
        page.click("[aria-label='Próxima semana']")                    # downloads next week too
        expect(events.first).to_be_visible()
        page.click("text=Hoje")
        expect(events).to_have_count(this_week)

        server.online = False                                            # the connection drops
        page.click("[aria-label='Próxima semana']")                    # already downloaded: still shown
        banner = page.locator("#offline-banner")
        expect(banner).to_be_visible()
        expect(events.first).to_be_visible()
        expect(page.locator(".offline-note")).to_be_hidden()           # every day of it was downloaded
        page.click(".segmented >> text=Mês")                          # another view of the same days
        expect(page.locator(".mv-chip").first).to_be_visible()
        expect(page.locator(".offline-note")).to_be_visible()          # but the month has days never downloaded
        page.click(".segmented >> text=Semana")
        page.click("text=Hoje")
        expect(events).to_have_count(this_week)

        # everything that changes something is blocked; only the agenda can be opened
        expect(page.locator("text=Novo agendamento")).to_be_disabled()
        expect(page.locator(".cal-controls >> text=Ausência")).to_be_disabled()
        for name in ("Serviços", "Profissionais", "Financeiro", "Funcionamento", "Acessos"):
            expect(page.locator(f"nav >> text={name}")).to_be_disabled()
        events.first.click()                                             # details: to look at, not to change
        expect(page.locator("dialog[open]")).to_contain_text("Sem conexão: dá para consultar, mas não alterar.")
        expect(page.locator("dialog[open] >> text=Cancelar agendamento")).to_have_count(0)
        expect(page.locator("dialog[open] >> text=Marcar como pago")).to_have_count(0)
        page.keyboard.press("Escape")
        page.reload()                                                    # reopened with no connection:
        expect(banner).to_be_visible()                                   # what was downloaded is on the device
        expect(events).to_have_count(this_week)
        for _ in range(8):                                               # far ahead: never downloaded
            page.click("[aria-label='Próxima semana']")
        expect(page.locator(".notice")).to_contain_text("ainda não foram baixados")

        server.online = True                                             # back: noticed within seconds
        expect(banner).to_be_hidden(timeout=15_000)
        expect(page.locator("nav >> text=Serviços")).to_be_enabled()
        expect(page.locator("text=Novo agendamento")).to_be_enabled()
        expect(page.locator(".notice")).to_have_count(0)                 # the agenda reloaded by itself
        browser.close()
    server.shutdown()

    # Started with no connection at all: nothing downloaded yet, so the agenda says so (no blank page).
    server = local_server.start(0, demo_data=True, connection="off")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url_of(server))
        expect(page.locator(".notice")).to_contain_text("Sem conexão com o servidor")
        expect(page.locator("#offline-banner")).to_be_visible()
        expect(page.locator("nav >> text=Serviços")).to_be_disabled()
        browser.close()
    server.shutdown()
    assert not errors, errors
    print("e2e ok (offline): the agenda shows what was downloaded, everything else is blocked, and it recovers")


def run_clients():
    """Clientes, with the demo data: found by name or phone; her page has the history and what is open,
    received right there; and booking with a known phone fills her name in."""
    server = local_server.start(0, demo_data=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto(url_of(server))
        expect(page.locator("#menu button")).to_have_text(["Agenda", "Clientes", "Serviços", "Profissionais", "Financeiro"])
        page.click("nav >> text=Clientes")
        expect(page.locator("h1")).to_have_text("Clientes (36)")
        expect(page.locator(".pager-page")).to_have_text("1 de 4")
        # a client who owes something (the demo leaves some past appointments unpaid)
        owing = page.evaluate("""async () => {
            for (const c of await fetch("/api/clients").then((r) => r.json())) {
                const d = await fetch(`/api/clients/${c.phone}`).then((r) => r.json());
                if (d.open.length > 0) return { ...c, open: d.open.length };
            }
        }""")
        assert owing, "the demo should leave some client with something open"
        page.fill(".list-search", owing["phone"][-4:])                  # found by the end of her phone
        page.locator(".list-item", has_text=owing["name"]).click()
        expect(page.locator("h1")).to_have_text(owing["name"])
        expect(page.locator(".history tbody tr").first).to_be_visible()
        expect(page.locator(".card h2", has_text="Em aberto")).to_contain_text(f"({owing['open']})")
        page.locator(".overdue li").first.locator("text=Marcar como pago").click()     # one of them
        expect(page.locator(".toast", has_text="Pagamento registrado")).to_be_visible()
        expect(page.locator(".overdue li")).to_have_count(owing["open"] - 1)
        if owing["open"] > 2:                                           # "Receber tudo": from two on
            page.locator("text=Receber tudo").click()
            expect(page.locator(".toast", has_text="Pagamentos registrados")).to_be_visible()
        elif owing["open"] == 2:
            expect(page.locator("text=Receber tudo")).to_have_count(0)
            page.locator(".overdue li").first.locator("text=Marcar como pago").click()
        expect(page.locator(".card", has_text="Nada em aberto")).to_be_visible()
        expect(page.locator(".history .pay.late")).to_have_count(0)

        # a new client by hand, then found by name without the accent
        page.click("text=‹ Clientes")
        page.click("main >> text=Nova cliente")
        page.fill("#k-phone", "(11) 3333-4444")
        page.fill("#k-name", "Zélia Prado")
        page.click("dialog[open] >> text=Salvar")
        expect(page.locator("h1")).to_have_text("Clientes (37)")
        page.fill(".list-search", "zelia")
        expect(page.locator(".list-item")).to_contain_text("(11) 3333-4444")

        # booking with her phone: the name comes in by itself
        page.click("nav >> text=Agenda")
        page.click("text=Novo agendamento")
        page.fill("#f-phone", owing["phone"])
        expect(page.locator("#f-name")).to_have_value(owing["name"])
        expect(page.locator(".client-note")).to_contain_text("Cliente cadastrada")
        page.keyboard.press("Escape")
        browser.close()
    server.shutdown()
    assert not errors, errors
    print("e2e ok (clients): by name or phone, history, receive what is open, new client, booking fills the name")


def run_as_employee():
    """`local/server.py employee --professional Ana`: sees only the agenda and the services, books
    nothing, and registers and removes only her own absences."""
    server = local_server.start(0, role="employee")
    service = Service.from_input({"name": "Corte", "duration_min": 60, "price_cents": 8000})
    server.deps.repo.save("local-salon", "service", service)
    ana = Professional.from_input({"name": "Ana", "services": [service.id]})
    bia = Professional.from_input({"name": "Bia", "services": [service.id]})
    for prof in (ana, bia):
        server.deps.repo.save("local-salon", "professional", prof)
    server.professional_id = ana.id                                  # this login is Ana's
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())
        page.goto(url_of(server))

        expect(page.locator("#local-mode")).to_have_text("Modo local, sem login (funcionária)")
        expect(page.locator("nav button")).to_have_text(["Agenda", "Serviços"])
        expect(page.locator("#settings-group")).to_be_hidden()          # the settings are the manager's
        expect(page.locator("text=Novo agendamento")).to_have_count(0)  # she does not book

        # her absence: the dialog only offers her
        page.click(".cal-controls >> text=Ausência")
        expect(page.locator("#o-professional option:not([value=''])")).to_have_text(["Ana"])
        page.click(".chips >> text=Folga")
        page.click("text=Salvar ausência")
        expect(page.locator(".toast", has_text="Ausência salva")).to_be_visible()
        page.locator(".away-chip, .tg-away, .mv-away").first.click()
        expect(page.locator("dialog[open] >> text=Remover ausência")).to_be_visible()   # hers: she may remove it
        page.click("dialog[open] >> text=Remover ausência")
        expect(page.locator(".toast", has_text="Ausência removida")).to_be_visible()

        page.click("nav >> text=Serviços")
        expect(page.locator(".list-item", has_text="Corte")).to_be_visible()
        expect(page.locator("main button", has_text=re.compile("^(Adicionar|Editar|Excluir|Desativar)$"))).to_have_count(0)
        expect(page.locator(".kebab")).to_have_count(0)                  # no actions menu for her
        for method, path, body in [("POST", "/api/services", {"name": "Cor", "duration_min": 60, "price_cents": 1}),
                                   ("POST", "/api/time-off", {"professional_id": bia.id, "first_day": "2030-01-02"})]:
            status = page.evaluate("""([method, path, body]) => fetch(path, { method, headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body) }).then((r) => r.status)""", [method, path, body])
            assert status == 403, (path, status)                         # the API refuses it too (Bia is not her)
        browser.close()
    server.shutdown()
    assert not errors, errors
    print("e2e ok (employee): only Agenda and Serviços, no booking, only her own absences; API answers 403")


def run_accesses():
    """Acessos: a login for a service provider starts her professional; from Profissionais, a login
    for one who had none."""
    server = local_server.start(0, demo_data=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(timezone_id=SALON_TIME_ZONE)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url_of(server))
        page.click("nav >> text=Acessos")
        expect(page.locator("h1")).to_have_text("Acessos (12)")                 # the demo's logins
        expect(page.locator(".pager-page")).to_have_text("1 de 2")
        page.click("main >> text=Novo acesso")
        page.fill("#x-email", "eva@salao.local")
        page.fill("#x-name", "Eva")
        expect(page.locator("#x-provider")).to_be_checked()
        page.click("dialog[open] >> text=Criar acesso")
        expect(page.locator(".toast", has_text="Configure os serviços e os dias de Eva")).to_be_visible()
        page.fill(".list-search", "eva")
        expect(page.locator(".list-item", has_text="Eva")).to_contain_text("Atende clientes como Eva")
        page.click("nav >> text=Profissionais")
        page.fill(".list-search", "eva")
        expect(page.locator(".list-item", has_text="Eva")).to_contain_text("Acesso ao sistema: eva@salao.local")
        page.fill(".list-search", "carla")
        carla = page.locator(".list-item", has_text="Carla")
        row_action(page, carla, "Criar acesso")                                  # the reverse path
        page.fill("#x-email", "carla@salao.local")
        page.click("dialog[open] >> text=Criar acesso")
        expect(carla).to_contain_text("Acesso ao sistema: carla@salao.local")
        expect(carla).to_contain_text("Comissão: Manicure R$")                   # the demo's fixed commission
        assert "Criar acesso" not in row_actions(page, carla)

        # someone left: her access is removed; she stays in Profissionais, with "Criar acesso" again
        page.on("dialog", lambda d: d.accept())
        page.click("nav >> text=Acessos")
        expect(page.locator("h1")).to_have_text("Acessos (14)")
        page.fill(".list-search", "eva")
        row_action(page, page.locator(".list-item", has_text="Eva"), "Remover acesso")
        expect(page.locator(".toast", has_text="Acesso removido")).to_be_visible()
        expect(page.locator("h1")).to_have_text("Acessos (13)")
        page.click("nav >> text=Profissionais")
        page.fill(".list-search", "eva")
        assert "Criar acesso" in row_actions(page, page.locator(".list-item", has_text="Eva"))
        browser.close()
    server.shutdown()
    assert not errors, errors
    print("e2e ok (accesses): a provider's login starts her professional; a professional gets her login")


if __name__ == "__main__":
    run()
    run_without_login()
    run_as_employee()
    run_accesses()
    run_absences_on_professionals()
    run_long_lists()
    run_finance()
    run_clients()
    run_offline()
    run_now_marker()
    run_layout()
