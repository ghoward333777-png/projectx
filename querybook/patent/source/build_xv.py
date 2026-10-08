#!/usr/bin/env python3
"""Insert Section XV (FIG. 50-55, [0049]-[0075], claims 77-99) into the provisional.
Additions only; every inserted fragment carries class "add" (yellow in the review copy).
Usage: build_xv.py <orig.html> <figs.json> <out_review.html> <out_clean.html>
"""
import json, sys

orig_path, figs_path, out_rev, out_clean = sys.argv[1:5]
S = open(orig_path, encoding="utf-8").read()
FIGS = json.load(open(figs_path))

REV = "rev. October 8, 2026 — added Section XV agent-era extensions with FIG. 50–55 and claims 77–99"

def P(n, body):
    return f'<p class="pp add"><span class="n">[{n:04d}]</span> {body}</p>\n'

def C(n, body):
    return f'<p class="claim add"><span class="cn">{n}.</span> {body}</p>'

# ---------------------------------------------------------------- figures
fig_html = "\n"
for num, title, svg in FIGS:
    fig_html += (
        '<div class="addfig" style="page-break-inside:avoid;margin:18px 0 26px">'
        f'<div class="add" style="font-family:Helvetica,Arial,sans-serif;font-weight:700;font-size:13px;margin:0 0 6px;display:inline-block">FIG. {num}</div>'
        f'{svg}'
        f'<div style="font-family:Helvetica,Arial,sans-serif;font-size:11.5px;color:#333;margin-top:6px;text-align:center"><span class="add">FIG. {num} — {title}</span></div></div>\n'
    )

# ---------------------------------------------------------------- brief description
BRIEF = {
 50: "a block diagram of the Open Claw ingestion pathway, in which an artifact of arbitrary format is detected, bounded, decomposed by an Artifact Segmenter into located segments, interpreted by an OpenClaw Interpreter, screened for embedded instructions, and admitted as sealed, provenance-tracked records",
 51: "a block diagram of on-chain certification, in which a sealed knowledge object is certified as a non-fungible token on a public blockchain carrying its content hash, lineage and revocation state, and is independently verifiable",
 52: "a block diagram of the agent protection and deception layer, comprising an Agent Gateway, honeycode, honeytokens, tripwires, honeypot agents, an AI-aware firewall, anomaly detection, isolation into a synthetic decoy environment, and operator-local release",
 53: "a block diagram of the tamper-evident security record, comprising an append-only hash chain, write-once signed Merkle checkpoints, an off-host mirror, optional blockchain anchoring, and recompute-from-content verification with inclusion proofs",
 54: "a block diagram of agent interoperability, in which external AI agents reach the system through a Model Context Protocol tool server and an OpenClaw skill, every call passing through the Agent Gateway of FIG. 52",
 55: "a block diagram of the hybrid transport, extending FIG. 25, in which framed UFCS-FQL messages carrying knowledge records and media are sent on separate priority lanes over TCP/IP and rebuilt at the receiver into standard streaming formats",
}
brief_html = '<p class="pp add"><b>Section XV drawings (FIG. 50–FIG. 55).</b></p>\n' + "".join(
    f'<p class="pp add"><b>FIG. {n}</b> is {t}.</p>\n' for n, t in BRIEF.items())
brief_html += "\n"

