# Interview Synthesis

Prepared answers for the 8 most common senior LLM engineer interview questions, grounded in what Lecturn actually built and measured.

---

## Q1: "How do you evaluate an LLM system?"

**The wrong answer:** "I use accuracy and F1."

**My answer:**

Evaluation for LLMs has to be three layers, because each layer catches different failures at different cost.

The first layer is deterministic checks — no LLM calls, runs in milliseconds. For Lecturn, that's JSON validity, required fields per output mode, citation format (`[source: X]` after every claim), and source diversity. These are your unit tests. They don't tell you if the output is good, but they immediately catch if it's broken.

The second layer is LLM-as-judge. In Lecturn I have two judges: `judge_faithfulness` which scores a cited claim against the retrieved chunks (0-5), and `judge_completeness` which scores how well the output covers expected key claims from a golden dataset. The judge catches semantic failures — claims that are technically formatted correctly but not actually supported by the sources.

The third layer is a golden dataset — 17 hand-crafted examples with expected sources and key claims. This is your ground truth. The first two layers tell you if something broke; the golden dataset tells you if the system is actually doing what you built it to do.

The critical insight: faithfulness is easy to score but hard to fix. Completeness is hard to score but easier to fix (retrieve more, plan better sections). Lecturn's naive RAG scored 4.03/5 on faithfulness but only 2.24/5 on completeness. That asymmetry told me exactly where to invest — the agent's planning layer, not the retrieval layer.

---

## Q2: "How do you handle hallucinations?"

**My answer:**

I think about hallucinations in two categories: retrieval hallucinations and generation hallucinations.

Retrieval hallucinations are when the right content was never in the retrieved chunks — the model invents because there's nothing better to say. The fix is upstream: better retrieval (reranking got me +0.078 MRR over baseline), larger k, or section-by-section retrieval so each part of the answer has dedicated evidence.

Generation hallucinations are when the model adds claims beyond what the retrieved chunks support. These are what the verify→revise loop in Lecturn addresses. After drafting, the agent calls an LLM judge on every cited sentence. Claims scoring ≤ 2/5 on faithfulness get flagged. The revision node then drops or softens those claims before the user ever sees them. On 1/17 eval examples this demonstrably removed an unsupported claim — the model had cited a paper as the source for a claim the paper doesn't actually make.

The honest limitation: both the faithfulness judge and the revision node are LLMs. The judge can miss hallucinations (false negatives) or over-flag (false positives). The threshold of ≤ 2 was chosen by hand. This is an inherent limit of self-evaluation — you're using the same type of model to check the output of the original model. The right complementary check is deterministic: does the cited title actually exist in the retrieved set? That's the citation validator in `production/guardrails.py`. It doesn't require an LLM and catches the coarser failure.

---

## Q3: "Walk me through your RAG architecture."

**My answer:**

Lecturn has four layers.

**Retrieval.** I implemented three strategies and measured them. Baseline is cosine similarity over raw chunk embeddings — fast, no API cost, 0.785 MRR. Contextual retrieval prepends an LLM-generated context prefix to each chunk before embedding, which helps chunks that are meaningless without document context — got 0.825 MRR but hurt source diversity (1.4 unique sources vs 1.7). Reranked baseline takes top-20 from the embedding search and rescores with a cross-encoder locally — best overall at 0.863 MRR.

The key insight: contextual fixes recall, reranking fixes precision. At small scale, precision is the bottleneck. Stacking both actually hurt — reranked contextual (0.850) was worse than reranked baseline (0.863) because the diversity penalty from contextual carried through.

**Generation.** The agent is a LangGraph state machine with 7 nodes and a conditional verify→revise loop. The state is a TypedDict passed between nodes; each node returns only the fields it changed. The conditional edge after `verify_citations` is what makes it an agent — it can route backwards based on the faithfulness scores.

**Evaluation.** Three layers: deterministic checks, LLM-as-judge, golden dataset of 17 examples.

**Production.** Structured JSONL logging and Langfuse tracing per run, disk cache for LLM calls (SHA-256 keyed), injection guard before the graph runs, citation title validator in `format_output`.

---

## Q4: "Why LangGraph instead of a simpler pipeline?"

**My answer:**

For a linear pipeline — retrieve, draft, done — LangGraph is overkill. A few function calls would be cleaner.

I used LangGraph specifically because I needed a conditional loop: the graph routes back from `verify_citations` to `revise` when claims are low-confidence, and forward to `format_output` when they're clean (or the revision budget is exhausted). That's a cycle in the execution graph, which a linear pipeline can't express without awkward while loops that tangle control flow with business logic.

LangGraph separates the *routing logic* (`_route_after_verify`) from the *node logic* (what each node does). The router is a pure function of state — easy to test, easy to reason about. If I want to add a re-retrieval node later, I add a node and an edge. I don't refactor a loop condition buried inside a generation function.

