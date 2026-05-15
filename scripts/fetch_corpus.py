#!/usr/bin/env python3
"""
Fetch blog posts for the Lectern corpus and save as markdown.

Usage:
    python scripts/fetch_corpus.py              # fetch all posts
    python scripts/fetch_corpus.py --dry-run    # show what would be fetched
    python scripts/fetch_corpus.py --only URL   # refetch a single post by URL

Requires: pip install trafilatura pyyaml
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import trafilatura
import yaml

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"
POSTS_DIR = CORPUS_DIR / "posts"
SOURCES_YAML = CORPUS_DIR / "sources.yaml"

TODAY = date.today().isoformat()

POSTS = [
    {
        "url": "https://lilianweng.github.io/posts/2023-06-23-agent/",
        "filename": "weng_2023_llm_powered_autonomous_agents.md",
        "title": "LLM Powered Autonomous Agents",
        "author": "Lilian Weng",
        "year": 2023,
    },
    {
        "url": "https://lilianweng.github.io/posts/2024-07-07-hallucination/",
        "filename": "weng_2024_extrinsic_hallucinations_in_llms.md",
        "title": "Extrinsic Hallucinations in LLMs",
        "author": "Lilian Weng",
        "year": 2024,
    },
    {
        "url": "https://www.eugeneyan.com/writing/llm-patterns/",
        "filename": "yan_2023_patterns_for_building_llm_systems.md",
        "title": "Patterns for Building LLM-based Systems",
        "author": "Eugene Yan",
        "year": 2023,
    },
    {
        "url": "https://www.eugeneyan.com/writing/evals/",
        "filename": "yan_2024_evaluation_and_hallucination_detection.md",
        "title": "Evaluation & Hallucination Detection",
        "author": "Eugene Yan",
        "year": 2024,
    },
    {
        "url": "https://hamel.dev/blog/posts/evals/",
        "filename": "husain_2024_your_ai_product_needs_evals.md",
        "title": "Your AI Product Needs Evals",
        "author": "Hamel Husain",
        "year": 2024,
    },
    {
        "url": "https://www.anthropic.com/research/building-effective-agents",
        "filename": "anthropic_2024_building_effective_agents.md",
        "title": "Building Effective Agents",
        "author": "Anthropic",
        "year": 2024,
    },
    {
        "url": "https://www.anthropic.com/news/contextual-retrieval",
        "filename": "anthropic_2024_contextual_retrieval.md",
        "title": "Contextual Retrieval",
        "author": "Anthropic",
        "year": 2024,
    },
    {
        "url": "https://huyenchip.com/2023/04/11/llm-engineering.html",
        "filename": "huyen_2023_building_llm_applications_for_production.md",
        "title": "Building LLM Applications for Production",
        "author": "Chip Huyen",
        "year": 2023,
    },
    {
        "url": "https://simonwillison.net/2023/Aug/27/wordcamp-llms/",
        "filename": "willison_2023_catching_up_on_the_weird_world_of_llms.md",
        "title": "Catching up on the weird world of LLMs",
        "author": "Simon Willison",
        "year": 2023,
    },
]

# Papers metadata (for sources.yaml generation only — PDFs are downloaded separately)
PAPERS = [
    {
        "filename": "papers/vaswani_2017_attention_is_all_you_need.pdf",
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit",
                     "Llion Jones", "Aidan N. Gomez", "Lukasz Kaiser", "Illia Polosukhin"],
        "year": 2017,
        "source_url": "https://arxiv.org/abs/1706.03762",
    },
    {
        "filename": "papers/lewis_2020_retrieval_augmented_generation.pdf",
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "authors": ["Patrick Lewis", "Ethan Perez", "Aleksandra Piktus", "Fabio Petroni",
                     "Vladimir Karpukhin", "Naman Goyal", "Heinrich Küttler", "Mike Lewis",
                     "Wen-tau Yih", "Tim Rocktäschel", "Sebastian Riedel", "Douwe Kiela"],
        "year": 2020,
        "source_url": "https://arxiv.org/abs/2005.11401",
    },
    {
        "filename": "papers/wei_2022_chain_of_thought_prompting.pdf",
        "title": "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
        "authors": ["Jason Wei", "Xuezhi Wang", "Dale Schuurmans", "Maarten Bosma",
                     "Brian Ichter", "Fei Xia", "Ed Chi", "Quoc Le", "Denny Zhou"],
        "year": 2022,
        "source_url": "https://arxiv.org/abs/2201.11903",
    },
    {
        "filename": "papers/yao_2022_react.pdf",
        "title": "ReAct: Synergizing Reasoning and Acting in Language Models",
        "authors": ["Shunyu Yao", "Jeffrey Zhao", "Dian Yu", "Nan Du",
                     "Izhak Shafran", "Karthik Narasimhan", "Yuan Cao"],
        "year": 2022,
        "source_url": "https://arxiv.org/abs/2210.03629",
    },
    {
        "filename": "papers/asai_2023_self_rag.pdf",
        "title": "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
        "authors": ["Akari Asai", "Zeqiu Wu", "Yizhong Wang", "Avirup Sil", "Hannaneh Hajishirzi"],
        "year": 2023,
        "source_url": "https://arxiv.org/abs/2310.11511",
    },
    {
        "filename": "papers/liu_2023_lost_in_the_middle.pdf",
        "title": "Lost in the Middle: How Language Models Use Long Contexts",
        "authors": ["Nelson F. Liu", "Kevin Lin", "John Hewitt", "Ashwin Paranjape",
                     "Michele Bevilacqua", "Fabio Petroni", "Percy Liang"],
        "year": 2023,
        "source_url": "https://arxiv.org/abs/2307.03172",
    },
    {
        "filename": "papers/gao_2023_rag_survey.pdf",
        "title": "Retrieval-Augmented Generation for Large Language Models: A Survey",
        "authors": ["Yunfan Gao", "Yun Xiong", "Xinyu Gao", "Kangxiang Jia",
                     "Jinliu Pan", "Yuxi Bi", "Yi Dai", "Jiawei Sun", "Meng Wang", "Haofen Wang"],
        "year": 2023,
        "source_url": "https://arxiv.org/abs/2312.10997",
    },
    {
        "filename": "papers/trivedi_2023_ircot.pdf",
        # NOTE: arxiv 2305.14283 is "Query Rewriting for RAG LLMs" by Ma et al.
        "title": "Query Rewriting for Retrieval-Augmented Large Language Models",
        "authors": ["Xinbei Ma", "Yeyun Gong", "Pengcheng He", "Hai Zhao", "Nan Duan"],
        "year": 2023,
        "source_url": "https://arxiv.org/abs/2305.14283",
    },
    {
        "filename": "papers/rafailov_2023_dpo.pdf",
        "title": "Direct Preference Optimization: Your Language Model is Secretly a Reward Model",
        "authors": ["Rafael Rafailov", "Archit Sharma", "Eric Mitchell",
                     "Stefano Ermon", "Christopher D. Manning", "Chelsea Finn"],
        "year": 2023,
        "source_url": "https://arxiv.org/abs/2305.18290",
    },
    {
        "filename": "papers/yan_2024_self_discover.pdf",
        # NOTE: First author is Pei Zhou, not Yan.
        "title": "Self-Discover: Large Language Models Self-Compose Reasoning Structures",
        "authors": ["Pei Zhou", "Jay Pujara", "Xiang Ren", "Xinyun Chen",
                     "Heng-Tze Cheng", "Quoc V. Le", "Ed H. Chi", "Denny Zhou", "Swaroop Mishra"],
        "year": 2024,
        "source_url": "https://arxiv.org/abs/2402.03620",
    },
]


def _extract_headings_from_html(html: str) -> list[tuple[int, str]]:
    """Extract heading tags (h1-h6) and their text from raw HTML.

    Only returns headings that appear inside the article/main content area
    (filters out nav/footer headings by excluding very short generic ones
    like 'Products', 'Company', etc. that appear after the main content).
    """
    pattern = re.compile(r"<(h[1-6])[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
    headings = []
    for m in pattern.finditer(html):
        level = int(m.group(1)[1])
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if text and len(text) > 2:
            headings.append((level, text, m.start()))
    return headings


def _normalize_ws(s: str) -> str:
    """Collapse all whitespace to single spaces and strip."""
    return re.sub(r"\s+", " ", s).strip().lower()


def _reinsert_headings(content: str, headings: list[tuple[int, str, int]]) -> str:
    """Re-insert markdown headings that trafilatura stripped.

    Strategy: for each heading from the HTML, find the paragraph in the
    extracted content that starts with text immediately following the heading
    in the original article, and insert the heading as a markdown line before it.
    If we can't find a match, look for a line whose text is a substring match
    of the heading text.
    """
    lines = content.split("\n")
    heading_prefix = {}  # line_index -> heading markdown

    for level, text, _ in headings:
        norm_heading = _normalize_ws(text)
        # Try exact line match first
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or i in heading_prefix:
                continue
            norm_line = _normalize_ws(stripped)
            if norm_line == norm_heading:
                heading_prefix[i] = "#" * level
                break
        else:
            # Try substring: find a line that contains the full heading text
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or i in heading_prefix:
                    continue
                norm_line = _normalize_ws(stripped)
                if norm_line.startswith(norm_heading) and len(norm_heading) > 10:
                    heading_prefix[i] = "#" * level
                    break

    for i in sorted(heading_prefix.keys(), reverse=True):
        prefix = heading_prefix[i]
        lines[i] = f"{prefix} {lines[i].strip()}"

    return "\n".join(lines)


def _inject_heading_markers(html: str) -> str:
    """Inject visible text markers before headings in the HTML so that
    trafilatura preserves them during extraction.

    This works around trafilatura stripping heading tags on some JS-heavy sites.
    We insert a unique sentinel paragraph before each heading containing
    the heading text prefixed with markdown-style '#' markers.
    """
    def _replace_heading(m: re.Match) -> str:
        tag = m.group(1)
        level = int(tag[1])
        inner = m.group(2)
        text = re.sub(r"<[^>]+>", "", inner).strip()
        if not text or len(text) <= 2:
            return m.group(0)
        marker = "#" * level
        # Insert a paragraph with the markdown heading right before the heading tag
        sentinel = f'<p data-heading-marker="true">{marker} {text}</p>'
        return sentinel + m.group(0)

    return re.sub(
        r"<(h[1-6])([^>]*)>(.*?)</\1>",
        lambda m: _replace_heading(re.match(r"<(h[1-6])[^>]*>(.*?)</\1>", m.group(0), re.DOTALL | re.IGNORECASE)),
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _cleanup_content(content: str) -> str:
    """Remove duplicate consecutive heading lines and common nav/footer headings."""
    lines = content.split("\n")
    cleaned = []
    prev_heading_text = ""
    # Common footer/nav headings to remove
    nav_headings = {
        "get the developer newsletter", "products", "models", "solutions",
        "claude platform", "resources", "help and security", "company",
        "terms and policies",
    }
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            heading_text = stripped.lstrip("#").strip().lower()
            # Strip anchor fragments like [#](#section-name) and trailing #
            heading_text_clean = re.sub(r"\[#\]\([^)]*\)", "", heading_text).rstrip("#").strip()
            # Skip nav/footer headings
            if heading_text_clean in nav_headings:
                continue
            # Skip duplicate headings (same text as previous heading, ignoring anchors)
            if heading_text_clean and heading_text_clean == prev_heading_text:
                continue
            prev_heading_text = heading_text_clean
        else:
            if stripped:
                prev_heading_text = ""
        cleaned.append(line)
    return "\n".join(cleaned)


def fetch_post(post: dict, output_dir: Path) -> bool:
    """Fetch a single blog post and save as markdown. Returns True on success."""
    url = post["url"]
    filepath = output_dir / post["filename"]

    print(f"Fetching: {url}")

    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            print(f"  FAILED: Could not fetch URL")
            return False

        content = trafilatura.extract(
            _inject_heading_markers(downloaded),
            output_format="markdown",
            include_links=True,
            include_images=False,
            include_tables=True,
            include_formatting=True,
            favor_recall=True,
        )

        if content is None or len(content.strip()) < 100:
            print(f"  FAILED: Extraction returned insufficient content")
            return False

        # Also try post-extraction heading reinsertion as a fallback
        headings = _extract_headings_from_html(downloaded)
        if headings:
            content = _reinsert_headings(content, headings)

        # Clean up: remove duplicate heading lines and nav/footer headings
        content = _cleanup_content(content)

        header = (
            f"# {post['title']}\n\n"
            f"Source: {url}\n"
            f"Author: {post['author']}\n"
            f"Retrieved: {TODAY}\n\n"
            f"---\n\n"
        )

        filepath.write_text(header + content, encoding="utf-8")
        print(f"  OK: {post['filename']} ({len(content):,} chars)")
        return True

    except Exception as e:
        print(f"  FAILED: {e}")
        return False


def build_sources_yaml(
    successful_posts: list[dict],
    papers: list[dict],
    output_path: Path,
):
    """Generate corpus/sources.yaml from successful downloads and paper metadata."""
    documents = []

    for paper in papers:
        pdf_path = output_path.parent / paper["filename"]
        if pdf_path.exists():
            documents.append({
                "filename": paper["filename"],
                "type": "paper",
                "title": paper["title"],
                "authors": paper["authors"],
                "year": paper["year"],
                "source_url": paper["source_url"],
                "date_retrieved": TODAY,
            })

    for post in successful_posts:
        documents.append({
            "filename": f"posts/{post['filename']}",
            "type": "post",
            "title": post["title"],
            "authors": [post["author"]],
            "year": post["year"],
            "source_url": post["url"],
            "date_retrieved": TODAY,
        })

    output_path.write_text(
        yaml.dump({"documents": documents}, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"\nWrote {output_path} ({len(documents)} documents)")


def main():
    parser = argparse.ArgumentParser(description="Fetch blog posts for the Lectern corpus.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fetched without downloading.")
    parser.add_argument("--only", type=str, help="Refetch only the post matching this URL.")
    parser.add_argument("--skip-yaml", action="store_true", help="Skip regenerating sources.yaml.")
    args = parser.parse_args()

    POSTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.only:
        targets = [p for p in POSTS if p["url"] == args.only]
        if not targets:
            print(f"No post found matching URL: {args.only}")
            sys.exit(1)
    else:
        targets = POSTS

    if args.dry_run:
        for post in targets:
            print(f"  Would fetch: {post['url']} -> {post['filename']}")
        return

    successes = []
    failures = []

    for post in targets:
        if fetch_post(post, POSTS_DIR):
            successes.append(post)
        else:
            failures.append(post["url"])

    print(f"\n--- Results: {len(successes)} success, {len(failures)} failed ---")
    if failures:
        print("Failed URLs:")
        for url in failures:
            print(f"  - {url}")

    if not args.skip_yaml:
        # Include all posts (not just the ones fetched this run) in sources.yaml
        all_successful = []
        for post in POSTS:
            md_path = POSTS_DIR / post["filename"]
            if md_path.exists():
                all_successful.append(post)
        build_sources_yaml(all_successful, PAPERS, SOURCES_YAML)


if __name__ == "__main__":
    main()
