import { Bot } from 'lucide-react';
import type { Robot } from '../types';

type Props = { robots: Robot[]; selected: string; onSelect: (id: string) => void };

export default function FleetPanel({ robots, selected, onSelect }: Props) {
  return (
    <section className="panel fleet-panel">
      <div className="panel-heading">
        <div className="heading-title"><Bot size={17} /><h2>Fleet</h2><span className="count">{robots.length}</span></div>
        <span className="subtle-tag">click to inspect</span>
      </div>
      <div className="robot-list">
        {robots.map((r) => {
          const next = r.stops[0];
          return (
            <button key={r.id} className={'robot-card' + (r.id === selected ? ' selected' : '')} style={{ '--c': r.color } as React.CSSProperties}
              onClick={() => onSelect(r.id)}>
              <span className="robot-badge">{r.id.slice(3)}</span>
              <div>
                <b>{r.id} · {r.name}</b>
                <span>{next ? `${next.kind === 'pickup' ? 'Pick up' : 'Drop off'} #${next.order} · ${next.place}` : r.status === 'idle' ? 'Docked' : r.status === 'charging' ? 'Charging at hub' : 'Returning to hub'}</span>
              </div>
              <div className="robot-side">
                <span className={'status-pill ' + r.status}><i className="dot" />{r.status}</span>
                <span className="mini-battery"><i style={{ width: `${r.battery}%` }} className={r.battery < 25 ? 'low' : ''} />{r.battery.toFixed(0)}%</span>
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
