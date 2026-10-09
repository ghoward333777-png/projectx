"""Standalone provisional application for Verified Agent Transport (the AI Agent Wrapper service)."""
import json, sys
TITLE = ("VERIFIED AGENT TRANSPORT: SYSTEM AND METHOD FOR VERIFYING, RECORDING AND CERTIFYING THE COMMUNICATIONS "
         "AND ACTIONS OF ARTIFICIAL-INTELLIGENCE AGENTS USING FACT UNITS CARRIED IN A FRAMED HYBRID TRANSPORT")
B = []
h = lambda t: B.append({"t": "h1", "text": t})
h2 = lambda t: B.append({"t": "h2", "text": t})
np_ = lambda t: B.append({"t": "np", "text": t})
B += [{"t": "center", "text": "PROVISIONAL PATENT APPLICATION", "bold": True, "after": 360},
      {"t": "title", "text": TITLE, "before": 600},
      {"t": "center", "text": "Inventors: Garry S. Howard; Christopher Caile", "after": 60},
      {"t": "center", "text": "[Inventorship to be confirmed for this application]", "italic": True, "after": 60},
      {"t": "center", "text": "Prepared October 9, 2026", "after": 600},
      {"t": "center", "text": "Short title: Verified Agent Transport (VAT) — the QueryBook AI Agent Wrapper Service", "italic": True},
      {"t": "pagebreak"}]

h("CROSS-REFERENCE TO RELATED APPLICATIONS")
np_("This application is related to the QueryBook provisional patent application filed or to be filed on or about October 9, 2026 "
    "[application number to be inserted], which discloses the Fact Unit, the UFCS packet and store, the Fact Query Language (FQL), the "
    "QueryBook-enhanced TCP/IP hybrid transport and its framed form, the provenance certificate, the tamper-evident security record and the "
    "Agent Gateway relied on below. The entire contents of that application are incorporated herein by reference. In that application the "
    "subject matter of this application appears as FIG. 56–57 and claims 355–365; in this application the same drawings are FIG. 1–2, "
    "reference numerals 5600–5795 there correspond to 100–295 here, and claims 355–365 there correspond to claims 1–11 here.")

h("FIELD OF THE INVENTION")
np_("The invention relates to artificial-intelligence agents and to data transport. More particularly, it relates to a relay service that carries "
    "every message an agent sends or receives as typed frames, verifies the factual statements in those messages against a store of certified "
    "knowledge records while they are in transit, binds the agent's actions to its declared intent, records the whole exchange in a hash-chained "
    "ledger, and issues a certificate for each session that any party can check.")

h("BACKGROUND")
np_("Software agents built on large language models now send messages to people and to other agents, call tools, read and write data, and take "
    "actions on behalf of their operators. Their output is fluent but may state things that are untrue, and an agent may report that it did something "
    "it did not do, or that a tool returned something it did not return.")
np_("Existing safeguards generally act on the agent or on its output after the fact: filters that inspect text for prohibited content, evaluation suites "
    "run before deployment, and logs that record what was said without checking it. A log records a statement; it does not establish whether the "
    "statement agreed with any trusted source, nor whether a reported action matches the action actually taken. A third party receiving an agent's "
    "message has no compact, independently checkable account of what in that message was verified.")
np_("There is accordingly a need for a service that sits in the path of an agent's communications, checks the factual content of each message against "
    "certified knowledge before the message arrives, checks actions against declared intent and tool records, and produces a verifiable record of the "
    "checks — without requiring changes to the agent itself.")

h("SUMMARY OF THE INVENTION")
np_("Verified Agent Transport (VAT) places a sidecar relay beside each AI agent and restricts the agent's outbound network access, by an egress rule, "
    "to that sidecar. The agent continues to speak its existing protocols — Model Context Protocol tool calls, agent-to-agent messages or HTTP — and the "
    "sidecar translates its traffic into frames of a framed hybrid transport. Each frame has a fixed header that identifies a message type, so that "
    "claims, queries, answers, intents, actions, results, verdicts, data, certificates and fingerprint-exchange messages are distinguished on the wire.")
np_("The sidecar classifies each sentence of an outbound message as fact, opinion, plan or prediction, and expresses each factual statement as a Fact Unit "
    "with a content fingerprint. A verification service looks up the fingerprint among certified Fact Units and, if there is no match, runs an FQL query "
    "for certified Fact Units with the same subject and predicate and a conflicting value. The outcome — verified, contradicted or unknown — is returned "
    "as a signed verdict frame on a control lane kept separate from the lane that carries the message, and the sidecar applies a delivery policy: deliver, "
    "annotate, hold for review or block.")
