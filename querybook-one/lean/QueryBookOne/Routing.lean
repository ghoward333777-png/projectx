/-!
# Answer routing: the Digital Synaptic Network (apps/_core/qbdsn.py `dsn_search`)

Each kind of question keeps one pathway strength per dataset. Constants: THETA 0.30, ETA 0.10, SILENCE 0.15, DRIFT 0.002;
a new pathway starts at 0.5.

  the dataset answered      s ← s + ETA·(1 − s)
  the dataset had nothing   s ← s − SILENCE·s
  before each lookup        s ← s + DRIFT·(0.5 − s)   if s < 0.5   (weak pathways recover slowly)

A pathway is asked first when s ≥ THETA. Python rounds to 4 decimals after each update; see Synapse.lean on rounding.
-/
import Mathlib

namespace QueryBookOne.Routing

def START : ℝ := 1 / 2
def THETA : ℝ := 3 / 10
def ETA : ℝ := 1 / 10
def SILENCE : ℝ := 3 / 20
def DRIFT : ℝ := 1 / 500

def hit (s : ℝ) : ℝ := s + ETA * (1 - s)
def miss (s : ℝ) : ℝ := s - SILENCE * s
noncomputable def recover (s : ℝ) : ℝ := if s < 1 / 2 then s + DRIFT * (1 / 2 - s) else s

/-- Every new pathway is strong enough to be asked. -/
theorem new_pathway_is_asked : THETA ≤ START := by unfold THETA START; norm_num

theorem hit_bounds (s : ℝ) (h0 : 0 ≤ s) (h1 : s ≤ 1) : s ≤ hit s ∧ hit s ≤ 1 := by
  unfold hit ETA; constructor <;> nlinarith

theorem miss_bounds (s : ℝ) (h0 : 0 ≤ s) : 0 ≤ miss s ∧ miss s ≤ s := by
  unfold miss SILENCE; constructor <;> nlinarith

/-- Recovery moves a weak pathway toward 0.5 and never past it; a strong pathway is left alone. -/
theorem recover_no_overshoot (s : ℝ) (h : s < 1 / 2) : s ≤ recover s ∧ recover s ≤ 1 / 2 := by
  unfold recover DRIFT; rw [if_pos h]; constructor <;> nlinarith

theorem recover_strong (s : ℝ) (h : 1 / 2 ≤ s) : recover s = s := by
  unfold recover; rw [if_neg (not_lt.mpr h)]

theorem recover_bounds (s : ℝ) (h0 : 0 ≤ s) (h1 : s ≤ 1) : 0 ≤ recover s ∧ recover s ≤ 1 := by
  by_cases h : s < 1 / 2
  · have := recover_no_overshoot s h; constructor <;> linarith [this.1, this.2]
  · rw [recover_strong s (not_lt.mp h)]; exact ⟨h0, h1⟩

inductive Event where
  | answered
  | empty
  | lookup

noncomputable def step : Event → ℝ → ℝ
  | .answered, s => hit s
  | .empty, s => miss s
  | .lookup, s => recover s

/-- Whatever sequence of lookups, answers and empty results happens, every pathway strength stays in [0, 1]. -/
theorem strength_stays_in_unit (es : List Event) (s : ℝ) (h0 : 0 ≤ s) (h1 : s ≤ 1) :
    0 ≤ es.foldl (fun x e => step e x) s ∧ es.foldl (fun x e => step e x) s ≤ 1 := by
  induction es generalizing s with
  | nil => exact ⟨h0, h1⟩
  | cons e es ih =>
    simp only [List.foldl]
    apply ih
    · cases e with
      | answered => have := hit_bounds s h0 h1; simp only [step]; linarith [this.1]
      | empty => have := miss_bounds s h0; simp only [step]; exact this.1
      | lookup => exact (recover_bounds s h0 h1).1
    · cases e with
      | answered => exact (hit_bounds s h0 h1).2
      | empty => have := miss_bounds s h0; simp only [step]; linarith [this.2]
      | lookup => exact (recover_bounds s h0 h1).2

end QueryBookOne.Routing
