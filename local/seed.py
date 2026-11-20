"""Demo data for the local server, so the app opens looking like a salon in real use: services,
professionals with their own hours, the salon's hours, a busy agenda from last week to two weeks
ahead (most of what already happened is paid: the rest shows in Financeiro), and a few absences (one
of them over appointments already booked, flagged with ⚠).

Everything is dated relative to today, so the agenda is never empty, whatever the day. The same
`random` seed gives the same agenda every time. Only used by `python local/server.py` (and
`python dev.py serve`); the tests start from an empty database."""
from __future__ import annotations

import random
from datetime import date, timedelta

from agenda_core.domain.errors import SlotConflict
from dataclasses import replace

from agenda_core.domain.models import (STEP_MIN, Access, Appointment, Professional, Service, Settings, TimeOff,
                                       format_time, new_id)
from agenda_core.domain.scheduling import away_intervals, is_past, overlaps, working_interval
from agenda_core.ports import Dependencies

SERVICES = [  # name, minutes, R$, active
    ("Corte feminino", 60, 80, True), ("Escova", 45, 50, True), ("Coloração", 120, 180, True),
    ("Hidratação", 60, 90, True), ("Manicure", 45, 35, True), ("Pedicure", 60, 45, True),
    ("Design de sobrancelha", 30, 40, True), ("Progressiva", 180, 250, False),       # disabled: not offered
    # more of the menu, so that Serviços has a second page
    ("Corte masculino", 30, 45, True), ("Barba", 30, 35, True), ("Luzes", 150, 260, True),
    ("Penteado", 60, 110, True), ("Maquiagem", 60, 120, True), ("Manicure em gel", 75, 90, True),
    ("Spa dos pés", 60, 70, True), ("Limpeza de pele", 60, 130, True), ("Massagem relaxante", 60, 140, True),
    ("Alongamento de cílios", 90, 150, True),
]

# Monday to Friday 09:00-19:00, Saturday 08:00-14:00, closed on Sunday.
SALON_HOURS = [{"day": d, "start": "09:00", "end": "19:00"} for d in range(5)] + [{"day": 5, "start": "08:00", "end": "14:00"}]


def _shifts(days, start, end):
    return [{"day": d, "start": start, "end": end} for d in days]


# Commissions: % of the price for the hair, a fixed amount per service for the nails.
COMMISSIONS = {"Ana": {"*": ("percent", 40)}, "Bia": {"*": ("percent", 50)}, "Duda": {"*": ("percent", 45)},
               "Carla": {"Manicure": ("fixed", 1500), "Pedicure": ("fixed", 2000)}}

PROFESSIONALS = [  # name, services, work hours (None = the salon's)
    ("Ana", ["Corte feminino", "Escova", "Coloração"], None),
    ("Bia", ["Corte feminino", "Escova", "Hidratação"], _shifts([1, 2, 3, 4], "10:00", "19:00") + _shifts([5], "10:00", "14:00")),
    # Saturday from 09:00: the salon opens at 08:00 with nobody there (the agenda shows that gap in yellow)
    ("Carla", ["Manicure", "Pedicure"], _shifts(range(5), "09:00", "17:00") + _shifts([5], "09:00", "14:00")),
    ("Duda", ["Design de sobrancelha", "Manicure"], _shifts([0, 2, 4], "13:00", "19:00")),
]

