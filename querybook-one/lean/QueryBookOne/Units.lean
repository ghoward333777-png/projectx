/-!
# Unit conversion (apps/stem/units.py `convert_value`), over exact fractions as the application computes it

A linear unit converts by `value · factor_from / factor_to`; a temperature scale by its affine map through kelvin.
-/
import Mathlib
import QueryBookOne.Degrees

namespace QueryBookOne.Units

open QueryBookOne.Degrees

def convert (v fs fd : ℚ) : ℚ := v * fs / fd

/-- Converting there and back gives the value you started with. -/
theorem convert_round_trip (v fs fd : ℚ) (hs : fs ≠ 0) (hd : fd ≠ 0) : convert (convert v fs fd) fd fs = v := by
  unfold convert; qb_field

/-- Converting through any intermediate unit gives the same result as converting directly. -/
theorem convert_via (v fs fm fd : ℚ) (hm : fm ≠ 0) : convert (convert v fs fm) fm fd = convert v fs fd := by
  unfold convert; qb_field

/-- A unit converted to itself is unchanged. -/
theorem convert_self (v f : ℚ) (h : f ≠ 0) : convert v f f = v := by
  unfold convert; qb_field

/-- Conversion is linear: doubling the value doubles the result. -/
theorem convert_linear (a b fs fd : ℚ) : convert (a + b) fs fd = convert a fs fd + convert b fs fd := by
  unfold convert; ring

/-- Temperature: value on scale (a, b) → kelvin = value · a + b → value on scale (a', b'). -/
def temperature (v a b a' b' : ℚ) : ℚ := (v * a + b - b') / a'

theorem temperature_round_trip (v a b a' b' : ℚ) (ha : a ≠ 0) (ha' : a' ≠ 0) :
    temperature (temperature v a b a' b') a' b' a b = v := by
  unfold temperature; qb_field

end QueryBookOne.Units
