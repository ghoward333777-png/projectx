/-!
# Network memory (apps/_core/qbsynapse.py)

Constants: INIT 0.20, ETA 0.10, DEPRESS 0.25, THETA 0.30, DECAY_PER_DAY 0.05, CONSOLIDATED_DECAY_PER_DAY 0.01,
CONSOLIDATE_AFTER 20 (and four good outcomes for every bad one).

  success   s ← s + ETA·(1 − s)
  failure   s ← s − DEPRESS·s
  idle      s ← s · (1 − rate)^days          (rate 0.01 when consolidated, else 0.05)
  threshold θ = THETA + 0.4 · bad / (good + bad)

The Python code also rounds each result to 4 decimals; the bounds proved here hold for the exact values, and rounding to
4 decimals keeps a value in [0, 1] because 0 and 1 are themselves 4-decimal numbers.
-/
import Mathlib

namespace QueryBookOne.Synapse

def INIT : ℝ := 1 / 5
def ETA : ℝ := 1 / 10
def DEPRESS : ℝ := 1 / 4
def THETA : ℝ := 3 / 10
def DECAY : ℝ := 1 / 20
def CONSOLIDATED_DECAY : ℝ := 1 / 100

def potentiate (s : ℝ) : ℝ := s + ETA * (1 - s)
def depress (s : ℝ) : ℝ := s - DEPRESS * s
noncomputable def fade (rate days s : ℝ) : ℝ := s * (1 - rate) ^ days
noncomputable def threshold (good bad : ℕ) : ℝ :=
  if good + bad = 0 then THETA else THETA + 2 / 5 * ((bad : ℝ) / ((good : ℝ) + (bad : ℝ)))
def consolidated (good bad : ℕ) : Prop := 20 ≤ good ∧ 4 * bad ≤ good

/-- A new synapse starts weak but inside [0, 1]. -/
theorem init_in_unit : 0 ≤ INIT ∧ INIT ≤ 1 := by unfold INIT; constructor <;> norm_num

/-- Success never weakens a synapse and never takes it above 1. -/
theorem potentiate_bounds (s : ℝ) (h0 : 0 ≤ s) (h1 : s ≤ 1) : s ≤ potentiate s ∧ potentiate s ≤ 1 := by
  unfold potentiate ETA; constructor <;> nlinarith

/-- Below full strength, success strictly strengthens. -/
theorem potentiate_strict (s : ℝ) (h1 : s < 1) : s < potentiate s := by
  unfold potentiate ETA; nlinarith

/-- Failure never strengthens a synapse and never takes it below 0. -/
theorem depress_bounds (s : ℝ) (h0 : 0 ≤ s) : 0 ≤ depress s ∧ depress s ≤ s := by
  unfold depress DEPRESS; constructor <;> nlinarith

/-- Idle time only fades a synapse, and never below 0. -/
theorem fade_bounds (rate days s : ℝ) (hr0 : 0 ≤ rate) (hr1 : rate ≤ 1) (hd : 0 ≤ days) (h0 : 0 ≤ s) :
    0 ≤ fade rate days s ∧ fade rate days s ≤ s := by
  unfold fade
  have hb0 : 0 ≤ 1 - rate := by linarith
  have hb1 : 1 - rate ≤ 1 := by linarith
  have hp0 : 0 ≤ (1 - rate) ^ days := Real.rpow_nonneg hb0 days
  have hp1 : (1 - rate) ^ days ≤ 1 := Real.rpow_le_one hb0 hb1 hd
  exact ⟨mul_nonneg h0 hp0, by nlinarith⟩

/-- A consolidated synapse fades no faster than an ordinary one over the same idle time. -/
theorem consolidated_fades_slower (days s : ℝ) (hd : 0 ≤ days) (h0 : 0 ≤ s) :
    fade DECAY days s ≤ fade CONSOLIDATED_DECAY days s := by
  unfold fade DECAY CONSOLIDATED_DECAY
  exact mul_le_mul_of_nonneg_left (Real.rpow_le_rpow (by norm_num) (by norm_num) hd) h0

/-- The activation threshold always lies between 0.30 and 0.70. -/
theorem threshold_bounds (good bad : ℕ) : THETA ≤ threshold good bad ∧ threshold good bad ≤ THETA + 2 / 5 := by
  unfold threshold
  split_ifs with h
  · exact ⟨le_refl _, by linarith⟩
  · have hn : 0 < good + bad := Nat.pos_of_ne_zero h
    have hpos : (0 : ℝ) < (good : ℝ) + (bad : ℝ) := by exact_mod_cast hn
    have hf0 : 0 ≤ (bad : ℝ) / ((good : ℝ) + (bad : ℝ)) := by positivity
    have hf1 : (bad : ℝ) / ((good : ℝ) + (bad : ℝ)) ≤ 1 := by
      rw [div_le_one hpos]; linarith [(Nat.cast_nonneg good : (0 : ℝ) ≤ good)]
    constructor <;> linarith

/-- What can happen to a synapse. -/
inductive Event where
  | success
  | failure
  | idle (rate days : ℝ)

noncomputable def step : Event → ℝ → ℝ
  | .success, s => potentiate s
  | .failure, s => depress s
  | .idle rate days, s => fade rate days s

def valid : Event → Prop
  | .idle rate days => 0 ≤ rate ∧ rate ≤ 1 ∧ 0 ≤ days
  | _ => True

theorem step_in_unit (e : Event) (he : valid e) (s : ℝ) (h0 : 0 ≤ s) (h1 : s ≤ 1) :
    0 ≤ step e s ∧ step e s ≤ 1 := by
  cases e with
  | success => have h := potentiate_bounds s h0 h1; exact ⟨by linarith [h.1], h.2⟩
  | failure => have h := depress_bounds s h0; exact ⟨h.1, by linarith [h.2]⟩
  | idle rate days =>
    obtain ⟨hr0, hr1, hd⟩ := he
    have h := fade_bounds rate days s hr0 hr1 hd h0
    exact ⟨h.1, by linarith [h.2]⟩

/-- Whatever sequence of successes, failures and idle periods happens, a synapse's strength stays in [0, 1]. -/
theorem strength_stays_in_unit (es : List Event) (hes : ∀ e ∈ es, valid e) (s : ℝ) (h0 : 0 ≤ s) (h1 : s ≤ 1) :
    0 ≤ es.foldl (fun x e => step e x) s ∧ es.foldl (fun x e => step e x) s ≤ 1 := by
  induction es generalizing s with
  | nil => exact ⟨h0, h1⟩
  | cons e es ih =>
    simp only [List.foldl]
    have h := step_in_unit e (hes e (by simp)) s h0 h1
    exact ih (fun x hx => hes x (by simp [hx])) _ h.1 h.2

end QueryBookOne.Synapse
