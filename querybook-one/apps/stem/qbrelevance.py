"""The relevance test — part of the harvest engine: can QueryBook answer what people actually ask?

A billion facts is not the measure. After three weeks the store held 1.5 billion and had no record of Ed Sullivan, and
took Babe Ruth for a baseball card. This is the measure: a fixed list of the best-known people, places, institutions,
events and works, by field (politics, entertainment, music, art and letters, science and education, religion, sport,
monuments and places, institutions, events, works, everyday things). For each one the store is asked the way the Ask
box asks; the answer must be the RIGHT KIND of thing (a person for a person) and hold the facts that make an answer (a
birth date and an occupation; a place's country; an event's date). The result is a score, a breakdown by field, the
list of misses, and a diagnosis from how much of Wikidata has ever been read. Every miss goes to the demand agent, which
fetches it at once, so the test also repairs what it finds. It runs by itself once a day (Control Panel monitor) and on
demand; the score's history is kept, so "is the store getting more useful?" has a number.

Standard library only. sense.py judges kinds; qbbulk finds the entities and holds the demand queue.
"""
import json
import os
import threading
import time

import sense

NAME = "_relevance.json"
# (field, the name as people say it, the kind of thing it must turn out to be)
BENCH = [
    ("Politics", "George Washington", "human"), ("Politics", "Abraham Lincoln", "human"), ("Politics", "Thomas Jefferson", "human"),
    ("Politics", "Franklin D. Roosevelt", "human"), ("Politics", "Theodore Roosevelt", "human"), ("Politics", "John F. Kennedy", "human"),
    ("Politics", "Ronald Reagan", "human"), ("Politics", "Barack Obama", "human"), ("Politics", "Winston Churchill", "human"),
    ("Politics", "Martin Luther King Jr.", "human"), ("Politics", "Benjamin Franklin", "human"), ("Politics", "Eleanor Roosevelt", "human"),
    ("Politics", "Susan B. Anthony", "human"), ("Politics", "Frederick Douglass", "human"), ("Politics", "Nelson Mandela", "human"),
    ("Politics", "Mahatma Gandhi", "human"), ("Politics", "Napoleon", "human"), ("Politics", "Queen Victoria", "human"),
    ("Entertainment", "Ed Sullivan", "human"), ("Entertainment", "Lucille Ball", "human"), ("Entertainment", "Walt Disney", "human"),
    ("Entertainment", "Charlie Chaplin", "human"), ("Entertainment", "Marilyn Monroe", "human"), ("Entertainment", "Johnny Carson", "human"),
    ("Entertainment", "Oprah Winfrey", "human"), ("Entertainment", "Bob Hope", "human"), ("Entertainment", "John Wayne", "human"),
    ("Entertainment", "Audrey Hepburn", "human"), ("Entertainment", "Alfred Hitchcock", "human"), ("Entertainment", "Steven Spielberg", "human"),
    ("Entertainment", "Shirley Temple", "human"), ("Entertainment", "Humphrey Bogart", "human"), ("Entertainment", "Jackie Gleason", "human"),
    ("Entertainment", "Walter Cronkite", "human"), ("Entertainment", "Fred Rogers", "human"), ("Entertainment", "Jim Henson", "human"),
    ("Music", "Elvis Presley", "human"), ("Music", "Frank Sinatra", "human"), ("Music", "Louis Armstrong", "human"),
    ("Music", "Michael Jackson", "human"), ("Music", "Bob Dylan", "human"), ("Music", "Aretha Franklin", "human"),
    ("Music", "Johnny Cash", "human"), ("Music", "Ella Fitzgerald", "human"), ("Music", "Duke Ellington", "human"),
    ("Music", "Ludwig van Beethoven", "human"), ("Music", "Wolfgang Amadeus Mozart", "human"), ("Music", "Johann Sebastian Bach", "human"),
    ("Music", "The Beatles", "organization"), ("Music", "John Lennon", "human"), ("Music", "Ray Charles", "human"),
    ("Music", "Bing Crosby", "human"), ("Music", "Madonna", "human"), ("Music", "George Gershwin", "human"),
    ("Art and letters", "Leonardo da Vinci", "human"), ("Art and letters", "Michelangelo", "human"), ("Art and letters", "Pablo Picasso", "human"),
    ("Art and letters", "Vincent van Gogh", "human"), ("Art and letters", "Andy Warhol", "human"), ("Art and letters", "Norman Rockwell", "human"),
    ("Art and letters", "William Shakespeare", "human"), ("Art and letters", "Mark Twain", "human"), ("Art and letters", "Ernest Hemingway", "human"),
    ("Art and letters", "Charles Dickens", "human"), ("Art and letters", "Jane Austen", "human"), ("Art and letters", "Maya Angelou", "human"),
    ("Art and letters", "Edgar Allan Poe", "human"), ("Art and letters", "Emily Dickinson", "human"), ("Art and letters", "Frank Lloyd Wright", "human"),
    ("Art and letters", "Claude Monet", "human"), ("Art and letters", "Rembrandt", "human"), ("Art and letters", "Homer", "human"),
    ("Science and education", "Albert Einstein", "human"), ("Science and education", "Isaac Newton", "human"), ("Science and education", "Marie Curie", "human"),
    ("Science and education", "Thomas Edison", "human"), ("Science and education", "Galileo Galilei", "human"), ("Science and education", "Nikola Tesla", "human"),
    ("Science and education", "Alexander Graham Bell", "human"), ("Science and education", "Helen Keller", "human"), ("Science and education", "Booker T. Washington", "human"),
    ("Science and education", "Maria Montessori", "human"), ("Science and education", "John Dewey", "human"), ("Science and education", "Neil Armstrong", "human"),
    ("Science and education", "Louis Pasteur", "human"), ("Science and education", "Florence Nightingale", "human"), ("Science and education", "George Washington Carver", "human"),
    ("Science and education", "Aristotle", "human"), ("Science and education", "Stephen Hawking", "human"), ("Science and education", "Jonas Salk", "human"),
    ("Religion", "Jesus", "human"), ("Religion", "Muhammad", "human"), ("Religion", "Gautama Buddha", "human"),
    ("Religion", "Moses", "human"), ("Religion", "Martin Luther", "human"), ("Religion", "Billy Graham", "human"),
    ("Religion", "Mother Teresa", "human"), ("Religion", "John Paul II", "human"), ("Religion", "Confucius", "human"),
    ("Religion", "Paul the Apostle", "human"), ("Religion", "Francis of Assisi", "human"), ("Religion", "John Wesley", "human"),
    ("Religion", "Catholic Church", "organization"), ("Religion", "Christianity", "thing"), ("Religion", "Islam", "thing"),
    ("Religion", "Judaism", "thing"), ("Religion", "Buddhism", "thing"), ("Religion", "Bible", "thing"),
    ("Sport", "Babe Ruth", "human"), ("Sport", "Jackie Robinson", "human"), ("Sport", "Muhammad Ali", "human"),
    ("Sport", "Michael Jordan", "human"), ("Sport", "Jesse Owens", "human"), ("Sport", "Lou Gehrig", "human"),
    ("Sport", "Joe DiMaggio", "human"), ("Sport", "Hank Aaron", "human"), ("Sport", "Jim Thorpe", "human"),
    ("Sport", "Arnold Palmer", "human"), ("Sport", "Billie Jean King", "human"), ("Sport", "Pelé", "human"),
    ("Sport", "New York Yankees", "organization"), ("Sport", "baseball", "thing"), ("Sport", "Olympic Games", "thing"),
    ("Monuments and places", "Statue of Liberty", "place"), ("Monuments and places", "Lincoln Memorial", "place"), ("Monuments and places", "Mount Rushmore", "place"),
    ("Monuments and places", "Washington Monument", "place"), ("Monuments and places", "White House", "place"), ("Monuments and places", "Golden Gate Bridge", "place"),
    ("Monuments and places", "Empire State Building", "place"), ("Monuments and places", "Eiffel Tower", "place"), ("Monuments and places", "Great Wall of China", "place"),
    ("Monuments and places", "Taj Mahal", "place"), ("Monuments and places", "Colosseum", "place"), ("Monuments and places", "Grand Canyon", "place"),
    ("Monuments and places", "Niagara Falls", "place"), ("Monuments and places", "Mount Everest", "place"), ("Monuments and places", "Mississippi River", "place"),
    ("Monuments and places", "New York City", "place"), ("Monuments and places", "Paris", "place"), ("Monuments and places", "London", "place"),
    ("Monuments and places", "California", "place"), ("Monuments and places", "Yellowstone National Park", "place"), ("Monuments and places", "Hoover Dam", "place"),
    ("Institutions", "Harvard University", "organization"), ("Institutions", "Yale University", "organization"), ("Institutions", "Smithsonian Institution", "organization"),
    ("Institutions", "United Nations", "organization"), ("Institutions", "NASA", "organization"), ("Institutions", "Library of Congress", "organization"),
    ("Institutions", "Federal Bureau of Investigation", "organization"), ("Institutions", "Supreme Court of the United States", "organization"), ("Institutions", "Ford Motor Company", "organization"),
    ("Institutions", "The New York Times", "organization"), ("Institutions", "Metropolitan Museum of Art", "organization"), ("Institutions", "University of Oxford", "organization"),
    ("Institutions", "Boy Scouts of America", "organization"), ("Institutions", "Republican Party", "organization"), ("Institutions", "Democratic Party", "organization"),
    ("Events", "American Civil War", "event"), ("Events", "World War II", "event"), ("Events", "World War I", "event"),
    ("Events", "American Revolutionary War", "event"), ("Events", "Great Depression", "event"), ("Events", "Apollo 11", "event"),
    ("Events", "attack on Pearl Harbor", "event"), ("Events", "September 11 attacks", "event"), ("Events", "Vietnam War", "event"),
    ("Events", "French Revolution", "event"), ("Events", "Battle of Gettysburg", "event"), ("Events", "Boston Tea Party", "event"),
    ("Events", "Cuban Missile Crisis", "event"), ("Events", "Woodstock", "event"), ("Events", "Black Death", "event"),
    ("Works", "The Ed Sullivan Show", "work"), ("Works", "I Love Lucy", "work"), ("Works", "The Wizard of Oz", "work"),
    ("Works", "Gone with the Wind", "work"), ("Works", "Star Wars", "work"), ("Works", "Casablanca", "work"),
    ("Works", "Mona Lisa", "work"), ("Works", "Hamlet", "work"), ("Works", "The Star-Spangled Banner", "work"),
    ("Works", "Moby-Dick", "work"), ("Works", "Citizen Kane", "work"), ("Works", "Sesame Street", "work"),
    ("Everyday things", "drinking fountain", "thing"), ("Everyday things", "telephone", "thing"), ("Everyday things", "printing press", "thing"),
    ("Everyday things", "piano", "thing"), ("Everyday things", "jazz", "thing"), ("Everyday things", "Christmas", "thing"),
    ("Everyday things", "photosynthesis", "thing"), ("Everyday things", "gold", "thing"), ("Everyday things", "dog", "thing"),
    ("Everyday things", "bicycle", "thing"), ("Everyday things", "coffee", "thing"), ("Everyday things", "light bulb", "thing"),
]
# what must be held for an answer to be an answer, by kind: any one predicate of EACH group
NEEDS = {
    "human": (("date of birth",), ("occupation", "description", "position held")),
    "place": (("country", "coordinate location", "located in the administrative territorial entity", "description"),),
    "organization": (("inception", "description", "country", "headquarters location", "instance of"),),
    "event": (("point in time", "start time", "end time", "description"),),
    "work": (("publication date", "inception", "creator", "author", "director", "description", "instance of"),),
    "thing": (("description", "instance of", "subclass of"),),
}
# kinds that count as right for what was expected (a monument may be recorded as a building, a show as a programme...)
ACCEPT = {"human": ("human",), "place": ("place", "organization", "thing"), "organization": ("organization", "place", "thing"),
          "event": ("event", "thing"), "work": ("work", "depiction", "thing"), "thing": ("thing", "work", "place", "organization", "event", "species", "substance", "award", "depiction")}