# The rest of the team, so that Profissionais and Acessos have more than one page and the search has
# something to find (names with accents: "julia" finds Júlia). Fewer appointments each than the four
# above, or the week view would be unreadable. Nobody starts before 09:00 on Saturday, so the yellow
# "nobody attends" gap of 08:00-09:00 stays.
HAIR = ["Corte feminino", "Escova", "Coloração", "Hidratação", "Luzes", "Penteado"]
NAILS = ["Manicure", "Pedicure", "Manicure em gel", "Spa dos pés"]
BEAUTY = ["Design de sobrancelha", "Maquiagem", "Limpeza de pele", "Alongamento de cílios"]
BARBER = ["Corte masculino", "Barba"]
WELLNESS = ["Massagem relaxante", "Limpeza de pele"]
WEEKDAYS = _shifts(range(5), "09:00", "18:00")
LATE = _shifts([1, 2, 3, 4], "10:00", "19:00") + _shifts([5], "10:00", "14:00")
AFTERNOONS = _shifts([0, 2, 4], "13:00", "19:00")
FULL_WEEK = _shifts(range(5), "09:00", "17:00") + _shifts([5], "09:00", "14:00")
TEAM = [  # name, services, work hours, commission (for each of her services), has a login
    ("Júlia Martins", HAIR[:4], WEEKDAYS, ("percent", 45), True),
    ("Patrícia Gomes", NAILS, FULL_WEEK, ("fixed", 1800), True),
    ("Letícia Rocha", BEAUTY[:3], LATE, ("percent", 40), True),
    ("Márcia Lopes", HAIR, FULL_WEEK, ("percent", 50), True),
    ("Fábio Nunes", BARBER, LATE, ("fixed", 2000), True),
    ("João Pedro Alves", BARBER + ["Corte feminino"], WEEKDAYS, ("percent", 40), True),
    ("Lívia Castro", BEAUTY, AFTERNOONS, ("percent", 35), True),
    ("Natália Prado", NAILS[:3], WEEKDAYS, ("fixed", 1500), True),
    ("Rafael Souza", WELLNESS, AFTERNOONS, ("percent", 50), True),
    ("Tânia Araújo", HAIR[2:], LATE, ("percent", 45), False),
    ("Vitória Dias", NAILS, AFTERNOONS, ("fixed", 1600), False),
    ("Gisele Moura", BEAUTY[1:], FULL_WEEK, ("percent", 40), False),
    ("Helena Faria", HAIR[:3] + ["Penteado"], WEEKDAYS, ("percent", 45), False),
    ("Isabela Reis", ["Maquiagem", "Penteado"], LATE, ("percent", 50), False),
    ("Kátia Ramos", NAILS[:2], FULL_WEEK, ("fixed", 1400), False),
    ("Mônica Teixeira", ["Coloração", "Luzes"], WEEKDAYS, ("percent", 40), False),
    ("Paula Cardoso", WELLNESS + ["Spa dos pés"], AFTERNOONS, ("percent", 45), False),
    ("Sabrina Lima", BEAUTY[:2] + NAILS[:1], LATE, ("percent", 40), False),
]
BUSY = 0.6                          # share of the hours booked: the four above
BUSY_TEAM = 0.25                    # and the rest of the team


def _email(name: str) -> str:
    """"João Pedro Alves" -> "joao@salao.local"."""
    first = name.split()[0].lower()
    return first.translate(str.maketrans("áâãàéêíóôõúç", "aaaaeeiooouc")) + "@salao.local"


CLIENTS = ["Maria Souza", "Juliana Lima", "Fernanda Alves", "Patrícia Rocha", "Camila Santos", "Aline Costa",
           "Beatriz Melo", "Larissa Gomes", "Renata Dias", "Vanessa Ribeiro", "Tatiane Moura", "Gabriela Nunes",
           "Luana Pires", "Rafaela Teixeira", "Carolina Freitas", "Simone Barros", "Débora Cardoso", "Priscila Martins"]


