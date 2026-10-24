"""Google GenAI connection shared by the robot agents and the dispatcher copilot."""
import json
import os
import threading
import time

from google import genai
from google.genai import types

DEFAULT_MODEL = 'gemma-4-26b-a4b-it'


class LLM:
    def __init__(self):
        self.model = os.getenv('GEMMA_MODEL') or DEFAULT_MODEL
        # Google's endpoints have busy spells: retry, and after this many failed tries the robot decides offline.
        self.attempts = max(1, int(os.getenv('AI_MAX_ATTEMPTS', '3')))
        self.client = None
        self.available = False
        self.reason = 'GEMINI_API_KEY is not configured. Robots use their offline rules; manual controls work.'
        # A handful of robots can be thinking at once; keep well inside free-tier rate limits.
        self.slots = threading.Semaphore(int(os.getenv('AI_MAX_PARALLEL', '3')))

    def connect(self):
        key = os.getenv('GEMINI_API_KEY')
        if not key:
            return
        try:
            # Short timeout: a robot standing still waiting for a slow model is worse than a quick fallback.
            self.client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=12_000))
            names = {m.name.removeprefix('models/') for m in self.client.models.list() if m.name}
            if self.model not in names:
                self.reason = f'Model {self.model} is not available to this API key.'
                return
            self.available = True
            self.reason = f'Model availability confirmed through the Google API. Up to {self.attempts} tries per decision, then offline rules.'
        except Exception:
            self.reason = 'Google API model discovery failed. Check the API key, account access, and network.'

    def status(self):
        return {'available': self.available, 'model': self.model, 'reason': self.reason}

    def generate(self, prompt, schema, info=None):
        """Ask for JSON matching a Pydantic model and validate it, retrying failed calls.
        Raises after `self.attempts` failures; `info['tries']` reports how many calls were made."""
        json_schema = schema.model_json_schema()
        error = None
        with self.slots:
            for attempt in range(1, self.attempts + 1):
                if info is not None:
                    info['tries'] = attempt
                try:
                    try:
                        response = self.client.models.generate_content(
                            model=self.model, contents=prompt,
                            config=types.GenerateContentConfig(response_mime_type='application/json',
                                                               response_json_schema=json_schema, temperature=0.3))
                    except Exception as exc:
                        if getattr(exc, 'code', None) != 400:
                            raise
                        # Some deployments don't expose structured generation for Gemma: plain JSON prompting.
                        response = self.client.models.generate_content(model=self.model, contents=prompt)
                    return schema.model_validate(extract_json(response.text or ''))
                except Exception as exc:
                    error = exc     # server error, timeout, rate limit or unusable answer: try again
                    if attempt < self.attempts:
                        time.sleep(0.5 * attempt)
        raise error


def extract_json(text):
    """The first JSON object in a reply, ignoring code fences and stray end-of-text tokens around it."""
    text = text.replace('<|endoftext|>', '')
    start = text.find('{')
    if start < 0:
        raise ValueError('No JSON object in the model reply.')
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data