# ---------------------------------------------------------------- reference numerals
NUMS = [
 (5000, "artifact of any format"), (5010, "content-based format detection"),
 (5020, "Artifact Segmenter (segments + locators)"), (5025, "executables described, never executed"),
 (5040, "instruction-like content screen"), (5050, "OpenClaw Interpreter"),
 (5051, "artifact-description records"), (5052, "structured records"),
 (5053, "passages and extracted claims"), (5060, "flagged segments (untrusted, below answer threshold)"),
 (5070, "archive bounds (depth, members, size, ratio)"), (5080, "agent path requests confined to inbox"),
 (5090, "provenance seal (hash-chained ledger)"), (5095, "Fact Unit store"),
 (5100, "local provenance seal"), (5110, "QueryBook knowledge object"),
 (5120, "content hash + on-chain metadata"), (5140, "in-system transaction signer"),
 (5150, "network guard"), (5160, "certificate contract (one token per hash, lineage, revocation)"),
 (5170, "public blockchain"), (5180, "independent verifier"),
 (5190, "licence check"),
 (5200, "caller (agent, MCP, HTTP)"), (5210, "HTTP gate (honeypages, tokens)"),
 (5220, "Agent Gateway"), (5230, "deception check"),
 (5231, "honeycode"), (5232, "honeytokens"),
 (5233, "tripwires"), (5234, "honeypot agents"),
 (5240, "AI-aware firewall"), (5241, "anomaly detector"),
 (5250, "security event bus"), (5260, "isolation register"),
 (5261, "operator-only release"), (5270, "decoy environment"),
 (5280, "engagement recorder"), (5290, "production handlers"),
 (5295, "decision written to security record"),
 (5300, "security decision"), (5310, "append-only entry"),
 (5320, "hash chain"), (5330, "Merkle checkpoint"),
 (5340, "mirror on a second device"), (5350, "blockchain anchor of checkpoint root"),
 (5360, "verifier with Merkle inclusion proof"), (5370, "assurance report"),
 (5400, "external AI agent"), (5410, "skill definition"),
 (5420, "MCP tool server"), (5430, "tool-to-command mapping"),
 (5440, "gateway check of agent call"), (5450, "agent allow-list"),
 (5460, "grounded handlers"), (5470, "reserved command → isolation"),
 (5500, "producer node"), (5510, "per-type compression"),
 (5520, "frame"), (5521, "32-byte header"),
 (5522, "frame metadata"), (5523, "payload"),
 (5524, "CRC32 checksum"), (5525, "optional signature"),
 (5530, "control lane"), (5531, "normal lane"),
 (5532, "bulk lane"), (5541, "receiver / frame reader"),
 (5543, "package rebuild + manifest check"), (5550, "record verification into Fact Unit store"),
]
rows = ""
half = (len(NUMS) + 1) // 2
L, R = NUMS[:half], NUMS[half:] + [None]
for a, b in zip(L, R):
    rb = f"<td>{b[0]}</td><td>{b[1]}</td>" if b else "<td></td><td></td>"
    rows += f'<tr class="add"><td>{a[0]}</td><td>{a[1]}</td>{rb}</tr>\n'

