"""QueryBook FQL — a Fauna-FQL-v10-style query language for the shared store.

    Language.where(.term == "ephemeral").first()
    History.search("printing press").order(.start_year).take(5) { title, start_year }
    let recent = Stem.all().order(desc(.ts)).take(3)
    recent.map(.title)
    Source.create({ kind: "feed", url: "https://example.org/rss", domain: "history" })
"""

from querybook.core.fql.errors import FQLError
from querybook.core.fql.evaluator import Evaluator, run_fql
from querybook.core.fql.parser import parse

__all__ = ["FQLError", "Evaluator", "parse", "run_fql"]
