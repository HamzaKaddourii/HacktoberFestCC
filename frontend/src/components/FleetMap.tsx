import { useEffect, useMemo, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { MapContainer, Marker, Polygon, Polyline, Popup, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import type { CityMap, FleetState, Hazard, LatLon, Robot } from '../types';

const CAMERA_RANGE = 35;
const icons = new Map<string, L.DivIcon>();
// Stadia's dark style works on localhost without a key; Esri's dark canvas is the keyless fallback elsewhere.
const TILES = [
  { url: 'https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png',
    attribution: '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a> &copy; <a href="https://openmaptiles.org/">OpenMapTiles</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' },
  { url: 'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' },
];

function icon(key: string, html: string, size: number, className: string) {
  if (!icons.has(key)) {
    icons.set(key, L.divIcon({ className, html, iconSize: [size, size], iconAnchor: [size / 2, size / 2] }));
  }
  return icons.get(key)!;
}

// Metres to degrees with a local flat-earth approximation: accurate at street scale.
function offset([lat, lon]: LatLon, bearing: number, metres: number): LatLon {
  const rad = (bearing * Math.PI) / 180;
  return [lat + (metres * Math.cos(rad)) / 110_540, lon + (metres * Math.sin(rad)) / (111_320 * Math.cos((lat * Math.PI) / 180))];
}

function cameraCone(pos: LatLon, heading: number): LatLon[] {
  const points: LatLon[] = [pos];
  for (let a = -35; a <= 35; a += 7) points.push(offset(pos, heading + a, CAMERA_RANGE));
  return points;
}

function hazardState(h: Hazard, known: Set<number>) {
  if (known.has(h.id)) return 'reported';
  return h.seen_by.length ? 'seen' : 'hidden';
}

function FitToCity({ bbox }: { bbox: CityMap['bbox'] }) {
  const map = useMap();
  useEffect(() => {
    map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: [8, 8] });
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map, bbox]);
  return null;
}

function ClickToPlace({ armed, onPlace }: { armed: boolean; onPlace: (p: LatLon) => void }) {
  useMapEvents({ click: (e) => armed && onPlace([e.latlng.lat, e.latlng.lng]) });
  return null;
}

type Props = {
  map: CityMap;
  state: FleetState;
  selected: string;
  onSelect: (id: string) => void;
  armed: string | null;
  onPlace: (p: LatLon) => void;
  onRemoveHazard: (id: number) => void;
  showGraph: boolean;
};