The tradeoff is real: LangGraph adds complexity, a dependency, and debugging is harder when things go wrong mid-graph. For a straight pipeline, a for-loop wins every time.

---

## Q5: "How would you take this to production?"

**My answer:**

The four biggest gaps between Lecturn and a real deployment:

**Async execution.** `graph.invoke()` is synchronous. Streamlit blocks the UI thread while the graph runs — the 9-second `verify_citations` call would block all users in a multi-user deployment. The fix is `graph.ainvoke()` with a job queue pattern: submit query, get a job ID, poll for result.

**Session isolation.** `run_id` is currently a module-level global in `observability.py`. Two concurrent sessions write to the same `_run_id`. For multi-user deployment, run_id needs to live in request context (FastAPI request state, Streamlit session state, etc.).

**Eval regression in CI.** The eval harness exists but isn't wired into any CI pipeline. A prompt change could regress completeness from 2.65 to 2.1 with no one noticing. The right setup: run `run_evals.py` on every PR, fail the check if faithfulness or completeness drops below a threshold. The LLM cache makes this cheap — second run on the same queries is near-instant.

**Latency.** `verify_citations` takes ~9 seconds for 9 claims because it makes 9 sequential LLM calls. Batching these or using a lighter judge model would cut it to 2 seconds. The other option is sampling — check a random subset of claims rather than all of them.

---

## Q6: "What would you do differently if you built this again?"

**My answer:**

Three things.

**Write the eval harness first.** I built retrieval in Week 1 and evals in Week 2. Every decision I made in Week 1 — chunk size, embedding model, k — I made without a way to measure the impact. If I'd written the golden dataset and deterministic checks on Day 1, I'd have made better decisions earlier and spent less time re-running experiments manually.

**Cheaper faithfulness checks.** I use an LLM judge for every cited claim during generation. At ~1s per claim and 8-10 claims per draft, `verify_citations` dominates latency. I should have prototyped with a lighter check first — even a simple regex asking "does this sentence appear near-verbatim in any chunk?" would catch the obvious hallucinations at zero cost. LLM-as-judge is the right tool for borderline cases, not for every claim.

**Section-level retrieval.** The `retrieve` node fetches 10 chunks once for the whole query. For a 4-section comparison answer, that means each section is competing for evidence from the same pool. The right design is to retrieve once per planned section using the section title as the query. This adds retrieval calls but would have meaningfully improved completeness — the metric that was lowest (2.24 for naive RAG, 2.65 for the agent).

---

## Q7: "How do you think about cost and latency for LLM systems?"

**My answer:**

I think about it per-call-type first, then per-query.

In Lecturn, the calls break down by purpose: classification (parse_query, ~256 tokens, fast), planning (plan_sections, ~256 tokens, fast), generation (draft, ~2048 tokens, the most expensive single call), and verification (verify_citations, ~9 calls × 512 tokens, dominates latency).

Per query on Gemini 2.5 Flash Lite: naive RAG costs ~$0.002 (3 calls). The agent costs ~$0.015 (15+ calls for a typical example with 8-9 cited claims). That's 7× more expensive for +0.41 completeness improvement. Whether that tradeoff is worth it depends entirely on the use case — for a research tool where quality matters, yes. For a high-volume consumer product, probably not.

The levers I'd pull to reduce cost, in order: (1) cache aggressively — same query, same response, zero cost; (2) batch verification calls where the API supports it; (3) use a lighter model for verification (the judge doesn't need a strong model, just an honest one); (4) sample claims instead of checking all of them.

The cache I built gives immediate payoff on repeated queries and makes the eval harness essentially free to re-run after the first pass.

---

## Q8: "How do you debug a RAG system when outputs are wrong?"

**My answer:**

I follow the data backwards through the pipeline.

**First, is it a retrieval failure or a generation failure?** I check what was in `retrieved_chunks` for that query. If the right source isn't in the top-10, it's a retrieval problem — no amount of prompt engineering will fix a generation that never had the right evidence. If the right source is there and the output still misses it, it's a generation problem.

**For retrieval failures:** I check MRR on similar queries. If it's consistently low, I look at chunk boundaries — is the answer split across two chunks? I look at the embedding — is this a terminology mismatch where the query uses different words than the corpus? And I check source diversity — is retrieval collapsing to one source when the query needs multiple?

**For generation failures:** I look at the faithfulness scores from `verify_citations`. Low scores on correct claims usually mean the claim extraction is breaking — `_extract_cited_claims` is splitting sentences wrong. Low scores on actually incorrect claims mean the model drifted from the sources. I check the draft prompt and whether the chunk evidence was clearly attributed.

**The JSONL log is my starting point every time.** Each run has a `run_id` and I can grep for it to see every node's timing and metadata. If `verify_citations` checked 2 claims on a draft that has 10 sentences, I know immediately that claim extraction is the problem. That observability — built in Day 22 — changed debugging from guesswork to tracing.
