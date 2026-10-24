import { Activity, Brain, Check, Radio, TriangleAlert } from 'lucide-react';
import type { FleetEvent, Robot } from '../types';

export default function ActivityPanel({ events, robots }: { events: FleetEvent[]; robots: Robot[] }) {
  const color = (id: string | null) => robots.find((r) => r.id === id)?.color;
  return (
    <section className="panel events-panel">
      <div className="panel-heading">
        <div className="heading-title"><Activity size={17} /><h2>Live activity</h2></div>
        <span className="subtle-tag">{events.length} events</span>
      </div>
      <div className="events">
        {events.map((e) => (
          <div className="event" key={e.id}>
            <span className={'event-icon ' + e.kind} style={e.robot ? { boxShadow: `0 0 0 1px ${color(e.robot)}` } : undefined}>
              {e.kind === 'success' ? <Check size={12} /> : e.kind === 'warning' ? <TriangleAlert size={12} /> : e.kind === 'ai' ? <Brain size={12} /> : <Radio size={12} />}
            </span>
            <div><b>{e.title}</b><p>{e.detail}</p></div>
            <time>{e.time}</time>
          </div>
        ))}
      </div>
    </section>
  );
}
