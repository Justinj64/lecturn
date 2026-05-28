import os
from openai import OpenAI

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-2.5-flash-lite"


def get_client() -> OpenAI:
    """
        Return an OpenAI client pointed at Google's Gemini endpoint.
    """
    return OpenAI(api_key=os.environ["GEMINI_API_KEY"], base_url=GEMINI_BASE_URL)