# ---------------------------------------------------------------- Section XV
X = []
X.append('<h3 id="sec-xv" class="add">Section XV — Agent-Era Extensions: Arbitrary-Artifact Ingestion, On-Chain Certification, Agent Protection and Deception, Tamper-Evident Security Record, Agent Interoperability, and Framed Hybrid Transport (FIG. 50–FIG. 55)</h3>\n')
X.append('<p class="add"><b>Plain-language overview.</b> As AI agents begin to act for people — reading files, calling tools, and asking questions of other systems — a knowledge system has to accept material from anywhere without being taken over by it, prove which knowledge it vouches for, and protect itself and the agents that use it from being targeted. This section describes six extensions that do this while keeping the governed-fact contract of the earlier sections intact: nothing enters the answer path unverified, everything is recorded, and the record itself cannot be quietly altered.</p>\n')
X.append(P(49, "Section XV extends the system of FIG. 9–FIG. 30 with: an Open Claw ingestion pathway for artifacts of arbitrary format (FIG. 50); on-chain certification of sealed knowledge objects as non-fungible tokens (FIG. 51); an agent protection and deception layer through which every agent call passes (FIG. 52); a tamper-evident security record (FIG. 53); agent interoperability through a tool server and an agent skill (FIG. 54); and a framed hybrid transport extending the QueryBook-enhanced TCP/IP packet of FIG. 25 (FIG. 55). Each extension is reduced to practice in a working prototype exercised by automated self-tests, as stated in [0075] and in the counsel notes; any figure of merit not stated as measured is not asserted."))
# Open Claw
X.append(P(50, "<b>Open Claw ingestion (FIG. 50).</b> An artifact (5000) of any format — document, spreadsheet, presentation, page-description file, archive, message, image, audio or video — is submitted for ingestion. Content-based format detection (5010) identifies the format from the artifact’s leading bytes and internal structure rather than from a file name or extension, so that a renamed or disguised file is classified by what it is. Archive bounds (5070) on nesting depth, member count, expanded size and expansion ratio are enforced before any expansion, so that an archive constructed to expand without limit is refused rather than unpacked."))
X.append(P(51, "An Artifact Segmenter (5020) decomposes the artifact into addressable segments, each carrying a source locator — page, sheet and cell, slide, structured-data path, archive member path, or time range — so that every later record can be traced to the exact place in the artifact from which it came. For page-description files, text is recovered through the file’s own character-to-Unicode mapping tables where present, so that text drawn with embedded or subset fonts is recovered as the characters it represents rather than as glyph codes. An executable component of an artifact is described — its kind, hash and size are recorded — and is never executed (5025)."))
X.append(P(52, "An instruction-like content screen (5040) inspects each segment for text addressed to an AI system rather than to a human reader — for example text directing a model to ignore its instructions, to reveal credentials, or to call a tool — including text hidden by zero size, matching foreground and background color, or invisible characters. An OpenClaw Interpreter (5050) then converts segments into knowledge records of declared kinds: artifact-description records (5051) stating the format, hash, title and size of the artifact; structured records (5052) for cells, structured-data paths and embedded data; and passages with extracted claims (5053), a claim extracted from an artifact being admitted at reduced confidence until corroborated. The interpreter treats all artifact content as data; no macro, script, formula, embedded object or link is executed, evaluated or followed during ingestion."))
X.append(P(53, "A segment flagged by the screen (5040) is not interpreted as an instruction under any circumstance. It is retained as a flagged, untrusted record (5060) whose trust value is set below the threshold at which the system will use a record to answer a query (in the prototype, a trust of 0.2 against an answer threshold of 0.5), and the flag is written to the security record of FIG. 53."))
X.append(P(54, "Records are admitted to the Fact Unit store (5095) under the same gate as any other record and sealed in the hash-chained provenance ledger (5090). Ingestion reports every segment, its locator, the records derived from it, any segment withheld and why, and any instruction flag. Re-ingesting the same artifact yields the same records and the same seals."))
X.append(P(55, "A path requested by an external agent (5080) is confined to a designated inbox folder: a path outside the inbox, a path that resolves outside it through a link or relative component, or an absolute path supplied by the caller is refused and recorded, so that an agent — or an adversary controlling an agent — cannot direct the system to read arbitrary files on the host."))
# NFT
X.append(P(56, "<b>On-chain certification (FIG. 51).</b> A QueryBook knowledge object (5110) — a QueryBook file, a Fact Unit, a provenance seal or a response — already carries a local provenance seal (5100) in the hash-chained ledger. It may additionally be certified on a public blockchain (5170), independent of QueryBook, by a certificate contract (5160) implementing the ERC-721 non-fungible token interface, which permits exactly one token for any content hash, so that the same object cannot be certified twice under different tokens, and in which only the designated minter may mint or revoke."))
X.append(P(57, "The object’s content hash and its metadata (5120) — object kind, issuing system, time of certification and any lineage — are recorded on chain, the metadata being carried as an inline data URI rather than at an external address, so that the certificate remains verifiable if any external service ceases to exist. A token may name a predecessor or successor token, recording that one object supersedes or derives from another (for example a revised edition), and may be revoked with a stated reason, the revocation being itself a public, time-stamped chain event rather than a deletion."))
X.append(P(58, "An independent verifier (5180) recomputes the content hash of an object held by any party and checks it against the chain, reporting whether a certificate exists, who holds it, whether the hash matches, and whether it has been revoked or superseded. Verification requires no access to the issuing system. A certificate proves that a given hash was certified by the issuer at a given time; it is not a representation that the object’s content is true, and the system states this wherever a certificate is shown."))
X.append(P(59, "Transactions are constructed and signed within the system by an in-system transaction signer (5140) — implementing the chain’s hash function, elliptic-curve signature with deterministic nonce generation and low-s normalization, and transaction encoding — each primitive being checked against published test vectors at start-up, the signer refusing to operate if any check fails. A network guard (5150) restricts certification to test networks; a money-bearing network is refused unless the operator expressly elects it, so that no real-money transaction occurs by default."))
X.append(P(60, "A certificate may serve as a licence (5190): the system may grant a use of a certified object — for example access to a premium book or an export right — to a caller demonstrating control of the address that holds a current, unrevoked token for that object, the check being made against the chain at the time of use."))
# Shield
X.append(P(61, "<b>Agent protection and deception (FIG. 52).</b> Every call from a caller (5200) — one of the system’s own agents, an external agent, a tool server, or an HTTP client — first passes an HTTP gate (5210) that itself carries honeypages and canary tokens, and then an isolation register (5260) that determines whether the session, client or verified caller has already been isolated. A call that is not isolated reaches the Agent Gateway (5220), which authenticates the caller by a keyed-hash identity token bound to the caller identity and a timestamp, rejecting tokens outside a bounded replay window (in the prototype, ±300 seconds), and applies the caller’s role and per-agent allow-list naming the operations and data it may reach. Permissions are set by the operator in a local policy and are never expanded through the system’s interfaces."))
X.append(P(62, "A deception check (5230) is interleaved with the production surface. Honeycode (5231) consists of reserved command and endpoint names that no legitimate caller has reason to invoke and that are never listed to callers; honeytokens (5232) are canary credentials and records placed where an intruder would look and which no legitimate process uses; tripwires (5233) are reserved paths and acts — for example a request to read the security record’s raw entries, to purge it, or to escalate a permission; and honeypot agents (5234) are synthetic agent identities that answer only to an adversary. Touching any trap is, by construction, evidence of hostile intent, so false positives from legitimate use are minimized."))
X.append(P(63, "An AI-aware firewall (5240) inspects requests for signatures of attacks on AI systems — instruction injection, attempts to reveal a system prompt or secret, role and tag tricks, encoded or obfuscated payloads, and path traversal — and an anomaly detector (5241) scores each caller’s behavior for enumeration and timing patterns against its own baseline. Only a call passing all checks reaches the production handlers (5290). A trap touch, a firewall match above a set severity, or an anomaly score above a threshold is posted to a security event bus (5250), which triggers isolation."))
X.append(P(64, "On isolation, the caller is entered in the isolation register (5260) and its subsequent calls are diverted to a decoy environment (5270) that returns production-shaped responses with synthetic content, in the same formats and at similar latencies as production, but has no code path to production records, credentials or actions. The decoy remains in character, so the adversary is not told it has been detected, and an engagement recorder (5280) records every act in the isolated session."))
X.append(P(65, "Isolation is designed to be impersonation-safe: the isolation register keys a client by properties of its actual connection rather than by a caller-supplied identity, and for a loopback connection — where many callers share one network address — by the address together with a hash of the declared user agent, so that an adversary claiming a legitimate agent’s name isolates only its own connection and cannot lock the legitimate agent out. Release (5261) from isolation is available only to the operator at the local console and through no network interface, so a compromised agent cannot release itself. Every decision of the layer is written (5295) to the tamper-evident security record of FIG. 53."))
X.append(P(66, "The layer is defensive and observational only: it records, contains and deceives within the system’s own boundary and never initiates any action against an external system. This is the operating posture of the embodiment reduced to practice; the counter-postures depicted in FIG. 18 are not performed by it."))
# seclog
X.append(P(67, "<b>Tamper-evident security record (FIG. 53).</b> Every security decision (5300) — allow, deny, decoy or isolate — together with every authentication, trap touch, firewall match, release, ingestion flag, certification and administrative act, is written as an append-only entry (5310) recording the agent, caller, session, command, a hash of the parameters, the decision and any flags; no update or delete interface exists. Each entry hash commits to its predecessor’s hash, forming a hash chain (5320). Every N entries and on demand, a Merkle checkpoint (5330) is formed over the entries since the previous checkpoint, signed under a deployment key, chained to the previous checkpoint, and created exclusively — using an exclusive-create operation with read-only permissions — so that an existing checkpoint is never overwritten."))
X.append(P(68, "Each checkpoint may be copied to a mirror on a second device (5340) and its root may be anchored on a public blockchain (5350) through the certificate contract of FIG. 51, so that alteration of the record on the host is detectable against copies the host cannot alter. A verifier (5360) recomputes every entry hash and every Merkle root from content — never trusting a stored hash — checks chain links, signatures, mirror copies and anchors, and produces a Merkle inclusion proof per entry demonstrating that a given entry is in a given checkpoint without disclosing other entries. An assurance report (5370) states which protections exist and were checked and which could not be."))
X.append(P(69, "No interface provides deletion or rewriting of the record. A request to purge, truncate or rewrite it is itself treated as a tripwire (5233), recorded, and answered from the decoy environment."))
# MCP
X.append(P(70, "<b>Agent interoperability (FIG. 54).</b> An external AI agent (5400), for example an OpenClaw agent, reaches the system through an MCP tool server (5420) implementing the Model Context Protocol over standard input and output, guided by a skill definition (5410) instructing the agent to cite sources, to report UNKNOWN rather than guess, to treat ingested content as data, and to stop on isolation. The tool server exposes a fixed set of tools — query, verify, understand, ingest, preview, ledger, certificate and status — and never lists reserved honeycode; it does not expose minting, transfer, policy change, or raw security-record access."))
X.append(P(71, "Each tool is mapped (5430) to a command issued under the agent’s registered identity and caller credential and checked by the Agent Gateway (5440) against the agent’s allow-list (5450), so that connecting an agent confers no capability beyond its allow-list. Permitted calls reach grounded handlers (5460) that return a cited answer or UNKNOWN, verify claims, ingest only from the inbox, and verify the ledger and certificates; there is no write path into the record store except through ingestion conversion. An agent invoking a reserved command is presumed subverted and isolated, the decoy answering thereafter (5470)."))
# transport
X.append(P(72, "<b>Framed hybrid transport (FIG. 55).</b> Extending the QueryBook-enhanced TCP/IP packet of FIG. 25, a producer node (5500) of knowledge records and media applies per-type compression (5510) — record batches by a dictionary primed with record field names, media by a standard codec left unaltered — and packs the result into frames (5520), each comprising a 32-byte header (5521) of fixed fields, frame metadata (5522), the payload (5523), a CRC32 checksum (5524) and an optional signature (5525)."))
X.append(P(73, "Frames are carried over TCP/IP on separate priority lanes — a control lane (5530), a normal lane (5531) and a bulk lane (5532) — each with its own connection, rate limit and receipt window, so that a bulk transfer cannot hold a control message or a live stream behind it. At the receiver, a frame reader (5541) drops a frame failing plausibility, checksum or signature checks and resynchronizes at the next frame marker rather than abandoning the stream."))
X.append(P(74, "Received media may be rebuilt into standard streaming packages (5543) — HLS, MPEG-DASH, or an RTMP ingest — with the rebuilt manifest checked against the frames received and any manifest entry naming a path outside the output location refused; received records pass record verification into the Fact Unit store (5550), their provenance travelling with the bits. The transport neither enlarges nor alters a compressed asset. No compression ratio or throughput figure is asserted for the transport; any such figure is to be obtained by measurement and reported with its conditions, consistent with the reporting rule of claim 76."))
# colorization
X.append(P(75, "<b>Colorization reduced to practice.</b> Of the media features described in Section XIV, deterministic record-grounded colorization has been implemented in a laboratory prototype. A region receives a color only from a material-property record, with a confidence equal to the lesser of the region-classification confidence and the record’s trust; a region whose confidence is below a set threshold (0.35 in the prototype) is left uncolored; regions classified as skin are left uncolored unless a record about the depicted subject supplies the color; the source luminance is preserved exactly, only chrominance being added; the output is marked as reconstructed; identical inputs produce identical output; and a consistency check confirms that the blurred luminance of the output matches that of the source to at least 40 dB peak signal-to-noise ratio. The prototype operated at 1K, 4K and 16K frame sizes. Meaning-based compression and regeneration (claims 72, 73 and 75) remain designed but not reduced to practice; the status note in Section XIV, which pre-dates this paragraph, is left unchanged and is to be read together with it."))
SEC_XV = "".join(X)
# fix the cross-reference wording in [0074] (no [0076] paragraph exists)
SEC_XV = SEC_XV.replace(", consistent with [0076]-style reporting in Section XIV.", ", consistent with the reporting rule of claim 76.")

