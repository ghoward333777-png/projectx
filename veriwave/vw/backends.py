"""VeriWave's model backends.

* LocalEngine (always on): deterministic, offline, no keys. Every answer is a QueryBook fact or a calculation; every
  creation comes from VeriWave's own generators (vector painter, synthesiser, animator, application templates).
* Claude (optional): when ANTHROPIC_API_KEY is set, VeriWave sends the generative work (conversation, writing, code,
  vector art, storyboards, scripts) to Claude. Answers stay cite-or-refuse: Claude only rewords facts QueryBook found.

Standard library only (urllib), matching QueryBook's no-dependency rule, so this is a raw HTTPS call to the Messages API.

Lean:
    structure Reply where
      stopReason : String
      texts : List String
    deriving Repr
    def DEFAULT_MODEL : String := "claude-opus-5-5"
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2026-10-21"
DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class BackendError(RuntimeError):
    """an engine failure, reported to the person as it is (never replaced by made-up output)

    Lean:
        inductive Outcome where | ok (text : String) | failed (why : String)
        deriving Repr, BEq
    """


def retryable(status: int) -> bool:
    """HTTP statuses worth trying again shortly (rate limit, server error, overloaded)

    Lean:
        def retryable (status : Nat) : Bool := [429, 500, 502, 503, 529].contains status
        #guard retryable 429                                               -- py: retryable(429)
    """
    return status in (429, 500, 502, 503, 529)


class Claude:
    """the optional Claude engine (key from ANTHROPIC_API_KEY; model from VERIWAVE_MODEL, default claude-opus-5-5)

    Lean:
        def modelOf (env : String) : String := if env == "" then DEFAULT_MODEL else env
        #guard modelOf "" == "claude-opus-5-5"                              -- py: Claude("", "").model in ("claude-opus-5-5", os.environ.get("VERIWAVE_MODEL", ""))
    """

    def __init__(self, key: str | None, model: str | None) -> None:
        """Lean:
            def available (key : String) : Bool := key != ""
            #guard !available ""                                            -- py: not Claude("", None).available
        """
        self.key = key if key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or os.environ.get("VERIWAVE_MODEL") or DEFAULT_MODEL

    @property
    def available(self) -> bool:
        """Lean:
            theorem available_iff (k : String) : available k = true ↔ k ≠ "" := by simp [available]
        """
        return bool(self.key)

    def request_body(self, system: str, messages: list[dict], max_tokens: int, effort: str) -> dict:
        """the Messages API request: model, limit, system prompt, conversation, effort, and server-side refusal fallback

        Lean:
            def bodyKeys : List String := ["model", "max_tokens", "system", "messages", "output_config", "fallbacks"]
            #guard bodyKeys.length == 6                                     -- py: sorted(Claude("k", None).request_body("s", [], 10, "low")) == sorted(["model", "max_tokens", "system", "messages", "output_config", "fallbacks"])
        """
        return {"model": self.model, "max_tokens": max_tokens, "system": system, "messages": messages,
                "output_config": {"effort": effort}, "fallbacks": "default"}

    def complete(self, system: str, messages: list[dict], max_tokens: int, effort: str) -> str:
        """one request to Claude; the text, or BackendError with the reason (HTTP status, network, refusal)

        Lean:
            #guard retryable 529 && !retryable 400                          -- py: retryable(529) and not retryable(400)
        """
        timeout = 600.0
        if not self.available:
            raise BackendError("No ANTHROPIC_API_KEY is set, so the Claude engine is off.")
        body = json.dumps(self.request_body(system, messages, max_tokens, effort)).encode("utf-8")
        req = urllib.request.Request(API_URL, data=body, method="POST", headers={
            "content-type": "application/json", "x-api-key": self.key, "anthropic-version": API_VERSION,
            "anthropic-beta": FALLBACK_BETA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            retry = " (try again shortly)" if retryable(e.code) else ""
            raise BackendError("Claude returned HTTP %s%s: %s" % (e.code, retry, detail)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise BackendError("Could not reach Claude: %s" % e) from None
        return extract_text(data)


def extract_text(data: dict) -> str:
    """the response's text blocks, joined; a refusal or a cut-off is reported, never passed off as an answer

    Lean:
        def extract (r : Reply) : Outcome :=
          if r.stopReason == "refusal" then .failed "refusal"
          else match String.join r.texts |>.trim with
            | "" => .failed "empty"
            | t => .ok (if r.stopReason == "max_tokens" then t ++ "\n\n[cut off at the length limit]" else t)
        theorem extract_refusal (ts : List String) : extract ⟨"refusal", ts⟩ = .failed "refusal" := by simp [extract]
        #guard extract ⟨"end_turn", ["Hi"]⟩ == .ok "Hi"                     -- py: extract_text({"stop_reason": "end_turn", "content": [{"type": "text", "text": "Hi"}]}) == "Hi"
    """
    if data.get("stop_reason") == "refusal":
        det = data.get("stop_details") or {}
        raise BackendError("Claude declined this request%s." % (" (%s)" % det.get("category") if det.get("category") else ""))
    text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text").strip()
    if not text:
        raise BackendError("Claude returned no text (stop reason: %s)." % data.get("stop_reason"))
    if data.get("stop_reason") == "max_tokens":
        text += "\n\n[cut off at the length limit]"
    return text


def strip_fence(text: str) -> str:
    """the inside of a single ``` fenced block, if the reply is one; the reply unchanged otherwise

    Lean:
        def stripFence (s : String) : String :=
          let t := s.trim
          if t.startsWith "```" then
            match t.splitOn "\n" with
            | _ :: rest => let body := "\n".intercalate rest
                           if body.endsWith "```" then (body.dropRight 3).trim else t
            | [] => t
          else t
        #guard stripFence "```json\n{\"a\": 1}\n```" == "{\"a\": 1}"        -- py: strip_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    """
    t = text.strip()
    if t.startswith("```"):
        first = t.find("\n")
        last = t.rfind("```")
        if first != -1 and last > first:
            return t[first + 1:last].strip()
    return t


def parse_json_reply(text: str) -> dict:
    """the JSON object in a reply (fence and surrounding words ignored), or BackendError

    Lean:
        def braceSpan (s : String) : Option (Nat × Nat) :=
          let cs := s.toList
          match cs.findIdx? (· == '{'), (cs.reverse.findIdx? (· == '}')).map (cs.length - 1 - ·) with
          | some a, some b => if a < b then some (a, b) else none
          | _, _ => none
        #guard braceSpan "x {\"a\": 1} y" == some (2, 9)                     -- py: parse_json_reply('x {"a": 1} y') == {"a": 1}
    """
    t = strip_fence(text)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise BackendError("Claude's reply was not the JSON VeriWave asked for.")
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError as e:
        raise BackendError("Claude's reply was not valid JSON: %s" % e) from None
