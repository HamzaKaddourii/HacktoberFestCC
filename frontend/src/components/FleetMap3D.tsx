import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Eye, Navigation } from 'lucide-react';
import type { CityMap, FleetState, LatLon, Robot } from '../types';

// Free vector tiles with building heights (OpenFreeMap). If they can't load, a plain background is used
// and the city is still drawn from our own street graph.
const STYLE = 'https://tiles.openfreemap.org/styles/dark';
const FALLBACK_STYLE: maplibregl.StyleSpecification = {
  version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#0e151e' } }],
};
const CAMERA_RANGE = 35;
// Robot and obstacle sizes are exaggerated (real robot ≈ 0.7 m) so they stay visible from above.
const ROBOT_SHAPE: [number, number][] = [[0, 3.4], [2.1, -2.3], [0, -1.1], [-2.1, -2.3]];
const HAZARD_SIZE: Record<string, [number, number]> = {
  pedestrians: [5, 1.8], parked_vehicle: [6, 2.6], roadworks: [7, 2.4], road_closure: [9, 1.4], sidewalk_obstacle: [3, 0.9], flooding: [9, 0.35],
};

type Pt = [number, number]; // [lng, lat] for GeoJSON

function at([lat, lon]: LatLon, east: number, north: number): Pt {
  return [lon + east / (111_320 * Math.cos((lat * Math.PI) / 180)), lat + north / 110_540];
}

/** Polygon from local metres (x = right, y = forward), rotated to a compass heading. */
function shape(pos: LatLon, heading: number, points: [number, number][]): Pt[] {
  const r = (heading * Math.PI) / 180;
  const ring = points.map(([x, y]) => at(pos, x * Math.cos(r) + y * Math.sin(r), -x * Math.sin(r) + y * Math.cos(r)));
  return [...ring, ring[0]];
}

const square = (pos: LatLon, side: number) => shape(pos, 0, [[-side / 2, -side / 2], [side / 2, -side / 2], [side / 2, side / 2], [-side / 2, side / 2]]);
const cone = (pos: LatLon, heading: number): Pt[] => {
  const pts: [number, number][] = [[0, 0]];
  for (let a = -35; a <= 35; a += 7) pts.push([Math.sin((a * Math.PI) / 180) * CAMERA_RANGE, Math.cos((a * Math.PI) / 180) * CAMERA_RANGE]);
  return shape(pos, heading, pts);
};
const lngLat = (p: LatLon): Pt => [p[1], p[0]];
const collection = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: 'FeatureCollection', features });
const polygon = (ring: Pt[], properties: Record<string, unknown>): GeoJSON.Feature => ({ type: 'Feature', properties, geometry: { type: 'Polygon', coordinates: [ring] } });

function robotColor(r: Robot) {
  if (r.status === 'thinking') return '#c9b2ff';
  if (r.status === 'waiting') return '#ecb971';
  return r.color;
}

function addLayers(map: maplibregl.Map, city: CityMap) {
  if (map.getSource('streets')) return;
  if (map.getSource('openmaptiles')) {
    map.addLayer({
      id: 'buildings-3d', type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', minzoom: 14,
      paint: {
        'fill-extrusion-color': '#2a3546', 'fill-extrusion-opacity': 0.78,
        'fill-extrusion-height': ['get', 'render_height'], 'fill-extrusion-base': ['get', 'render_min_height'],
      },
    });
  }
  const empty = collection([]);
  map.addSource('streets', { type: 'geojson', data: collection(city.streets.map((s) => ({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: s.geometry.map(lngLat) } }))) });
  for (const id of ['routes', 'cones', 'places', 'hazards', 'robots', 'hub']) map.addSource(id, { type: 'geojson', data: empty });
  map.addLayer({ id: 'streets', type: 'line', source: 'streets', paint: { 'line-color': '#6f8bab', 'line-width': 1.4, 'line-opacity': 0.45 } });
  map.addLayer({ id: 'cones', type: 'fill', source: 'cones', paint: { 'fill-color': ['get', 'color'], 'fill-opacity': ['get', 'opacity'] } });
  map.addLayer({
    id: 'routes', type: 'line', source: 'routes', layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': ['get', 'color'], 'line-width': ['get', 'width'], 'line-opacity': 0.9, 'line-dasharray': [2, 1.5] },
  });
  map.addLayer({
    id: 'places', type: 'circle', source: 'places',
    paint: { 'circle-radius': ['get', 'radius'], 'circle-color': ['get', 'color'], 'circle-opacity': ['get', 'opacity'], 'circle-stroke-color': '#0e151e', 'circle-stroke-width': 1.5, 'circle-pitch-alignment': 'map' },
  });
  map.addLayer({ id: 'hub', type: 'fill-extrusion', source: 'hub', paint: { 'fill-extrusion-color': '#5dbba4', 'fill-extrusion-height': 4, 'fill-extrusion-opacity': 0.9 } });
  map.addLayer({
    id: 'hazards-hidden', type: 'fill-extrusion', source: 'hazards', filter: ['==', ['get', 'state'], 'hidden'],
    paint: { 'fill-extrusion-color': '#f08a7a', 'fill-extrusion-height': ['get', 'height'], 'fill-extrusion-opacity': 0.35 },
  });
  map.addLayer({
    id: 'hazards-known', type: 'fill-extrusion', source: 'hazards', filter: ['!=', ['get', 'state'], 'hidden'],
    paint: { 'fill-extrusion-color': ['get', 'color'], 'fill-extrusion-height': ['get', 'height'], 'fill-extrusion-opacity': 0.95 },
  });
  map.addLayer({ id: 'robots', type: 'fill-extrusion', source: 'robots', paint: { 'fill-extrusion-color': ['get', 'color'], 'fill-extrusion-height': ['get', 'height'], 'fill-extrusion-opacity': 1 } });
}