_RUNNING = {}


def question_for(name, kind):
    return ("Who is %s?" if kind == "human" else "What is %s?") % name


def judge(name, kind, found):
    """one subject: found = qbbulk.find_entities(...). Returns the row of the report."""
    ents, facts = found.get("entities") or [], found.get("facts") or []
    res = sense.answer_for(question_for(name, kind), name, ents, facts)
    pick = res["entity"]
    row = {"name": name, "expected": kind, "matches": len(ents), "picked": sense.clean(pick.get("subject") or ""), "kind": pick.get("kind") or "",
           "said": res["said"][:300], "facts": len(res["facts"])}
    if not ents:
        return dict(row, result="missing", why="no record of this name at all")
    if pick["kind"] not in ACCEPT[kind]:
        others = ", ".join("%s (%s)" % (sense.clean(r["subject"]), r["kind"]) for r in pick["ranked"][:4])
        return dict(row, result="wrong kind", why="only %s by this name: %s" % (sense.KIND_WORD.get(pick["kind"], "a thing"), others))
    preds = {str(f.get("predicate") or "").lower() for f in res["facts"]}
    lacking = [" or ".join(g) for g in NEEDS[kind if kind in NEEDS else "thing"] if not any(p in preds for p in g)]
    if lacking:
        return dict(row, result="thin", why="the record lacks: " + "; ".join(lacking))
    return dict(row, result="answerable", why="")