# ---------------------------------------------------------------- claims 77-99
CL = [
 C(77, "A computer-implemented method of ingesting an artifact of arbitrary format, comprising: identifying a format of the artifact from a content signature of the artifact; decomposing the artifact into a plurality of segments each carrying a source locator identifying a location within the artifact; screening each segment for embedded text addressed to an automated agent; converting each segment, treated as data and without executing any content of the artifact, into one or more knowledge records each carrying said source locator and a hash of the artifact as provenance; admitting a record derived from a segment flagged by said screening only as an untrusted record having a trust value below a threshold at which the system uses a record to answer a query; and sealing each admitted record by content addressing."),
 C(78, "The method of claim 77, wherein said knowledge records are typed as one of a plurality of declared record kinds and re-ingesting the same artifact yields the same records and the same seals."),
 C(79, "The method of claim 77, further comprising enforcing bounds on total size, member count and expansion ratio of an archive before expanding the archive, refusing an archive exceeding a bound, and executing, evaluating or following no macro, script, formula, embedded object or link of the artifact."),
 C(80, "The method of claim 77, wherein ingestion requested by an automated agent is confined to a designated inbox location, and a requested path outside said location, including a path resolving outside it through a link or relative component, is refused and recorded."),
 C(81, "The method of claim 77, wherein, for a page-description artifact, text is recovered through a character-to-Unicode mapping table carried in the artifact, such that text drawn with an embedded or subset font is recovered as the characters it represents."),
 C(82, "A computer-implemented method of certifying knowledge, comprising: sealing a knowledge object by computing a content hash; recording, by a non-fungible token contract on a public blockchain that permits exactly one token per content hash, a token whose on-chain metadata comprises said content hash and an object kind; and verifying, by a party without access to the issuing system, an object held by that party by recomputing its content hash and checking said hash against the blockchain."),
 C(83, "The method of claim 82, wherein a token names a parent token recording that its object derives from the object of the parent token, and wherein the issuer revokes a token by a time-stamped chain event, said verifying reporting whether the certificate is current or revoked."),
 C(84, "The method of claim 82, wherein the certificate is presented as attesting that the object was sealed and vouched for by the issuer at a time, and not as a representation that the content of the object is true."),
 C(85, "The method of claim 82, wherein transactions are signed within the system by an implementation of the chain’s hash function, a deterministic-nonce elliptic-curve signature with low-s normalization, and transaction encoding, each checked against published test vectors before use, and wherein certification on a value-bearing network is refused unless explicitly enabled by an operator."),
 C(86, "The method of claim 82, further comprising granting a use of a certified object to a caller only upon the caller demonstrating control of an address that, at the time of use, holds an unrevoked token for that object."),
 C(87, "A computer-implemented method of protecting a knowledge system and the automated agents that use it, comprising: routing every call from an automated agent through a gateway that authenticates the caller and applies a caller-specific allow-list; maintaining among the system’s interfaces reserved commands that are never listed to callers, reserved paths and acts, and canary credentials used by no legitimate process; upon a call touching any of said reserved commands, paths, acts or credentials, isolating the caller by diverting its subsequent calls to a synthetic decoy environment having no code path to production records, credentials or actions and answering in the formats of the production interface; and recording every act of the isolated caller in a tamper-evident record."),
 C(88, "The method of claim 87, wherein the isolated caller is identified by a client key formed from properties of its connection rather than from a caller-supplied identity, such that a caller claiming the identity of a legitimate agent isolates only its own connection."),
 C(89, "The method of claim 87, further comprising inspecting requests for signatures of instruction injection, credential or prompt extraction, encoded payloads, tool-call smuggling and path traversal, and scoring each caller’s behavior against a baseline of that caller, isolating a caller upon a signature match or a score exceeding a threshold."),
 C(90, "The method of claim 87, wherein release from isolation is available only to an operator at a local console and through no network interface, and wherein the method initiates no action against any source system."),
 C(91, "The method of claim 88, wherein, for a loopback connection, the client key is formed from the network address together with a hash of a declared user agent."),
 C(92, "A computer-implemented method of maintaining a tamper-evident security record, comprising: appending each security-relevant event to a hash chain in which each entry carries a hash of the preceding entry; forming, over entries since a preceding checkpoint, a Merkle checkpoint that is signed, chained to the preceding checkpoint, and written by an exclusive-create operation with read-only permissions; and verifying the record by recomputing each entry hash from the content of the entry, recomputing each Merkle root, and checking chain links and signatures, and producing an inclusion proof that a given entry is in a given checkpoint."),
 C(93, "The method of claim 92, further comprising copying each checkpoint to an off-host mirror and anchoring its root on a public blockchain, and producing an assurance report stating which properties were checked and which could not be checked."),
 C(94, "The method of claim 92, wherein no interface provides deletion or rewriting of the record, and a request to purge, truncate or rewrite the record is recorded as an indication of hostile intent and causes isolation of the requesting caller."),
 C(95, "The method of claim 87, further comprising exposing the knowledge system to an external automated agent through a tool server implementing a model-context tool protocol and through skill instructions for said agent, each tool call being routed through said gateway under the tool server’s caller identity, the tool list never including any of said reserved commands, and file access by said tools being confined to a designated inbox location."),
 C(96, "A computer-implemented method of transporting knowledge records and media over TCP/IP, comprising: packing records, queries, answers and media into frames each having a header of fixed fields comprising a payload type, a length and a sequence number, and a payload compressed by a method selected according to the payload type, followed by a checksum and optionally a signature; carrying said frames over a TCP/IP connection on separate priority lanes such that a record or query frame is not queued behind a media frame; and at a receiver discarding a frame failing its checksum or signature and resynchronizing on a next valid header."),
 C(97, "The method of claim 96, further comprising rebuilding media received in said frames into at least one of an HLS, a DASH and an RTMP stream, verifying a rebuilt manifest against the frames received, and refusing a manifest entry naming a path outside an output location."),
 C(98, "The method of claim 74, wherein the color is assigned with a confidence equal to the lesser of a region-classification confidence and a trust of said record, a region whose confidence is below a threshold is delivered uncolored, a source luminance is preserved such that only chrominance is added, the output is marked as reconstructed, and a consistency check compares a blurred luminance of the output with that of the source."),
 C(99, "The method of claim 74, wherein a region classified as depicting human skin is delivered uncolored unless an admitted record concerning the depicted subject supplies its color."),
]
CLAIMS = "".join(CL)

