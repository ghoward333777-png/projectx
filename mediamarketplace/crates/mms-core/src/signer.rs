use base64::Engine;
use hmac::{Hmac, Mac};
use serde::de::DeserializeOwned;
use serde::Serialize;
use sha2::Sha256;

type HmacSha256 = Hmac<Sha256>;

/// HMAC-SHA256 signed tokens: `base64url(json) "." base64url(mac)`.
///
/// The same format is produced by the PHP bridge plugins for single sign-on, so the
/// verifier works on the raw JSON bytes and never re-serialises the payload.
/// Every payload carries an `exp` unix timestamp.
#[derive(Clone)]
pub struct Signer {
    key: Vec<u8>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum TokenError {
    Malformed,
    BadSignature,
    Expired,
    BadPayload,
}

impl Signer {
    /// Signer for server-issued tokens (signed URLs, session cookies), derived from the master key.
    pub fn from_master_key(master: &[u8]) -> Self {
        use sha2::Digest;
        let key = Sha256::new()
            .chain_update(b"mms-signer|")
            .chain_update(master)
            .finalize();
        Self { key: key.to_vec() }
    }

    /// Signer using a shared secret verbatim (bridge SSO secrets configured in both places).
    pub fn from_shared_secret(secret: &str) -> Self {
        Self {
            key: secret.as_bytes().to_vec(),
        }
    }

    pub fn sign<T: Serialize>(&self, payload: &T) -> String {
        let json = serde_json::to_vec(payload).expect("serialisable payload");
        self.sign_raw(&json)
    }

    pub fn sign_raw(&self, json: &[u8]) -> String {
        let mut mac = HmacSha256::new_from_slice(&self.key).expect("hmac accepts any key length");
        mac.update(json);
        let tag = mac.finalize().into_bytes();
        format!("{}.{}", b64(json), b64(&tag))
    }

    /// Verifies signature and expiry, then deserialises the payload.
    pub fn verify<T: DeserializeOwned>(&self, token: &str, now_unix: i64) -> Result<T, TokenError> {
        let (p, s) = token.split_once('.').ok_or(TokenError::Malformed)?;
        let json = unb64(p).ok_or(TokenError::Malformed)?;
        let tag = unb64(s).ok_or(TokenError::Malformed)?;
        let mut mac = HmacSha256::new_from_slice(&self.key).expect("hmac accepts any key length");
        mac.update(&json);
        mac.verify_slice(&tag)
            .map_err(|_| TokenError::BadSignature)?;
        let value: serde_json::Value =
            serde_json::from_slice(&json).map_err(|_| TokenError::BadPayload)?;
        let exp = value
            .get("exp")
            .and_then(|v| v.as_i64())
            .ok_or(TokenError::BadPayload)?;
        if exp < now_unix {
            return Err(TokenError::Expired);
        }
        serde_json::from_value(value).map_err(|_| TokenError::BadPayload)
    }
}

fn b64(raw: &[u8]) -> String {
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(raw)
}

fn unb64(s: &str) -> Option<Vec<u8>> {
    base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(s)
        .ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    #[derive(Serialize, Deserialize, Debug, PartialEq)]
    struct Claims {
        sub: String,
        exp: i64,
    }

    #[test]
    fn sign_and_verify() {
        let s = Signer::from_master_key(b"master");
        let token = s.sign(&Claims {
            sub: "42".into(),
            exp: 2_000_000_000,
        });
        let back: Claims = s.verify(&token, 1_900_000_000).unwrap();
        assert_eq!(back.sub, "42");
        assert_eq!(
            s.verify::<Claims>(&token, 2_000_000_001).unwrap_err(),
            TokenError::Expired
        );
        let other = Signer::from_master_key(b"other");
        assert_eq!(
            other.verify::<Claims>(&token, 0).unwrap_err(),
            TokenError::BadSignature
        );
        assert_eq!(
            s.verify::<Claims>("nodot", 0).unwrap_err(),
            TokenError::Malformed
        );
    }

    /// Fixture shared with tests/mms-bridge-contract.php: the PHP bridges must produce this exact token.
    #[test]
    fn matches_php_bridge_fixture() {
        let s = Signer::from_shared_secret("test-secret");
        let json =
            br#"{"sub":"42","email":"a@b.c","name":"Ada","host":"wordpress","exp":1900000000}"#;
        let token = s.sign_raw(json);
        assert_eq!(
            token,
            "eyJzdWIiOiI0MiIsImVtYWlsIjoiYUBiLmMiLCJuYW1lIjoiQWRhIiwiaG9zdCI6IndvcmRwcmVzcyIsImV4cCI6MTkwMDAwMDAwMH0.8pn1jJulBkTg4ho6xxjDns7Akf83M9bYHHoTsF6lmr8"
        );
    }
}