np_("Before acting, the agent declares an intent naming the tool, target and purpose; each action is compared with that intent and each reported result "
    "with the tool's own record. Every claim, verdict, intent, action and result is appended to a hash-chained ledger. At the end of a session the sidecar "
    "issues an Agent Session Certificate stating the verdict counts, the coverage of the checks and a Merkle root over the ledger, sealed as a Fact Unit "
    "and verifiable by any party. Verdict history accumulates as an evidence pair that gives each agent a reputation.")
np_("The lanes run as independent streams of a QUIC connection, or as separate TLS-on-TCP connections where QUIC is unavailable. Before bulk transfer, "
    "peers exchange have and want lists of fingerprints so that only missing Fact Units are sent, and a privacy mode lets verification proceed from "
    "fingerprints alone so that message text never leaves the sidecar.")
np_("The certificate records what was checked and what the checks found. It does not assert that an agent is honest or that any content is true.")

h("BRIEF DESCRIPTION OF THE DRAWINGS")
np_("**FIG. 1** is a block diagram of Verified Agent Transport, showing an AI agent inside an egress-lock boundary; a sidecar comprising protocol adapters, "
    "claim extraction, intent binding and a frame codec and signer; an encrypted connection carrying control, normal and bulk lanes to a peer sidecar and a "
    "destination; a UFCS verification service; a ledger and certificate store; and a control plane.")
np_("**FIG. 2** is a flow diagram of claim verification, showing classification of an outbound message, extraction and fingerprinting of factual statements, "
    "fingerprint lookup and FQL contradiction query, the verified, contradicted and unknown outcomes, the signed verdict and delivery policy, intent and "
    "result binding, ledger append, the session certificate, reputation, have/want exchange and privacy mode.")

h("DETAILED DESCRIPTION OF THE INVENTION")
h2("Terms")
np_("A **Fact Unit** is a knowledge record stating one assertion as subject, predicate, object and polarity, with provenance, a certification trust score and "
    "an integrity hash. Its **semantic fingerprint** is a SHA-256 digest over the normalized subject, predicate, object and polarity, so that the same "
    "assertion has the same fingerprint wherever it is made. The **UFCS store** holds certified Fact Units indexed by fingerprint. **FQL** is the query "
    "language over that store, with match, where, exclude, rank and return clauses. These are described in the related application.")
np_("A **frame** is the unit of the framed hybrid transport (UFCS-FQL/1): a 32-byte header (magic 0xF051, version, message type, content type, compression, "
    "flags, payload length, metadata length, message identifier, sequence number and a reserved field), JSON metadata, a payload and a CRC32 footer, followed "
    "by an Ed25519 signature when the SIGNED flag is set.")

h2("Deployment (FIG. 1)")
np_("An AI agent (100) runs inside an egress-lock boundary (105). The boundary is a host firewall rule (for example an nftables rule permitting the agent's "
    "user only the sidecar's local port), a Kubernetes NetworkPolicy denying the agent container all egress except to the sidecar in the same pod, or an "
    "equivalent desktop firewall rule. Any other outbound connection is dropped and recorded, so that the agent's only route to the network is the sidecar.")
np_("The sidecar (110) is co-located with the agent. It comprises protocol adapters (112) that accept the agent's existing traffic — acting as the agent's MCP "
    "server for tool calls, wrapping agent-to-agent messages, and acting as an HTTP forward proxy — a claim extractor (114), an intent binder (116) and a frame "
    "codec and signer (118). The adapters change how traffic is carried, never its content; traffic that cannot be translated is refused rather than forwarded raw.")
np_("Frames travel over one encrypted connection (120) carrying a control lane (122), a normal lane (124) and a bulk lane (126) to a peer sidecar (130), which "
    "verifies, records and delivers them to a destination (140) — a tool, a data source or another agent. A UFCS verification service (150) is a shared, "
    "read-only client of the Fact Unit store and FQL engine. A ledger and certificate store (160) holds the hash chain and certificates. A control plane (170) "
    "distributes allow-lists, honeytokens, verification tiers and verifier keys to sidecars as signed, pull-only bundles; a sidecar rejects an unsigned or stale bundle.")

