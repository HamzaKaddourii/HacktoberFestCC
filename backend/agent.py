"""The onboard brain of each robot: sense -> think -> act.

When a robot's sensors report something (an obstacle on camera, a blocked bumper, a path that is still
blocked after waiting, a low battery), the fleet engine builds an observation from that robot's own
sensors, its map reading (detour options with street names), its mission and its memory of earlier
decisions. The agent then decides one action.

Two layers, like a real robot:
- the AI agent (Gemma through the Google GenAI API) reasons over the full observation;
- reflex rules decide instantly from the classifier label when the AI is unavailable, slow or invalid.
Every decision records which layer made it, so the dashboard never presents a rule as AI output.
"""
import json
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ACTIONS = ('continue', 'proceed_slowly', 'wait', 'detour', 'request_dispatch', 'return_to_hub')
ACTION_LABELS = {'continue': 'Continue route', 'proceed_slowly': 'Pass slowly', 'wait': 'Wait and re-scan',
                 'detour': 'Detour', 'request_dispatch': 'Ask dispatcher', 'return_to_hub': 'Return to hub'}
TRIGGERS = {'camera': 'Obstacle on camera', 'still_blocked': 'Still blocked after waiting',
            'bumper': 'Path physically blocked', 'low_battery': 'Low battery'}


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    analysis: str = Field(max_length=700, description='1-3 sentences, first person: what you see, what it means, why this action.')
    hazard_kind: Literal['pedestrians', 'parked_vehicle', 'roadworks', 'road_closure', 'sidewalk_obstacle',
                         'flooding', 'none', 'unknown'] = 'unknown'
    blocks_path: bool = True
    expected_duration: Literal['seconds', 'minutes', 'long', 'permanent', 'unknown'] = 'unknown'
    action: Literal[ACTIONS]
    wait_seconds: int = Field(0, ge=0, le=180)
    detour_option: int = Field(1, ge=1, le=3)
    share_with_fleet: bool = False
    radio_message: str = Field('', max_length=240, description='Short message to the dispatcher and other robots, or empty.')


INSTRUCTIONS = '''You are the onboard autonomy agent of {robot}, a sidewalk delivery robot working in {city}.
You run inside the robot. When something happens you receive one observation built from your own sensors,
your street map and your mission, and you choose the next action. Think like an experienced courier.

Safety rules (never break them):
- Never push through people, animals or vehicles. Never drive into water, trenches or a fenced works area.
- proceed_slowly is only safe when lidar free_gap_m is at least robot_width_m + 0.1.
- Keep enough battery to get back to the hub.

How to judge:
- The camera classifier label is only a hint. Trust the scene description and the lidar more; say so if they disagree.
- Estimate how long the obstacle will last: people usually move within a minute, an unloading van takes several
  minutes, roadworks, closures and flooding last a long time.
- Weigh waiting against detour length: you drive 1.8 m/s, so 100 m of detour costs about 55 s.
  Urgent parcels on board make waiting more costly.
- Use your memory: if you already waited here and it did not clear, change strategy.
- If the obstacle blocks the street for minutes or longer, set share_with_fleet so other robots avoid it.
- Use request_dispatch when no detour is good or your remaining orders would be better served by another robot.
- Only choose an action listed in options. detour_option must be one of the listed detours.

Reply with ONLY a JSON object that matches the schema. Write analysis in first person and be concrete:
mention the street, distances and the reason for your choice.'''


class RobotAgent:
    def __init__(self, llm=None):
        self.llm = llm

    def prompt(self, obs):
        return (INSTRUCTIONS.format(robot=obs['robot'], city=obs['city'])
                + '\n\nSCHEMA:\n' + json.dumps(Decision.model_json_schema())
                + '\n\nOBSERVATION:\n' + json.dumps(obs, ensure_ascii=False, indent=1))

    def decide(self, obs):
        started = time.perf_counter()
        note = None
        if self.llm is not None and self.llm.available:
            try:
                decision = self.llm.generate(self.prompt(obs), Decision)
                problem = check(decision, obs)
                if problem is None:
                    return {'decision': normalise(decision), 'source': 'ai', 'model': self.llm.model,
                            'latency_ms': round((time.perf_counter()-started)*1000), 'note': None}
                note = f'AI answer rejected ({problem}); reflex rules took over.'
            except Exception as exc:
                note = f'AI unavailable for this decision ({type(exc).__name__}); reflex rules took over.'
        return {'decision': reflex(obs), 'source': 'reflex', 'model': None,
                'latency_ms': round((time.perf_counter()-started)*1000), 'note': note}


