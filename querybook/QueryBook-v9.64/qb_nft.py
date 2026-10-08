"""On-chain NFTs for QueryBook  — Registry Domain 8 NFT Engine (101, 109–118).

This is the REAL blockchain layer that qb_integrity.py's local seals lead up to. A local
provenance seal (hash-chained, tamper-evident on this machine) can be certified on a public
EVM blockchain as an ERC-721 token of the QueryBookProvenance contract
(contracts/QueryBookProvenance.sol). Anyone can then check, without trusting this machine,
that the token exists, who owns it, and which content hash it certifies.

  8.8.1 QBF NFT minting          kind="qbf"
  8.8.2 Fact Unit NFT minting     kind="fact_unit"
  8.8.3 Provenance NFT engine     kind="provenance" (a seal / lineage chain)
  8.8.4 Response NFT engine       kind="response"
  8.8.5 Lineage chain manager     remint(): successor token linked to its predecessor on-chain
  8.8.6 Ownership verification    verify(): reads ownerOf / contentHashOf / revoked from the chain
  8.8.7 NFT transfer events       transfer(): on-chain transfer, recorded locally
  8.8.8 NFT event hooks           NFT_MINTED / NFT_TRANSFERRED / NFT_REVOKED / NFT_VERIFIED
  8.8.9 NFT metadata schema       metadata(): fully on-chain data: URI (no IPFS, no server)
  8.8.10 Revocation & re-minting  revoke() + remint()
  8.7.5 NFT-based licensing       license_check(): a token holder holds the licence

No third-party packages: Keccak-256, secp256k1 signing (RFC 6979), RLP, EIP-1559/EIP-155
transactions, ABI encoding and JSON-RPC are implemented below with the standard library and
checked in qc() against published test vectors.

SAFETY: test networks only by default (Sepolia, Base Sepolia, Polygon Amoy, or a local dev
chain). Known main networks (real money) are refused unless qb_nft_config.json says
"allow_mainnet": true. The wallet key is generated locally and stored in qb_nft_wallet.key
(git-ignored, owner-only permissions) — or supplied via the QB_NFT_PRIVATE_KEY variable.
"""

import base64 as _b64
import hashlib as _hashlib
import hmac as _hmac
import json as _json
import os as _os
import time as _time
import urllib.request as _url

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_CONFIG = _os.path.join(_HERE, "qb_nft_config.json")
_WALLET = _os.path.join(_HERE, "qb_nft_wallet.key")
_REGISTRY = _os.path.join(_HERE, "qb_nft_registry.json")
_ARTIFACT = _os.path.join(_HERE, "contracts", "QueryBookProvenance.json")

NETWORKS = {
    "local": {"name": "Local dev chain (anvil / hardhat)", "rpc": "http://127.0.0.1:8545",
              "chain_id": 31337, "explorer": "", "faucet": "pre-funded test accounts"},
    "sepolia": {"name": "Ethereum Sepolia testnet", "rpc": "https://ethereum-sepolia-rpc.publicnode.com",
                "chain_id": 11155111, "explorer": "https://sepolia.etherscan.io",
                "faucet": "https://cloud.google.com/application/web3/faucet/ethereum/sepolia"},
    "base-sepolia": {"name": "Base Sepolia testnet", "rpc": "https://sepolia.base.org",
                     "chain_id": 84532, "explorer": "https://sepolia.basescan.org",
                     "faucet": "any Base Sepolia faucet (search 'Base Sepolia faucet')"},
    "polygon-amoy": {"name": "Polygon Amoy testnet", "rpc": "https://rpc-amoy.polygon.technology",
                     "chain_id": 80002, "explorer": "https://amoy.polygonscan.com",
                     "faucet": "https://faucet.polygon.technology"},
}
# Main networks: real money. Refused unless the config explicitly allows them.
MAINNET_CHAIN_IDS = {1, 10, 56, 137, 8453, 42161, 43114, 59144, 324, 534352, 81457}

KINDS = ("qbf", "fact_unit", "provenance", "response")


# ============================================================================
# Keccak-256 (the pre-NIST variant Ethereum uses; hashlib.sha3_256 is different)
# ============================================================================
_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
       0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
       0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
       0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
       0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56],
        [27, 20, 39, 8, 14]]
