"""LLM-judge answer eval: answer generation (fake gateway), the pure scoring /
aggregation, and the judge wrapper (stub Agent — no gateway)."""

from __future__ import annotations

from app.eval.judge import (DIMENSIONS, JudgedItem, RubricVerdict, generate_answer,
                            judge_answer, judge_prompt, overall_score, summarize)

from .conftest import FakeGateway, webbook_payload

TUTOR_CORE = "You are the STAT 350 tutor. Cite [n]. Never write URLs."


def _verdict(**kw) -> RubricVerdict:
    base = dict(correctness=2, grounded=2, citations=2, scope=2, pedagogy=2,
                addressed=2, verdict="pass", main_issue="none")
    base.update(kw)
    return RubricVerdict(**base)


# ---- answer generation (reproduces the pipeline, no DB) -------------------

def test_generate_answer_concept(settings, resolver):
    gw = FakeGateway(
        retrieval_payloads={"kb-web": webbook_payload(
            ("7-3-clt.rst", "The Central Limit Theorem: the sample mean is "
                            "approximately normal for large n.", 0.86))},
        stream_chunks=["The sample mean is approximately normal by the CLT [1]. ",
                       "What condition on n makes this hold? [2]"])
    q = {"question": "explain the central limit theorem", "type": "concept"}
    ar = generate_answer(gw, resolver, settings, TUTOR_CORE, q)

    assert ar.refused is False and ar.tier == "strong"
    assert ar.kind == "concept"
    assert "CLT" in ar.answer or "normal" in ar.answer
    assert ar.passages and ar.passages[0].n == 1
    # [1] maps to a real passage; [2] does not (only one passage retrieved)
    assert 1 in ar.resolved_markers and 2 in ar.hallucinated_markers
    assert gw.chat_calls, "the answer must come from a real generation call"


def test_generate_answer_refuses_on_no_evidence(settings, resolver):
    from app.grounding.pipeline import REFUSAL_MESSAGE
    gw = FakeGateway(retrieval_payloads={})   # nothing retrievable -> no_evidence
    q = {"question": "what is the airspeed velocity of an unladen swallow?",
         "type": "concept"}
    ar = generate_answer(gw, resolver, settings, TUTOR_CORE, q)

    assert ar.refused is True and ar.tier == "no_evidence"
    assert ar.answer == REFUSAL_MESSAGE
    # weak retrieval runs a cheap triage (fake -> STATS); the refusal still skips
    # the grounded generation call — only the one-word triage ran.
    assert len(gw.chat_calls) == 1
    assert "STATS, VENTING, or OFFTOPIC" in gw.chat_calls[0][0]["content"]


# ---- pure scoring + aggregation -------------------------------------------

def test_overall_score():
    assert overall_score(_verdict()) == 1.0
    assert overall_score(_verdict(correctness=0, grounded=0, citations=0,
                                  scope=0, pedagogy=0, addressed=0)) == 0.0
    # one dimension at 1, rest at 2 -> 11/12
    assert abs(overall_score(_verdict(pedagogy=1)) - 11 / 12) < 1e-9


def test_rubric_verdict_rejects_out_of_range():
    import pytest
    with pytest.raises(Exception):
        _verdict(correctness=3)


def test_summarize_aggregates_and_ranks_worst():
    items = [
        JudgedItem("q1", chapter=8, kind="concept", modality=None, refused=False,
                   tier="strong", verdict=_verdict(), score=1.0, answer="a"),
        JudgedItem("q2", chapter=8, kind="concept", modality=None, refused=False,
                   tier="caveat", verdict=_verdict(correctness=0, verdict="fail",
                                                   main_issue="wrong test"),
                   score=0.5, answer="b"),
        JudgedItem("q3", chapter=9, kind="syllabus", modality="flipped",
                   refused=True, tier="no_evidence",
                   verdict=_verdict(correctness=0, addressed=0, verdict="fail",
                                    main_issue="refused an answerable question"),
                   score=0.2, answer="c"),
    ]
    s = summarize(items, errors=1)
    assert s["n"] == 3 and s["errors"] == 1
    assert abs(s["mean_score"] - (1.0 + 0.5 + 0.2) / 3) < 1e-9
    assert s["verdicts"] == {"pass": 1, "borderline": 0, "fail": 2}
    assert s["refusals"] == 1
    assert set(s["dimension_means"]) == set(DIMENSIONS)
    # worst is ranked ascending by score; q3 (0.2) first
    assert s["worst"][0]["question"] == "q3"
    assert s["worst"][0]["issue"] == "refused an answerable question"
    assert s["per_chapter_mean"]["8"] == 0.75  # (1.0 + 0.5) / 2


def test_summarize_empty():
    assert summarize([], errors=2) == {"n": 0, "errors": 2}


# ---- judge wrapper (stub Agent) -------------------------------------------

class _FakeAgentResult:
    def __init__(self, output):
        self.output = output


class _FakeJudge:
    def __init__(self, output=None, raises=False):
        self._output, self._raises = output, raises
        self.prompts: list = []

    def run(self, prompt):
        self.prompts.append(prompt)
        if self._raises:
            raise RuntimeError("gateway blew up")
        return _FakeAgentResult(self._output)


def _answer_run():
    from app.eval.judge import AnswerRun
    return AnswerRun(question="how much is homework worth?", kind="syllabus",
                     modality="flipped", answer="Homework is 24% of your grade [1].",
                     refused=False, tier="strong", passages=[],
                     resolved_markers=[1], hallucinated_markers=[])


def test_judge_answer_returns_verdict():
    v = _verdict(pedagogy=1, verdict="borderline", main_issue="a bit terse")
    judge = _FakeJudge(output=v)
    q = {"question": "how much is homework worth?", "type": "syllabus",
         "modality": "flipped", "expected_answer": "24% (Flipped)"}
    out = judge_answer(judge, q, _answer_run())
    assert out is v
    # the reference answer is shown to the judge for syllabus questions
    assert "24% (Flipped)" in judge.prompts[0]


def test_judge_answer_none_on_error():
    assert judge_answer(_FakeJudge(raises=True), {"question": "q"}, _answer_run()) is None
    assert judge_answer(_FakeJudge(output=None), {"question": "q"}, _answer_run()) is None


def test_judge_prompt_flags_refusal_and_hallucinations():
    from app.eval.judge import AnswerRun
    ar = AnswerRun(question="q", kind="concept", modality=None, answer="…",
                   refused=True, tier="no_evidence", passages=[])
    assert "REFUSED" in judge_prompt({"question": "q", "type": "concept"}, ar)
