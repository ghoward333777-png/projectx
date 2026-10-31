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


# -- the lattice (1.1): any recurring event Wikidata models, one query per series, every useful property per edition
# How the editions hang off the series item: P31 (each edition is an instance of it: Super Bowl), P179 (part of the
# series), P3450 (a season of the league or competition). Each edition gives its winner, place, country, dates, number of
# participants and its own name; neighbouring editions are linked (previous / next edition), so every slot sits in a lattice.
EDITION_QUERY = ("SELECT ?item ?itemLabel ?year ?valueLabel ?locationLabel ?countryLabel ?date ?start ?end ?participants WHERE { "
                 "?item wdt:%s wd:%s. OPTIONAL { ?item wdt:P585 ?date } OPTIONAL { ?item wdt:P580 ?start } OPTIONAL { ?item wdt:P582 ?end } "
                 "OPTIONAL { ?item wdt:P571 ?inc } BIND(YEAR(COALESCE(?date, ?start, ?inc)) AS ?year) FILTER(BOUND(?year)) "
                 "OPTIONAL { ?item wdt:P1346 ?value } OPTIONAL { ?item wdt:P276 ?location } OPTIONAL { ?item wdt:P17 ?country } "
                 "OPTIONAL { ?item wdt:P1132 ?participants } %%s }")
AWARD_QUERY = "SELECT ?item ?year ?valueLabel WHERE { ?value p:P166 ?st. ?st ps:P166 wd:%s; pq:P585 ?d. BIND(?value AS ?item) BIND(YEAR(?d) AS ?year) %%s }"
# the columns an edition query returns → the predicate each becomes (valueLabel takes the series' own slot predicate)
COLUMNS = {"locationLabel": "location", "countryLabel": "country", "date": "date", "start": "start date", "end": "end date",
           "participants": "number of participants", "itemLabel": "known as"}


def editions(name, pred, qid, link, first, step=1, value="P1346"):
    """step 0: the series has no fixed rhythm (elections called early, cancelled years): no slots are predicted"""
    return (name, pred, first, step, EDITION_QUERY.replace("wdt:P1346 ?value", "wdt:%s ?value" % value) % (link, qid))


def award(name, qid, first, pred="laureate"):
    return (name, pred, first, 1, AWARD_QUERY % qid)



