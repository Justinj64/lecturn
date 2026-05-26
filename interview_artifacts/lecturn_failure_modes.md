# Lecturn Failure Modes

10 ways Lecturn can fail, grouped by what type of eval catches them.

---

## Structural failures (caught by deterministic checks)

### 1. Invalid JSON output
**What happens:** Lecturn's structured output is malformed — missing a closing brace, trailing comma, unescaped quote inside a string. Nothing downstream can parse it.

**Why it happens:** The LLM generates free-form text that almost-but-not-quite follows the JSON schema. Common with longer outputs where the model loses track of nesting depth.

**Eval:** `is_valid_json()` — instant, zero cost. Should be the first check on every output.

**Severity:** Critical. A broken response is worse than no response.

---

### 2. Missing required sections
**What happens:** The output is valid JSON but skips a required field. A comparison-mode output might have "similarities" but no "differences" section, or a lit-review might lack a "methodology" section.

**Eval:** `has_required_fields()` — checks output dict against a per-mode schema.

**Severity:** High. An incomplete output wastes the user's time.

---

### 3. Uncited claims
**What happens:** The output makes factual claims without any citation. "RAG reduces hallucinations by 50%" — says who? Which paper? The claim might be correct, but without a source it's unverifiable.

**Eval:** `citation_format_valid()` — regex check that every claim sentence has a `[source: X]` tag.

**Severity:** High. Uncited claims undermine Lecturn's core value proposition (traceable, cited answers).

---

### 4. Source concentration (lack of diversity)
**What happens:** The output cites the same source 8 times and ignores 4 other relevant sources. The user asked for a literature review but got a summary of one paper.

**Eval:** `no_duplicate_sources()` — counts citation distribution. We already saw this in retrieval (contextual had 1.4 unique sources vs baseline's 1.7).

**Severity:** Medium. The output might be correct but not useful for the user's intent.

---

## Semantic failures (caught by LLM-as-judge)

### 5. Hallucinated citations
**What happens:** The output cites a source that doesn't exist in the corpus, or attributes a claim to a paper that doesn't make that claim. "According to Wei et al. 2022, RAG outperforms fine-tuning" — Wei et al. wrote about chain-of-thought, not RAG.

**Why it happens:** The LLM blends knowledge from its training data with the retrieved chunks. It "knows" that various papers exist and confabulates citations.

**Eval:** `judge_faithfulness()` — the LLM judge checks each claim against the actual retrieved chunks. Also catchable with a stricter deterministic check that verifies cited sources exist in the corpus.

**Severity:** Critical. This is the worst failure — it looks authoritative but is wrong. Users can't catch it without reading the original sources.

---

### 6. Wrong attribution between similar papers
**What happens:** The output correctly states a finding but attributes it to the wrong paper. "Asai et al. (Self-RAG) showed that contextual embeddings reduce retrieval failure by 35%" — that's actually from Anthropic's contextual retrieval post.

**Why it happens:** Multiple papers in the corpus discuss similar topics (RAG, retrieval, self-reflection). When chunks from different sources are retrieved together, the LLM can mix up which finding came from which source.

**Eval:** `judge_faithfulness()` with per-claim source verification. Harder to catch than outright hallucination because the claim IS in the corpus — it's just attributed to the wrong source.

**Severity:** Critical. Same trust-erosion as hallucinated citations.

---

### 7. Missed key sources
**What happens:** The output answers the question but misses the most important source. A query about "how does contextual retrieval work" returns chunks from the RAG survey but not from Anthropic's actual contextual retrieval post.

**Why it happens:** Retrieval failure — the right chunks didn't make it into the top-K. Or the generation model ignored relevant retrieved chunks in favor of others.

**Eval:** `judge_completeness()` — checks whether expected sources from the golden dataset are actually cited. Also detectable via retrieval-level eval (our MRR/hit-rate comparison from Day 5).

**Severity:** High. The answer is incomplete and may mislead the user about the state of the field.

---

### 8. Fabricated quotes
**What happens:** The output includes a direct quote that doesn't appear anywhere in the corpus. "As Lilian Weng writes, 'agents are the future of AI'" — she never wrote that exact phrase.

**Why it happens:** LLMs are very good at generating plausible-sounding quotes. When asked to cite sources, they may invent quotes that match the author's style and topic.

**Eval:** Deterministic string-matching (check if the quoted text appears verbatim in the retrieved chunks) + `judge_faithfulness()` as a fallback for paraphrased quotes.

**Severity:** Critical. Fabricated quotes are the most embarrassing failure — they're easy for a reader to verify and immediately destroy credibility.

---

## Behavioral failures (caught by golden dataset comparison)

### 9. Confidence not calibrated
**What happens:** Lecturn says "the evidence clearly shows" when the corpus has conflicting views, or says "it's unclear" when the corpus has strong consensus. The confidence level doesn't match the actual evidence.

**Why it happens:** LLMs default to confident-sounding language. They don't naturally hedge based on evidence strength — they hedge based on training data patterns.

**Eval:** No clean automated eval for this. Best approach: include golden dataset examples where the correct answer requires hedging ("the papers disagree on this point") and check via `judge_completeness()` whether the hedge is present.

**Severity:** Medium. Miscalibrated confidence is subtle but erodes trust over time.

---

### 10. Self-contradiction between sections
**What happens:** Section 1 says "RAG is preferred over fine-tuning for knowledge-intensive tasks" and Section 3 says "fine-tuning is more effective than RAG for knowledge tasks." Both claims might be supported by different sources, but the output doesn't reconcile them.

**Why it happens:** Each section is generated somewhat independently. The model doesn't always maintain consistency across a long structured output, especially when different retrieved chunks support different conclusions.

**Eval:** `judge_faithfulness()` applied to pairs of claims within the same output. Custom check: extract all claims, compare for logical consistency. Hard to fully automate — this is where human review adds the most value.

**Severity:** Medium-High. Self-contradictory output makes Lecturn look unreliable even if both claims are individually supported.

---

## Eval coverage summary

| Failure mode | Deterministic | LLM-as-judge | Golden dataset | Human review |
|---|:---:|:---:|:---:|:---:|
| 1. Invalid JSON | ✓ | | | |
| 2. Missing sections | ✓ | | | |
| 3. Uncited claims | ✓ | | | |
| 4. Source concentration | ✓ | | | |
| 5. Hallucinated citations | partial | ✓ | | |
| 6. Wrong attribution | | ✓ | | ✓ |
| 7. Missed key sources | | ✓ | ✓ | |
| 8. Fabricated quotes | partial | ✓ | | |
| 9. Confidence calibration | | | ✓ | ✓ |
| 10. Self-contradiction | | partial | | ✓ |

**Key insight:** Deterministic checks catch failures 1-4 instantly and cheaply. LLM-as-judge catches 5-8 but is itself unreliable (the judge can miss things or hallucinate its own reasoning). Failures 9-10 fundamentally need human review — no automated eval is reliable enough. A production system needs all three layers.
