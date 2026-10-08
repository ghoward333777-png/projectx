/* QueryBook client SDK (browser + Node fetch). One engine, many surfaces — this is the thin
   client for the HTTP embodiment, usable from conventional apps and AI back ends alike.

   Usage:
     const qb = new QueryBook("http://127.0.0.1:8099");
     await qb.query("Who wrote Hamlet?");
     await qb.verify("France capital_of Paris");
     await qb.speak("hello", { provider: "google", dialect: "en-GB-scot" });
*/
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.QueryBook = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  function QueryBook(base) { this.base = (base || "").replace(/\/$/, ""); }
  QueryBook.prototype._post = function (path, body) {
    return fetch(this.base + path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json(); });
  };
  QueryBook.prototype._get = function (path) {
    return fetch(this.base + path).then(function (r) { return r.json(); });
  };
  // ---- Query system ----
  QueryBook.prototype.query = function (text) { return this._post("/api/chat", { q: text }); };
  QueryBook.prototype.understand = function (text) { return this._post("/api/query/understand", { text: text }); };
  QueryBook.prototype.translate = function (text, src, dst, dialect) {
    return this._post("/api/language/translate", { text: text, src: src, dst: dst, dialect: dialect });
  };
  QueryBook.prototype.speak = function (text, opts) {
    opts = opts || {}; opts.text = text; return this._post("/api/language/speak", opts);
  };
  // ---- Ingestion system ----
  QueryBook.prototype.ingest = function (text, lang) { return this._post("/api/language/ingest", { text: text, lang: lang }); };
  QueryBook.prototype.strategy = function () { return this._get("/api/ingest/strategy"); };
  // ---- Integrity / rights / knowledge ----
  QueryBook.prototype.verifyClaim = function (claim) { return this._post("/api/middleware/verify", { text: claim }); };
  QueryBook.prototype.seal = function (text, author) { return this._post("/api/integrity/seal", { text: text, author: author }); };
  QueryBook.prototype.ontology = function (opts) { return this._post("/api/ontology", opts || {}); };
  QueryBook.prototype.assess = function (opts) { return this._post("/api/assess", opts || {}); };
  // ---- System / editions / embodiments ----
  QueryBook.prototype.system = function () { return this._get("/api/system"); };
  QueryBook.prototype.edition = function () { return this._get("/api/edition"); };
  QueryBook.prototype.embodiments = function () { return this._get("/api/embodiments"); };
  return QueryBook;
});
