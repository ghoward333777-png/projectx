use anyhow::{anyhow, Result};
use argon2::password_hash::{
    rand_core::OsRng, PasswordHash, PasswordHasher, PasswordVerifier, SaltString,
};
use argon2::Argon2;

pub fn hash(plain: &str) -> Result<String> {
    if plain.chars().count() < 10 {
        return Err(anyhow!("password must be at least 10 characters"));
    }
    let salt = SaltString::generate(&mut OsRng);
    Ok(Argon2::default()
        .hash_password(plain.as_bytes(), &salt)
        .map_err(|e| anyhow!("hashing failed: {e}"))?
        .to_string())
}

pub fn verify(plain: &str, stored: &str) -> bool {
    match PasswordHash::new(stored) {
        Ok(parsed) => Argon2::default()
            .verify_password(plain.as_bytes(), &parsed)
            .is_ok(),
        Err(_) => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hashes_verify_and_reject() {
        let h = hash("correct horse battery").unwrap();
        assert!(verify("correct horse battery", &h));
        assert!(!verify("wrong", &h));
        assert!(hash("short").is_err());
    }
}