type Props = {
  map: CityMap; state: FleetState; selected: string; onSelect: (id: string) => void; armed: string | null;
  onPlace: (p: LatLon) => void; onPlaceClick: (id: string) => void; allRoutes: boolean;
  building: boolean; draft: { pos: LatLon; n: number }[]; chosen: string[];
};

export default function FleetMap3D({ map: city, state, selected, onSelect, armed, onPlace, onPlaceClick, allRoutes, building, draft, chosen }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markers = useRef(new Map<string, maplibregl.Marker>());
  const stopMarkers = useRef(new Map<string, maplibregl.Marker>());
  const latest = useRef({ armed, onPlace, onSelect, onPlaceClick });
  latest.current = { armed, onPlace, onSelect, onPlaceClick };
  const [ready, setReady] = useState(false);
  const [follow, setFollow] = useState(true);

  useEffect(() => {
    const [s, w, n, e] = city.bbox;
    const map = new maplibregl.Map({
      container: container.current!, style: STYLE, bounds: [[w, s], [e, n]], pitch: 58, bearing: -18, maxPitch: 75,
      attributionControl: { compact: true, customAttribution: city.attribution },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-left');
    let fellBack = false;
    map.on('error', () => {
      if (!fellBack && !map.isStyleLoaded()) {
        fellBack = true;
        map.setStyle(FALLBACK_STYLE);
      }
    });
    map.on('style.load', () => { addLayers(map, city); setReady(true); });
    map.on('click', (e) => {
      const { armed, onPlace, onSelect, onPlaceClick } = latest.current;
      const place = map.queryRenderedFeatures(e.point, { layers: ['places'] })[0];
      if (place) return onPlaceClick(String(place.properties.id));
      if (armed) return onPlace([e.lngLat.lat, e.lngLat.lng]);
      const robot = map.queryRenderedFeatures(e.point, { layers: ['robots'] })[0];
      if (robot) onSelect(String(robot.properties.id));
    });
    map.on('dragstart', () => setFollow(false));
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(container.current!);
    return () => {
      ro.disconnect();
      for (const group of [markers.current, stopMarkers.current]) { group.forEach((m) => m.remove()); group.clear(); }
      map.remove();
    };
  }, [city]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const set = (id: string, data: GeoJSON.FeatureCollection) => (map.getSource(id) as maplibregl.GeoJSONSource | undefined)?.setData(data);
    const known = new Set(state.knowledge.map((k) => k.hazard));
    const active = new Set(state.orders.filter((o) => o.status !== 'delivered').flatMap((o) => [o.pickup, o.dropoff]));
    const moving = state.robots.filter((r) => !['idle', 'charging'].includes(r.status));

    set('routes', collection(state.robots.filter((r) => r.path.length > 1 && (allRoutes || r.id === selected)).map((r) => ({
      type: 'Feature', properties: { color: r.color, width: r.id === selected ? 5 : 3 },
      geometry: { type: 'LineString', coordinates: r.path.map(lngLat) },
    }))));
    set('cones', collection(moving.map((r) => polygon(cone(r.pos, r.heading), { color: r.sensors.camera ? '#f3b66a' : r.color, opacity: r.sensors.camera ? 0.35 : 0.12 }))));
    set('places', collection(state.places.map((p) => ({
      type: 'Feature',
      properties: {
        id: p.id, color: p.role === 'pickup' ? '#f2c46d' : '#d892e6',
        opacity: chosen.includes(p.id) || building || active.has(p.id) ? 1 : 0.35,
        radius: chosen.includes(p.id) ? 10 : building ? 8 : 6,
      },
      geometry: { type: 'Point', coordinates: lngLat(p.pos) },
    }))));
    set('hub', collection([polygon(square(city.hub.pos, 9), {})]));
    set('hazards', collection(state.hazards.map((h) => {
      const [side, height] = HAZARD_SIZE[h.kind] ?? [5, 2];
      const st = known.has(h.id) ? 'reported' : h.seen_by.length ? 'seen' : 'hidden';
      return polygon(square(h.pos, side), { state: st, height, color: st === 'reported' ? '#e5534b' : '#f3b66a' });
    })));
    set('robots', collection(state.robots.map((r) => polygon(shape(r.pos, r.heading, ROBOT_SHAPE), { id: r.id, color: robotColor(r), height: r.id === selected ? 2.8 : 2.2 }))));

    for (const r of state.robots) {
      let marker = markers.current.get(r.id);
      if (!marker) {
        // MapLibre owns the marker element's classes; our label lives inside it.
        const el = document.createElement('div');
        el.appendChild(document.createElement('span'));
        el.addEventListener('click', () => latest.current.onSelect(r.id));
        marker = new maplibregl.Marker({ element: el, anchor: 'bottom', offset: [0, -16] }).setLngLat(lngLat(r.pos)).addTo(map);
        markers.current.set(r.id, marker);
      }
      const label = marker.getElement().firstElementChild as HTMLSpanElement;
      label.style.setProperty('--c', r.color);
      label.className = `robot-label ${r.status}${r.id === selected ? ' selected' : ''}`;
      label.textContent = r.status === 'thinking' ? `${r.id} · thinking…` : r.status === 'waiting' ? `${r.id} · waiting ${r.wait_left ?? ''}s` : r.id;
      marker.setLngLat(lngLat(r.pos));
    }

    // Numbered points: the route being drawn, otherwise the selected robot's upcoming stops.
    const stops = building
      ? draft.map((d) => ({ key: `draft${d.n}`, pos: d.pos, kind: 'draft', urgent: false }))
      : (state.robots.find((r) => r.id === selected)?.stops ?? []).map((s, i) => ({ key: `${s.order ?? 'w' + i}${s.kind}${s.place}`, pos: s.pos, kind: s.kind, urgent: s.urgent }));
    const keep = new Set<string>();
    stops.forEach((stop, i) => {
      const key = stop.key;
      keep.add(key);
      let marker = stopMarkers.current.get(key);
      if (!marker) {
        const el = document.createElement('div');
        el.appendChild(document.createElement('span'));
        marker = new maplibregl.Marker({ element: el }).setLngLat(lngLat(stop.pos)).addTo(map);
        stopMarkers.current.set(key, marker);
      }
      const pin = marker.getElement().firstElementChild as HTMLSpanElement;
      pin.className = `stop-pin ${stop.kind}${stop.urgent ? ' urgent' : ''}`;
      pin.textContent = String(i + 1);
      marker.setLngLat(lngLat(stop.pos));
    });
    for (const [key, marker] of stopMarkers.current) {
      if (!keep.has(key)) { marker.remove(); stopMarkers.current.delete(key); }
    }

    const target = state.robots.find((r) => r.id === selected);
    if (follow && target) {
      // Chase camera: sit behind the robot, looking where it is heading.
      map.easeTo({ center: lngLat(target.pos), bearing: target.heading, pitch: 62, zoom: 18.8, duration: 450, essential: true });
    }
  }, [state, ready, selected, follow, city, allRoutes, building, draft, chosen]);

  const overview = () => {
    setFollow(false);
    const [s, w, n, e] = city.bbox;
    mapRef.current?.fitBounds([[w, s], [e, n]], { pitch: 58, bearing: -18, duration: 900 });
  };

  return (
    <div className="map3d">
      <div ref={container} className={'fleet-map' + (armed ? ' armed' : '')} />
      <div className="map3d-controls">
        <button className={follow ? 'selected' : ''} onClick={() => setFollow(true)} title="Ride behind the selected robot"><Navigation size={13} />Follow {selected}</button>
        <button className={!follow ? 'selected' : ''} onClick={overview} title="See the whole district"><Eye size={13} />Overview</button>
      </div>
    </div>
  );
}
