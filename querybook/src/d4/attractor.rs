//! Neuromorphic cognitive layer: stabilizes the admitted candidate set into
//! the one best-supported interpretation.
//!
//! Two registered regimes (QBF-C066), exactly one in effect, disclosed with
//! every output:
//!  * unique-equilibrium: a <- tanh(W a + b) with the weight matrix scaled so
//!    its spectral norm is below 1 (Frobenius bound, which dominates the
//!    spectral norm). tanh is 1-Lipschitz, so the map is a contraction and
//!    has exactly one fixed point, reached from any start (Banach).
//!  * capacity-bound: asynchronous sign updates s_i = sign(sum_j W_ij s_j + b_i)
//!    in fixed index order with symmetric W and zero diagonal. Each accepted
//!    flip strictly lowers E = -1/2 sum W s s - sum b s, so it terminates
//!    (QBF-C065); uniqueness is not guaranteed, only made improbable.
//!
//! Competitive Candidate Resolution (QBF-C074) is carried by negative weights
//! between mutually inconsistent candidates: each one's activation is reduced
//! in proportion to the activation of those inconsistent with it.

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Convergence {
    pub regime: String,
    pub units: usize,
    pub iterations: usize,
    pub residual: f64,
    pub energy: f64,
    /// Frobenius norm of W after scaling (upper bound on the spectral norm).
    pub weight_norm: f64,
    /// Attractor load ratio alpha = P/N (competing interpretations / units).
    pub load: f64,
    pub retained: usize,
}

pub struct Network {
    pub bias: Vec<f64>,
    /// dense symmetric weights, zero diagonal, row-major n*n
    pub w: Vec<f64>,
    pub n: usize,
}

impl Network {
    pub fn new(bias: Vec<f64>) -> Network {
        let n = bias.len();
        Network { bias, w: vec![0.0; n * n], n }
    }
    pub fn connect(&mut self, i: usize, j: usize, v: f64) {
        if i != j {
            self.w[i * self.n + j] += v;
            self.w[j * self.n + i] += v;
        }
    }

    /// Symmetric degree normalization: w_ij / sqrt(d_i d_j), with d the sum
    /// of absolute couplings. Bounds every unit's total input independently
    /// of how many neighbours it has, so a large cluster of mutually related
    /// records cannot outvote a small, highly relevant one by size alone.
    pub fn normalize(&mut self, kappa: f64) {
        let n = self.n;
        let deg: Vec<f64> = (0..n).map(|i| self.w[i * n..(i + 1) * n].iter().map(|x| x.abs()).sum::<f64>().max(1e-12)).collect();
        for i in 0..n {
            for j in 0..n {
                self.w[i * n + j] *= kappa / (deg[i] * deg[j]).sqrt();
            }
        }
    }

    fn frobenius(&self) -> f64 {
        self.w.iter().map(|x| x * x).sum::<f64>().sqrt()
    }

    fn energy(&self, s: &[f64]) -> f64 {
        let n = self.n;
        let mut e = 0.0;
        for i in 0..n {
            let mut acc = 0.0;
            for j in 0..n {
                acc += self.w[i * n + j] * s[j];
            }
            e -= 0.5 * s[i] * acc + self.bias[i] * s[i];
        }
        e
    }

    /// Settle the network. Returns final activations (positive = retained).
    pub fn settle(&mut self, regime: &str, bound: f64, interpretations: usize) -> (Vec<f64>, Convergence) {
        let n = self.n;
        if n == 0 {
            return (
                vec![],
                Convergence {
                    regime: regime.into(),
                    units: 0,
                    iterations: 0,
                    residual: 0.0,
                    energy: 0.0,
                    weight_norm: 0.0,
                    load: 0.0,
                    retained: 0,
                },
            );
        }
        let norm = self.frobenius();
        if regime == "unique-equilibrium" && norm > bound {
            let k = bound / norm;
            for x in self.w.iter_mut() {
                *x *= k;
            }
        }
        let norm = self.frobenius();
        let load = interpretations.max(1) as f64 / n as f64;
        let mut iterations = 0;
        let mut residual = 0.0;
        let a: Vec<f64> = if regime == "unique-equilibrium" {
            let mut a = self.bias.iter().map(|b| b.tanh()).collect::<Vec<_>>();
            let mut next = vec![0.0; n];
            for it in 0..10_000 {
                for i in 0..n {
                    let mut acc = self.bias[i];
                    let row = &self.w[i * n..(i + 1) * n];
                    for (wij, aj) in row.iter().zip(&a) {
                        acc += wij * aj;
                    }
                    next[i] = acc.tanh();
                }
                residual = a.iter().zip(&next).map(|(x, y)| (x - y).abs()).fold(0.0, f64::max);
                std::mem::swap(&mut a, &mut next);
                iterations = it + 1;
                if residual < 1e-12 {
                    break;
                }
            }
            // canonical rounding so the stable state is byte-stable
            a.iter().map(|x| (x * 1e9).round() / 1e9).collect()
        } else {
            let mut s: Vec<f64> = self.bias.iter().map(|b| if *b >= 0.0 { 1.0 } else { -1.0 }).collect();
            loop {
                let mut changed = false;
                for i in 0..n {
                    let mut acc = self.bias[i];
                    for j in 0..n {
                        acc += self.w[i * n + j] * s[j];
                    }
                    let v = if acc >= 0.0 { 1.0 } else { -1.0 };
                    if v != s[i] {
                        s[i] = v;
                        changed = true;
                    }
                }
                iterations += 1;
                if !changed || iterations > 10 * n + 10 {
                    break;
                }
            }
            s
        };
        let energy = (self.energy(&a) * 1e9).round() / 1e9;
        let retained = a.iter().filter(|x| **x > 0.0).count();
        (
            a,
            Convergence {
                regime: regime.into(),
                units: n,
                iterations,
                residual,
                energy,
                weight_norm: (norm * 1e9).round() / 1e9,
                load,
                retained,
            },
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn net() -> Network {
        let mut n = Network::new(vec![0.6, 0.5, -0.2, 0.55, -0.4]);
        n.connect(0, 1, 0.4);
        n.connect(1, 2, 0.3);
        n.connect(0, 3, -0.9); // 0 and 3 are inconsistent candidates
        n.connect(3, 4, 0.2);
        n
    }

    #[test]
    fn contraction_has_one_fixed_point_from_any_start() {
        let (a1, c1) = net().settle("unique-equilibrium", 0.9, 2);
        let (a2, _) = net().settle("unique-equilibrium", 0.9, 2);
        assert_eq!(a1, a2);
        assert!(c1.weight_norm <= 0.9 + 1e-9);
        assert!(c1.residual < 1e-9);
        // competitive resolution: the better-supported of 0 and 3 wins
        assert!(a1[0] > 0.0 && a1[0] > a1[3]);
    }

    #[test]
    fn capacity_regime_descends_energy_and_terminates() {
        let (s, c) = net().settle("capacity-bound", 0.9, 2);
        assert!(s.iter().all(|x| *x == 1.0 || *x == -1.0));
        assert!(c.iterations < 20);
    }
}