# (1.1) 102 more series, each checked live on 31 October 2026: the Wikidata item, how its editions hang off it, the
# first edition and the rhythm measured from the editions themselves (0 = no fixed rhythm: no slots predicted)
SERIES.update({
    'world-series': editions('World Series', 'winner', 'Q265538', 'P3450', 1903, 1),
    'nba-finals': editions('NBA Finals', 'winner', 'Q842375', 'P31', 1947, 1),
    'stanley-cup': editions('Stanley Cup', 'winner', 'Q211872', 'P31', 1915, 1),
    'uefa-cl-final': editions('UEFA Champions League final', 'winner', 'Q80716240', 'P31', 1956, 1),
    'wimbledon': editions('Wimbledon Championships', 'winner', 'Q41520', 'P31', 1898, 1),
    'us-open-tennis': editions('US Open (tennis)', 'winner', 'Q123577', 'P31', 1881, 1),
    'french-open': editions('French Open', 'winner', 'Q43605', 'P31', 1891, 1),
    'australian-open': editions('Australian Open', 'winner', 'Q60874', 'P31', 1905, 1),
    'tour-de-france': editions('Tour de France', 'winner', 'Q33881', 'P31', 1903, 1),
    'giro': editions("Giro d'Italia", 'winner', 'Q33861', 'P31', 1909, 1),
    'vuelta': editions('Vuelta a España', 'winner', 'Q33937', 'P31', 1935, 1),
    'commonwealth-games': editions('Commonwealth Games', 'winner', 'Q178340', 'P3450', 1930, 4),
    'cricket-world-cup': editions('Cricket World Cup', 'winner', 'Q192202', 'P3450', 1975, 4),
    'rugby-world-cup': editions('Rugby World Cup', 'winner', 'Q16640', 'P3450', 1987, 4),
    'kentucky-derby': editions('Kentucky Derby', 'winner', 'Q1141795', 'P3450', 1875, 1),
    'masters': editions('Masters Tournament', 'winner', 'Q280275', 'P31', 1934, 1),
    'open-championship': editions('The Open Championship', 'winner', 'Q848797', 'P31', 1860, 1),
    'indy-500': editions('Indianapolis 500', 'winner', 'Q8032', 'P31', 1911, 1),
    'daytona-500': editions('Daytona 500', 'winner', 'Q841738', 'P31', 1959, 1),
    'le-mans': editions('24 Hours of Le Mans', 'winner', 'Q187579', 'P3450', 1923, 1),
    'monaco-gp': editions('Monaco Grand Prix', 'winner', 'Q9102', 'P3450', 1930, 1),
    'boston-marathon': editions('Boston Marathon', 'winner', 'Q826038', 'P31', 1897, 1),
    'london-marathon': editions('London Marathon', 'winner', 'Q578794', 'P31', 1981, 1),
    'nyc-marathon': editions('New York City Marathon', 'winner', 'Q752138', 'P31', 1970, 1),
    'grand-national': editions('Grand National', 'winner', 'Q1542651', 'P3450', 1836, 1),
    'melbourne-cup': editions('Melbourne Cup', 'winner', 'Q1311060', 'P3450', 1861, 1),
    'ryder-cup': editions('Ryder Cup', 'winner', 'Q854376', 'P3450', 1927, 2),
    'americas-cup': editions("America's Cup", 'winner', 'Q467557', 'P3450', 1851, 0),
    'davis-cup': editions('Davis Cup', 'winner', 'Q132377', 'P3450', 1900, 1),
    'world-snooker': editions('World Snooker Championship', 'winner', 'Q502948', 'P3450', 1926, 1),
    'world-chess': editions('World Chess Championship', 'winner', 'Q190042', 'P3450', 1886, 0),
    'six-nations': editions('Six Nations Championship', 'winner', 'Q16642', 'P3450', 1882, 1),
    'super-rugby': editions('Super Rugby', 'winner', 'Q855988', 'P3450', 1996, 0),
    'copa-america': editions('Copa América', 'winner', 'Q178750', 'P3450', 1916, 0),
    'euro-championship': editions('UEFA European Championship', 'winner', 'Q260858', 'P3450', 1960, 4),
    'afcon': editions('Africa Cup of Nations', 'winner', 'Q83145', 'P3450', 1957, 2),
    'asian-games': editions('Asian Games', 'winner', 'Q483463', 'P3450', 1951, 4),
    'pan-am-games': editions('Pan American Games', 'winner', 'Q230186', 'P3450', 1951, 4),
    'ncaa-mens-basketball': editions("NCAA Division I men's basketball tournament", 'winner', 'Q996954', 'P3450', 1939, 1),
    'cfp-championship': editions('College Football Playoff National Championship', 'winner', 'Q16256406', 'P3450', 2015, 1),
    'uefa-champions-league': editions('UEFA Champions League season', 'champion', 'Q18756', 'P3450', 1955, 1),
    'copa-libertadores': editions('Copa Libertadores', 'champion', 'Q184795', 'P3450', 1960, 1),
    'mlb-season': editions('Major League Baseball season', 'champion', 'Q1163715', 'P3450', 1887, 1),
    'nba-season': editions('NBA season', 'champion', 'Q155223', 'P3450', 1949, 1),
    'nfl-season': editions('NFL season', 'champion', 'Q1215884', 'P3450', 1920, 1),
    'nhl-season': editions('NHL season', 'champion', 'Q1215892', 'P3450', 1941, 1),
    'wnba-season': editions('WNBA season', 'champion', 'Q2593221', 'P3450', 1997, 1),
    'mls-season': editions('Major League Soccer season', 'champion', 'Q18543', 'P3450', 1996, 1),
    'premier-league': editions('Premier League season', 'champion', 'Q9448', 'P3450', 1992, 1),
    'la-liga': editions('La Liga season', 'champion', 'Q324867', 'P3450', 1929, 1),
    'bundesliga': editions('Bundesliga season', 'champion', 'Q82595', 'P3450', 1963, 1),
    'serie-a': editions('Serie A season', 'champion', 'Q15804', 'P3450', 1898, 1),
    'ligue-1': editions('Ligue 1 season', 'champion', 'Q13394', 'P3450', 1932, 1),
    'eredivisie': editions('Eredivisie season', 'champion', 'Q167541', 'P3450', 1900, 1),
    'primeira-liga': editions('Primeira Liga season', 'champion', 'Q182994', 'P3450', 1935, 1),
    'formula-one': editions('Formula One season', 'champion', 'Q1968', 'P3450', 1950, 1),
    'indycar': editions('IndyCar Series season', 'champion', 'Q832052', 'P3450', 1996, 1),
    'nascar-cup': editions('NASCAR Cup Series season', 'champion', 'Q2707177', 'P3450', 1949, 1),
    'eurovision': editions('Eurovision Song Contest', 'winner', 'Q276', 'P179', 1956, 1),
    'miss-universe': editions('Miss Universe', 'winner', 'Q161376', 'P179', 1952, 1),
    'ballon-dor': editions("Ballon d'Or", 'winner', 'Q166177', 'P179', 1956, 1),
    'uk-general': editions('United Kingdom general election', 'winner', 'Q15283424', 'P31', 1802, 0, value='P991'),
    'india-general': editions('Indian general election', 'winner', 'Q22696407', 'P31', 1920, 0, value='P991'),
    'australia-federal': editions('Australian federal election', 'winner', 'Q22284407', 'P31', 1901, 0, value='P991'),
    'germany-federal': editions('German federal election', 'winner', 'Q1007356', 'P31', 1949, 4, value='P991'),
    'best-actor': award('Academy Award for Best Actor', 'Q103916', 1929, 'awarded to'),
    'best-actress': award('Academy Award for Best Actress', 'Q103618', 1929, 'awarded to'),
    'best-director': award('Academy Award for Best Director', 'Q103360', 1930, 'awarded to'),
    'best-supporting-actor': award('Academy Award for Best Supporting Actor', 'Q106291', 1937, 'awarded to'),
    'best-supporting-actress': award('Academy Award for Best Supporting Actress', 'Q106301', 1937, 'awarded to'),
    'best-animated-feature': award('Academy Award for Best Animated Feature', 'Q106800', 2002, 'awarded to'),
    'pulitzer-fiction': award('Pulitzer Prize for Fiction', 'Q833633', 1938, 'laureate'),
    'pulitzer-poetry': award('Pulitzer Prize for Poetry', 'Q2117891', 1918, 'laureate'),
    'booker': award('Booker Prize', 'Q160082', 1969, 'laureate'),
    'turing': award('Turing Award', 'Q185667', 1966, 'laureate'),
    'abel': award('Abel Prize', 'Q188184', 2003, 'laureate'),
    'mlb-mvp': award('Major League Baseball Most Valuable Player Award', 'Q1514249', 1911, 'awarded to'),
    'cy-young': award('Cy Young Award', 'Q634857', 1956, 'awarded to'),
    'nba-mvp': award('NBA Most Valuable Player Award', 'Q222047', 1956, 'awarded to'),
    'heisman': award('Heisman Trophy', 'Q1035067', 1941, 'awarded to'),
    'grammy-album': award('Grammy Award for Album of the Year', 'Q904528', 1959, 'awarded to'),
    'grammy-record': award('Grammy Award for Record of the Year', 'Q843219', 1959, 'awarded to'),
    'grammy-song': award('Grammy Award for Song of the Year', 'Q1027904', 1959, 'awarded to'),
    'grammy-new-artist': award('Grammy Award for Best New Artist', 'Q1453643', 1960, 'awarded to'),
    'emmy-drama': award('Primetime Emmy Award for Outstanding Drama Series', 'Q989438', 1974, 'awarded to'),
    'tony-musical': award('Tony Award for Best Musical', 'Q1780176', 1949, 'awarded to'),
    'tony-play': award('Tony Award for Best Play', 'Q1799442', 1948, 'awarded to'),
    'hugo-novel': award('Hugo Award for Best Novel', 'Q255032', 1953, 'laureate'),
    'nebula-novel': award('Nebula Award for Best Novel', 'Q266012', 1966, 'laureate'),
    'newbery': award('Newbery Medal', 'Q622813', 1922, 'laureate'),
    'caldecott': award('Caldecott Medal', 'Q1026417', 1938, 'laureate'),
    'time-person': award('Time Person of the Year', 'Q207826', 1927, 'named'),
    'golden-globe-drama': award('Golden Globe Award for Best Motion Picture – Drama', 'Q1011509', 1954, 'awarded to'),
    'palme-dor': award("Palme d'Or", 'Q179808', 1946, 'awarded to'),
    'golden-lion': award('Golden Lion', 'Q209459', 1949, 'awarded to'),
    'goncourt': award('Prix Goncourt', 'Q187300', 1903, 'laureate'),
    'wolf-physics': award('Wolf Prize in Physics', 'Q845333', 1978, 'laureate'),
    'templeton': award('Templeton Prize', 'Q603631', 1974, 'laureate'),
    'pritzker': award('Pritzker Architecture Prize', 'Q133160', 1979, 'laureate'),
    'japan-prize': award('Japan Prize', 'Q908745', 1985, 'laureate'),
    'crafoord': award('Crafoord Prize', 'Q583069', 1982, 'laureate'),
    'breakthrough-physics': award('Breakthrough Prize in Fundamental Physics', 'Q1314470', 2012, 'laureate'),
})

