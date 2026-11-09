import Lake
open Lake DSL

/-- Machine-checked proofs of QueryBook's formula math (STEM formulas, unit conversion, network memory, answer routing). -/
package querybook_one

require mathlib from git "https://github.com/leanprover-community/mathlib4" @ "v4.15.0"

@[default_target]
lean_lib QueryBookOne
