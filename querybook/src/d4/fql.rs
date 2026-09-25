//! FQL execution floor (QBQL/FQL, QBF-C054/C058): a declarative, read-only
//! query that filters jointly on semantic structure and on certification
//! trust, freshness and status in a single operation. It is expressed over
//! the record and translated here, at the adapter, into the index's native
//! query form (QBF-C290); the host store never sees it.

use crate::d2::index::FactIndex;
use crate::d8::Scope;
use serde::Serialize;
use std::ops::Bound;
use tantivy::Term;
use tantivy::query::{AllQuery, BooleanQuery, BoostQuery, ConstScoreQuery, Occur, Query, RangeQuery, TermQuery};
use tantivy::schema::IndexRecordOption;

#[derive(Clone, Debug, Default, Serialize)]
pub struct Fql {
    /// free-text terms (analyzed with the index's stemmer)
    pub text: Vec<String>,
    /// concept identifiers the record must or should reference
    pub concepts: Vec<String>,
    /// if true, a record must reference at least one of `concepts`
    pub require_concept: bool,
    /// predicates to prefer (boost, not filter)
    pub prefer_predicates: Vec<String>,
    /// predicates to restrict to (filter)
    pub only_predicates: Vec<String>,
    pub chapter: Option<u64>,
    pub min_trust: f64,
    pub limit: usize,
}

impl Fql {
    /// Human-readable rendering, returned with every answer.
    pub fn render(&self, scope: &Scope) -> String {
        let mut w = Vec::new();
        let mut m = Vec::new();
        if !self.text.is_empty() {
            m.push(format!("text ~ \"{}\"", self.text.join(" ")));
        }
        if !self.concepts.is_empty() {
            m.push(format!("concept IN [{}]", self.concepts.join(", ")));
        }
        if !m.is_empty() {
            w.push(format!("({})", m.join(if self.require_concept { " AND " } else { " OR " })));
        }
        if !self.only_predicates.is_empty() {
            w.push(format!("predicate IN [{}]", self.only_predicates.join(", ")));
        }
        if let Some(c) = self.chapter {
            w.push(format!("chapter = {c}"));
        }
        let works: Vec<String> = scope
            .works()
            .iter()
            .map(
                |(wk, max)| {
                    if *max == u64::MAX { format!("work = \"{wk}\"") } else { format!("(work = \"{wk}\" AND pos <= {max})") }
                },
            )
            .chain(scope.corpora().iter().map(|c| format!("corpus = \"{c}\"")))
            .collect();
        w.push(format!("({})", works.join(" OR ")));
        w.push(format!("acl ∈ {{{}}}", scope.acl().join(", ")));
        w.push(format!("trust >= {}", self.min_trust));
        w.push("status ∉ {superseded, revoked, unverified}".into());
        w.push("safety < restricted".into());
        let mut rank = vec!["bm25(text)".to_string()];
        if !self.concepts.is_empty() {
            rank.push("4×concept".into());
        }
        if !self.prefer_predicates.is_empty() {
            rank.push(format!("1.5×predicate∈[{}]", self.prefer_predicates.join(",")));
        }
        format!("FIND fact WHERE {} RANK BY {} LIMIT {}", w.join("\n  AND "), rank.join(" + "), self.limit)
    }
}

fn term(_ix: &FactIndex, field: tantivy::schema::Field, v: &str) -> Box<dyn Query> {
    Box::new(TermQuery::new(Term::from_field_text(field, v), IndexRecordOption::WithFreqs))
}

fn filter(q: Box<dyn Query>) -> Box<dyn Query> {
    Box::new(ConstScoreQuery::new(q, 0.0))
}

