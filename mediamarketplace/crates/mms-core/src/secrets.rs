use anyhow::{anyhow, Result};
use base64::Engine;
use chacha20poly1305::aead::{Aead, KeyInit};
use chacha20poly1305::{XChaCha20Poly1305, XNonce};
use sha2::{Digest, Sha256};

/// Encrypts secrets at rest (API keys, gateway credentials, bridge secrets).
/// Ciphertext is prefixed with a scheme tag so the algorithm can rotate later.
#[derive(Clone)]
pub struct Secrets {
    cipher: XChaCha20Poly1305,
}

impl Secrets {
    pub fn from_master_key(master: &[u8]) -> Self {
        let key = Sha256::new()
            .chain_update(b"mms-secrets|")
            .chain_update(master)
            .finalize();
        Self {
            cipher: XChaCha20Poly1305::new((&key).into()),
        }
    }

    pub fn encrypt(&self, plain: &str) -> Result<String> {
        if plain.is_empty() {
            return Ok(String::new());
        }
        use rand::RngCore;
        let mut nonce = [0u8; 24];
        rand::thread_rng().fill_bytes(&mut nonce);
        let cipher = self
            .cipher
            .encrypt(XNonce::from_slice(&nonce), plain.as_bytes())
            .map_err(|_| anyhow!("encryption failed"))?;
        let mut out = nonce.to_vec();
        out.extend(cipher);
        Ok(format!(
            "x1:{}",
            base64::engine::general_purpose::STANDARD.encode(out)
        ))
    }

    pub fn decrypt(&self, stored: &str) -> Result<String> {
        if stored.is_empty() {
            return Ok(String::new());
        }
        let (scheme, payload) = stored
            .split_once(':')
            .ok_or_else(|| anyhow!("corrupt secret"))?;
        if scheme != "x1" {
            return Err(anyhow!("unknown secret scheme {scheme}"));
        }
        let raw = base64::engine::general_purpose::STANDARD.decode(payload)?;
        if raw.len() < 24 {
            return Err(anyhow!("corrupt secret"));
        }
        let (nonce, cipher) = raw.split_at(24);
        let plain = self
            .cipher
            .decrypt(XNonce::from_slice(nonce), cipher)
            .map_err(|_| anyhow!("secret failed authentication"))?;
        Ok(String::from_utf8(plain)?)
    }

    /// Display form for admin screens: never reveals more than the last four characters.
    pub fn mask(plain: &str) -> String {
        let n = plain.chars().count();
        if n == 0 {
            return String::new();
        }
        if n <= 4 {
            return "•".repeat(n);
        }
        let tail: String = plain.chars().skip(n - 4).collect();
        format!("{}{}", "•".repeat((n - 4).max(4)), tail)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_and_tamper_detection() {
        let s = Secrets::from_master_key(b"master-key-material-of-sufficient-length");
        let enc = s.encrypt("sk_live_abc123").unwrap();
        assert!(enc.starts_with("x1:"));
        assert_eq!(s.decrypt(&enc).unwrap(), "sk_live_abc123");
        let mut broken = enc.clone();
        broken.pop();
        broken.push('A');
        assert!(s.decrypt(&broken).is_err());
        let other = Secrets::from_master_key(b"different-key");
        assert!(other.decrypt(&enc).is_err());
        assert_eq!(s.encrypt("").unwrap(), "");
        assert_eq!(Secrets::mask("sk_live_abc123"), "••••••••••c123");
    }
}