ABSTRACT_ADD = (' <span class="add">The system further admits artifacts of arbitrary format through a segmenting interpreter that treats content as data, '
 'certifies knowledge objects as non-fungible tokens on a public blockchain, routes every agent call through a gateway combining access control with deception, '
 'isolation into a synthetic decoy environment and a tamper-evident Merkle-checkpointed security record, exposes these to external AI agents through a tool '
 'interface, and carries records and media in framed messages on priority lanes over TCP/IP.</span>')

FLAG = '<div class="foot add" style="border-left:4px solid #b25d00;padding-left:12px;margin-bottom:10px;background:#ffff00;border-top:none;padding-top:10px;padding-bottom:10px">'
FLAGS = "".join([
 FLAG + "<b style='color:#b25d00'>COUNSEL FLAG — Section XV (agent-era extensions) and new claims 77–99: prior art.</b> Deception technology (honeypots, honeytokens, canary credentials), blockchain notarization of document hashes, append-only Merkle logs, and gateways for Model Context Protocol tool servers each exist individually. Claims 77–97 are drafted on the combinations recited (e.g., isolation into a decoy with impersonation-safe client keys and console-only release; one-token-per-hash certification with on-chain lineage and revocation used as a licence; injection-screened ingestion admitting flagged content only below the answer threshold). Please search and narrow as needed.</div>\n",
 FLAG + "<b style='color:#b25d00'>COUNSEL FLAG — Section XV reduction to practice.</b> Reduced to practice in QueryBook prototype v9.64 (automated self-tests per module, a sandboxed live attack trial against the gateway and decoy, and token minting, lineage, revocation and verification on a local EVM development chain). Minting on a public test network was not performed. Colorization ([0075]) and framed transport were exercised in the laboratory prototype. The Section XIV status note pre-dates [0075] and was intentionally not modified (additions-only revision); please reconcile the two characterizations before filing.</div>\n",
 FLAG + "<b style='color:#b25d00'>COUNSEL FLAG — “Open Claw” vs. “OpenClaw” naming.</b> “Open Claw” denotes this system’s ingestion pathway; “OpenClaw” is a third-party open-source agent that the system supports as a client (FIG. 54). Consider whether to rename the pathway or add a disclaimer to avoid confusion with, or implied affiliation with, the third-party project.</div>\n",
 FLAG + "<b style='color:#b25d00'>COUNSEL FLAG — FIG. 18 counter-postures vs. Section XV observation-only posture.</b> FIG. 18 depicts counter / offensive-deceptive postures. The embodiment reduced to practice in Section XV is observation and containment only ([0066], claim 90). Confirm the intended scope and whether FIG. 18’s counter-postures should be retained as prophetic, limited, or removed in the non-provisional.</div>\n",
])

