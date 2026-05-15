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
            downloaded,
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
