# Lecturn Eval Strategy

Week 2 of the Lecturn build. By the end of this week: a working eval harness
on a 17-example golden dataset, scoring faithfulness + completeness + format
validity, with a baseline scorecard from the live pipeline.

---

## Section 1 — Why Citation Faithfulness Is Lecturn's Hardest Eval

Lecturn's core promise is **cited, traceable answers**. Every factual claim
should point to a specific source in the corpus. That makes faithfulness —
"is this claim actually supported by what was retrieved?" — the most
important thing to measure.

It is also the hardest.

### Why faithfulness is hard to eval

**Deterministic checks can only check the format, not the truth.**
`citation_format_valid()` verifies that every claim sentence ends with
`[source: X]`. It cannot verify that the cited source actually says what
the claim asserts. A claim like "RAG was invented at Google in 2019.
[source: Lewis 2020]" passes the deterministic check but is factually wrong
(Lewis et al. were at Facebook AI Research, 2020).

**LLM-as-judge for faithfulness is itself unreliable.**
The natural solution — ask an LLM to check whether a claim is supported by
the retrieved chunks — has a fundamental problem: the judge is also an LLM.
It has its own hallucination risk. It can:

- **Miss a hallucination** if the hallucinated claim is plausible and
  consistent with the judge's training data, even if it's not in the chunks.
- **Flag a correct claim** if the claim is phrased differently from how
  the source puts it, and the judge doesn't infer the equivalence.
- **Get confused by long contexts** when many chunks are passed together
  and the judge loses track of which chunk supports which claim.

This is not a reason to abandon LLM-as-judge — it is better than no
semantic check. But it is a reason to treat faithfulness scores as signals,
not ground truth, and to pair them with human spot-checking on low-scoring
examples.

**The deeper problem: plausible-sounding hallucinations are invisible.**
The failures that matter most are the ones that look correct. A wildly wrong
claim ("RAG was invented in 1985") is easy to catch. A subtly wrong claim
("Self-RAG uses three reflection tokens" when it actually uses four) is much
harder — for the judge, for the user, and for any automated check.

This is why Lecturn's eval strategy uses three layers rather than one.
No single check is sufficient. Deterministic checks catch format failures
cheaply. LLM-as-judge catches semantic failures at moderate cost.
The golden dataset catches retrieval failures by comparison against ground
truth. Only together do they provide reasonable coverage.

---

## Section 2 — The 10 Failure Modes

See `lecturn_failure_modes.md` for the full breakdown with explanations
and severity ratings. Summary:

### Structural failures (caught by deterministic checks)

| # | Failure | Eval function |
|---|---------|--------------|
| 1 | Invalid JSON output | `is_valid_json()` |
| 2 | Missing required sections | `has_required_fields()` |
| 3 | Uncited claims | `citation_format_valid()` |
| 4 | Source concentration (over-reliance on one source) | `no_duplicate_sources()` |

### Semantic failures (caught by LLM-as-judge)

| # | Failure | Eval function |
|---|---------|--------------|
| 5 | Hallucinated citations | `judge_faithfulness()` |
| 6 | Wrong attribution (right fact, wrong source) | `judge_faithfulness()` |
| 7 | Missed key sources | `judge_completeness()` |
| 8 | Fabricated quotes | Deterministic string-match + `judge_faithfulness()` |

### Behavioural failures (caught by golden dataset + human review)

| # | Failure | Eval function |
|---|---------|--------------|
| 9 | Confidence not calibrated to evidence strength | `judge_completeness()` + human |
| 10 | Self-contradiction between sections | `judge_faithfulness()` on claim pairs + human |

---

## Section 3 — What Each Eval Catches

The three eval layers are ordered by cost and run in sequence:
deterministic first (free, milliseconds), then judge (LLM call, seconds).
If deterministic checks fail, the LLM judge is skipped — no point scoring
semantics on a broken response.

```
Output
  │
  ▼
[1] Deterministic checks          ← always run, free
    is_valid_json()
    has_required_fields()
    citation_format_valid()
    no_duplicate_sources()
  │
  ├─ FAIL → log failure, skip further checks
  │
  ▼
[2] LLM faithfulness judge        ← per-claim, costs ~1 API call per claim
    judge_faithfulness(claim, retrieved_chunks)
  │
  ▼
[3] LLM completeness judge        ← per-example, costs 1 API call
    judge_completeness(output, expected_key_claims)
```

The golden dataset also drives a **source recall check** in the eval runner:
for each example, we check whether the sources Lecturn cited overlap with
`expected_sources` from the golden dataset. This is a deterministic check
but requires ground truth, which is why it lives in the runner rather than
`deterministic.py`.

Full coverage map:

| Failure mode | Deterministic | Faithfulness judge | Completeness judge | Golden dataset |
|---|:---:|:---:|:---:|:---:|
| 1. Invalid JSON | ✓ | | | |
| 2. Missing sections | ✓ | | | |
| 3. Uncited claims | ✓ | | | |
| 4. Source concentration | ✓ | | | |
| 5. Hallucinated citations | partial* | ✓ | | |
| 6. Wrong attribution | | ✓ | | |
| 7. Missed key sources | | | ✓ | ✓ |
| 8. Fabricated quotes | partial* | ✓ | | |
| 9. Confidence calibration | | | ✓ | ✓ |
| 10. Self-contradiction | | ✓ (pairs) | | |

*Partial = citation format is checked, not citation accuracy.

---