h2("Frame types, flag and header field")
np_("The frame header is unchanged from the framed hybrid transport; message types 0–2 keep their existing meanings, and the following types are added:")
B.append({"t": "table", "header": ["Code", "Type", "Lane", "Carries"], "widths": [6, 9, 8, 50], "rows": [
  ["16", "CLAIM", "normal", "Fact Unit packet(s) with claim identifiers and assertion type"],
  ["17", "QUERY", "normal", "FQL text with minimum trust"],
  ["18", "ANSWER", "normal", "Results with citations and a provenance hash"],
  ["19", "INTENT", "control", "Declared plan: ordered steps, each naming a tool and parameter constraints"],
  ["20", "ACTION", "control", "Tool call, with intent identifier and step"],
  ["21", "RESULT", "control", "The tool's own result record and the agent's reported result"],
  ["22", "VERDICT", "control", "Signed verdict records"],
  ["23", "DATA", "bulk", "Fact Unit batch or media chunk"],
  ["24", "CERT", "control", "Agent Session Certificate"],
  ["25", "HAVE", "control", "Fingerprints offered"],
  ["26", "WANT", "control", "Fingerprints requested"],
  ["27", "TEXT", "normal", "Free message text, from which the sidecar extracts claims"]]})
np_("A frame type outside the defined set is dropped and recorded, never forwarded. A flag value 0x0040 (VERIFIED_HOP) marks a frame that has passed a verifying "
    "hop; a frame bearing the flag without a matching signed verdict in the ledger is treated as unverified. The reserved header field carries a session number "
    "in its low 16 bits and a hop count in its high 16 bits.")

h2("Lanes and transport binding")
np_("Over QUIC, the control lane is a bidirectional stream of highest priority, the normal lane a second bidirectional stream, and the bulk lane one unidirectional "
    "stream per transfer at lowest priority, so that a stalled bulk transfer never delays a verdict. Where UDP is blocked or QUIC is unavailable, the three lanes "
    "are carried as three TLS 1.3 connections over TCP with mutual authentication between sidecars. Where every middlebox is under operator control, the IP-level "
    "semantic header of the hybrid protocol may additionally be used; it is not relied on across the public internet.")

h2("Claim extraction and verification (FIG. 2)")
np_("An outbound message (200) is split into sentences and each is classified (205) as fact, opinion, plan or prediction by deterministic rules — modal verbs, "
    "first-person intent, future tense and evaluative adjectives. Opinions, plans and predictions are labelled and forwarded (206) and are never verified or "
    "contradicted. Each factual sentence is normalized into subject, predicate, object and polarity mapped to canonical identifiers, built into a candidate Fact "
    "Unit and fingerprinted (210). The sidecar records coverage: the fact-sentence characters successfully converted divided by all fact-sentence characters. "
    "A sentence that cannot be converted is marked unchecked and is never presented as verified.")
np_("The verification service first tests whether the fingerprint is present among certified Fact Units at or above the tier's minimum trust (220). If it is, "
    "the verdict is VERIFIED (231), citing the matching unit. Otherwise it executes an FQL contradiction query (225) — match the claim's subject and predicate, "
    "where trust is at least the minimum, excluding the claim's object. If a rival of higher trust exists, the verdict is CONTRADICTED (232), citing the strongest "
    "rival; the same subject, predicate and object with opposite polarity is also CONTRADICTED. Otherwise the verdict is UNKNOWN (233). Unknown is not treated as false.")
B.append({"t": "code", "lines": [
  "verify(claim):",
  "    if store.has_fingerprint(claim.fp) and record.trust >= tier.min_trust:",
  "        return VERIFIED, cite = record.fuid",
  "    rivals = FQL: MATCH subject = claim.s, predicate = claim.p",
  "                  WHERE certification.trust_score >= tier.min_trust",
  "                  EXCLUDE object = claim.o",
  "    if rivals and max(rival.trust) > claim_source_trust:",
  "        return CONTRADICTED, cite = argmax_trust(rivals).fuid",
  "    return UNKNOWN"]})
np_("The verdict is returned as a VERDICT frame (240) on the control lane, carrying the claim identifier, fingerprint, verdict, citation, trust, tier, verifier "
    "identity and timestamp, signed with Ed25519. The sidecar sets VERIFIED_HOP on the forwarded frame, attaches the verdict identifiers, and applies the delivery "
    "policy configured for the agent: a verified claim is delivered with its citation; an unknown claim is delivered labelled unverified; a contradicted claim is "
    "blocked, held for review, or delivered with the contradicting citation attached; an unchecked sentence is delivered and counted against coverage. A "
    "contradicted claim is never delivered unannotated.")
np_("Verification tiers set by the control plane select full checking of every claim, deterministic sampling keyed on a hash of the session and claim identifiers, "
    "or the fingerprint-only privacy mode described below.")