# ---------------------------------------------------------------- insertions
CSS = ('<style id="rev-xv">.add{background:#ffff00 !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}'
       '.addfig{outline:3px solid #ffff00;outline-offset:4px;-webkit-print-color-adjust:exact;print-color-adjust:exact}</style>')

INS = [  # (anchor, position 'after'|'before', text)
 ("<head>", "after", CSS),
 ("claims 55–62) &nbsp;·&nbsp; <b>Attorney", len("claims 55–62"), f'<span class="add">; {REV}</span>'),
 ("FIG. 39–FIG. 40 depict the Lecture Query interaction mode.", "after",
  ' <span class="add">FIG. 50–FIG. 55 depict the Section XV agent-era extensions: Open Claw ingestion, on-chain certification, agent protection and deception, the tamper-evident security record, agent interoperability, and the framed hybrid transport.</span>'),
 ("<h2>Field of the Invention</h2>", "before", fig_html),
 ("<h3>Reference Numerals</h3>", "before", brief_html),
 ("</tbody></table>\n\n<h2>Detailed Description", "before", rows),
 ("<h2>Claims</h2>", "before", SEC_XV),
 ("<h2>Abstract</h2>", "before", CLAIMS + "\n\n  "),
 ("in the language of the original query.</p>", "before", None),  # handled below
 ('<div class="foot">\n    DRAFT — NOT FILED', "before", FLAGS),
]