def diagnose(rows, coverage, demand_pending):
    """why the misses are misses, from what the engine knows about its own harvest"""
    n = len(rows) or 1
    cnt = {k: sum(1 for r in rows if r["result"] == k) for k in ("answerable", "missing", "wrong kind", "thin")}
    out = []
    if cnt["missing"]:
        share = coverage.get("share")
        out.append("%d of %d well-known subjects have no record at all. %s" % (cnt["missing"], n, coverage.get("text") or ""))
        if share is not None and share < 0.95:
            out.append("A subject in a part of the dump that was never read cannot be in the store, however many facts it holds.")
    if cnt["wrong kind"]:
        out.append("%d resolve only to something ABOUT the subject (a card, a portrait, a film, an award) and not the subject itself — its own "
                   "record was never read." % cnt["wrong kind"])
    if cnt["thin"]:
        out.append("%d have a record too thin to answer from (no date of birth, no description)." % cnt["thin"])
    if cnt["missing"] or cnt["wrong kind"] or cnt["thin"]:
        out.append("What happens now: every miss was sent to the demand agent, which fetches it from Wikidata directly (%d waiting); the hot lattices "
                   "harvest the best-known people, places, institutions, events and works of each kind first; and the dump lanes read the parts never "
                   "read before the ones already held." % demand_pending)
    else:
        out.append("Every subject of the test is answerable.")
    return out


