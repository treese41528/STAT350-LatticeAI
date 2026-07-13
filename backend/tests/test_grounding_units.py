"""Router, rewrite, retrieve, citations — the deterministic grounding units."""

from __future__ import annotations

from app.config import RetrievalCfg, ThresholdsCfg
from app.grounding.citations import (catalog_card_for, extract_markers,
                                     lint_links, normalize_markers,
                                     validate_markers)
from app.grounding.retrieve import retrieve
from app.grounding.rewrite import build_retrieval_query
from app.grounding.router import route

from .conftest import FakeGateway, webbook_payload


# ---- router -----------------------------------------------------------------

def test_router_intents(resolver):
    assert route("hi there!", resolver).intent == "smalltalk"
    assert route("what's on exam 2?", resolver).intent == "exam_info"
    assert route("give me the link to worksheet 5", resolver).intent == "resource_lookup"
    assert route("where is the CLT video", resolver).intent == "resource_lookup"
    assert route("why do we divide by n-1?", resolver).intent == "concept_question"
    # question words override lookup phrasing
    assert route("can you explain what section 10.2 says about power?",
                 resolver).intent == "concept_question"


def test_route_frustration_vs_real_question(resolver):
    # pure venting -> frustration (empathetic reply, no retrieval/resources)
    for msg in ["Fuck STATS", "stats sucks", "this is so hard", "ugh",
                "i give up", "I'm so lost", "this is stupid", "I hate stats"]:
        assert route(msg, resolver).intent == "frustration", msg
    # a profanity-laced ACTUAL question must NOT be swallowed — it gets answered
    for msg in ["why the hell do we divide by n-1?",
                "what the heck is a p-value?",
                "how do I compute the variance?"]:
        assert route(msg, resolver).intent == "concept_question", msg

    # disengagement / quitting -> empathy path (no congratulations, no cards)
    for msg in ["I quit!", "I'm dropping out", "maybe I'll leave university",
                "I am just done with stats and maybe will leave university",
                "thinking of quitting school", "I might drop out"]:
        assert route(msg, resolver).intent == "frustration", msg
    # superficially-similar REAL questions must not be caught as disengagement
    for msg in ["how do I quit R?", "should I drop outliers?",
                "how do I drop my lowest quiz?"]:
        assert route(msg, resolver).intent != "frustration", msg

    # venting with an academic noun between the subject and the sentiment word
    # (these vector-match course vocabulary, so they MUST be caught at the router)
    for msg in ["This course sucks!", "this class is confusing",
                "the lectures are useless", "I hate this course",
                "this homework is impossible", "the exams are impossible"]:
        assert route(msg, resolver).intent == "frustration", msg
    # real questions that MENTION those nouns must still route normally
    for msg in ["explain the material in chapter 5", "is this course curved?",
                "what course topics are on exam 2?",
                "can you explain the lectures on CLT?"]:
        assert route(msg, resolver).intent != "frustration", msg


async def test_triage_weak_parsing():
    # the weak-retrieval triage extracts one label and DEFAULTS TO STATS on any
    # error or ambiguity (so a hiccup never turns a real question into a brush-off)
    from types import SimpleNamespace

    from app.grounding.pipeline import _triage_weak

    class _FakeGW:
        def __init__(self, out):
            self._out = out

        def stream_chat(self, messages, **kw):
            def _gen():
                if self._out is None:
                    raise RuntimeError("gateway boom")
                yield self._out
            return _gen()

    cases = [("VENTING", "VENTING"), ("OFFTOPIC", "OFFTOPIC"),
             ("off-topic", "OFFTOPIC"), ("STATS", "STATS"), ("stats", "STATS"),
             ("  venting\n", "VENTING"), ("nonsense", "STATS"), (None, "STATS")]
    for out, expected in cases:
        ctx = SimpleNamespace(gateway=_FakeGW(out), message="whatever")
        assert await _triage_weak(ctx) == expected, out


def test_router_syllabus_link_vs_content(resolver):
    # pure "where is it / give me the link" -> deterministic link response
    for q in ["where is the syllabus?", "can you send me the syllabus link",
              "link to the schedule please", "where can i find the schedule"]:
        assert route(q, resolver).intent == "syllabus_schedule", q
    # policy / logistics questions -> quote from the syllabus (content)
    for q in ["how much is the homework worth?", "what's the late homework policy?",
              "how many midterms are there?", "when is the final exam date?",
              "how do make-up exams work?", "are the lowest quizzes dropped?",
              "what are the office hours?"]:
        assert route(q, resolver).intent == "syllabus_content", q
    # content questions still need the modality first
    assert route("how much are exams worth?", resolver, modality=None).needs_modality
    assert not route("how much are exams worth?", resolver,
                     modality="flipped").needs_modality


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
    # scores are similarities (higher=better): strong>=0.75, weak-floor 0.66
    base = dict(k_webbook=4, k_transcripts=2, max_passages=6,
                min_transcript_slots=1, higher_is_better=True,
                thresholds=ThresholdsCfg(strong=0.75, weak=0.66))
    base.update(kw)
    return RetrievalCfg(**base)