h2("Intent and result binding")
np_("Before acting, the agent — or the adapter on its behalf — sends an INTENT frame declaring an ordered list of steps, each naming a tool and constraints on its "
    "parameters. Each ACTION frame is checked (245) against the agent's allow-list and against the open intent: the tool must be in the plan and the parameters "
    "must satisfy the constraints. The tool's own result record is hashed, and when the agent later reports the outcome, the report is compared with that record. "
    "An action outside the intent, or a report that does not match the tool record, produces a CONTRADICTED verdict without reference to the Fact Unit store, so "
    "that an agent cannot misreport what it did or what a tool returned. Trap mechanisms of the Agent Gateway — honeytokens, honeycode and tripwires — apply unchanged.")

h2("Ledger and Agent Session Certificate")
np_("Every claim, verdict, intent, action and result is appended (250) to a hash chain in which each entry includes the hash of its predecessor, with write-once "
    "Merkle checkpoints at a configured interval. Altering any entry breaks the chain and changes the Merkle root.")
np_("When a session closes, the sidecar issues an Agent Session Certificate (270) stating the agent and session, the opening and closing times, the counts of claims "
    "verified, contradicted, unknown and unchecked, opinions labelled, actions in and out of plan and report mismatches, the coverage, the tier, the Merkle root "
    "and checkpoint identifiers, and the verifier keys, together with the statement that the certificate records what was checked and what the checks found and "
    "does not assert that the agent is honest or that its content is true. The certificate is signed, sealed as a Fact Unit and written to the ledger, and may "
    "optionally be anchored to a public ledger as a provenance certificate. Any party holding the ledger entries can recompute the Merkle root and check it against "
    "the certificate and any anchor, without trusting the agent or the verification service.")

h2("Reputation")
np_("Each agent has an evidence pair (280): α increases with verified claims and in-plan actions, and β with contradicted claims, out-of-plan actions and report "
    "mismatches, each with a configurable weight; unknown and unchecked claims do not change the pair. The reputation is α/(α+β) with a credible interval from the "
    "Beta distribution — the same model used for Fact Unit confidence. When the reputation falls below a policy threshold, the control plane proposes a lower tier, "
    "an approval requirement or a restricted allow-list, applied only upon a recorded operator decision.")

h2("Have/want exchange and privacy mode")
np_("Before bulk transfer, the sender offers a HAVE frame listing the fingerprints it holds; the receiver answers with a WANT frame listing those it lacks; only the "
    "wanted Fact Units are sent as DATA on the bulk lane (290). A list longer than 4,096 fingerprints is sent as a Bloom filter with a false-positive rate of at most "
    "one in a million, followed by an exact list for the hits. A receiver may instead issue an FQL QUERY and receive matching fingerprints, followed by the same "
    "exchange. Every received record is checked — signature, provenance chain, and fingerprint recomputed from content — before it enters the receiver's store.")
np_("In privacy mode (295) the sidecar sends only fingerprints, and for contradiction checking only the canonical identifiers of subject and predicate, to the "
    "verification service; verdicts are computed from these alone, and message text and objects never leave the sidecar.")

h2("Configuration and interfaces")
np_("A sidecar is configured with the agent identity, listening address, peers, transport preference and fallback, verification service, tier and minimum trust, "
    "delivery policies, ledger location and checkpoint interval, certification options and privacy mode. It exposes local endpoints to submit text, intents and "
    "actions and to retrieve a session certificate; the verification service accepts batches of claims or fingerprints and returns signed verdicts; the control "
    "plane serves signed policy bundles and keys; and a verifier tool recomputes a certificate's Merkle root from a ledger and checks its signatures and any anchor.")

h2("Alternative embodiments")
np_("The sidecar may be a separate process on the same host, a container in the same pod, a library linked into an agent framework, or a gateway serving several "
    "agents with per-agent identities. The verification service may be local to the sidecar or shared. The ledger may be mirrored. The transport may be QUIC, TLS "
    "on TCP, or another encrypted channel providing independent ordered streams. Claim classification may be rule-based, as described, or assisted by a model, in "
    "which case the classifier used is recorded in the verdict. Delivery policies, tiers, weights and thresholds are configurable per agent.")

h2("Limitations and status")
np_("Claim extraction is imperfect; coverage is therefore always reported and unchecked content is never presented as verified. Verdicts are only as good as the "
    "certified store and its trust ceilings, which is why the certificate names the verifier keys and tier. Only traffic passing through the sidecar is covered, which "
    "is why the egress lock is part of the system. The service records, contains and labels; it takes no action against external systems.")
