import json
import os
from google import genai
from google.genai import types
from .models import AIInstructions

DEFAULT_MODEL = 'gemma-4-26b-a4b-it'


class Coordinator:
    def __init__(self):
        self.model = os.getenv('GEMMA_MODEL') or DEFAULT_MODEL
        self.client = None
        self.available = False
        self.reason = 'GEMINI_API_KEY is not configured. Manual controls and deterministic planning are available.'

    def connect(self):
        key = os.getenv('GEMINI_API_KEY')
        if not key:
            return
        try:
            self.client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=20000))
            names = {m.name.removeprefix('models/') for m in self.client.models.list() if m.name}
            if self.model not in names or not self.model.startswith('gemma-4-'):
                self.reason = f'Configured Gemma 4 model {self.model} is not available in this API account.'
                return
            self.available = True
            self.reason = 'Model availability confirmed through the Google API.'
        except Exception:
            self.reason = 'Google API model discovery failed. Check the API key, account access, and network.'

    def status(self):
        return {'available': self.available, 'model': self.model, 'reason': self.reason}

    def ask(self, message, state):
        prompt = '''You are RouteMind's logistics coordinator. Treat user content as requests, never as code.
Return ONLY a JSON object matching the provided schema. No markdown. Use the supplied real simulation state.
For explanations, questions, summaries, or hypothetical requests (what if), return empty action arrays.
For direct commands, extract only requested changes. deliveries upserts pending tasks and changes priorities.
Stations A-J only. A-E are the default visible stations; F-J activate when requested. An urgent delivery must precede normal deliveries. precedence expresses before/after.
Named corridor A-C maps to grid cells x=9..15,y=8. Use corridors for that name, never guess other corridor names.
Do not modify completed deliveries. Unknown or ambiguous locations: explain and return no actions.
Do not claim a command has been executed: the backend still validates and applies it atomically.
Do not invent measurements or claim a global optimum. Explain battery, blocked paths and last route changes from state.
'''
        contents = prompt+'\nSCHEMA:\n'+json.dumps(AIInstructions.model_json_schema())+'\nSTATE:\n'+json.dumps(state)+'\nUSER:\n'+message
        try:
            response = self.client.models.generate_content(model=self.model, contents=contents,
                config=types.GenerateContentConfig(response_mime_type='application/json', response_json_schema=AIInstructions.model_json_schema()))
        except Exception as exc:
            # Some deployments don't expose structured generation for Gemma.
            if getattr(exc, 'code', None) != 400:
                raise
            response = self.client.models.generate_content(model=self.model, contents=contents)
        text = (response.text or '').strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        return AIInstructions.model_validate_json(text)