def expected_years(series, this_year=None):
    """the editions a series' rule expects up to last year (the current year's may not have happened yet)"""
    name, pred, first, step, q = SERIES[series]
    last = (this_year or datetime.date.today().year) - 1
    return list(range(first, last + 1, step)) if step else []


def query(series):
    return SERIES[series][4] % _LABEL


def _nameless(v):
    return not v or (v[0] == "Q" and v[1:].isdigit())


def _value(col, raw):
    v = raw.strip()
    if col in ("date", "start", "end"):
        return v[:10] if len(v) >= 10 and v[4] == "-" and not v.startswith("-") else None
    if col == "participants":
        try:
            n = float(v)
            return str(int(n)) if n == int(n) and n > 0 else None
        except ValueError:
            return None
    return None if _nameless(v) else v


def slot_facts(series, bindings):
    """SPARQL bindings → [(subject, predicate, object, year, wikidata url)]: the slot's own value (winner, laureate...),
    every other column the edition query returns, and the lattice links between neighbouring editions. Labels that are
    bare Q-ids are skipped (Wikidata has no English name for them yet); nothing is guessed."""
    name, pred, first, step, q = SERIES[series]
    out, seen, years, items = [], set(), set(), {}
    for b in bindings:
        try:
            year = int(b["year"]["value"])
        except (KeyError, ValueError):
            continue
        if year < first - step:
            continue
        item = (b.get("item") or {}).get("value", "").replace("http://", "https://")
        subj = "%s %d" % (name, year)
        cols = [("valueLabel", pred)] + [(c, p) for c, p in COLUMNS.items() if c in b]
        for col, p in cols:
            if col not in b:
                continue
            v = _value(col, b[col]["value"]) if col != "valueLabel" else (None if _nameless(b[col]["value"].strip()) else b[col]["value"].strip())
            if not v or (col == "itemLabel" and v == subj):
                continue
            key = (year, p, v)
            if key in seen:
                continue
            seen.add(key)
            out.append((subj, p, v, year, item))
            years.add(year)
            items.setdefault(year, item)
    ys = sorted(years)
    for a, b2 in zip(ys, ys[1:]):                       # the lattice: each edition linked to its neighbours
        out.append(("%s %d" % (name, a), "next edition", "%s %d" % (name, b2), a, items[a]))
        out.append(("%s %d" % (name, b2), "previous edition", "%s %d" % (name, a), b2, items[b2]))
    for y in ys:
        out.append(("%s %d" % (name, y), "edition of", name, y, items[y]))
    return sorted(out, key=lambda r: (r[3], r[1], r[2]))


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
    ok("slots: a filled edition becomes a fact; a nameless Q-id is not guessed", f == [("Nobel Prize in Physics 1921", "edition of", "Nobel Prize in Physics", 1921, "https://www.wikidata.org/entity/Q937"),
                                                                                      ("Nobel Prize in Physics 1921", "laureate", "Albert Einstein", 1921, "https://www.wikidata.org/entity/Q937")])
    sb = [{"year": {"value": "1967"}, "item": {"value": "http://www.wikidata.org/entity/Q1"}, "itemLabel": {"value": "Super Bowl I"},
           "valueLabel": {"value": "Green Bay Packers"}, "locationLabel": {"value": "Los Angeles Memorial Coliseum"}, "date": {"value": "1967-01-15T00:00:00Z"},
           "participants": {"value": "2"}, "countryLabel": {"value": "Q30"}},
          {"year": {"value": "1968"}, "item": {"value": "http://www.wikidata.org/entity/Q2"}, "valueLabel": {"value": "Green Bay Packers"}}]
    f = {(a, b, c) for a, b, c, _y, _u in slot_facts("super-bowl", sb)}
    ok("lattice: every column of an edition becomes a fact, neighbours are linked, nameless values skipped",
       {("Super Bowl 1967", "winner", "Green Bay Packers"), ("Super Bowl 1967", "known as", "Super Bowl I"), ("Super Bowl 1967", "date", "1967-01-15"),
        ("Super Bowl 1967", "location", "Los Angeles Memorial Coliseum"), ("Super Bowl 1967", "number of participants", "2"),
        ("Super Bowl 1967", "next edition", "Super Bowl 1968"), ("Super Bowl 1968", "previous edition", "Super Bowl 1967")} <= f
       and not any(c == "Q30" for _a, _b, c in f))
    return out