np_("Verified Agent Transport is disclosed in this application and in an accompanying technical specification. It has not yet been reduced to practice, and no "
    "latency, bandwidth or accuracy figures are asserted for it. It reuses the frame format, Fact Unit store, FQL engine, provenance certificate, tamper-evident record "
    "and Agent Gateway of the related application.")

B.append({"t": "pagebreak"})
h("CLAIMS")
B.append({"t": "p", "text": "What is claimed is:"})
B.append({"t": "claim", "num": 1, "text": "A method of verifying communications of an artificial-intelligence agent, comprising:", "elements": [
  "receiving, at a relay interposed between the agent and a network, a message sent by the agent;",
  "encoding the message as one or more frames each having a header that identifies a message type, at least one frame carrying a factual statement expressed as a Fact Unit having a content fingerprint;",
  "determining, at a verification service, a verdict for the Fact Unit by looking up said fingerprint among certified Fact Units and, absent a match, executing a query for certified Fact Units having the same subject and predicate and a conflicting value;",
  "transmitting a signed verdict frame on a control lane separate from the lane carrying the message;",
  "appending the frame and the verdict to a hash-chained record; and",
  "issuing, at the end of a session, a session certificate stating counts of verdicts and a Merkle root over the hash-chained record."]})
deps = [
 "The method of claim 1, wherein a message containing a Fact Unit whose verdict is contradicted is blocked, held for review, or forwarded with an annotation identifying the certified Fact Units that contradict it.",
 "The method of claim 1, further comprising receiving from the agent an intent frame declaring a tool, a target and a purpose; comparing each subsequent action frame with the declared intent; comparing each result reported by the agent with a record returned by the tool; and issuing a contradicted verdict upon a mismatch.",
 "The method of claim 1, further comprising exchanging between relays have and want frames identifying fingerprints held and needed, represented as a Bloom filter when their number exceeds a threshold, and transmitting only Fact Units identified as needed.",
 "The method of claim 1, wherein in a privacy mode the relay transmits fingerprints without message content and the verdict is determined from the fingerprints alone.",
 "The method of claim 1, wherein the control lane, a normal lane and a bulk lane are carried as independent streams of a QUIC connection, and, where QUIC is unavailable, as separate connections over TLS on TCP.",
 "The method of claim 1, wherein the relay is a sidecar co-located with the agent, outbound network access of the agent is restricted by an egress rule to the sidecar, and the sidecar translates Model Context Protocol, agent-to-agent and HTTP traffic into said frames.",
 "The method of claim 1, wherein the session certificate further states a coverage measure equal to the share of factual statements in the session that were verified or contradicted, statements not checked being reported as unchecked.",
 "The method of claim 1, further comprising maintaining for the agent an evidence pair of verified and contradicted counts, computing a reputation from said pair, and restricting or isolating the agent when the reputation falls below a threshold.",
 "The method of claim 1, wherein the session certificate is sealed as a Fact Unit, is optionally anchored to a public ledger, and is verifiable by a party holding neither the agent nor the verification service.",
 "A non-transitory computer-readable medium storing instructions that, when executed by one or more processors, cause the processors to perform the method of any one of claims 1 to 10."]
for k, c in enumerate(deps, 2): B.append({"t": "claim", "num": k, "text": c})

B.append({"t": "pagebreak"})
h("ABSTRACT")
ABS = ("A relay placed beside an artificial-intelligence agent, with the agent's outbound access restricted to the relay, carries every message as typed frames "
       "of a framed hybrid transport. Factual statements are expressed as Fact Units with content fingerprints and verified in transit by fingerprint lookup among "
       "certified Fact Units and a query for conflicting certified values. Signed verdicts — verified, contradicted or unknown — travel on a separate control lane "
       "and drive delivery policy. Actions are checked against declared intent and reported results against tool records. All frames and verdicts are appended "
       "to a hash-chained ledger, and each session ends with a certificate stating verdict counts, coverage and a Merkle root, verifiable by any party. "
       "Fingerprint have/want exchange avoids resending held data, and a privacy mode verifies from fingerprints alone.")
assert len(ABS.split()) <= 150, len(ABS.split())
B.append({"t": "p", "text": ABS})
json.dump({"title": "Verified Agent Transport — Provisional Patent Application", "font": "Times New Roman", "size": 12, "line": 360,
           "justify": True, "h1center": True, "header": "Verified Agent Transport — Provisional Patent Application", "blocks": B},
          open(sys.argv[1], "w"), ensure_ascii=False)
print("abstract words:", len(ABS.split()))
