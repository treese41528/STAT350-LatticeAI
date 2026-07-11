"""Router, rewrite, retrieve, citations — the deterministic grounding units."""

from __future__ import annotations

from app.config import RetrievalCfg, ThresholdsCfg
from app.grounding.citations import (catalog_card_for, extract_markers,
                                     lint_links, validate_markers)
from app.grounding.retrieve import retrieve
from app.grounding.rewrite import build_retrieval_query
from app.grounding.router import route

from .conftest import FakeGateway, webbook_payload


# ---- router -----------------------------------------------------------------

def test_router_intents(resolver):
    assert route("hi there!", resolver).intent == "smalltalk"
    assert route("what's on exam 2?", resolver).intent == "exam_info"
    assert route("when is the final exam date?", resolver).intent == "syllabus_schedule"
    assert route("give me the link to worksheet 5", resolver).intent == "resource_lookup"
    assert route("where is the CLT video", resolver).intent == "resource_lookup"
    assert route("why do we divide by n-1?", resolver).intent == "concept_question"
    # question words override lookup phrasing
    assert route("can you explain what section 10.2 says about power?",
                 resolver).intent == "concept_question"


def test_router_exam_key(resolver):
    assert route("what will be on the final?", resolver).exam_key == "final"
    assert route("what's covered on exam 2", resolver).exam_key == "2"


def test_router_modality_gate(resolver):
    assert route("where is the syllabus?", resolver, modality=None).needs_modality
    assert not route("where is the syllabus?", resolver,
                     modality="flipped").needs_modality


# ---- rewrite -------------------------------------------------------------------

def test_rewrite_passthrough_for_full_questions():
    q = "How do I construct a 95% confidence interval for the mean?"
    assert build_retrieval_query([], q) == q


def test_rewrite_prepends_context_for_anaphora():
    history = [
        {"role": "user", "content": "What are the assumptions of the two-sample t test?"},
        {"role": "assistant", "content": "The key assumptions are independence and normality."},
    ]
    out = build_retrieval_query(history, "what about the second one?")
    assert "two-sample t test" in out
    assert "second one" in out


def test_rewrite_strips_fluff():
    out = build_retrieval_query([], "hi can you help me with pooled variance please")
    assert not out.lower().startswith("hi")
    assert "pooled variance" in out


# ---- retrieve ---------------------------------------------------------------------

def _cfg(**kw) -> RetrievalCfg:
    base = dict(k_webbook=4, k_transcripts=2, max_passages=6,
                min_transcript_slots=1,
                thresholds=ThresholdsCfg(strong=0.55, weak=0.80))
    base.update(kw)
    return RetrievalCfg(**base)


def test_retrieve_labels_and_tiers(resolver):
    gw = FakeGateway(retrieval_payloads={
        "kb-web": webbook_payload(
            ("7-3-clt.rst", "The CLT says the sample mean is approximately normal.", 0.30),
            ("7-2-sampling-distribution-for-the-sample-mean.rst", "Sampling distributions...", 0.50)),
        "kb-tr": {"documents": [["In lecture we said the CLT kicks in around n=30."]],
                  "distances": [[0.45]],
                  "metadatas": [[{"name": "lecture_7-3_transcript.vtt"}]]},
    })
    rr = retrieve(gw, resolver, "central limit theorem", _cfg())
    assert rr.tier == "strong"
    assert [p.collection for p in rr.passages] == ["webbook", "transcript", "webbook"]
    assert [p.n for p in rr.passages] == [1, 2, 3]
    assert rr.passages[0].resolved.section.number == "7.3"
    assert rr.passages[1].resolved.video_url  # transcript → video link
    assert len(gw.retrieval_calls) == 2  # one per collection by default


def test_retrieve_weak_tier_and_empty(resolver):
    gw = FakeGateway(retrieval_payloads={
        "kb-web": webbook_payload(("7-3-clt.rst", "off topic text", 0.95))})
    rr = retrieve(gw, resolver, "quantum chromodynamics", _cfg())
    assert rr.tier == "no_evidence"

    gw2 = FakeGateway()
    rr2 = retrieve(gw2, resolver, "anything", _cfg())
    assert rr2.tier == "no_evidence" and rr2.passages == []


def test_retrieve_caveat_between_thresholds(resolver):
    gw = FakeGateway(retrieval_payloads={
        "kb-web": webbook_payload(("7-3-clt.rst", "loosely related", 0.70))})
    rr = retrieve(gw, resolver, "something adjacent", _cfg())
    assert rr.tier == "caveat"


def test_retrieve_dedupes(resolver):
    same = ("7-3-clt.rst", "identical chunk text repeated in both", 0.4)
    gw = FakeGateway(retrieval_payloads={
        "kb-web": webbook_payload(same, same)})
    rr = retrieve(gw, resolver, "clt", _cfg())
    assert len(rr.passages) == 1


def test_retrieve_survives_gateway_error(resolver):
    class Boom(FakeGateway):
        def retrieval_query(self, *a, **kw):
            raise ConnectionError("gateway down")
    rr = retrieve(Boom(), resolver, "clt", _cfg())
    assert rr.tier == "no_evidence" and rr.error


def test_retrieve_single_call_labels_rows(resolver):
    gw = FakeGateway(retrieval_payloads={
        "both": {
            "documents": [["webbook chunk about the CLT"],
                          ["transcript chunk about the CLT"]],
            "distances": [[0.3], [0.4]],
            "metadatas": [[{"name": "7-3-clt.rst"}],
                          [{"name": "lecture_7-3_transcript.vtt"}]],
        }})
    rr = retrieve(gw, resolver, "clt", _cfg(), single_call=True)
    assert len(gw.retrieval_calls) == 1
    assert {p.collection for p in rr.passages} == {"webbook", "transcript"}


# ---- citations & linting -------------------------------------------------------------

def test_extract_and_validate_markers(resolver):
    gw = FakeGateway(retrieval_payloads={
        "kb-web": webbook_payload(("7-3-clt.rst", "text", 0.3))})
    rr = retrieve(gw, resolver, "clt", _cfg())
    text = "The CLT [1] applies here. Also see [1] and the bogus [7]."
    assert extract_markers(text) == [1, 7]
    ok, bad = validate_markers(text, rr.passages)
    assert ok == [1] and bad == [7]


def test_lint_links_removes_unknown_urls(resolver):
    good = "https://treese41528.github.io/STAT350/Website/chapter7/lectures/7-3-clt.html"
    text = f"See {good} but never http://sketchy.io/stats and https://evil.com/x."
    clean, removed = lint_links(text, resolver)
    assert good in clean
    assert "sketchy" not in clean and "evil.com" not in clean
    assert len(removed) == 2


def test_catalog_card_only_with_banner(resolver):
    banner = (">>> BEYOND STAT 350 SCOPE: Enrichment for curious learners; "
              "not required for this course. <<<\nSee STAT 41600 for proofs.")
    card = catalog_card_for(banner, resolver)
    assert card and card["kind"] == "catalog" and "41600" in card["title"]
    assert "catalog.purdue.edu" in card["url"]
    assert catalog_card_for("Plain answer mentioning STAT 41600", resolver) is None