def seed(deps: Dependencies, owner: str, today: date) -> None:
    repo, rng = deps.repo, random.Random(42)

    repo.save_settings(owner, Settings.from_input({"hours": SALON_HOURS}))
    services = {}
    for name, minutes, reais, active in SERVICES:
        service = Service.from_input({"name": name, "duration_min": minutes, "price_cents": reais * 100, "active": active})
        repo.save(owner, "service", service)
        services[name] = service
    professionals = []
    for name, names, hours in PROFESSIONALS:
        rules = COMMISSIONS[name]
        commissions = {services[n].id: dict(zip(("kind", "value"), rules.get(n) or rules["*"])) for n in names}
        prof = Professional.from_input({"name": name, "services": [services[n].id for n in names], "work_hours": hours,
                                        "commissions": commissions})
        repo.save(owner, "professional", prof)
        professionals.append(prof)
    ana, bia, carla, duda = professionals
    team = []
    for name, names, hours, rule, _ in TEAM:
        prof = Professional.from_input({"name": name, "services": [services[n].id for n in names], "work_hours": hours,
                                        "commissions": {services[n].id: {"kind": rule[0], "value": rule[1]} for n in names}})
        repo.save(owner, "professional", prof)
        team.append(prof)

    # Logins the manager created: Ana and Bia have theirs (Carla and Duda do not, yet), plus the
    # receptionist, who does not attend clients.
    logins = [(ana, "ana@salao.local"), (bia, "bia@salao.local"), (None, "recepcao@salao.local")]
    logins += [(prof, _email(prof.name)) for prof, (*_, has_login) in zip(team, TEAM) if has_login]
    for prof, email in logins:
        name = prof.name if prof else "Recepção"
        login_id = deps.identity.create_login(email, name, owner, prof.id if prof else None, False)
        repo.save_access(owner, Access(login_id, email, name, False, prof.id if prof else None))
        if prof:
            repo.save(owner, "professional", replace(prof, login=email))
    settings = repo.get_settings(owner)

    # Planned absences come first, so nothing is booked inside them.
    def absence(prof, first, last, kind, reason="", start=None, end=None):
        repo.save_time_off(owner, TimeOff.from_input({
            "professional_id": prof.id, "first_day": first.isoformat(), "last_day": last.isoformat(),
            "kind": kind, "reason": reason, **({"start": start, "end": end} if start else {})}))

    absence(carla, today + timedelta(days=10), today + timedelta(days=20), "vacation")
    next_friday = today + timedelta(days=(4 - today.weekday()) % 7 or 7)
    absence(duda, next_friday, next_friday, "day_off")
    time_offs = repo.time_off_between(owner, (today - timedelta(days=7)).isoformat(), (today + timedelta(days=14)).isoformat())

    # Part of each professional's hours booked (BUSY, BUSY_TEAM), from a week ago to two weeks ahead.
    busy = {p.id: BUSY for p in professionals} | {p.id: BUSY_TEAM for p in team}
    professionals = professionals + team
    for offset in range(-7, 15):
        day = today + timedelta(days=offset)
        iso = day.isoformat()
        for prof in professionals:
            hours = working_interval(settings, day, prof)
            if hours is None:
                continue
            away = away_intervals(time_offs, prof.id, iso)
            hers = [s for s in services.values() if s.id in prof.services and s.active]
            start = hours[0]
            while True:
                service = rng.choice(hers)
                end = start + service.duration_min
                if end > hours[1]:
                    break
                if rng.random() < busy[prof.id] and not overlaps(start, end, away):
                    client = rng.choice(CLIENTS)
                    phone = f"119{rng.randrange(10_000_000, 99_999_999)}"
                    appt = Appointment(f"{iso}_{start // 60:02d}{start % 60:02d}_{new_id()}", iso, format_time(start),
                                       service.duration_min, prof.id, prof.name, service.id, service.name,
                                       service.price_cents, client, phone,
                                       # what already happened was mostly paid; a few are still to receive
                                       paid=is_past(day, start, deps.now()) and rng.random() < 0.85,
                                       commission_cents=prof.commission_for(service.id, service.price_cents))
                    try:
                        repo.create_appointment(owner, appt)
                    except SlotConflict:
                        pass
                    start = end + rng.choice([0, 0, 0, STEP_MIN, 2 * STEP_MIN])
                else:
                    start += rng.choice([STEP_MIN, 2 * STEP_MIN, 4 * STEP_MIN])

    # And one that came up after the agenda was full: Bia has a doctor's appointment this afternoon
    # (or on her next working day), so her clients then show ⚠, to be moved or cancelled.
    doctor_day = next(today + timedelta(days=i) for i in range(7)
                      if working_interval(settings, today + timedelta(days=i), bia))
    absence(bia, doctor_day, doctor_day, "other", "Médico", "15:00", "17:00")