def run(commons_folder, bulk=None, limit=None, note=True):
    """the whole test. bulk: the qbbulk module (tests pass a stand-in with find_entities, dump_coverage, demand_note)."""
    if bulk is None:
        import qbbulk as bulk
    t0 = time.time()
    rows = []
    for field, name, kind in BENCH[:limit] if limit else BENCH:
        try:
            found = bulk.find_entities(commons_folder, name, 6)
        except Exception as e:
            found = {"entities": [], "facts": [], "error": str(e)}
        rows.append(dict(judge(name, kind, found), field=field))
    pending = 0
    if note:
        for r in rows:
            if r["result"] != "answerable":
                try:
                    pending = bulk.demand_note(commons_folder, r["name"], question_for(r["name"], r["expected"]), "relevance test: " + r["result"]).get("pending", pending)
                except Exception:
                    pass
    try:
        cov = bulk.dump_coverage(commons_folder)
    except Exception as e:
        cov = {"share": None, "text": "The coverage of the dump could not be read (%s)." % e}
    fields = {}
    for r in rows:
        f = fields.setdefault(r["field"], {"field": r["field"], "answerable": 0, "of": 0})
        f["of"] += 1
        f["answerable"] += 1 if r["result"] == "answerable" else 0
    ok = sum(1 for r in rows if r["result"] == "answerable")
    out = {"at": time.time(), "seconds": round(time.time() - t0, 1), "answerable": ok, "of": len(rows), "percent": round(100 * ok / max(1, len(rows))),
           "fields": list(fields.values()), "misses": [r for r in rows if r["result"] != "answerable"], "rows": rows,
           "coverage": {k: cov.get(k) for k in ("share", "parts", "read", "current", "text")}, "diagnosis": diagnose(rows, cov, pending),
           "demand_pending": pending}
    path = os.path.join(commons_folder, "shards", NAME)
    prev = last(commons_folder) or {}
    out["history"] = ((prev.get("history") or []) + [{"at": out["at"], "percent": out["percent"], "answerable": ok, "of": len(rows)}])[-60:]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(path + ".tmp", path)
    except OSError:
        pass
    return out


