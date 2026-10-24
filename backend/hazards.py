"""Ground-truth obstacles in the simulated city.

Robots never read this directly. They only learn about a hazard through their sensors
(camera description, classifier label, lidar gap) or when another robot shares it.
Some camera variants are deliberately ambiguous: the classifier label is a weak hint and the
onboard agent has to read the scene description to work out what is really happening.
"""
import random
from dataclasses import dataclass, field

# duration: (min, max) simulated seconds before it clears by itself; None = stays until removed.
KINDS = {
    'pedestrians': {
        'label': 'Pedestrian crowd', 'passable': False, 'duration': (20, 50), 'gap': (0.0, 0.3), 'moving': True,
        'views': [
            ('A tour group of about 15 people is standing on the sidewalk listening to a guide; they are shuffling slowly.', 'person', 0.94),
            ('A queue of people outside a bakery spills across the whole sidewalk; the line is advancing.', 'person', 0.91),
            ('Parents and children crossing at the corner; the crossing light just turned green.', 'person', 0.89),
        ]},
    'parked_vehicle': {
        'label': 'Vehicle on sidewalk', 'passable': False, 'duration': (150, 320), 'gap': (0.1, 0.4), 'moving': False,
        'views': [
            ('A white delivery van is parked fully on the sidewalk with hazard lights on; the driver is unloading boxes onto a trolley.', 'vehicle', 0.93),
            ('A moving truck with its tail-lift down blocks the sidewalk; two movers are carrying a sofa out of a building.', 'vehicle', 0.88),
            ('Several people are standing around a parked van with the side door open; they are loading crates and the van covers the sidewalk.', 'person', 0.57),
        ]},
    'roadworks': {
        'label': 'Roadworks', 'passable': False, 'duration': None, 'gap': (0.0, 0.1), 'moving': False,
        'views': [
            ('Orange and white barriers fence off the sidewalk and half of the lane; an excavator and a trench are behind them.', 'construction', 0.95),
            ('Two workers in hi-vis vests are setting up metal fences around an open manhole and stacking paving slabs.', 'person', 0.61),
            ('A scaffolding tunnel is closed with a "Trottoir fermé" sign; workers are cutting stone behind the fence.', 'construction', 0.83),
        ]},
    'road_closure': {
        'label': 'Street closed', 'passable': False, 'duration': None, 'gap': (0.0, 0.0), 'moving': False,
        'views': [
            ('Police tape stretched across the full street and a "Route barrée" sign; a police car is parked across the junction.', 'barrier', 0.92),
            ('Crowd-control barriers close the street for a market; stalls are being set up behind them.', 'barrier', 0.86),
        ]},
    'sidewalk_obstacle': {
        'label': 'Small obstacle', 'passable': True, 'duration': None, 'gap': (0.9, 1.2), 'moving': False,
        'views': [
            ('A shared e-scooter is lying across the sidewalk; there is a clear gap of about one metre on the left.', 'object', 0.9),
            ('Rubbish bags left on the sidewalk for collection; about one metre of sidewalk is still free.', 'object', 0.84),
            ('A café has put tables out on the sidewalk, leaving a narrow but open lane next to the kerb.', 'furniture', 0.72),
        ]},
    'flooding': {
        'label': 'Flooded sidewalk', 'passable': False, 'duration': (400, 800), 'gap': (0.0, 0.2), 'moving': False,
        'views': [
            ('A burst water main has flooded the sidewalk and gutter; the water depth is unknown and still rising.', 'water', 0.9),
            ('Street cleaning has left a wide, deep puddle covering the sidewalk from wall to kerb.', 'water', 0.78),
        ]},
}
ROBOT_WIDTH = 0.7


@dataclass
class Hazard:
    id: int
    kind: str
    a: int            # edge (a, b) in key order
    b: int
    along: float      # metres from a
    pos: tuple
    street: str
    created: float
    clears_at: float | None
    view: str
    label: str
    confidence: float
    gap: float
    announced: bool = False
    seen_by: list = field(default_factory=list)

    @property
    def passable(self):
        return self.gap >= ROBOT_WIDTH + 0.1

    def public(self, now):
        return {'id': self.id, 'kind': self.kind, 'label': KINDS[self.kind]['label'], 'pos': self.pos,
                'street': self.street, 'announced': self.announced, 'seen_by': self.seen_by,
                'passable': self.passable, 'view': self.view,
                'clears_in': None if self.clears_at is None else max(0, round(self.clears_at-now))}


def make(hid, kind, a, b, along, pos, street, now, rng=random):
    spec = KINDS[kind]
    view, label, confidence = rng.choice(spec['views'])
    duration = spec['duration']
    return Hazard(hid, kind, a, b, along, pos, street, now,
                  None if duration is None else now + rng.uniform(*duration),
                  view, label, confidence, round(rng.uniform(*spec['gap']), 2))