def test_retrieve_labels_and_tiers(resolver):
    gw = FakeGateway(retrieval_payloads={
        "kb-web": webbook_payload(
            ("7-3-clt.rst", "The CLT says the sample mean is approximately normal.", 0.86),
            ("7-2-sampling-distribution-for-the-sample-mean.rst", "Sampling distributions...", 0.80)),
        "kb-tr": {"documents": [["In lecture we said the CLT kicks in around n=30."]],
                  "distances": [[0.83]],
                  "metadatas": [[{"name": "lecture_7-3_transcript.vtt"}]]},
    })
    rr = retrieve(gw, resolver, "central limit theorem", _cfg())
    assert rr.tier == "strong"
    # best-first ordering: 0.86 web, 0.83 transcript, 0.80 web
    assert [p.collection for p in rr.passages] == ["webbook", "transcript", "webbook"]
    assert [p.n for p in rr.passages] == [1, 2, 3]
    assert rr.passages[0].resolved.section.number == "7.3"
    assert rr.passages[0].similarity > rr.passages[2].similarity  # higher score = higher sim
    assert rr.passages[1].resolved.video_url  # transcript → video link
    assert len(gw.retrieval_calls) == 2  # one per collection by default


def test_retrieve_weak_tier_and_empty(resolver):
    gw = FakeGateway(retrieval_payloads={
        "kb-web": webbook_payload(("7-3-clt.rst", "off topic text", 0.58))})
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
    same = ("7-3-clt.rst", "identical chunk text repeated in both", 0.8)
    gw = FakeGateway(retrieval_payloads={
        "kb-web": webbook_payload(same, same)})
    rr = retrieve(gw, resolver, "clt", _cfg())
    assert len(rr.passages) == 1


def test_retrieve_transcript_floor_adds_multiple(resolver):
    # webbook dominates top-k; two transcripts sit just below the cut but clear
    # the weak bar. min_transcript_slots=2 must surface BOTH (regression: the
    # old code overwrote the same slot and added only one).
    gw = FakeGateway(retrieval_payloads={
        "kb-web": webbook_payload(
            ("7-3-clt.rst", "w1", 0.90),
            ("7-2-sampling-distribution-for-the-sample-mean.rst", "w2", 0.88),
            ("7-1-statistics-and-sampling-distributions.rst", "w3", 0.86)),
        "kb-tr": {
            "documents": [["t1", "t2"]], "distances": [[0.80, 0.78]],
            "metadatas": [[{"name": "STAT 350 - Chapter 7.3 CLT.srt"},
                           {"name": "STAT 350 - Chapter 7.2 sampling.srt"}]]},
    })
    rr = retrieve(gw, resolver, "clt", _cfg(max_passages=3, min_transcript_slots=2))
    assert sum(1 for p in rr.passages if p.collection == "transcript") == 2
    assert len(rr.passages) == 3  # cap respected


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


def test_normalize_markers_folds_openai_citations():
    # gpt-oss sometimes emits OpenAI file-citation style; fold it to plain [n]
    assert normalize_markers("the mean is normal [1†L7-L12] for large n") == \
        "the mean is normal [1] for large n"
    assert normalize_markers("see [2†source] and [3†L1-L4]") == "see [2] and [3]"
    assert normalize_markers("cite 【1†syllabus.md†L5】 here") == "cite [1] here"
    # plain markers and non-citation brackets are untouched
    assert normalize_markers("already [1] and [2][3] fine") == "already [1] and [2][3] fine"
    # after normalizing, the markers actually validate as [n]
    assert extract_markers(normalize_markers("x [4†L1-L9] y")) == [4]


def test_lint_links_removes_unknown_urls(resolver):
    good = "https://treese41528.github.io/STAT350/Website/chapter7/lectures/7-3-clt.html"
    text = f"See {good} but never http://sketchy.io/stats and https://evil.com/x."
    clean, removed = lint_links(text, resolver)
    assert good in clean
    assert "sketchy" not in clean and "evil.com" not in clean
    assert len(removed) == 2


def test_lint_links_case_insensitive(resolver):
    # uppercase scheme must NOT bypass the lint (the frontend renders HTTP://
    # as a live link, so a survivor is a phishing vector)
    text = "click HTTP://evil.com/x or Https://bad.example/y"
    clean, removed = lint_links(text, resolver)
    assert "evil.com" not in clean and "bad.example" not in clean
    assert len(removed) == 2


def test_catalog_card_only_with_banner(resolver):
    banner = (">>> BEYOND STAT 350 SCOPE: Enrichment for curious learners; "
              "not required for this course. <<<\nSee STAT 41600 for proofs.")
    card = catalog_card_for(banner, resolver)
    assert card and card["kind"] == "catalog" and "41600" in card["title"]
    assert "catalog.purdue.edu" in card["url"]
    assert catalog_card_for("Plain answer mentioning STAT 41600", resolver) is None


def test_catalog_card_stat418_next_course(resolver):
    # STAT 350 is a direct prerequisite of STAT 41800 (Tim's course); the tutor
    # should surface it as the go-deeper course, and the app attaches its site.
    banner = (">>> BEYOND STAT 350 SCOPE: Enrichment for curious learners; "
              "not required for this course. <<<\nBootstrap CIs are covered in "
              "STAT 41800.")
    card = catalog_card_for(banner, resolver)
    assert card and card["kind"] == "catalog"
    assert "41800" in card["title"] and "Computational Methods" in card["title"]
    assert card["url"].startswith(
        "https://treese41528.github.io/ComputationalDataScience")
    assert resolver.is_allowed_url(card["url"])