## Section 4 — Day 13 Scorecard and What It Means

### The numbers

```
Examples evaluated :  17
Deterministic pass :  0/17  (0%)
Avg faithfulness   :  4.03 / 5
Avg completeness   :  2.24 / 5

By mode:
  comparison    n=6   faith=4.08   comp=2.33
  lit-review    n=5   faith=3.91   comp=2.20
  notes         n=6   faith=0.00   comp=2.17
```

### What's working: faithfulness at 4.03/5

The retrieval layer is doing its job. When chunks are retrieved and passed
to the generation model, the model is mostly generating claims that are
grounded in those chunks. A 4.03 average faithfulness on a naive RAG
baseline (retrieve → stuff → generate) is a solid foundation.

The `notes` mode showing 0.00 faithfulness is a data artefact: those
examples returned invalid JSON, giving the judge an empty or garbled input
and producing a 0 score. The retrieval and generation quality for notes
questions is consistent with the other modes.

### What's broken: deterministic at 0/17

Two root causes:

**1. The model is not returning strict JSON.**
11 out of 17 responses were wrapped in markdown code fences
(` ```json ... ``` `) despite the prompt saying not to. This is a known
behaviour with instruction-following models — the generation prompt needs
to enforce JSON mode at the API level using
`response_format={"type": "json_object"}`, not just in natural language.

**2. Claims are not consistently cited.**
Even the examples with valid JSON had uncited sentences. The model followed
the citation instruction partially but not reliably. The fix is a stronger
citation instruction with a worked example embedded directly in the prompt,
plus chain-of-thought: "for each claim you write, immediately add
[source: title]."

Both are **generation prompt failures**, not retrieval failures. The
deterministic checks caught them correctly. This is exactly what they're
there for.

### What's the real problem: completeness at 2.24/5

This is the genuinely low signal and it's informative:

- Average completeness of 2.24 means the outputs cover roughly 40–50% of
  the key claims we expected from the golden dataset.
- The three worst examples (score 1/5) share a pattern: the model retrieved
  topically related chunks but not the specific chunks containing the key
  claim. For example, a query about contextual retrieval got chunks about
  retrieval in general but not the specific Anthropic post passage that
  describes the 67% failure-rate reduction.

This is a **retrieval coverage gap**, not solely a generation problem.
The naive baseline retrieval (embed query → cosine similarity → top-5) is
good at finding topically related content but poor at ensuring *all* key
claims from a topic are represented in the top-5. A query about a
comparison topic needs chunks from both sides of the comparison;
top-5 cosine similarity may skew toward one side.

The agent (Week 3) addresses this directly: it can plan to retrieve from
multiple angles, check coverage, and issue follow-up retrievals if key
claims are missing.

### Interpreting the baseline numbers

These numbers are expected for a naive RAG baseline with no agent, no
query planning, and a first-pass generation prompt. The purpose of running
evals on Day 13 is not to show a polished system — it's to establish a
honest baseline that every future improvement can be measured against.

The raw results are saved to `evals/last_run_results.json`. Every time a
significant change is made to the pipeline (fixing JSON mode, adding the
agent, improving prompts), re-running `scripts/run_evals.py` will show
whether the change helped or hurt, and by how much.

---

## Section 5 — What Production Would Add

The current eval harness is a solid foundation, but production systems
require more:

### Human evaluation

LLM-as-judge is a proxy. For a production system, you would run
**periodic human eval** on a sample of real queries — not the golden
dataset, but actual user queries from production logs. Human evaluators
catch the subtle failures automated evals miss: wrong tone, misleading
framing, correct facts presented in a confusing order.

A practical setup: weekly, randomly sample 20 production queries, have
a team member rate each output on faithfulness (1–5) and completeness
(1–5). Plot the human scores against the automated scores. If they
diverge over time, the automated evals have drifted and need recalibration.

### Regression testing

The golden dataset currently runs as a one-shot scorecard. In production
it should run as a **regression suite** on every code change — like unit
tests, but for output quality. Any PR that drops faithfulness by more than
0.3 or completeness by more than 0.5 should be flagged for review before
merging.

This requires version-pinning: the same model, the same retrieval index,
the same corpus. If any of those change, re-establish the baseline first.

### Eval drift

The golden dataset reflects what *you* thought was important when you
wrote it. Over time, as the corpus grows and user queries evolve, the
golden dataset becomes stale. Production eval strategy should include:

- **Adding new golden examples whenever a real user query reveals a new
  failure mode.** The best golden examples come from production failures,
  not upfront speculation.
- **Retiring golden examples** that no longer reflect realistic queries.
- **Tracking eval coverage**: what failure modes are not covered by any
  golden example? The coverage table in Section 3 is a useful guide.

### Confidence-aware serving

Right now the eval harness produces scores but doesn't act on them.
A production system would use real-time quality signals to decide whether
to serve a response or fall back. For example: if faithfulness of all
claims is below 3.0, show the user the retrieved chunks directly rather
than the generated synthesis, with a note that confidence is low.

### Eval cost management

At scale, running a faithfulness judge on every claim in every production
response is expensive. Production approaches to manage this:

- **Sample-based evaluation**: run full evals on 5–10% of production
  responses rather than every one.
- **Tiered evaluation**: run deterministic checks on 100% of responses,
  LLM judge on samples, human eval on a smaller sample.
- **Cached judge results**: if the same claim appears repeatedly (common
  for factual questions about popular papers), cache the faithfulness
  score rather than re-running the judge.
