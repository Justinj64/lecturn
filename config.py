import os

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-2.5-flash-lite"


def get_client():
    """
    Return an OpenAI-compatible client pointed at Gemini.

    If LANGFUSE_SECRET_KEY is present, wraps the client with langfuse.openai
    so every LLM call is automatically traced as a Langfuse generation (input,
    output, latency, token counts) — no extra code needed at the call site.
    Falls back to the standard openai.OpenAI client if Langfuse is not
    installed or keys are absent.
    """
    api_key = os.environ["GEMINI_API_KEY"]
    base_url = GEMINI_BASE_URL

    if os.environ.get("LANGFUSE_SECRET_KEY"):
        try:
            from langfuse.openai import OpenAI
            return OpenAI(api_key=api_key, base_url=base_url)
        except ImportError:
            pass

    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=base_url)