export default function FleetMap({ map, state, selected, onSelect, armed, onPlace, onRemoveHazard, showGraph }: Props) {
  const streets = useMemo(() => map.streets.map((s) => s.geometry), [map]);
  const [tiles, setTiles] = useState(0);
  const known = new Set(state.knowledge.map((k) => k.hazard));
  const activePlaces = new Set(state.orders.filter((o) => o.status !== 'delivered').flatMap((o) => [o.pickup, o.dropoff]));
  const [s, w, n, e] = map.bbox;
  const pad = 0.006;

  // Docked robots share the hub; fan them out a little so each stays clickable.
  const shown = (r: Robot, i: number): LatLon => {
    const docked = (r.status === 'idle' || r.status === 'charging') && Math.abs(r.pos[0] - map.hub.pos[0]) < 1e-5 && Math.abs(r.pos[1] - map.hub.pos[1]) < 1e-5;
    return docked ? offset(map.hub.pos, 45 + i * 90, 14) : r.pos;
  };

  return (
    <MapContainer className={'fleet-map' + (armed ? ' armed' : '')} center={map.center} zoom={16} minZoom={14} maxZoom={19}
      maxBounds={[[s - pad, w - pad], [n + pad, e + pad]]} scrollWheelZoom>
      <FitToCity bbox={map.bbox} />
      <ClickToPlace armed={!!armed} onPlace={onPlace} />
      <TileLayer key={tiles} url={TILES[tiles].url} attribution={TILES[tiles].attribution} maxZoom={20}
        eventHandlers={{ tileerror: () => setTiles((t) => Math.min(t + 1, TILES.length - 1)) }} />
      {showGraph && <Polyline positions={streets} interactive={false} pathOptions={{ color: '#6f8bab', weight: 1.6, opacity: 0.45 }} />}

      {state.robots.map((r) => r.path.length > 1 && (
        <Polyline key={'path' + r.id} positions={r.path} interactive={false}
          pathOptions={{ color: r.color, weight: r.id === selected ? 4 : 2.5, opacity: r.id === selected ? 0.95 : 0.6, dashArray: '7 7' }} />
      ))}
      {state.robots.filter((r) => !['idle', 'charging'].includes(r.status)).map((r) => (
        <Polygon key={'cone' + r.id} positions={cameraCone(r.pos, r.heading)} interactive={false}
          pathOptions={{ color: r.sensors.camera ? '#f3b66a' : r.color, weight: 1, opacity: 0.55, fillOpacity: r.sensors.camera ? 0.25 : 0.07 }} />
      ))}

      {map.places.map((p) => (
        <Marker key={p.id} position={p.pos} icon={icon(`place:${p.role}:${activePlaces.has(p.id)}`,
          `<div class="place-pin ${p.role}${activePlaces.has(p.id) ? ' active' : ''}">${p.role === 'pickup' ? 'P' : 'D'}</div>`, 18, 'place-icon')}>
          <Tooltip direction="top" offset={[0, -8]}><b>{p.name}</b><br />{p.id} · {p.kind} · {p.role === 'pickup' ? 'pickup' : 'drop-off'}</Tooltip>
        </Marker>
      ))}
      <Marker position={map.hub.pos} icon={icon('hub', '<div class="hub-pin">⚡</div>', 26, 'hub-icon')}>
        <Tooltip direction="top" offset={[0, -12]}><b>{map.hub.name}</b><br />Charging and dispatch hub</Tooltip>
      </Marker>

      {state.hazards.map((h) => {
        const st = hazardState(h, known);
        return (
          <Marker key={'hz' + h.id} position={h.pos} icon={icon(`hz:${st}:${h.kind}`, `<div class="hazard-pin ${st} ${h.kind}">!</div>`, 22, 'hazard-icon')}>
            <Popup>
              <div className="hazard-popup">
                <b>{h.label}</b> <span>{h.street}</span>
                <p>{h.view}</p>
                <small>
                  {st === 'hidden' ? 'Hidden: no robot has seen it yet.' : st === 'seen' ? `Seen by ${h.seen_by.join(', ')}, not reported.` : 'On the fleet map.'}
                  {h.clears_in !== null ? ` Clears by itself in ~${h.clears_in} s.` : ' Stays until removed.'}
                </small>
                <button onClick={() => onRemoveHazard(h.id)}>Remove obstacle</button>
              </div>
            </Popup>
          </Marker>
        );
      })}
      {state.knowledge.filter((k) => !state.hazards.some((h) => h.id === k.hazard)).map((k) => (
        <Marker key={'stale' + k.hazard} position={k.pos} icon={icon('stale', '<div class="hazard-pin stale">?</div>', 20, 'hazard-icon')}>
          <Tooltip>Report by {k.by}: {k.message}. Gone in reality; robots still avoid it {k.expires_in !== null ? `for ${k.expires_in} s` : 'until cleared'}.</Tooltip>
        </Marker>
      ))}

      {state.robots.map((r, i) => {
        const heading = Math.round(r.heading / 15) * 15;
        const sel = r.id === selected;
        return (
          <Marker key={r.id} position={shown(r, i)} zIndexOffset={sel ? 1000 : 500} eventHandlers={{ click: () => onSelect(r.id) }}
            icon={icon(`robot:${r.id}:${heading}:${r.status}:${sel}`,
              `<div class="robot-dot ${r.status}${sel ? ' selected' : ''}" style="--c:${r.color}"><span class="robot-heading" style="transform:rotate(${heading}deg)"></span><b>${r.id.slice(3)}</b></div>`,
              34, 'robot-icon')}>
            <Tooltip direction="right" offset={[16, 0]}>{r.id} {r.name} · {r.status}</Tooltip>
          </Marker>
        );
      })}
    </MapContainer>
  );
}
