"""qbscaffold — scaffold facts: what can be known in advance, computed by rule, and the slots that recurring events leave
to be filled from a documented source.

Two kinds:

  Computed  facts that follow from a published rule with no source to consult: the day of the week of every date, leap
            years, Easter (Western and Orthodox), the equinoxes and solstices (Meeus, Astronomical Algorithms ch. 27, to
            the day in UTC), US federal holidays (from the year each statute took effect) and US federal election days.
            Each names its rule. Method "recompute": anyone can recompute it and must get the same answer.
  Slots     recurring events whose outcome cannot be computed (who won, where it was held). The scaffold knows which
            editions to expect (the series' rule); each slot is filled only from a documented source — Wikidata, CC0 —
            one query per series. A slot no source fills stays open and is reported as open, never guessed.

Deterministic, standard library only; no AI model computes or fills anything.
"""
import datetime, math

VERSION = "1.0.0"
FIRST_YEAR, LAST_YEAR = 1600, 2200          # computed facts (Gregorian calendar, rules valid throughout)
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


# ------------------------------------------------------------------------------------------------ calendar rules
def is_leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def easter_western(y):
    """Gregorian Easter Sunday (the anonymous Gregorian algorithm, valid from 1583)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return datetime.date(y, month, (h + l - 7 * m + 114) % 31 + 1)


def easter_orthodox(y):
    """Orthodox Easter Sunday: the Julian computus (Meeus), given as its Gregorian date."""
    a, b, c = y % 4, y % 7, y % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = (d + e + 114) % 31 + 1
    return datetime.date(y, month, day) + datetime.timedelta(days=y // 100 - y // 400 - 2)


def nth_weekday(y, month, weekday, n):
    """the n-th weekday (0 = Monday) of a month; n = -1 for the last"""
    if n > 0:
        d = datetime.date(y, month, 1)
        return d + datetime.timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))
    d = datetime.date(y + (month == 12), month % 12 + 1, 1) - datetime.timedelta(days=1)
    return d - datetime.timedelta(days=(d.weekday() - weekday) % 7)


def election_day(y):
    """US federal election day: the Tuesday after the first Monday in November"""
    return nth_weekday(y, 11, 0, 1) + datetime.timedelta(days=1)


# US federal holidays: (name, first year the rule applies, last year or None, date rule). Only the statute's own date:
# when a holiday falls on a weekend the day off moves, but the holiday's date does not.
US_HOLIDAYS = [
    ("New Year's Day", 1870, None, lambda y: datetime.date(y, 1, 1)),
    ("Martin Luther King Jr. Day", 1986, None, lambda y: nth_weekday(y, 1, 0, 3)),
    ("Washington's Birthday", 1971, None, lambda y: nth_weekday(y, 2, 0, 3)),
    ("Memorial Day", 1971, None, lambda y: nth_weekday(y, 5, 0, -1)),
    ("Juneteenth National Independence Day", 2021, None, lambda y: datetime.date(y, 6, 19)),
    ("Independence Day", 1870, None, lambda y: datetime.date(y, 7, 4)),
    ("Labor Day", 1894, None, lambda y: nth_weekday(y, 9, 0, 1)),
    ("Columbus Day", 1971, None, lambda y: nth_weekday(y, 10, 0, 2)),
    ("Veterans Day", 1971, 1977, lambda y: nth_weekday(y, 10, 0, 4)),
    ("Veterans Day", 1978, None, lambda y: datetime.date(y, 11, 11)),
    ("Thanksgiving Day", 1942, None, lambda y: nth_weekday(y, 11, 3, 4)),
    ("Christmas Day", 1870, None, lambda y: datetime.date(y, 12, 25)),
]
HOLIDAY_RULE = "5 U.S.C. § 6103 (and the year each holiday's present rule took effect)"


# ------------------------------------------------------------------------------------------------ equinoxes and solstices
_TERMS = [(485, 324.96, 1934.136), (203, 337.23, 32964.467), (199, 342.08, 20.186), (182, 27.85, 445267.112), (156, 73.14, 45036.886),
          (136, 171.52, 22518.443), (77, 222.54, 65928.934), (74, 296.72, 3034.906), (70, 243.58, 9037.513), (58, 119.81, 33718.147),
          (52, 297.17, 150.678), (50, 21.02, 2281.226), (45, 247.54, 29929.562), (44, 325.15, 31555.956), (29, 60.93, 4443.417),
          (18, 155.12, 67555.328), (17, 288.79, 4562.452), (16, 198.04, 62894.029), (14, 199.76, 31436.921), (12, 95.39, 14577.848),
          (12, 287.11, 31931.756), (12, 320.81, 34777.259), (9, 227.73, 1222.114), (8, 15.45, 16859.074)]
_MEAN = {"March equinox": (2451623.80984, 365242.37404, 0.05169, -0.00411, -0.00057),
         "June solstice": (2451716.56767, 365241.62603, 0.00325, 0.00888, -0.00030),
         "September equinox": (2451810.21715, 365242.01767, -0.11575, 0.00337, 0.00078),
         "December solstice": (2451900.05952, 365242.74049, -0.06223, -0.00823, 0.00032)}


def _delta_t(y):
    """seconds between terrestrial and universal time (Espenak–Meeus approximations; minutes at worst here)"""
    if 2005 <= y <= 2050:
        t = y - 2000
        return 62.92 + 0.32217 * t + 0.005589 * t * t
    u = (y - 1820) / 100
    return -20 + 32 * u * u


def _jd_to_datetime(jd):
    z, f = int(jd + 0.5), jd + 0.5 - int(jd + 0.5)
    a = z if z < 2299161 else z + 1 + int((z - 1867216.25) / 36524.25) - int(int((z - 1867216.25) / 36524.25) / 4)
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e)
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    return datetime.datetime(year, month, day) + datetime.timedelta(days=f)


def season_start(y, which):
    """UTC moment of an equinox or solstice (Meeus ch. 27; within about a minute for 1600–2200)"""
    c0, c1, c2, c3, c4 = _MEAN[which]
    yy = (y - 2000) / 1000
    jde0 = c0 + c1 * yy + c2 * yy ** 2 + c3 * yy ** 3 + c4 * yy ** 4
    t = (jde0 - 2451545.0) / 36525
    w = math.radians(35999.373 * t - 2.47)
    dl = 1 + 0.0334 * math.cos(w) + 0.0007 * math.cos(2 * w)
    s = sum(a * math.cos(math.radians(b + c * t)) for a, b, c in _TERMS)
    jde = jde0 + 0.00001 * s / dl
    return _jd_to_datetime(jde - _delta_t(y) / 86400)


# ------------------------------------------------------------------------------------------------ computed facts
def year_facts(y):
    """[(subject, predicate, object, rule)] for one year"""
    out = []
    add = lambda s, p, o, rule: out.append((s, p, o, rule))
    yr = "Year %d" % y
    add(yr, "is a leap year (Gregorian calendar)", "yes" if is_leap(y) else "no", "Gregorian rule: divisible by 4, except centuries not divisible by 400")
    add(yr, "number of days", "366" if is_leap(y) else "365", "Gregorian leap-year rule")
    add(yr, "1 January falls on", WEEKDAYS[datetime.date(y, 1, 1).weekday()], "Gregorian calendar")
    add(yr, "Easter Sunday (Western churches)", easter_western(y).isoformat(), "Gregorian computus")
    add(yr, "Easter Sunday (Orthodox churches), Gregorian date", easter_orthodox(y).isoformat(), "Julian computus, converted to the Gregorian calendar")
    for which in _MEAN:
        add(yr, "%s (UTC date)" % which, season_start(y, which).date().isoformat(), "Meeus, Astronomical Algorithms, ch. 27")
    for name, first, last, rule in US_HOLIDAYS:
        if y >= first and (last is None or y <= last):
            d = rule(y)
            add("%s %d (United States federal holiday)" % (name, y), "date", d.isoformat(), HOLIDAY_RULE)
            add("%s %d (United States federal holiday)" % (name, y), "day of the week", WEEKDAYS[d.weekday()], HOLIDAY_RULE)
    if y >= 1848 and y % 4 == 0:
        add("United States presidential election %d" % y, "election day", election_day(y).isoformat(), "3 U.S.C. § 1: the Tuesday after the first Monday in November")
    if y >= 1876 and y % 2 == 0:
        add("United States House of Representatives election %d" % y, "election day", election_day(y).isoformat(),
            "2 U.S.C. § 7: the Tuesday after the first Monday in November of even years")
    return out


def date_facts(y):
    """the day of the week and day of the year of every date in one year"""
    d, out = datetime.date(y, 1, 1), []
    while d.year == y:
        s = "%d %s %d" % (d.day, MONTHS[d.month - 1], y)
        out.append((s, "day of the week", WEEKDAYS[d.weekday()], "Gregorian calendar"))
        out.append((s, "day of the year", str(d.timetuple().tm_yday), "Gregorian calendar"))
        d += datetime.timedelta(days=1)
    return out


# ------------------------------------------------------------------------------------------------ recurring-event slots
# key: (series name, slot predicate, first edition year, years between editions, SPARQL returning ?item ?year and ?value)
# The query returns every edition at once; one query per series. Editions the rule expects but no source records stay open.
_LABEL = 'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }'
SERIES = {
    "nobel-physics": ("Nobel Prize in Physics", "laureate", 1901, 1,
                      "SELECT ?item ?year ?valueLabel WHERE { ?value p:P166 ?st. ?st ps:P166 wd:Q38104; pq:P585 ?d. BIND(?value AS ?item) BIND(YEAR(?d) AS ?year) %s }"),
    "nobel-chemistry": ("Nobel Prize in Chemistry", "laureate", 1901, 1,
                        "SELECT ?item ?year ?valueLabel WHERE { ?value p:P166 ?st. ?st ps:P166 wd:Q44585; pq:P585 ?d. BIND(?value AS ?item) BIND(YEAR(?d) AS ?year) %s }"),
    "nobel-medicine": ("Nobel Prize in Physiology or Medicine", "laureate", 1901, 1,
                       "SELECT ?item ?year ?valueLabel WHERE { ?value p:P166 ?st. ?st ps:P166 wd:Q80061; pq:P585 ?d. BIND(?value AS ?item) BIND(YEAR(?d) AS ?year) %s }"),
    "nobel-literature": ("Nobel Prize in Literature", "laureate", 1901, 1,
                         "SELECT ?item ?year ?valueLabel WHERE { ?value p:P166 ?st. ?st ps:P166 wd:Q37922; pq:P585 ?d. BIND(?value AS ?item) BIND(YEAR(?d) AS ?year) %s }"),
    "nobel-peace": ("Nobel Peace Prize", "laureate", 1901, 1,
                    "SELECT ?item ?year ?valueLabel WHERE { ?value p:P166 ?st. ?st ps:P166 wd:Q35637; pq:P585 ?d. BIND(?value AS ?item) BIND(YEAR(?d) AS ?year) %s }"),
    "nobel-economics": ("Nobel Memorial Prize in Economic Sciences", "laureate", 1969, 1,
                        "SELECT ?item ?year ?valueLabel WHERE { ?value p:P166 ?st. ?st ps:P166 wd:Q47170; pq:P585 ?d. BIND(?value AS ?item) BIND(YEAR(?d) AS ?year) %s }"),
    "summer-olympics": ("Summer Olympic Games", "location", 1896, 4,
                        "SELECT ?item ?year ?valueLabel WHERE { ?item wdt:P31 wd:Q159821; wdt:P585 ?d; wdt:P276 ?value. BIND(YEAR(?d) AS ?year) %s }"),
    "winter-olympics": ("Winter Olympic Games", "location", 1924, 4,
                        "SELECT ?item ?year ?valueLabel WHERE { ?item wdt:P31 wd:Q82414; wdt:P585 ?d; wdt:P276 ?value. BIND(YEAR(?d) AS ?year) %s }"),
    "fifa-world-cup": ("FIFA World Cup", "winner", 1930, 4,
                       "SELECT ?item ?year ?valueLabel WHERE { ?item wdt:P31 wd:Q19317; wdt:P585 ?d; wdt:P1346 ?value. BIND(YEAR(?d) AS ?year) %s }"),
    "super-bowl": ("Super Bowl", "winner", 1967, 1,
                   "SELECT ?item ?year ?valueLabel WHERE { ?item wdt:P31 wd:Q32096; wdt:P585 ?d; wdt:P1346 ?value. BIND(YEAR(?d) AS ?year) %s }"),
    "best-picture": ("Academy Award for Best Picture", "awarded to", 1929, 1,
                     "SELECT ?item ?year ?valueLabel WHERE { ?value p:P166 ?st. ?st ps:P166 wd:Q102427; pq:P585 ?d. BIND(?value AS ?item) BIND(YEAR(?d) AS ?year) %s }"),
    "us-presidential": ("United States presidential election", "winner", 1788, 4,
                        "SELECT ?item ?year ?valueLabel WHERE { ?item wdt:P31 wd:Q47566; wdt:P585 ?d; wdt:P991 ?value. BIND(YEAR(?d) AS ?year) %s }"),
}


def expected_years(series, this_year=None):
    """the editions a series' rule expects up to last year (the current year's may not have happened yet)"""
    name, pred, first, step, q = SERIES[series]
    last = (this_year or datetime.date.today().year) - 1
    return list(range(first, last + 1, step))


def query(series):
    return SERIES[series][4] % _LABEL


def slot_facts(series, bindings):
    """SPARQL bindings → [(subject, predicate, object, year, wikidata url)]; labels that are bare Q-ids are skipped
    (Wikidata has no English name for them yet)"""
    name, pred, first, step, q = SERIES[series]
    out, seen = [], set()
    for b in bindings:
        try:
            year = int(b["year"]["value"])
            value = b["valueLabel"]["value"].strip()
        except (KeyError, ValueError):
            continue
        if not value or (value[0] == "Q" and value[1:].isdigit()):
            continue
        item = (b.get("item") or {}).get("value", "")
        key = (year, value)
        if key in seen:
            continue
        seen.add(key)
        out.append(("%s %d" % (name, year), pred, value, year, item.replace("http://", "https://")))
    return sorted(out, key=lambda r: (r[3], r[2]))


def self_test():
    out = []
    ok = lambda n, c: out.append((n, bool(c)))
    ok("Western Easter 2024, 2025, 2038", [easter_western(y).isoformat() for y in (2024, 2025, 2038)] == ["2024-03-31", "2025-04-20", "2038-04-25"])
    ok("Orthodox Easter 2024, 2025", [easter_orthodox(y).isoformat() for y in (2024, 2025)] == ["2024-05-05", "2025-04-20"])
    ok("Thanksgiving 2024, Labor Day 2025, Memorial Day 2024, MLK Day 2026",
       [nth_weekday(2024, 11, 3, 4), nth_weekday(2025, 9, 0, 1), nth_weekday(2024, 5, 0, -1), nth_weekday(2026, 1, 0, 3)]
       == [datetime.date(2024, 11, 28), datetime.date(2025, 9, 1), datetime.date(2024, 5, 27), datetime.date(2026, 1, 19)])
    ok("election days 2024 and 2028", (election_day(2024), election_day(2028)) == (datetime.date(2024, 11, 5), datetime.date(2028, 11, 7)))
    m = season_start(2024, "March equinox")
    ok("March equinox 2024 at 03:06 UTC on 20 March (Meeus, within 2 minutes)", abs((m - datetime.datetime(2024, 3, 20, 3, 6)).total_seconds()) < 120)
    ok("solstices 2024: 20 June and 21 December", (season_start(2024, "June solstice").date(), season_start(2024, "December solstice").date())
       == (datetime.date(2024, 6, 20), datetime.date(2024, 12, 21)))
    ok("leap years", [is_leap(y) for y in (1900, 2000, 2024, 2100)] == [False, True, True, False])
    ok("dates: 366 dates in 2024, 15 March 2024 a Friday", len(date_facts(2024)) == 732 and ("15 March 2024", "day of the week", "Friday", "Gregorian calendar") in date_facts(2024))
    f = slot_facts("nobel-physics", [{"year": {"value": "1921"}, "valueLabel": {"value": "Albert Einstein"}, "item": {"value": "http://www.wikidata.org/entity/Q937"}},
                                     {"year": {"value": "1921"}, "valueLabel": {"value": "Q123"}}])
    ok("slots: a filled edition becomes a fact; a nameless Q-id is not guessed", f == [("Nobel Prize in Physics 1921", "laureate", "Albert Einstein", 1921, "https://www.wikidata.org/entity/Q937")])
    return out
