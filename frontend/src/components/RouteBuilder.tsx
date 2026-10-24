import { ArrowDown, ArrowUp, Check, Eraser, Play, Route, Trash2, X } from 'lucide-react';
import type { Place, Robot } from '../types';

export type RoutePoint = { place?: string; lat?: number; lon?: number; name: string };
export type RouteDraft = { robot: string; points: RoutePoint[]; saved: boolean };

type Props = {
  draft: RouteDraft;
  robot: Robot;
  places: Place[];
  busy: boolean;
  onChange: (points: RoutePoint[]) => void;
  onSave: () => void;
  onStart: () => void;
  onCancelRoute: () => void;
  onClose: () => void;
};

/** Floating panel over the map: click points in visiting order, save the route, then start the robot. */
export default function RouteBuilder({ draft, robot, places, busy, onChange, onSave, onStart, onCancelRoute, onClose }: Props) {
  const points = draft.points;
  const move = (i: number, d: number) => {
    const next = [...points];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    onChange(next);
  };
  const rename = (i: number, name: string) => onChange(points.map((p, k) => (k === i ? { ...p, name } : p)));
  const remove = (i: number) => onChange(points.filter((_, k) => k !== i));
  const kind = (p: RoutePoint) => places.find((x) => x.id === p.place)?.kind ?? 'spot on the map';
  return (
    <div className="order-builder route-builder" role="dialog" aria-label={`Route for ${robot.id}`} style={{ '--c': robot.color } as React.CSSProperties}>
      <div className="ob-head"><Route size={15} /><b>Route for {robot.id} · {robot.name}</b><button aria-label="Close" onClick={onClose}><X size={15} /></button></div>
      {!draft.saved && <p className="rb-hint">Click points on the map in the order {robot.id} should visit them: existing P/D points or any spot on a street.</p>}
      <ol className="rb-list">
        {points.map((p, i) => (
          <li key={i}>
            <span className="ob-num">{i + 1}</span>
            <div>
              {p.place ? <b>{p.name}</b> : <input value={p.name} maxLength={40} onChange={(e) => rename(i, e.target.value)} aria-label={`Name of point ${i + 1}`} />}
              <small>{kind(p)}</small>
            </div>
            <button aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={12} /></button>
            <button aria-label="Move down" disabled={i === points.length - 1} onClick={() => move(i, 1)}><ArrowDown size={12} /></button>
            <button aria-label="Remove point" onClick={() => remove(i)}><X size={12} /></button>
          </li>
        ))}
        {!points.length && <li className="rb-empty">No points yet</li>}
      </ol>
      {points.length > 0 && (
        <div className="rb-end">
          <span>then back to the hub to recharge</span>
          <button className="rb-clear" disabled={busy} onClick={() => onChange([])}><Eraser size={12} />Clear points</button>
        </div>
      )}
      {draft.saved ? (
        <>
          <div className="rb-saved"><Check size={13} />Route saved: the dashed line on the map is the street route.</div>
          <button className="button primary" disabled={busy} onClick={onStart}><Play size={14} />Start {robot.id}</button>
          <button className="button danger" disabled={busy} onClick={onCancelRoute}><Trash2 size={13} />Delete route</button>
        </>
      ) : (
        <button className="button primary" disabled={busy || !points.length || points.some((p) => !p.name.trim())} onClick={onSave}>Save route</button>
      )}
    </div>
  );
}
