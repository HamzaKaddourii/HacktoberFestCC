"""Dispatcher copilot: the operator talks to the fleet server in plain language.

The model only proposes structured changes (new orders, priority changes, announced street closures).
Everything is validated against the real map and mission before anything is applied.
"""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class OrderRequest(Strict):
    pickup: str
    dropoff: str
    priority: Literal['normal', 'urgent'] = 'normal'


class PriorityChange(Strict):
    order: int
    priority: Literal['normal', 'urgent']


class StreetClosure(Strict):
    street: str
    kind: Literal['roadworks', 'road_closure'] = 'road_closure'


class CopilotReply(Strict):
    explanation: str = Field(max_length=3000)
    new_orders: list[OrderRequest] = Field(default_factory=list, max_length=6)
    priority_changes: list[PriorityChange] = Field(default_factory=list, max_length=10)
    street_closures: list[StreetClosure] = Field(default_factory=list, max_length=3)


PROMPT = '''You are the dispatcher copilot of the RouteMind delivery robot fleet in {city}.
The operator writes to you. Use ONLY the supplied live state. Return ONLY a JSON object matching the schema.
- Questions, summaries, explanations and "what if" questions: answer in explanation and leave every action list empty.
- Direct commands: fill only the requested changes. Places are referenced by their id from PLACES;
  orders by number; streets by their exact name from STREETS. Unknown or ambiguous references: explain, no actions.
- Robots decide for themselves on the street; when asked why a robot did something, use its recent thoughts.
- Never claim a change was executed: the server validates and applies it. Never invent numbers.
'''


def ask(llm, message, fleet, snap):
    state = {
        'clock': snap['clock'], 'status': snap['status'], 'metrics': snap['metrics'],
        'robots': [{k: r[k] for k in ('id', 'name', 'status', 'battery', 'street', 'load', 'stops')}
                   | {'recent_thoughts': [{k: t[k] for k in ('time', 'trigger_label', 'street', 'saw', 'analysis', 'action_label', 'source', 'outcome')}
                                          for t in r['thoughts'][:3]]} for r in snap['robots']],
        'orders': [{k: o[k] for k in ('id', 'pickup', 'pickup_name', 'dropoff', 'dropoff_name', 'priority', 'status', 'robot')} for o in snap['orders']],
        'fleet_reports': snap['knowledge'],
        'recent_events': [f"{e['time']} {e['title']}: {e['detail']}" for e in snap['events'][:12]],
    }
    places = [{'id': p['id'], 'name': p['name'], 'kind': p['kind'], 'role': p['role']} for p in fleet.city.places.values()]
    streets = sorted({e.name for e in fleet.city.edges.values() if not e.name.startswith('unnamed')})
    prompt = (PROMPT.format(city=fleet.city.name) + '\nSCHEMA:\n' + json.dumps(CopilotReply.model_json_schema())
              + '\nPLACES:\n' + json.dumps(places, ensure_ascii=False) + '\nSTREETS:\n' + json.dumps(streets, ensure_ascii=False)
              + '\nSTATE:\n' + json.dumps(state, ensure_ascii=False) + '\nOPERATOR:\n' + message)
    return llm.generate(prompt, CopilotReply)


def apply(reply, fleet):
    """Validate every proposed change first, then apply them together. Raises ValueError on any problem."""
    places = fleet.city.places
    for o in reply.new_orders:
        if places.get(o.pickup, {}).get('role') != 'pickup' or places.get(o.dropoff, {}).get('role') != 'dropoff':
            raise ValueError(f'Unknown pickup/drop-off pair {o.pickup} → {o.dropoff}.')
    for c in reply.priority_changes:
        if c.order not in fleet.orders or fleet.orders[c.order]['status'] == 'delivered':
            raise ValueError(f'Order #{c.order} cannot be changed.')
    closures = []
    for s in reply.street_closures:
        edges = [e for e in fleet.city.edges.values() if e.name.lower() == s.street.lower()]
        if not edges:
            raise ValueError(f'Street not found on the map: {s.street}.')
        middle = edges[len(edges)//2]
        closures.append((middle.geometry[len(middle.geometry)//2], s.kind))
    for o in reply.new_orders:
        fleet.add_order(o.pickup, o.dropoff, o.priority)
    for (lat, lon), kind in closures:
        fleet.add_hazard(lat, lon, kind, announced=True)
    for c in reply.priority_changes:
        fleet.orders[c.order]['priority'] = c.priority
    if reply.new_orders or reply.priority_changes:
        fleet.dispatch('Copilot instructions')
    return bool(reply.new_orders or reply.priority_changes or closures)
