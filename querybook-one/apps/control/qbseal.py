"""qbseal — sealed boxes with the standard library only: anyone can seal for the server, only the server can open.

Used by farmed-out harvesting (qbfarm): a harvester on another PC seals what it gathers to the QueryBook server's public
key, so the person running it cannot read the facts (it shows them only a tally); the server opens them on import.

  seal(server_public, plaintext, header) -> blob      open_sealed(server_private, blob) -> (header, plaintext)

Construction (encrypt-then-MAC, a fresh key per box):
  * X25519 (RFC 7748) between a one-time key pair and the server's key — the shared secret;
  * HKDF-SHA256 -> an encryption key and a MAC key;
  * BLAKE2b in counter mode as the keystream (a keyed PRF: block i = BLAKE2b(key=K, nonce || i));
  * HMAC-SHA256 over magic, header, one-time public key, nonce and ciphertext — any change is refused.
The header (assignment, dataset, counts) travels in the clear but is authenticated.
X25519 here is plain Python (one multiplication per box, a few milliseconds); the keystream runs at hashlib speed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import struct

MAGIC = b"QBSEAL1\n"
_P = 2 ** 255 - 19
_A24 = 121665


def _clamp(k: bytes) -> int:
    b = bytearray(k)
    b[0] &= 248
    b[31] &= 127
    b[31] |= 64
    return int.from_bytes(bytes(b), "little")


def x25519(scalar: bytes, u_bytes: bytes) -> bytes:
    """RFC 7748 X25519: the Montgomery ladder, constant in its sequence of operations."""
    k = _clamp(scalar)
    u = int.from_bytes(u_bytes, "little") & ((1 << 255) - 1)
    x1, x2, z2, x3, z3, swap = u, 1, 0, u, 1, 0
    for t in range(254, -1, -1):
        kt = (k >> t) & 1
        swap ^= kt
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = kt
        a, b = (x2 + z2) % _P, (x2 - z2) % _P
        aa, bb = a * a % _P, b * b % _P
        e = (aa - bb) % _P
        c, d = (x3 + z3) % _P, (x3 - z3) % _P
        da, cb = d * a % _P, c * b % _P
        x3 = (da + cb) ** 2 % _P
        z3 = x1 * (da - cb) ** 2 % _P
        x2 = aa * bb % _P
        z2 = e * (aa + _A24 * e) % _P
    if swap:
        x2, z2 = x3, z3
    return (x2 * pow(z2, _P - 2, _P) % _P).to_bytes(32, "little")


BASE = (9).to_bytes(32, "little")


def keypair() -> tuple[bytes, bytes]:
    """(private, public), 32 bytes each."""
    priv = os.urandom(32)
    return priv, x25519(priv, BASE)


def _hkdf(secret: bytes, info: bytes, length: int = 64) -> bytes:
    prk = hmac.new(b"qbseal-v1", secret, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:length]


def _keystream_xor(key: bytes, nonce: bytes, data: bytes) -> bytes:
    out = bytearray(len(data))
    block = 64
    for i in range(0, len(data), block):
        ks = hashlib.blake2b(nonce + struct.pack("<Q", i // block), key=key, digest_size=block).digest()
        chunk = data[i:i + block]
        out[i:i + len(chunk)] = bytes(a ^ b for a, b in zip(chunk, ks))
    return bytes(out)


def _keystream_xor_fast(key: bytes, nonce: bytes, data: bytes) -> bytes:
    """the same keystream, XORed a megabyte at a time with big integers (pure-Python byte loops are slow)"""
    out = []
    step = 1 << 20
    for off in range(0, len(data), step):
        part = data[off:off + step]
        first = off // 64
        ks = b"".join(hashlib.blake2b(nonce + struct.pack("<Q", first + j), key=key, digest_size=64).digest()
                      for j in range((len(part) + 63) // 64))[:len(part)]
        out.append((int.from_bytes(part, "little") ^ int.from_bytes(ks, "little")).to_bytes(len(part), "little"))
    return b"".join(out)


def seal(recipient_public: bytes, plaintext: bytes, header: dict) -> bytes:
    """MAGIC | header length (4) | header JSON | one-time public key (32) | nonce (16) | ciphertext | tag (32)"""
    eph_priv, eph_pub = keypair()
    shared = x25519(eph_priv, recipient_public)
    if shared == bytes(32):
        raise ValueError("unusable server key")
    keys = _hkdf(shared, b"seal" + eph_pub + recipient_public)
    enc_key, mac_key = keys[:32], keys[32:]
    nonce = os.urandom(16)
    hdr = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ct = _keystream_xor_fast(enc_key, nonce, plaintext)
    head = MAGIC + struct.pack("<I", len(hdr)) + hdr + eph_pub + nonce
    tag = hmac.new(mac_key, head + ct, hashlib.sha256).digest()
    return head + ct + tag


def read_header(blob: bytes) -> dict:
    """the clear (authenticated on opening) header — what a harvester may show: dataset, counts, never the facts"""
    if not blob.startswith(MAGIC):
        raise ValueError("not a sealed QueryBook file")
    n = struct.unpack("<I", blob[len(MAGIC):len(MAGIC) + 4])[0]
    return json.loads(blob[len(MAGIC) + 4:len(MAGIC) + 4 + n].decode("utf-8"))


def open_sealed(recipient_private: bytes, blob: bytes) -> tuple[dict, bytes]:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 4 + 32 + 16 + 32:
        raise ValueError("not a sealed QueryBook file")
    n = struct.unpack("<I", blob[len(MAGIC):len(MAGIC) + 4])[0]
    p = len(MAGIC) + 4
    hdr = blob[p:p + n]
    eph_pub = blob[p + n:p + n + 32]
    nonce = blob[p + n + 32:p + n + 48]
    ct, tag = blob[p + n + 48:-32], blob[-32:]
    recipient_public = x25519(recipient_private, BASE)
    keys = _hkdf(x25519(recipient_private, eph_pub), b"seal" + eph_pub + recipient_public)
    enc_key, mac_key = keys[:32], keys[32:]
    if not hmac.compare_digest(hmac.new(mac_key, blob[:-32 - len(ct)] + ct, hashlib.sha256).digest(), tag):
        raise ValueError("the sealed file was changed, damaged, or sealed for another server")
    return json.loads(hdr.decode("utf-8")), _keystream_xor_fast(enc_key, nonce, ct)


def self_test() -> list[tuple[str, bool]]:
    # RFC 7748 section 5.2 and 6.1 vectors
    k = bytes.fromhex("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4")
    u = bytes.fromhex("e6db6810cd34b58cf1ae47f29d2fb5d6c7c3e9a0ab1e1e3a2a8f3d1e4d5b8c4a")
    vec1 = x25519(k, bytes.fromhex("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c"))
    a_priv = bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
    b_priv = bytes.fromhex("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
    a_pub, b_pub = x25519(a_priv, BASE), x25519(b_priv, BASE)
    srv_priv, srv_pub = keypair()
    other_priv, _ = keypair()
    data = os.urandom(200_000) + "Gutenberg — 1440 ✓".encode("utf-8")
    box = seal(srv_pub, data, {"dataset": "x", "facts": 3})
    hdr, back = open_sealed(srv_priv, box)
    try:
        open_sealed(other_priv, box)
        wrong_key = False
    except ValueError:
        wrong_key = True
    bad = bytearray(box)
    bad[len(box) // 2] ^= 1
    try:
        open_sealed(srv_priv, bytes(bad))
        tamper = False
    except ValueError:
        tamper = True
    hdr_bad = box.replace(b'"facts":3', b'"facts":9')
    try:
        open_sealed(srv_priv, hdr_bad)
        hdr_tamper = False
    except ValueError:
        hdr_tamper = True
    slow = _keystream_xor(b"k" * 32, b"n" * 16, data[:1000]) == _keystream_xor_fast(b"k" * 32, b"n" * 16, data[:1000])
    return [
        ("X25519 matches RFC 7748 test vector 1",
         vec1.hex() == "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552"),
        ("X25519 key agreement matches RFC 7748 section 6.1 (Alice, Bob, shared secret)",
         a_pub.hex() == "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"
         and b_pub.hex() == "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"
         and x25519(a_priv, b_pub).hex() == "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"
         and x25519(a_priv, b_pub) == x25519(b_priv, a_pub)),
        ("a sealed box opens with the server's key: same bytes, same header", back == data and hdr == {"dataset": "x", "facts": 3}),
        ("the facts are not readable in the box", data[:64] not in box and "Gutenberg".encode() not in box),
        ("another key cannot open it (the harvester's own machine cannot)", wrong_key),
        ("one changed byte anywhere is refused", tamper),
        ("a changed header (e.g. an inflated count) is refused", hdr_tamper),
        ("the fast keystream equals the plain one", slow and len(u) == 32),
    ]


if __name__ == "__main__":
    res = self_test()
    for name, ok in res:
        print(("  [OK]   " if ok else "  [FAIL] ") + name)
    print("%d of %d checks passed" % (sum(ok for _, ok in res), len(res)))
    raise SystemExit(0 if all(ok for _, ok in res) else 1)
