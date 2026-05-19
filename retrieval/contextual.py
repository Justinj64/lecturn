"""
Contextual retrieval: Anthropic's pattern for improving chunk retrieval
by prepending LLM-generated context to each chunk before embedding.

THE PROBLEM:
    When you split a document into chunks, each chunk loses context.
    A chunk might say "this approach improved performance by 15%" without
    saying WHICH approach or FROM WHICH PAPER. The embedding of that chunk
    captures the words but not the meaning. So when someone queries
    "how did contextual retrieval improve performance," that chunk
    might not rank highly — even though it's exactly what they want.

THE FIX:
    Before embedding each chunk, send Claude the FULL document + the chunk
    and ask: "give me a short context that situates this chunk within the
    document." Claude returns something like:

        "This chunk is from Anthropic's 2024 paper on contextual retrieval.
         It describes the 35% improvement in retrieval failure rate when
         using contextual embeddings."

    We prepend that context to the chunk, then embed the combined text.
    Now the embedding captures the full meaning.

WHY THIS WORKS:
    Embeddings encode semantic meaning. "The company grew 3%" and
    "ACME Corp's Q2 2023 revenue grew 3% from $314M" produce very
    different embeddings. The second one actually matches queries about
    ACME Corp. The context prefix turns every chunk into the second kind.

COST:
    One LLM call per chunk. For a corpus of ~300 chunks, this takes
    a few minutes and costs a small amount. We cache aggressively
    so it's a one-time cost.
"""



import os
import json
import hashlib
from pathlib import Path
from openai import OpenAI
from retrieval.store import VectorStore
from langchain_core.documents import Document
from concurrent.futures import ThreadPoolExecutor, as_completed


# Gemini's OpenAI-compatible endpoint lets us use the same OpenAI SDK
# with just a different base_url and API key. No extra dependency needed.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL = "gemini-2.5-flash-lite"


# ---------------------------------------------------------------------------
# Cache: stores context prefixes to disk so we only call Claude once per chunk
# ---------------------------------------------------------------------------
# Why a separate directory? Context prefixes are derived data (generated from
# source documents). We don't want them mixed into the corpus or the vector DB.
# A flat JSON file is simple and works for our corpus size (~300 chunks).

CACHE_DIR = Path(__file__).parent.parent / ".context_cache"
CACHE_FILE = CACHE_DIR / "context_prefixes.json"

# Contextual chunks live in a separate ChromaDB collection from baseline.
# This lets us query both independently and compare results.
CONTEXTUAL_COLLECTION = "lecturn_contextual"


def _cache_key(chunk_text: str, doc_text: str) -> str:
    """
    Deterministic cache key from chunk + its source document.

    Why hash both? If the chunk text changes (different chunking params)
    or the document changes (updated corpus), the prefix should be
    regenerated. Hashing both ensures staleness is impossible.
    """
    content = f"{doc_text}|||{chunk_text}"
    return hashlib.sha256(content.encode()).hexdigest()


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


# ---------------------------------------------------------------------------
# Context prefix generation
# ---------------------------------------------------------------------------

def generate_context_prefix(
    chunk_text: str,
    full_document: str,
    client: OpenAI,
) -> str:
    """
    Ask the LLM to write a short context prefix for this chunk.

    The prompt is taken directly from Anthropic's contextual retrieval
    blog post. It tells the model:
    - Here's the whole document
    - Here's one chunk from it
    - Give me a short context to help retrieval

    The response is typically 50-100 tokens — just enough to capture
    the who/what/when/where that the chunk alone is missing.
    """
    response = client.chat.completions.create(
        model=GEMINI_MODEL,
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": (
                f"<document>\n{full_document}\n</document>\n"
                f"Here is the chunk we want to situate within the whole document\n"
                f"<chunk>\n{chunk_text}\n</chunk>\n"
                f"Please give a short succinct context to situate this chunk "
                f"within the overall document for the purposes of improving "
                f"search retrieval of the chunk. Answer only with the succinct "
                f"context and nothing else."
            ),
        }],
    )
    return response.choices[0].message.content


def build_full_documents(docs: list[Document]) -> dict[str, str]:
    """
    Reconstruct full document text from the per-page/per-file Documents.

    load_corpus() returns one Document per PDF page or one per markdown file.
    To generate context prefixes, Claude needs the FULL document — all pages
    concatenated. We group by the 'source' metadata field (which is the
    file path) and join the text.

    Returns: dict mapping source path → full document text
    """
    full_docs: dict[str, str] = {}
    for doc in docs:
        source = doc.metadata.get("source", "")
        if source not in full_docs:
            full_docs[source] = ""
        full_docs[source] += doc.page_content + "\n"
    return full_docs


