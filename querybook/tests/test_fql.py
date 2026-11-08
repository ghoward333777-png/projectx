import shutil
import tempfile
import unittest
from pathlib import Path

from querybook.core.fql import FQLError, Evaluator, parse, run_fql
from querybook.core.store import FQLStore


class FQLTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.store = FQLStore(self.dir / "t.fqldb")
        self.w = Evaluator(self.store)
        for term, n, pos in (("ephemeral", 3, "adjective"), ("lucid", 1, "adjective"), ("lexicon", 2, "noun")):
            self.w.run(f'Language.create({{ term: "{term}", n: {n}, pos: "{pos}", body: "about {term}" }})')

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def q(self, src):
        return Evaluator(self.store, readonly=True).run(src)

    def test_where_map_order_take(self):
        self.assertEqual(self.q('Language.where(.n > 1).map(.term).toArray()'), ["ephemeral", "lexicon"])
        self.assertEqual(self.q('Language.all().order(desc(.n)).take(2) { term }'),
                         {"data": [{"term": "ephemeral"}, {"term": "lexicon"}]})
        self.assertEqual(self.q('Language.all().order(.pos, desc(.term)).map(.term).toArray()'),
                         ["lucid", "ephemeral", "lexicon"])

    def test_projection_with_computed_fields(self):
        self.assertEqual(self.q('Language.firstWhere(.term == "lucid") { term, double: .n * 2, up: .term.toUpperCase() }'),
                         {"term": "lucid", "double": 2, "up": "LUCID"})

    def test_lambdas_let_and_arrays(self):
        self.assertEqual(self.q('let k = 10\n[1, 2, 3].map(x => x * k).where(x => x > 0)'), [10, 20, 30])
        self.assertEqual(self.q('let f = (a, b) => a + b; f(2, 3)'), 5)
        self.assertEqual(self.q('[3, 1, 2].order().first()'), 1)
        self.assertEqual(self.q('Language.all().any(.n == 2) && Language.all().every(.n > 0)'), True)

    def test_search_and_by_id(self):
        doc = self.q('Language.search("lucid").first()')
        self.assertEqual(doc["term"], "lucid")
        self.assertEqual(self.q(f'Language.byId("{doc["id"]}").term'), "lucid")
        self.assertIsNone(self.q('Language.byId("nope")'))

    def test_missing_fields_are_null_and_compare_false(self):
        self.assertEqual(self.q('Language.where(.missing > 3).count()'), 0)
        self.assertEqual(self.q('Language.all().first().missing.deeper'), None)

    def test_update_delete_and_readonly(self):
        out = self.w.run('Language.firstWhere(.term == "lucid").update({ n: 9, pos: null }) { n, pos }')
        self.assertEqual(out, {"n": 9, "pos": None})
        self.w.run('Language.firstWhere(.term == "lucid").delete()')
        self.assertEqual(self.q('Language.count()'), 2)
        with self.assertRaises(FQLError) as ctx:
            self.q('Language.create({ term: "x" })')
        self.assertEqual(ctx.exception.code, "readonly")

    def test_create_is_idempotent(self):
        a = self.w.run('Language.create({ term: "same" })')
        b = self.w.run('Language.create({ term: "same" })')
        self.assertEqual(a["id"], b["id"])

    def test_collection_namespace(self):
        self.assertEqual(self.q('Collection.all()'), [{"name": "Language", "count": 3}])

    def test_errors_have_codes_and_positions(self):
        cases = {'Language.where(.n >': "syntax_error", '"a" < 3': "type_error", '1 / 0': "divide_by_zero",
                 'nope': "unbound_variable", '.term': "invalid_field_access", 'Language.frobnicate()': "invalid_method",
                 '"unterminated': "syntax_error", 'lowercase.create({})': "unbound_variable"}
        for src, code in cases.items():
            res = run_fql(self.store, src, readonly=True)
            with self.subTest(src=src):
                self.assertFalse(res["ok"])
                self.assertEqual(res["error"]["code"], code)
                self.assertIsInstance(res["error"]["pos"], int)

    def test_parser_round_trip_shapes(self):
        node = parse('History.where(.start_year <= 1850 && .end_year >= 1750).order(.start_year).take(5) { title }')
        self.assertEqual(type(node).__name__, "Projection")

    def test_numbers(self):
        self.assertEqual(self.q('5 / 2'), 2.5)
        self.assertEqual(self.q('6 / 3'), 2)
        self.assertEqual(self.q('1_000 + 2.5e3'), 3500.0)
        self.assertEqual(self.q('-(2 + 3) * 2 % 7'), 4)


if __name__ == "__main__":
    unittest.main()
