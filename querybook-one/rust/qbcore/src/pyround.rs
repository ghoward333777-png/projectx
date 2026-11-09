//! Python's `round(x, ndigits)` for floats: the exact binary value is rounded to `ndigits` decimals, ties to even,
//! and the decimal result is read back as the nearest f64 (CPython uses the same correctly rounded conversion).

pub fn round(x: f64, ndigits: usize) -> f64 {
    if !x.is_finite() {
        return x;
    }
    let neg = x < 0.0;
    // 60 decimals is far beyond any digit that decides a 4-decimal rounding of a value of practical size
    let s = format!("{:.60}", x.abs());
    let (int_part, frac_part) = s.split_once('.').unwrap_or((&s, ""));
    let frac: Vec<u8> = frac_part.bytes().map(|b| b - b'0').collect();
    let mut digits: Vec<u8> = int_part.bytes().map(|b| b - b'0').collect();
    let int_len = digits.len();
    digits.extend_from_slice(&frac[..ndigits.min(frac.len())]);
    let next = frac.get(ndigits).copied().unwrap_or(0);
    let rest_nonzero = frac.iter().skip(ndigits + 1).any(|&d| d != 0);
    let last_odd = digits.last().map(|d| d % 2 == 1).unwrap_or(false);
    let up = next > 5 || (next == 5 && (rest_nonzero || last_odd));
    if up {
        let mut i = digits.len();
        loop {
            if i == 0 {
                digits.insert(0, 1);
                break;
            }
            i -= 1;
            if digits[i] == 9 {
                digits[i] = 0;
            } else {
                digits[i] += 1;
                break;
            }
        }
    }
    let carry = digits.len() - (int_len + ndigits);
    let split = int_len + carry;
    let int_s: String = digits[..split].iter().map(|d| (d + b'0') as char).collect();
    let frac_s: String = digits[split..].iter().map(|d| (d + b'0') as char).collect();
    let v: f64 = format!("{}.{}", if int_s.is_empty() { "0" } else { &int_s }, if frac_s.is_empty() { "0" } else { &frac_s })
        .parse()
        .unwrap_or(x);
    if neg { -v } else { v }
}

#[cfg(test)]
mod tests {
    use super::round;

    #[test]
    fn matches_python_examples() {
        assert_eq!(round(0.28, 4), 0.28);
        assert_eq!(round(0.03125, 4), 0.0312); // exact binary tie: Python rounds half to even
        assert_eq!(round(0.09375, 4), 0.0938);
        assert_eq!(round(2.675, 2), 2.67); // 2.675 is really 2.67499999...
        assert_eq!(round(0.99995, 4), 1.0); // 0.99995 is really 0.9999500000000000055..., so it rounds up (as in Python)
        assert_eq!(round(9.99996, 4), 10.0);
    }
}
