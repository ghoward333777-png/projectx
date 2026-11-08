/-!
# The billion-row guard (`querybook/core/fql/evaluator.py: call_sequence`, `FSet.bounded`)

Sets over the suite's bulk facts (`Facts.all()`, `Commons.all()`, ...) are *unbounded*.
Python refuses `order count last reverse distinct toArray every includes concat` on an
unbounded set with the error `unbounded_set`; `take(n)` makes a set bounded; every other
method keeps the set's boundedness.

Proved here: a pipeline is refused exactly when a whole-set method meets an unbounded set
(`guard_refuses`), a bounded set accepts every pipeline (`bounded_total`), and putting
`take n` first makes any pipeline acceptable (`take_first`). The `example`s are the cases in
`tests/test_legacy.py`; `tests/test_lean_spec.py` runs the same pipelines through the evaluator.
-/

namespace QueryBook

inductive Bound where
  | bounded | unbounded
  deriving DecidableEq, Repr

inductive Method where
  | where_ | map | flatMap | first | firstWhere | any | nonEmpty | isEmpty | drop
  | take
  | order | count | last | reverse | distinct | toArray | every | includes | concat
  deriving DecidableEq, Repr

/-- Python `WHOLE_SET_METHODS`. -/
def Method.whole : Method → Bool
  | .order | .count | .last | .reverse | .distinct | .toArray | .every | .includes | .concat => true
  | _ => false

/-- One method applied to a set: `none` is the `unbounded_set` refusal. -/
def apply : Bound → Method → Option Bound
  | _, .take => some .bounded
  | .unbounded, m => if m.whole then none else some .unbounded
  | .bounded, _ => some .bounded

def run : Bound → List Method → Option Bound
  | b, [] => some b
  | b, m :: ms =>
    match apply b m with
    | none => none
    | some b' => run b' ms

theorem guard_refuses (m : Method) (h : m.whole = true) : apply .unbounded m = none := by
  cases m <;> simp_all [apply, Method.whole]

theorem guard_allows (m : Method) (h : m.whole = false) : apply .unbounded m ≠ none := by
  cases m <;> simp_all [apply, Method.whole]

theorem bounded_total (ms : List Method) : run .bounded ms = some .bounded := by
  induction ms with
  | nil => rfl
  | cons m ms ih => cases m <;> simp [run, apply, ih]

theorem take_first (b : Bound) (ms : List Method) : run b (.take :: ms) = some .bounded := by
  cases b <;> simp [run, apply, bounded_total]

-- the cases in tests/test_legacy.py
example : run .unbounded [.count] = none := by decide                              -- Facts.all().count()
example : run .unbounded [.order] = none := by decide                              -- Facts.all().order(.subject)
example : run .unbounded [.where_, .toArray] = none := by decide                   -- Facts.where(...).toArray()
example : run .unbounded [.where_, .take, .count] = some .bounded := by decide     -- ...take(3).count()
example : run .unbounded [.take, .map, .toArray] = some .bounded := by decide      -- inDataset(..).take(5).map(..).toArray()
example : run .unbounded [.where_, .first] = some .unbounded := by decide          -- first() stops early: allowed

end QueryBook
