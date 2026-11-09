import Mathlib

/-!
# Angles in degrees, as the STEM application uses them (`sind`, `asind` in apps/stem/engine.py)

sind x = sin(x · π / 180) and asind y = arcsin(y) · 180 / π.
-/

namespace QueryBookOne.Degrees

/-- `field_simp`, followed by `ring` when `field_simp` alone does not close the goal. -/
macro "qb_field" : tactic => `(tactic| first | (field_simp; done) | (field_simp; ring))

noncomputable def sind (x : ℝ) : ℝ := Real.sin (x * Real.pi / 180)
noncomputable def asind (y : ℝ) : ℝ := Real.arcsin y * 180 / Real.pi

/-- An angle strictly between 0° and 180° has a positive sine. -/
theorem sind_pos (x : ℝ) (h0 : 0 < x) (h1 : x < 180) : 0 < sind x := by
  unfold sind
  have hpi := Real.pi_pos
  apply Real.sin_pos_of_pos_of_lt_pi
  · positivity
  · linarith [mul_lt_mul_of_pos_right h1 hpi]

/-- `asind` undoes `sind` on [-1, 1]: the angle it returns has exactly that sine. -/
theorem sind_asind (y : ℝ) (h1 : -1 ≤ y) (h2 : y ≤ 1) : sind (asind y) = y := by
  unfold sind asind
  have hpi := Real.pi_pos.ne'
  rw [show Real.arcsin y * 180 / Real.pi * Real.pi / 180 = Real.arcsin y by qb_field]
  exact Real.sin_arcsin h1 h2

end QueryBookOne.Degrees
