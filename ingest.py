"""
Walk the corpus folder, load pdf and markdown files,
return list of Document(text, source_url, title, metadata).

Each Document is a langchain Document object with:
  - page_content: the actual text content
  - metadata: dict with title, source_url, authors, year, etc.

For PDFs, each page becomes a separate Document.
For Markdown files, the entire file becomes one Document.
"""
from pathlib import Path

import yaml
from langchain_community.document_loaders import PyPDFLoader  # uses pypdf under the hood
from langchain_core.documents import Document

# Root path to the corpus folder, resolved relative to this file's location
CORPUS_DIR = Path(__file__).parent / "corpus"


def load_sources_metadata():
    """
    Load sources.yaml and return a dict keyed by filename.

    sources.yaml contains metadata about each file in the corpus:
    title, authors, source_url, year, etc. We use the filename
    (e.g. "papers/asai_2023_self_rag.pdf") as the key so we can
    look up metadata when loading each file.
    """
    sources_path = CORPUS_DIR / "sources.yaml"
    with open(sources_path) as f:
        data = yaml.safe_load(f)
    return {doc["filename"]: doc for doc in data.get("documents", [])}


def load_pdf(file_path: Path) -> list[Document]:
    """
    Load a PDF file and return a list of Documents, one per page.

    PyPDFLoader extracts text from each page and creates a Document
    with metadata like page number, total_pages, and source path.
    """
    loader = PyPDFLoader(str(file_path))
    return loader.load()


def load_markdown(file_path: Path) -> list[Document]:
    """
    Load a markdown file and return it as a single Document.

    Unlike PDFs, markdown files don't have pages, so the entire
    file content becomes one Document.
    """
    text = file_path.read_text(encoding="utf-8")
    return [Document(page_content=text, metadata={"source": str(file_path)})]


def load_corpus() -> list[Document]:
    """
    Walk the corpus directory, load all PDFs and markdown files,
    and enrich each Document with metadata from sources.yaml.

    Returns a flat list of Documents ready to be chunked/embedded.
    """
    sources = load_sources_metadata()
    documents = []

    # rglob("*") recursively finds all files in corpus/ (papers/, posts/, etc.)
    for file_path in sorted(CORPUS_DIR.rglob("*")):
        if file_path.suffix == ".pdf":
            docs = load_pdf(file_path)
        elif file_path.suffix == ".md":
            docs = load_markdown(file_path)
        else:
            continue  # skip non-document files like sources.yaml

        # Match this file to its entry in sources.yaml using the relative path
        # e.g. "papers/asai_2023_self_rag.pdf"
        relative = str(file_path.relative_to(CORPUS_DIR))
        meta = sources.get(relative, {})

        # Attach useful metadata to each Document so we can reference it later
        # during retrieval (e.g. showing the source URL to the user)
        for doc in docs:
            doc.metadata["title"] = meta.get("title", "")
            doc.metadata["source_url"] = meta.get("source_url", "")
            doc.metadata["authors"] = meta.get("authors", [])
            doc.metadata["year"] = meta.get("year", "")

        documents.extend(docs)

    return documents