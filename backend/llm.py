"""Google GenAI connection shared by the robot agents and the dispatcher copilot."""
import json
import os
import threading

from google import genai
from google.genai import types

DEFAULT_MODEL = 'gemma-4-26b-a4b-it'


class LLM:
    def __init__(self):
        self.model = os.getenv('GEMMA_MODEL') or DEFAULT_MODEL
        # Tried in order when the main model errors or is too slow (Google's endpoints have busy spells).
        self.fallbacks = [m.strip() for m in os.getenv('AI_FALLBACK_MODELS', '').split(',') if m.strip()]
        self.chain = []
        self.client = None
        self.available = False
        self.reason = 'GEMINI_API_KEY is not configured. Robots use their reflex rules; manual controls work.'
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
            self.chain = [m for m in [self.model, *self.fallbacks] if m in names]
            if not self.chain:
                self.reason = f'Model {self.model} is not available to this API key.'
                return
            self.available = True
            backup = f" Backup: {', '.join(self.chain[1:])}." if len(self.chain) > 1 else ''
            self.reason = f'Model availability confirmed through the Google API.{backup}'
        except Exception:
            self.reason = 'Google API model discovery failed. Check the API key, account access, and network.'

    def status(self):
        return {'available': self.available, 'model': self.model, 'reason': self.reason}

    def generate(self, prompt, schema, info=None):
        """Ask for JSON matching a Pydantic model and validate it. Raises if every model in the chain fails.
        `info['model']` is set to the model that actually answered."""
        json_schema = schema.model_json_schema()
        error = None
        with self.slots:
            for model in self.chain or [self.model]:
                try:
                    try:
                        response = self.client.models.generate_content(
                            model=model, contents=prompt,
                            config=types.GenerateContentConfig(response_mime_type='application/json',
                                                               response_json_schema=json_schema, temperature=0.3))
                    except Exception as exc:
                        if getattr(exc, 'code', None) != 400:
                            raise
                        # Some deployments don't expose structured generation for Gemma: plain JSON prompting.
                        response = self.client.models.generate_content(model=model, contents=prompt)
                    result = schema.model_validate(extract_json(response.text or ''))
                except Exception as exc:
                    error = exc     # server error, timeout, rate limit or unusable answer: try the next model
                    continue
                if info is not None:
                    info['model'] = model
                return result
        raise error


def extract_json(text):
    """The first JSON object in a reply, ignoring code fences and stray end-of-text tokens around it."""
    text = text.replace('<|endoftext|>', '')
    start = text.find('{')
    if start < 0:
        raise ValueError('No JSON object in the model reply.')
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data