def generate_context_prefixes(
    chunks: list[Document],
    full_documents: dict[str, str],
    max_workers: int = 10,
) -> list[str]:
    """
    Generate context prefixes for all chunks, using cache where possible.
    Uncached chunks are processed in parallel using a thread pool.

    For each chunk:
    1. Check if we already have a cached prefix (by hash of chunk + doc)
    2. If yes, use it (free, instant)
    3. If no, submit to thread pool for parallel LLM generation
    4. Save to cache periodically (so interruptions don't lose progress)

    Args:
        chunks: chunked Documents with metadata (including 'source')
        full_documents: dict from build_full_documents()
        max_workers: number of parallel API calls (default 10)

    Returns:
        list of context prefix strings, one per chunk, in the same order
    """
    client = OpenAI(
        api_key=os.environ["GEMINI_API_KEY"],
        base_url=GEMINI_BASE_URL,
    )
    cache = _load_cache()

    # First pass: resolve cached prefixes, collect uncached work
    prefixes = [None] * len(chunks)
    uncached = []  # list of (index, chunk_text, doc_text, cache_key)

    for i, chunk in enumerate(chunks):
        source = chunk.metadata.get("source", "")
        doc_text = full_documents.get(source, "")
        key = _cache_key(chunk.page_content, doc_text)

        if key in cache:
            prefixes[i] = cache[key]
        else:
            uncached.append((i, chunk.page_content, doc_text, key))

    cached_count = len(chunks) - len(uncached)
    if cached_count > 0:
        print(f"  {cached_count} prefixes loaded from cache")

    if not uncached:
        print(f"Context prefixes: 0 generated, {cached_count} from cache")
        return prefixes

    print(f"  {len(uncached)} chunks need LLM calls ({max_workers} parallel workers)...")

    # Second pass: generate uncached prefixes in parallel
    generated_count = 0

    def _generate(item):
        idx, chunk_text, doc_text, key = item
        prefix = generate_context_prefix(chunk_text, doc_text, client)
        return idx, key, prefix

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_generate, item): item for item in uncached}

        for future in as_completed(futures):
            idx, key, prefix = future.result()
            prefixes[idx] = prefix
            cache[key] = prefix
            generated_count += 1

            if generated_count % 50 == 0:
                _save_cache(cache)
                print(f"  Generated {generated_count}/{len(uncached)} new prefixes...")

    _save_cache(cache)
    print(f"Context prefixes: {generated_count} generated, {cached_count} from cache")
    return prefixes


def contextualize_chunks(
    chunks: list[Document],
    prefixes: list[str],
) -> list[Document]:
    """
    Create new Documents with context prefix prepended to each chunk.

    The resulting Documents have:
    - page_content: "context prefix\\n\\noriginal chunk text"
    - metadata: same as original chunk (title, source_url, etc.)

    These are what get embedded and stored. At query time, the embeddings
    reflect both the context AND the content, so retrieval is more accurate.
    """
    contextualized = []
    for chunk, prefix in zip(chunks, prefixes):
        new_text = f"{prefix}\n\n{chunk.page_content}"
        contextualized.append(
            Document(page_content=new_text, metadata=chunk.metadata)
        )
    return contextualized


# ---------------------------------------------------------------------------
# Retrieval — mirrors baseline_retrieve() exactly
# ---------------------------------------------------------------------------

def contextual_retrieve(query: str, k: int = 5) -> list[Document]:
    """
    Retrieve the top-k most similar chunks from the CONTEXTUAL collection.

    Same interface as baseline_retrieve(). The only difference is which
    ChromaDB collection we query — this one has chunks with context
    prefixes prepended, so the embeddings capture richer meaning.

    Use this alongside baseline_retrieve() to compare results:

        from retrieval.baseline import baseline_retrieve
        from retrieval.contextual import contextual_retrieve

        baseline_results = baseline_retrieve("what is contextual retrieval")
        contextual_results = contextual_retrieve("what is contextual retrieval")
    """
    store = VectorStore(collection_name=CONTEXTUAL_COLLECTION)
    return store.query(query, k=k)