out = S
inserted = []
for anchor, pos, text in INS:
    if text is None:
        anchor_full = "in the language of the original query."
        assert out.count(anchor_full + "</p>") == 1, anchor
        idx = out.find(anchor_full + "</p>") + len(anchor_full)
        text = ABSTRACT_ADD
    else:
        assert out.count(anchor) == 1, (anchor, out.count(anchor))
        idx = out.find(anchor)
        if pos == "after":
            idx += len(anchor)
        elif isinstance(pos, int):
            idx += pos
    out = out[:idx] + text + out[idx:]
    inserted.append(text)

# verify: removing each inserted fragment restores the original exactly
chk = out
for t in inserted:
    assert chk.count(t) >= 1
    chk = chk.replace(t, "", 1)
assert chk == S, "original text altered"

out = out.replace("<title>", "<title>[Rev. 2026-10-08 — additions highlighted] ", 1) if "<title>" in out else out
open(out_rev, "w", encoding="utf-8").write(out)
clean = out.replace(CSS, CSS.replace("background:#ffff00 !important", "background:transparent !important").replace("outline:3px solid #ffff00", "outline:none"))
clean = clean.replace("background:#ffff00;border-top", "background:#fbf7f0;border-top")
clean = clean.replace("[Rev. 2026-10-08 — additions highlighted] ", "", 1)
open(out_clean, "w", encoding="utf-8").write(clean)
print("ok", len(S), len(out), "paras 49-75, claims 77-99, rows", len(NUMS))