def last(commons_folder):
    try:
        with open(os.path.join(commons_folder, "shards", NAME), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def summary(r):
    if not r:
        return "The relevance test has not run yet."
    worst = sorted(r.get("fields") or [], key=lambda f: f["answerable"] / max(1, f["of"]))[:3]
    return "Relevance: %d of %d well-known subjects answerable (%d%%). Weakest: %s." % (
        r["answerable"], r["of"], r["percent"], ", ".join("%s %d/%d" % (f["field"], f["answerable"], f["of"]) for f in worst) or "—")


def run_in_background(commons_folder, every_s=86400, force=False):
    """started by the Control Panel's monitor: the test runs once a day by itself (never two at once)"""
    prev = last(commons_folder)
    if _RUNNING.get(commons_folder) or (not force and prev and time.time() - (prev.get("at") or 0) < every_s):
        return False
    _RUNNING[commons_folder] = True

    def go():
        try:
            run(commons_folder)
        finally:
            _RUNNING.pop(commons_folder, None)
    threading.Thread(target=go, daemon=True, name="qb-relevance").start()
    return True


def running(commons_folder):
    return bool(_RUNNING.get(commons_folder))


def self_test():
    results = []
    man, card = "Babe Ruth (Q213812)", "Babe Ruth (Q99)"
    f_man = [{"subject": man, "predicate": p, "object": o} for p, o in (("instance of", "human (Q5)"), ("date of birth", "1895-02-06"),
             ("occupation", "baseball player (Q10871364)"), ("place of birth", "Baltimore (Q5092)"), ("Baseball-Reference ID", "ruthba01"))]
    f_card = [{"subject": card, "predicate": p, "object": o} for p, o in (("instance of", "baseball card (Q809892)"), ("depicts", man))]

    class Fake:
        noted = []

        def __init__(self, world):
            self.world = world

        def find_entities(self, cf, name, top=6):
            return self.world.get(name) or {"entities": [], "facts": []}

        def dump_coverage(self, cf):
            return {"share": 0.31, "parts": 147, "read": 46, "current": "2026-11-11", "text": "46 of 147 parts (31%) have ever been read."}

        def demand_note(self, cf, subject, question="", why=""):
            Fake.noted.append(subject)
            return {"queued": True, "pending": len(Fake.noted)}
    both = {"entities": [{"subject": card, "facts": 2}, {"subject": man, "facts": 5}], "facts": f_card + f_man}
    r1 = judge("Babe Ruth", "human", both)
    results.append(("the man is chosen over the card of the same name, and counts as answerable (born, occupation)",
                    r1["result"] == "answerable" and r1["picked"] == "Babe Ruth" and r1["kind"] == "human" and "1895" in r1["said"]))
    r2 = judge("Babe Ruth", "human", {"entities": [{"subject": card, "facts": 2}], "facts": f_card})
    results.append(("only the card is held: 'wrong kind' — a baseball card is not Babe Ruth", r2["result"] == "wrong kind" and "depicting" in r2["why"]))
    r3 = judge("Ed Sullivan", "human", {"entities": [], "facts": []})
    results.append(("nothing by that name: missing", r3["result"] == "missing"))
    r4 = judge("Babe Ruth", "human", {"entities": [{"subject": man, "facts": 1}], "facts": [f_man[0]]})
    results.append(("a record with no birth date or occupation is too thin to answer from", r4["result"] == "thin" and "date of birth" in r4["why"]))
    import tempfile
    tmp = tempfile.mkdtemp()
    Fake.noted = []
    out = run(tmp, Fake({"Babe Ruth": both}))
    results.append(("the whole test: a score, a breakdown by field, the misses, and each miss sent to the demand agent",
                    out["of"] == len(BENCH) and out["answerable"] == 1 and len(out["fields"]) == len({b[0] for b in BENCH})
                    and len(Fake.noted) == len(BENCH) - 1 and "Ed Sullivan" in Fake.noted and "Babe Ruth" not in Fake.noted))
    results.append(("the diagnosis says why: how much of the dump was ever read, and what happens now",
                    any("31%" in d for d in out["diagnosis"]) and any("demand agent" in d for d in out["diagnosis"])))
    out2 = run(tmp, Fake({"Babe Ruth": both}), limit=5, note=False)
    results.append(("the score's history is kept, run after run", len(out2["history"]) == 2 and last(tmp)["history"][0]["of"] == len(BENCH)))
    results.append(("the test list covers the fields asked for, each well-known name once",
                    len(BENCH) >= 180 and len({b[1] for b in BENCH}) == len(BENCH)
                    and {"Politics", "Entertainment", "Music", "Art and letters", "Science and education", "Religion"} <= {b[0] for b in BENCH}))
    for name, ok in results:
        print("  [%s] %s" % ("OK" if ok else "FAIL", name))
    passed = sum(1 for _, ok in results if ok)
    print("\n  %d of %d checks passed" % (passed, len(results)))
    return passed == len(results)


if __name__ == "__main__":
    import sys
    sys.exit(0 if self_test() else 1)
