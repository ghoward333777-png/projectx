import Lake
open Lake DSL

/-- VeriWave's Lean mirror: every function of the Python engine (vw/*.py) with its theorems and #guard vectors.
    Generated from the Python's embedded Lean by tools/gen_lean.py. Core Lean 4 only (no Mathlib), so it builds in
    seconds; every #guard is evaluated and every theorem checked by `lake build`. -/
package veriwave

@[default_target]
lean_lib VeriWave
