"""Google GenAI connection shared by the robot agents and the dispatcher copilot."""
import os
import threading

from google import genai
from google.genai import types

DEFAULT_MODEL = 'gemma-4-26b-a4b-it'


class LLM:
    def __init__(self):
        self.model = os.getenv('GEMMA_MODEL') or DEFAULT_MODEL
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
            self.client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=25_000))
            names = {m.name.removeprefix('models/') for m in self.client.models.list() if m.name}
            if self.model not in names:
                self.reason = f'Model {self.model} is not available to this API key.'
                return
            self.available = True
            self.reason = 'Model availability confirmed through the Google API.'
        except Exception:
            self.reason = 'Google API model discovery failed. Check the API key, account access, and network.'

    def status(self):
        return {'available': self.available, 'model': self.model, 'reason': self.reason}

    def generate(self, prompt, schema):
        """Ask for JSON matching a Pydantic model and validate it. Raises on any failure."""
        json_schema = schema.model_json_schema()
        with self.slots:
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type='application/json',
                                                       response_json_schema=json_schema, temperature=0.3))
            except Exception as exc:
                # Some deployments don't expose structured generation for Gemma: fall back to plain JSON prompting.
                if getattr(exc, 'code', None) != 400:
                    raise
                response = self.client.models.generate_content(model=self.model, contents=prompt)
        text = (response.text or '').strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        return schema.model_validate_json(text)