def check(decision, obs):
    options = obs['options']
    if decision.action not in options:
        return f'{decision.action} is not available here'
    if decision.action == 'detour' and decision.detour_option > len(options['detour']):
        return f'detour option {decision.detour_option} does not exist'
    if decision.action == 'proceed_slowly':
        lidar = obs['sensors'].get('lidar') or {}
        if lidar.get('free_gap_m', 0) < lidar.get('robot_width_m', 0.7) + 0.1:
            return 'the lidar gap is too narrow to pass safely'
    if decision.action == 'continue' and obs['trigger'] == 'low_battery':
        if obs['battery']['range_m'] < obs['battery']['needed_for_plan_m']:
            return 'the battery range does not cover the remaining plan'
    return None


def normalise(decision):
    if decision.action == 'wait' and decision.wait_seconds < 5:
        decision.wait_seconds = 15
    return decision


def reflex(obs):
    """Deterministic fallback autopilot. It only looks at labels and numbers, never at the scene text."""
    options = obs['options']
    detours = options.get('detour') or []
    trigger = obs['trigger']

    def make(action, analysis, **kw):
        if action == 'detour' and not detours:
            action = 'request_dispatch'
            analysis += ' No detour available, so the dispatcher decides.'
        return Decision(analysis=analysis, action=action, **kw)

    if trigger == 'low_battery':
        b = obs['battery']
        if b['range_m'] >= b['needed_for_plan_m']*1.15:
            return make('continue', f"Rule: range {b['range_m']} m covers the remaining plan ({b['needed_for_plan_m']} m) with margin.",
                        hazard_kind='none', blocks_path=False)
        return make('return_to_hub', f"Rule: range {b['range_m']} m is too short for the remaining plan ({b['needed_for_plan_m']} m).",
                    hazard_kind='none', blocks_path=False, radio_message='Low battery, returning to hub.')

    camera = obs['sensors']['camera']['detection'] or {}
    lidar = obs['sensors'].get('lidar') or {}
    label, conf = camera.get('classifier', 'unknown'), camera.get('confidence', 0)
    gap, width = lidar.get('free_gap_m', 0), lidar.get('robot_width_m', 0.7)
    waits = obs['encounter']['waits']
    extra = detours[0]['extra_m'] if detours else None
    tag = f"Rule: classifier '{label}' ({conf:.2f}), lidar gap {gap} m"

    if trigger == 'bumper':
        return make('detour', 'Rule: bumper contact, path is physically blocked; go around.', blocks_path=True,
                    share_with_fleet=True, radio_message='Path physically blocked here.')
    if gap >= width + 0.1 and 'proceed_slowly' in options:
        return make('proceed_slowly', f'{tag} ≥ robot width + margin; pass slowly.',
                    hazard_kind='sidewalk_obstacle', blocks_path=False)
    if label == 'person':
        if waits < 2:
            return make('wait', f'{tag}; people usually move, wait 20 s.', hazard_kind='pedestrians',
                        expected_duration='seconds', wait_seconds=20)
        return make('detour', f'{tag}; waited {waits} times without success, go around.', hazard_kind='pedestrians')
    if label == 'vehicle':
        if extra is not None and extra <= 250 or waits >= 1:
            return make('detour', f'{tag}; vehicle detected, detour (+{extra} m) is cheaper than waiting.',
                        hazard_kind='parked_vehicle', expected_duration='minutes')
        return make('wait', f'{tag}; vehicle detected and detour is long, wait 60 s.',
                    hazard_kind='parked_vehicle', expected_duration='minutes', wait_seconds=60)
    if label in ('construction', 'barrier', 'water'):
        kind = {'construction': 'roadworks', 'barrier': 'road_closure', 'water': 'flooding'}[label]
        return make('detour', f'{tag}; long-lasting blockage, detour and warn the fleet.', hazard_kind=kind,
                    expected_duration='long', share_with_fleet=True, radio_message=f'{kind.replace("_", " ").title()} ahead, avoid this street.')
    if waits == 0:
        return make('wait', f'{tag}; unknown obstacle, wait 15 s and re-scan.', wait_seconds=15)
    return make('detour', f'{tag}; unknown obstacle did not clear, go around.')
