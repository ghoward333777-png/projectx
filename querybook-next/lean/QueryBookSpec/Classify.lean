/-!
# Domain classification (`querybook/core/text.py: classify`, `rust/querybook-core/src/text.rs: classify`)

Python:
```
best = DOMAINS[0]
for d in DOMAINS:
    if scores[d] > scores[best]:
        best = d
```
Proved here: the chosen domain has the highest score (`classify_max`), and on a tie the
earlier domain wins (`classify_tie_language`). The `example`s are the score rows of
`contracts/golden_text.tsv`; `tests/test_lean_spec.py` checks that Python agrees with them.
-/

namespace QueryBook

inductive Domain where
  | language | stem | history | video
  deriving DecidableEq, Repr

structure Scores where
  language : Nat
  stem : Nat
  history : Nat
  video : Nat
  deriving DecidableEq, Repr

def Scores.get (s : Scores) : Domain → Nat
  | .language => s.language
  | .stem => s.stem
  | .history => s.history
  | .video => s.video

/-- One iteration of the Python loop. -/
def step (s : Scores) (best d : Domain) : Domain :=
  if s.get d > s.get best then d else best

/-- The loop over DOMAINS (the first iteration, d = language, never changes `best`). -/
def classify (s : Scores) : Domain :=
  step s (step s (step s .language .stem) .history) .video

theorem step_ge (s : Scores) (b d : Domain) :
    s.get b ≤ s.get (step s b d) ∧ s.get d ≤ s.get (step s b d) := by
  unfold step
  split
  · constructor <;> omega
  · constructor <;> omega

/-- The chosen domain's score is at least every domain's score. -/
theorem classify_max (s : Scores) (d : Domain) : s.get d ≤ s.get (classify s) := by
  have h1 := step_ge s .language .stem
  have h2 := step_ge s (step s .language .stem) .history
  have h3 := step_ge s (step s (step s .language .stem) .history) .video
  cases d with
  | language => exact Nat.le_trans h1.1 (Nat.le_trans h2.1 h3.1)
  | stem => exact Nat.le_trans h1.2 (Nat.le_trans h2.1 h3.1)
  | history => exact Nat.le_trans h2.2 h3.1
  | video => exact h3.2

/-- `step` only moves to a strictly higher score. -/
theorem step_keeps_on_tie (s : Scores) (b d : Domain) (h : s.get d ≤ s.get b) : step s b d = b := by
  unfold step
  split
  · omega
  · rfl

/-- All-equal scores (including all zero: text that matches nothing) are filed under language. -/
theorem classify_tie_language (n : Nat) : classify ⟨n, n, n, n⟩ = .language := by
  have e : ∀ b d : Domain, step ⟨n, n, n, n⟩ b d = b := by
    intro b d
    apply step_keeps_on_tie
    cases b <;> cases d <;> exact Nat.le_refl n
  unfold classify
  rw [e, e, e]

-- golden_text.tsv score rows (language, stem, history, video) and their expected domain
example : classify ⟨0, 0, 0, 0⟩ = .language := by decide
example : classify ⟨0, 1, 0, 0⟩ = .stem := by decide
example : classify ⟨0, 0, 2, 0⟩ = .history := by decide
example : classify ⟨3, 0, 0, 0⟩ = .language := by decide
example : classify ⟨0, 0, 0, 7⟩ = .video := by decide
example : classify ⟨0, 5, 0, 0⟩ = .stem := by decide
example : classify ⟨0, 0, 4, 0⟩ = .history := by decide
-- ties: the earlier domain wins
example : classify ⟨2, 2, 1, 0⟩ = .language := by decide
example : classify ⟨0, 3, 3, 3⟩ = .stem := by decide

end QueryBook