_M64 = (1 << 64) - 1


def _rol(x, n):
    return ((x << n) | (x >> (64 - n))) & _M64 if n else x


def _keccak_f(a):
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        a = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        a[0][0] ^= rc
    return a


def keccak256(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    rate = 136
    msg = bytearray(data) + b"\x01"
    msg += b"\x00" * ((-len(msg)) % rate)
    msg[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        block = msg[off:off + rate]
        for i in range(rate // 8):
            x, y = i % 5, i // 5
            a[x][y] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        a = _keccak_f(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
    return out


# ============================================================================
# secp256k1 + deterministic ECDSA (RFC 6979), low-s, with recovery id
# ============================================================================
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
      0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _jadd(p, q):
    if p is None:
        return q
    if q is None:
        return p
    x1, y1, z1 = p
    x2, y2, z2 = q
    z1z1, z2z2 = z1 * z1 % _P, z2 * z2 % _P
    u1, u2 = x1 * z2z2 % _P, x2 * z1z1 % _P
    s1, s2 = y1 * z2 * z2z2 % _P, y2 * z1 * z1z1 % _P
    if u1 == u2:
        if s1 != s2:
            return None
        return _jdouble(p)
    h, r = (u2 - u1) % _P, (s2 - s1) % _P
    hh = h * h % _P
    hhh = h * hh % _P
    v = u1 * hh % _P
    x3 = (r * r - hhh - 2 * v) % _P
    y3 = (r * (v - x3) - s1 * hhh) % _P
    return (x3, y3, h * z1 * z2 % _P)


def _jdouble(p):
    if p is None:
        return None
    x, y, z = p
    if y == 0:
        return None
    yy = y * y % _P
    s = 4 * x * yy % _P
    m = 3 * x * x % _P
    x3 = (m * m - 2 * s) % _P
    y3 = (m * (s - x3) - 8 * yy * yy) % _P
    return (x3, y3, 2 * y * z % _P)


def _mul(k, point=_G):
    r, q = None, (point[0], point[1], 1)
    while k:
        if k & 1:
            r = _jadd(r, q)
        q = _jdouble(q)
        k >>= 1
    if r is None:
        return None
    x, y, z = r
    zi = pow(z, _P - 2, _P)
    return (x * zi * zi % _P, y * zi * zi * zi % _P)


def _rfc6979_k(priv, h32):
    x = priv.to_bytes(32, "big")
    h = (int.from_bytes(h32, "big") % _N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = _hmac.new(k, v + b"\x00" + x + h, _hashlib.sha256).digest()
    v = _hmac.new(k, v, _hashlib.sha256).digest()
    k = _hmac.new(k, v + b"\x01" + x + h, _hashlib.sha256).digest()
    v = _hmac.new(k, v, _hashlib.sha256).digest()
    while True:
        v = _hmac.new(k, v, _hashlib.sha256).digest()
        cand = int.from_bytes(v, "big")
        if 1 <= cand < _N:
            return cand
        k = _hmac.new(k, v + b"\x00", _hashlib.sha256).digest()
        v = _hmac.new(k, v, _hashlib.sha256).digest()


def sign_hash(priv, h32):
    """Return (recovery_id, r, s) with low-s normalisation (EIP-2)."""
    z = int.from_bytes(h32, "big")
    while True:
        k = _rfc6979_k(priv, h32)
        rp = _mul(k)
        r = rp[0] % _N
        if r == 0:
            continue
        s = pow(k, _N - 2, _N) * (z + r * priv) % _N
        if s == 0:
            continue
        rec = (rp[1] & 1) | (2 if rp[0] >= _N else 0)
        if s > _N // 2:
            s = _N - s
            rec ^= 1
        return rec, r, s


def address_of(priv):
    x, y = _mul(priv)
    return checksum(keccak256(x.to_bytes(32, "big") + y.to_bytes(32, "big"))[-20:].hex())


def checksum(addr):
    """EIP-55 mixed-case checksum address."""
    a = addr.lower().replace("0x", "")
    h = keccak256(a.encode()).hex()
    return "0x" + "".join(c.upper() if c.isalpha() and int(h[i], 16) >= 8 else c for i, c in enumerate(a))


# ============================================================================
# RLP, ABI
# ============================================================================
def _rlp(item):
    if isinstance(item, int):
        item = b"" if item == 0 else item.to_bytes((item.bit_length() + 7) // 8, "big")
    if isinstance(item, (bytes, bytearray)):
        item = bytes(item)
        if len(item) == 1 and item[0] < 0x80:
            return item
        return _rlp_len(len(item), 0x80) + item
    payload = b"".join(_rlp(x) for x in item)
    return _rlp_len(len(payload), 0xC0) + payload


def _rlp_len(n, offset):
    if n < 56:
        return bytes([offset + n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([offset + 55 + len(b)]) + b


def selector(signature):
    return keccak256(signature.encode())[:4]


def _hex2b(h):
    h = h[2:] if h.startswith("0x") else h
    return bytes.fromhex(h)


def abi_encode(types, values):
    head, tail = b"", b""
    dyn_offset = 32 * len(types)
    for t, v in zip(types, values):
        if t in ("string", "bytes"):
            data = v.encode("utf-8") if isinstance(v, str) and t == "string" else (v if isinstance(v, bytes) else _hex2b(v))
            enc = len(data).to_bytes(32, "big") + data + b"\x00" * ((-len(data)) % 32)
            head += (dyn_offset + len(tail)).to_bytes(32, "big")
            tail += enc
        elif t == "address":
            head += b"\x00" * 12 + _hex2b(v)
        elif t == "bytes32":
            b = v if isinstance(v, bytes) else _hex2b(v)
            head += b.ljust(32, b"\x00")
        elif t == "bool":
            head += (1 if v else 0).to_bytes(32, "big")
        elif t == "uint256":
            head += int(v).to_bytes(32, "big")
        else:
            raise ValueError("unsupported ABI type " + t)
    return head + tail


def abi_decode(types, data):
    out = []
    for i, t in enumerate(types):
        word = data[32 * i:32 * i + 32]
        if t in ("string", "bytes"):
            off = int.from_bytes(word, "big")
            n = int.from_bytes(data[off:off + 32], "big")
            raw = data[off + 32:off + 32 + n]
            out.append(raw.decode("utf-8", "replace") if t == "string" else raw)
        elif t == "address":
            out.append(checksum(word[-20:].hex()))
        elif t == "bytes32":
            out.append("0x" + word.hex())
        elif t == "bool":
            out.append(int.from_bytes(word, "big") != 0)
        else:
            out.append(int.from_bytes(word, "big"))
    return out


# ============================================================================
# JSON-RPC client + signer
# ============================================================================
class ChainError(Exception):
    pass


class Chain:
    def __init__(self, rpc, chain_id=None, timeout=30):
        self.rpc, self.timeout, self._id = rpc, timeout, 0
        self.chain_id = chain_id

    def call(self, method, params=None):
        self._id += 1
        body = _json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []}).encode()
        req = _url.Request(self.rpc, data=body, headers={"Content-Type": "application/json",
                                                         "User-Agent": "QueryBook-NFT"})
        try:
            with _url.urlopen(req, timeout=self.timeout) as r:
                resp = _json.loads(r.read())
        except OSError as e:
            raise ChainError("cannot reach the blockchain at %s: %s" % (self.rpc, e))
        if resp.get("error"):
            e = resp["error"]
            raise ChainError("%s: %s" % (method, e.get("message", e)))
        return resp.get("result")

    def eth_call(self, to, data):
        return _hex2b(self.call("eth_call", [{"to": to, "data": "0x" + data.hex()}, "latest"]) or "0x")

    def send(self, priv, to, data, value=0, gas=None):
        """Sign and send a transaction (EIP-1559 when the chain supports it); wait for the receipt."""
        sender = address_of(priv)
        chain_id = self.chain_id or int(self.call("eth_chainId"), 16)
        nonce = int(self.call("eth_getTransactionCount", [sender, "pending"]), 16)
        tx = {"from": sender, "data": "0x" + data.hex(), "value": hex(value)}
        if to:
            tx["to"] = to
        if gas is None:
            gas = int(int(self.call("eth_estimateGas", [tx]), 16) * 1.25) + 10000
        block = self.call("eth_getBlockByNumber", ["latest", False]) or {}
        to_b = _hex2b(to) if to else b""
        if block.get("baseFeePerGas"):
            base = int(block["baseFeePerGas"], 16)
            try:
                tip = int(self.call("eth_maxPriorityFeePerGas"), 16)
            except ChainError:
                tip = 1_500_000_000
            max_fee = base * 2 + tip
            fields = [chain_id, nonce, tip, max_fee, gas, to_b, value, data, []]
            rec, r, s = sign_hash(priv, keccak256(b"\x02" + _rlp(fields)))
            raw = b"\x02" + _rlp(fields + [rec & 1, r, s])
        else:
            price = int(self.call("eth_gasPrice"), 16)
            fields = [nonce, price, gas, to_b, value, data]
            rec, r, s = sign_hash(priv, keccak256(_rlp(fields + [chain_id, 0, 0])))
            raw = _rlp(fields + [chain_id * 2 + 35 + (rec & 1), r, s])
        txh = self.call("eth_sendRawTransaction", ["0x" + raw.hex()])
        deadline = _time.time() + 180
        while _time.time() < deadline:
            receipt = self.call("eth_getTransactionReceipt", [txh])
            if receipt:
                if int(receipt.get("status", "0x1"), 16) != 1:
                    raise ChainError("transaction %s failed on-chain" % txh)
                return receipt
            _time.sleep(1.0)
        raise ChainError("transaction %s not confirmed within 3 minutes (it may still confirm)" % txh)


# ============================================================================
# Config, wallet, registry
# ============================================================================
def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return _json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, data, private=False):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(data, f, indent=2)
    _os.replace(tmp, path)
    if private:
        try:
            _os.chmod(path, 0o600)
        except OSError:
            pass


def config():
    cfg = _load(_CONFIG, {})
    net = cfg.get("network", "sepolia")
    preset = NETWORKS.get(net, {})
    return {"network": net, "rpc": cfg.get("rpc") or preset.get("rpc", ""),
            "chain_id": int(cfg.get("chain_id") or preset.get("chain_id") or 0),
            "explorer": cfg.get("explorer", preset.get("explorer", "")),
            "contracts": cfg.get("contracts", {}), "allow_mainnet": bool(cfg.get("allow_mainnet", False))}


def set_network(network, rpc=None, chain_id=None, explorer=None):
    """Choose the chain: a preset name, or 'custom' with rpc + chain_id."""
    if network not in NETWORKS and network != "custom":
        return {"ok": False, "error": "unknown network; choose one of: " + ", ".join(list(NETWORKS) + ["custom"])}
    cfg = _load(_CONFIG, {})
    cfg["network"] = network
    for k, v in (("rpc", rpc), ("chain_id", chain_id), ("explorer", explorer)):
        if v not in (None, ""):
            cfg[k] = v
        elif network != "custom":
            cfg.pop(k, None)
    _save(_CONFIG, cfg)
    return {"ok": True, "config": config()}


def _private_key():
    env = _os.environ.get("QB_NFT_PRIVATE_KEY", "").strip()
    if env:
        return int(env[2:] if env.startswith("0x") else env, 16)
    try:
        with open(_WALLET, encoding="ascii") as f:
            return int(f.read().strip(), 16)
    except OSError:
        pass
    while True:
        k = int.from_bytes(_os.urandom(32), "big")
        if 1 <= k < _N:
            break
    with open(_WALLET, "w", encoding="ascii") as f:
        f.write("%064x\n" % k)
    try:
        _os.chmod(_WALLET, 0o600)
    except OSError:
        pass
    return k


def _chain():
    cfg = config()
    if not cfg["rpc"]:
        raise ChainError("no blockchain configured: choose a network first")
    if cfg["chain_id"] in MAINNET_CHAIN_IDS and not cfg["allow_mainnet"]:
        raise ChainError("chain %d is a main network (real money). QueryBook refuses it unless "
                         "qb_nft_config.json sets \"allow_mainnet\": true." % cfg["chain_id"])
    ch = Chain(cfg["rpc"], cfg["chain_id"] or None)
    live = int(ch.call("eth_chainId"), 16)
    if cfg["chain_id"] and live != cfg["chain_id"]:
        raise ChainError("the RPC at %s is chain %d, not the configured %d" % (cfg["rpc"], live, cfg["chain_id"]))
    if live in MAINNET_CHAIN_IDS and not cfg["allow_mainnet"]:
        raise ChainError("the RPC is a main network (chain %d); refused (see allow_mainnet)" % live)
    ch.chain_id = live
    return ch, cfg


def _contract_address(cfg):
    return (cfg.get("contracts") or {}).get(str(cfg["chain_id"]))


def _registry():
    return _load(_REGISTRY, {"tokens": [], "events": []})


def _emit(reg, event, **data):
    """8.8.8 NFT event hooks: recorded locally, logged, and returned to the caller."""
    ev = dict(event=event, ts=int(_time.time()), **data)
    reg["events"].append(ev)
    try:
        import qb_log
        qb_log.log("ok", "nft", "%s %s" % (event, _json.dumps(data)[:200]))
    except Exception:
        pass
    return ev


def _link(cfg, kind, value):
    if not cfg.get("explorer") or not value:
        return ""
    return "%s/%s/%s" % (cfg["explorer"].rstrip("/"), kind, value)


# ============================================================================
# Public API
# ============================================================================
def wallet():
    """The node's wallet address and balance (fund it from a testnet faucet)."""
    priv = _private_key()
    addr = address_of(priv)
    cfg = config()
    out = {"address": addr, "network": cfg["network"], "chain_id": cfg["chain_id"],
           "faucet": NETWORKS.get(cfg["network"], {}).get("faucet", ""),
           "explorer": _link(cfg, "address", addr)}
    try:
        ch, cfg = _chain()
        wei = int(ch.call("eth_getBalance", [addr, "latest"]), 16)
        out.update(balance_wei=wei, balance=wei / 1e18, reachable=True)
    except ChainError as e:
        out.update(reachable=False, detail=str(e))
    return out


def status():
    cfg = config()
    reg = _registry()
    w = wallet()
    return {"config": cfg, "wallet": w, "contract": _contract_address(cfg),
            "tokens": len(reg["tokens"]), "networks": NETWORKS,
            "ready": bool(w.get("reachable") and _contract_address(cfg)),
            "note": "Real ERC-721 tokens on the configured EVM chain. Test networks by default."}


def deploy():
    """Deploy the QueryBookProvenance contract once per chain (the node becomes the minter)."""
    ch, cfg = _chain()
    existing = _contract_address(cfg)
    if existing and ch.call("eth_getCode", [existing, "latest"]) not in (None, "0x", "0x0"):
        return {"ok": True, "contract": existing, "already": True, "explorer": _link(cfg, "address", existing)}
    art = _load(_ARTIFACT, None)
    if not art:
        raise ChainError("contract artifact missing: contracts/QueryBookProvenance.json")
    priv = _private_key()
    receipt = ch.send(priv, None, _hex2b(art["bytecode"]))
    addr = checksum(receipt["contractAddress"])
    raw = _load(_CONFIG, {})
    raw.setdefault("contracts", {})[str(ch.chain_id)] = addr
    if "network" not in raw:
        raw["network"] = cfg["network"]
    _save(_CONFIG, raw)
    return {"ok": True, "contract": addr, "tx": receipt["transactionHash"],
            "explorer": _link(cfg, "address", addr), "gas_used": int(receipt["gasUsed"], 16)}


def metadata(kind, ref, content_hash, seal=None, extra=None):
    """8.8.9 metadata schema — rendered as an on-chain data: URI."""
    attrs = [{"trait_type": "kind", "value": kind}, {"trait_type": "ref", "value": str(ref)},
             {"trait_type": "content_hash", "value": content_hash}]
    if seal:
        attrs += [{"trait_type": "seal_id", "value": seal["id"]},
                  {"trait_type": "sealed_at", "value": seal.get("ts")},
                  {"trait_type": "seal_prev", "value": seal.get("prev")}]
    for k, v in sorted((extra or {}).items()):
        attrs.append({"trait_type": str(k), "value": v if isinstance(v, (int, float)) else str(v)[:200]})
    doc = {"name": "QueryBook %s %s" % (kind.replace("_", " "), str(ref)[:24]),
           "description": "Certifies a QueryBook %s by its content hash. Verify: the token's "
                          "contentHashOf() must equal the hash of the object." % kind.replace("_", " "),
           "attributes": attrs, "schema": "querybook-nft/1"}
    return "data:application/json;base64," + _b64.b64encode(
        _json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).decode()


def _content_hash(value):
    v = str(value)
    if len(v) in (64, 66) and all(c in "0123456789abcdefABCDEF" for c in v.replace("0x", "", 1)):
        return "0x" + v.replace("0x", "", 1).lower()
    return "0x" + _hashlib.sha256(v.encode("utf-8")).hexdigest()


def mint(kind, ref, content=None, seal_id=None, to=None, predecessor=0, extra=None):
    """8.8.1–8.8.4: certify a QueryBook object on-chain.

    kind: qbf | fact_unit | provenance | response.  ref: its id (qbf_id, fu_id, ...).
    content: the object's hash (64 hex) or its text (hashed with SHA-256). With seal_id, the
    local provenance seal is used: its payload hash is certified and its id goes in the metadata.
    """
    if kind not in KINDS:
        return {"ok": False, "error": "kind must be one of " + ", ".join(KINDS)}
    seal = None
    if seal_id:
        import qb_integrity
        seal = next((r for r in qb_integrity._load() if r["id"] == seal_id), None)
        if not seal:
            return {"ok": False, "error": "no local seal %s" % seal_id}
        content = content or seal["payload_hash"]
    if content in (None, ""):
        return {"ok": False, "error": "give content (a hash or text) or a seal_id"}
    ch, cfg = _chain()
    contract = _contract_address(cfg)
    if not contract:
        return {"ok": False, "error": "no contract on this chain yet: deploy first"}
    priv = _private_key()
    owner = checksum(to) if to else address_of(priv)
    chash = _content_hash(content)
    uri = metadata(kind, ref, chash, seal, extra)
    data = selector("mint(address,string,bytes32,uint256)") + abi_encode(
        ["address", "string", "bytes32", "uint256"], [owner, uri, chash, int(predecessor or 0)])
    receipt = ch.send(priv, contract, data)
    minted_topic = "0x" + keccak256("Minted(uint256,bytes32,uint256)").hex()
    token_id = None
    for lg in receipt.get("logs", []):
        if lg["topics"] and lg["topics"][0].lower() == minted_topic:
            token_id = int(lg["topics"][1], 16)
    reg = _registry()
    rec = {"token_id": token_id, "chain_id": ch.chain_id, "contract": contract, "kind": kind, "ref": str(ref),
           "content_hash": chash, "seal_id": seal_id, "owner": owner, "predecessor": int(predecessor or 0),
           "tx": receipt["transactionHash"], "ts": int(_time.time())}
    reg["tokens"].append(rec)
    ev = _emit(reg, "NFT_MINTED", token_id=token_id, chain_id=ch.chain_id, tx=rec["tx"])
    _save(_REGISTRY, reg)
    try:
        import qb_integrity
        qb_integrity.mint("nft_minted", "%s:%s:%s" % (ch.chain_id, contract, token_id),
                          {"tx": rec["tx"], "content_hash": chash, "kind": kind, "ref": str(ref)})
    except Exception:
        pass
    return {"ok": True, "token": rec, "event": ev, "tx_explorer": _link(cfg, "tx", rec["tx"]),
            "token_explorer": _link(cfg, "nft", "%s/%s" % (contract, token_id))}


def _read(ch, contract, sig, types, args, out):
    data = selector(sig) + abi_encode(types, args)
    try:
        return abi_decode(out, ch.eth_call(contract, data))
    except ChainError:
        return None


def verify(token_id, content=None):
    """8.8.6 ownership verification, straight from the chain (no trust in this machine)."""
    ch, cfg = _chain()
    contract = _contract_address(cfg)
    if not contract:
        return {"ok": False, "error": "no contract on this chain"}
    t = int(token_id)
    owner = _read(ch, contract, "ownerOf(uint256)", ["uint256"], [t], ["address"])
    if not owner:
        return {"ok": False, "exists": False, "token_id": t}
    chash = _read(ch, contract, "contentHashOf(uint256)", ["uint256"], [t], ["bytes32"])[0]
    revoked = _read(ch, contract, "revoked(uint256)", ["uint256"], [t], ["bool"])[0]
    pred = _read(ch, contract, "predecessorOf(uint256)", ["uint256"], [t], ["uint256"])[0]
    succ = _read(ch, contract, "successorOf(uint256)", ["uint256"], [t], ["uint256"])[0]
    uri = _read(ch, contract, "tokenURI(uint256)", ["uint256"], [t], ["string"])[0]
    meta = None
    if uri.startswith("data:application/json;base64,"):
        try:
            meta = _json.loads(_b64.b64decode(uri.split(",", 1)[1]))
        except ValueError:
            meta = None
    res = {"ok": True, "exists": True, "token_id": t, "owner": owner[0], "content_hash": chash,
           "revoked": revoked, "predecessor": pred, "successor": succ, "current": succ == 0 and not revoked,
           "metadata": meta, "chain_id": ch.chain_id, "contract": contract,
           "explorer": _link(cfg, "nft", "%s/%d" % (contract, t))}
    if content is not None:
        res["content_matches"] = _content_hash(content) == chash
    reg = _registry()
    res["event"] = _emit(reg, "NFT_VERIFIED", token_id=t, owner=owner[0], revoked=revoked)
    _save(_REGISTRY, reg)
    return res


def transfer(token_id, to):
    """8.8.7: transfer a token held by this node's wallet to another address."""
    ch, cfg = _chain()
    contract = _contract_address(cfg)
    priv = _private_key()
    me = address_of(priv)
    data = selector("transferFrom(address,address,uint256)") + abi_encode(
        ["address", "address", "uint256"], [me, checksum(to), int(token_id)])
    receipt = ch.send(priv, contract, data)
    reg = _registry()
    for rec in reg["tokens"]:
        if rec["token_id"] == int(token_id) and rec["chain_id"] == ch.chain_id:
            rec["owner"] = checksum(to)
    ev = _emit(reg, "NFT_TRANSFERRED", token_id=int(token_id), sender=me, receiver=checksum(to),
               tx=receipt["transactionHash"])
    _save(_REGISTRY, reg)
    return {"ok": True, "tx": receipt["transactionHash"], "event": ev, "tx_explorer": _link(cfg, "tx", receipt["transactionHash"])}


def revoke(token_id, reason):
    """8.8.10: flag a certificate as revoked on-chain, with the reason in the event log."""
    ch, cfg = _chain()
    contract = _contract_address(cfg)
    data = selector("revoke(uint256,string)") + abi_encode(["uint256", "string"], [int(token_id), str(reason)])
    receipt = ch.send(_private_key(), contract, data)
    reg = _registry()
    ev = _emit(reg, "NFT_REVOKED", token_id=int(token_id), reason=str(reason), tx=receipt["transactionHash"])
    _save(_REGISTRY, reg)
    return {"ok": True, "tx": receipt["transactionHash"], "event": ev}


def remint(predecessor_id, kind, ref, content=None, seal_id=None, reason="updated"):
    """8.8.5 + 8.8.10: mint the successor of a token, linked on-chain, and revoke the old one."""
    res = mint(kind, ref, content=content, seal_id=seal_id, predecessor=int(predecessor_id),
               extra={"supersedes": int(predecessor_id), "change_type": reason})
    if res.get("ok"):
        res["revoked_predecessor"] = revoke(int(predecessor_id), "superseded by token %s: %s"
                                            % (res["token"]["token_id"], reason))
    return res


def license_check(token_id, holder):
    """8.7.5 NFT-based licensing: the holder is licensed while they own a current, unrevoked token."""
    v = verify(token_id)
    ok = bool(v.get("exists") and not v.get("revoked") and v.get("owner", "").lower() == str(holder).lower())
    return {"licensed": ok, "token_id": int(token_id), "holder": holder,
            "reason": "holder owns an unrevoked token" if ok else
            ("token revoked" if v.get("revoked") else "holder does not own this token")}


def tokens():
    reg = _registry()
    return {"tokens": reg["tokens"], "events": reg["events"][-50:], "config": config()}


# ============================================================================
# Quality control (offline: published test vectors, no network needed)
# ============================================================================
def qc():
    checks = []
    checks.append(("keccak256('') vector", keccak256(b"").hex() ==
                   "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"))
    checks.append(("keccak256('abc') vector", keccak256(b"abc").hex() ==
                   "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"))
    checks.append(("keccak256 multi-block (200 bytes)", keccak256(b"a" * 200).hex() ==
                   "96ea54061def936c4be90b518992fdc6f12f535068a256229aca54267b4d084d"))
    checks.append(("ERC-721 Transfer topic", keccak256("Transfer(address,address,uint256)").hex() ==
                   "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"))
    checks.append(("selector transfer(address,uint256)", selector("transfer(address,uint256)").hex() == "a9059cbb"))
    # Address of private key 1 (well-known) and anvil/hardhat account #0
    checks.append(("address of key 1", address_of(1) == "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"))
    checks.append(("address of anvil key #0", address_of(
        0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80) ==
        "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"))
    checks.append(("EIP-55 checksum", checksum("0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed") ==
                   "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"))
    # RLP vectors from the Ethereum wiki
    checks.append(("RLP 'dog'", _rlp(b"dog") == b"\x83dog"))
    checks.append(("RLP ['cat','dog']", _rlp([b"cat", b"dog"]) == b"\xc8\x83cat\x83dog"))
    checks.append(("RLP 1024", _rlp(1024) == b"\x82\x04\x00"))
    # Deterministic signature that verifies (recover the public key from r, s, v)
    h = keccak256(b"querybook")
    rec, r, s = sign_hash(0x4646464646464646464646464646464646464646464646464646464646464646, h)
    checks.append(("signature low-s", s <= _N // 2))
    checks.append(("signature recovers signer", _recover(h, rec, r, s) ==
                   address_of(0x4646464646464646464646464646464646464646464646464646464646464646)))
    checks.append(("ABI round trip", abi_decode(["address", "string", "bytes32", "uint256"], abi_encode(
        ["address", "string", "bytes32", "uint256"],
        ["0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266", "hello", "0x" + "ab" * 32, 7])) ==
        ["0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266", "hello", "0x" + "ab" * 32, 7]))
    checks.append(("contract artifact present", bool((_load(_ARTIFACT, {}) or {}).get("bytecode"))))
    meta = metadata("fact_unit", "fu-1", "0x" + "00" * 32)
    checks.append(("metadata is on-chain data URI", meta.startswith("data:application/json;base64,")))
    passed = sum(1 for _, c in checks if c)
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
            "rows": [{"check": n, "pass": c} for n, c in checks]}


def _recover(h32, rec, r, s):
    """Public-key recovery (used only by qc to prove signatures are valid)."""
    x = r + (_N if rec & 2 else 0)
    alpha = (pow(x, 3, _P) + 7) % _P
    beta = pow(alpha, (_P + 1) // 4, _P)
    y = beta if (beta & 1) == (rec & 1) else _P - beta
    e = int.from_bytes(h32, "big")
    rinv = pow(r, _N - 2, _N)
    p1 = _mul(s * rinv % _N, (x, y))
    p2 = _mul((-e * rinv) % _N)
    q = _jadd((p1[0], p1[1], 1), (p2[0], p2[1], 1))
    zi = pow(q[2], _P - 2, _P)
    qx, qy = q[0] * zi * zi % _P, q[1] * zi * zi * zi % _P
    return checksum(keccak256(qx.to_bytes(32, "big") + qy.to_bytes(32, "big"))[-20:].hex())


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args or args[0] == "--qc":
        print(_json.dumps(qc(), indent=2))
    elif args[0] == "status":
        print(_json.dumps(status(), indent=2))
    elif args[0] == "network":
        print(_json.dumps(set_network(*args[1:2], rpc=(args[2] if len(args) > 2 else None),
                                      chain_id=(int(args[3]) if len(args) > 3 else None)), indent=2))
    elif args[0] == "deploy":
        print(_json.dumps(deploy(), indent=2))
    elif args[0] == "mint":
        print(_json.dumps(mint(args[1], args[2], content=args[3] if len(args) > 3 else None), indent=2))
    elif args[0] == "verify":
        print(_json.dumps(verify(args[1]), indent=2))
    else:
        print("usage: python qb_nft.py [--qc|status|network <name> [rpc chain_id]|deploy|mint <kind> <ref> <content>|verify <id>]")
