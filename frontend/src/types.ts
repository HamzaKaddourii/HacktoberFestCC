export type LatLon = [number, number];

export type Place = { id: string; role: 'pickup' | 'dropoff'; name: string; kind: string; node: number; pos: LatLon };

export type CityMap = {
  name: string;
  bbox: [number, number, number, number];
  center: LatLon;
  attribution: string;
  fetched: string;
  hub: { name: string; node: number; pos: LatLon };
  places: Place[];
  streets: { name: string; highway: string; geometry: LatLon[] }[];
  hazard_kinds: Record<string, { label: string }>;
};

export type Thought = {
  id: number; time: string; robot: string; trigger: string; trigger_label: string; street: string;
  saw: string | null; classifier: string | null; gap: number | null;
  source: 'ai' | 'reflex'; model: string | null; latency_ms: number; note: string | null;
  analysis: string; hazard_kind: string; expected_duration: string;
  action: string; action_label: string; detail: string; shared: boolean; radio: string; outcome: string | null;
};

export type Sensors = {
  gps?: LatLon; gps_accuracy_m?: number; heading?: number; battery?: number;
  camera?: { distance_m: number; description: string; classifier: string; confidence: number } | null;
  lidar?: { obstacle_distance_m: number; free_gap_m: number; robot_width_m: number; moving_objects: boolean } | null;
};

export type Robot = {
  id: string; name: string; color: string; status: string; pos: LatLon; heading: number; battery: number;
  load: number[]; capacity: number; distance: number; street: string;
  stops: { order: number; kind: 'pickup' | 'dropoff'; place: string; urgent: boolean; metres: number }[];
  path: LatLon[]; sensors: Sensors; wait_left: number | null; thoughts: Thought[];
};

export type Order = {
  id: number; pickup: string; dropoff: string; pickup_name: string; dropoff_name: string;
  priority: 'normal' | 'urgent'; status: 'queued' | 'assigned' | 'onboard' | 'delivered'; robot: string | null;
  created: string; delivered_at: string | null;
};

export type Hazard = {
  id: number; kind: string; label: string; pos: LatLon; street: string; announced: boolean;
  seen_by: string[]; passable: boolean; view: string; clears_in: number | null;
};

export type Knowledge = {
  hazard: number; pos: LatLon; street: string; kind: string; blocks: boolean; by: string; message: string; expires_in: number | null;
};

export type PlanMetrics = { distance: number; makespan: number };

export type FleetEvent = { id: number; time: string; title: string; detail: string; kind: string; robot: string | null };

export type FleetState = {
  clock: string; time: number; running: boolean; speed: number; status: 'ready' | 'running' | 'paused' | 'completed';
  robots: Robot[]; orders: Order[]; hazards: Hazard[]; knowledge: Knowledge[]; events: FleetEvent[];
  metrics: {
    delivered: number; orders: number; fleet_distance: number; active: number;
    ai_decisions: number; reflex_decisions: number; avg_ai_ms: number | null;
    reports: number; reroutes: number; dispatches: number; hazards_seen: number;
    plan: { optimized: PlanMetrics; greedy: PlanMetrics } | null;
  };
  ai: { available: boolean; model: string; reason: string };
};