/// Compose the single index query for an FQL request under a scope.
pub fn compile(ix: &FactIndex, scope: &Scope, q: &Fql) -> Box<dyn Query> {
    let f = &ix.f;
    let mut clauses: Vec<(Occur, Box<dyn Query>)> = Vec::new();

    // structure: text and/or concepts
    let mut text_q: Vec<(Occur, Box<dyn Query>)> = Vec::new();
    for t in &q.text {
        for a in ix.analyze(t) {
            text_q.push((Occur::Should, term(ix, f.text, &a)));
        }
    }
    let concept_q: Vec<(Occur, Box<dyn Query>)> = q
        .concepts
        .iter()
        .map(|c| (Occur::Should, Box::new(BoostQuery::new(term(ix, f.concepts, c), 4.0)) as Box<dyn Query>))
        .collect();
    if q.require_concept && !concept_q.is_empty() {
        clauses.push((Occur::Must, Box::new(BooleanQuery::new(concept_q))));
        if !text_q.is_empty() {
            clauses.push((Occur::Should, Box::new(BooleanQuery::new(text_q))));
        }
    } else {
        let mut any = text_q;
        any.extend(concept_q);
        if any.is_empty() {
            clauses.push((Occur::Must, Box::new(AllQuery)));
        } else {
            clauses.push((Occur::Must, Box::new(BooleanQuery::new(any))));
        }
    }
    for p in &q.prefer_predicates {
        clauses.push((Occur::Should, Box::new(BoostQuery::new(term(ix, f.predicate, p), 1.5))));
        // the same relation as imported under a feed's governed namespace
        clauses.push((Occur::Should, Box::new(BoostQuery::new(term(ix, f.predicate, &format!("ufcs:{p}")), 1.5))));
    }
    if !q.only_predicates.is_empty() {
        let only: Vec<(Occur, Box<dyn Query>)> =
            q.only_predicates.iter().map(|p| (Occur::Should, term(ix, f.predicate, p))).collect();
        clauses.push((Occur::Must, filter(Box::new(BooleanQuery::new(only)))));
    }
    if let Some(c) = q.chapter {
        clauses.push((
            Occur::Must,
            filter(Box::new(RangeQuery::new(
                Bound::Included(Term::from_field_u64(f.chapter, c)),
                Bound::Included(Term::from_field_u64(f.chapter, c)),
            ))),
        ));
    }

    // scope: works (bounded by reading position) or enabled corpora
    let mut scope_q: Vec<(Occur, Box<dyn Query>)> = Vec::new();
    for (w, max) in scope.works() {
        let mut both: Vec<(Occur, Box<dyn Query>)> = vec![(Occur::Must, term(ix, f.work, w))];
        if *max != u64::MAX {
            both.push((
                Occur::Must,
                Box::new(RangeQuery::new(
                    Bound::Included(Term::from_field_u64(f.pos, 0)),
                    Bound::Included(Term::from_field_u64(f.pos, *max)),
                )),
            ));
        }
        scope_q.push((Occur::Should, Box::new(BooleanQuery::new(both))));
    }
    for c in scope.corpora() {
        scope_q.push((Occur::Should, term(ix, f.corpus, c)));
    }
    clauses.push((Occur::Must, filter(Box::new(BooleanQuery::new(scope_q)))));
    // access control carried in the record
    let acl_q: Vec<(Occur, Box<dyn Query>)> = scope.acl().iter().map(|a| (Occur::Should, term(ix, f.acl, a))).collect();
    clauses.push((Occur::Must, filter(Box::new(BooleanQuery::new(acl_q)))));
    // trust-native pruning, status and safety
    if q.min_trust > 0.0 {
        clauses.push((
            Occur::Must,
            filter(Box::new(RangeQuery::new(Bound::Included(Term::from_field_f64(f.trust, q.min_trust)), Bound::Unbounded))),
        ));
    }
    // reader-authored records are listed by their own surface, never cited as the book
    clauses.push((Occur::MustNot, term(ix, f.group, "reader")));
    for s in ["superseded", "revoked", "unverified"] {
        clauses.push((Occur::MustNot, term(ix, f.status, s)));
    }
    clauses
        .push((Occur::MustNot, Box::new(RangeQuery::new(Bound::Included(Term::from_field_u64(f.safety, 2)), Bound::Unbounded))));
    Box::new(BooleanQuery::new(clauses))
}
