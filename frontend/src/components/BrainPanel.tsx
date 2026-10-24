import { BatteryLow, Brain, Camera, Cpu, MapPin, Package, Play, Radar, Radio, Route, Satellite, ShieldAlert } from 'lucide-react';
import type { FleetState, Robot, Thought } from '../types';

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
const compass = (deg = 0) => COMPASS[Math.round(deg / 45) % 8];

function ThoughtCard({ t }: { t: Thought }) {
  return (
    <article className={'thought ' + t.source}>
      <header>
        <span className="trigger">{t.trigger_label}</span>
        <span className="where">{t.street}</span>
        <time>{t.time}</time>
      </header>
      {t.trigger !== 'low_battery' && t.saw && <blockquote>“{t.saw}”</blockquote>}
      {t.classifier && <div className="sensor-line">classifier <b>{t.classifier}</b> · lidar gap <b>{t.gap} m</b></div>}
      <p className="analysis">{t.analysis}</p>
      <div className="decision-row">
        <span className={'action ' + t.action}>{t.action_label}</span>
        {t.detail && <span className="detail">{t.detail}</span>}
        {t.shared && <span className="shared"><Radio size={11} /> shared with fleet</span>}
      </div>
      {t.radio && <div className="radio"><Radio size={11} /> “{t.radio}”</div>}
      <footer>
        <span className={'source ' + t.source}>
          {t.source === 'ai' ? <><Brain size={11} /> {t.model} · {(t.latency_ms / 1000).toFixed(1)} s</> : <><Cpu size={11} /> Reflex rules</>}
        </span>
        <span className={'outcome' + (t.outcome ? '' : ' pending')}>→ {t.outcome ?? 'in progress'}</span>
      </footer>
      {t.note && <div className="note"><ShieldAlert size={11} /> {t.note}</div>}
    </article>
  );
}

type Props = {
  robot: Robot; ai: FleetState['ai']; busy: boolean; onLowBattery: (id: string) => void;
  onPlanRoute: (id: string) => void; onStartRoute: (id: string) => void;
};

export default function BrainPanel({ robot: r, ai, busy, onLowBattery, onPlanRoute, onStartRoute }: Props) {
  const cam = r.sensors.camera;
  const lidar = r.sensors.lidar;
  const next = r.stops[0];
  const gapRatio = lidar ? Math.min(1, lidar.free_gap_m / 1.5) : 0;
  return (
    <section className="panel brain-panel" id="brain">
      <div className="panel-heading">
        <div className="heading-title">
          <Brain size={18} />
          <h2>Robot brain</h2>
          <span className="robot-tag" style={{ '--c': r.color } as React.CSSProperties}>{r.id} · {r.name}</span>
          <span className={'status-pill ' + r.status}><i className="dot" />{r.status}{r.wait_left !== null ? ` · ${r.wait_left}s` : ''}</span>
        </div>
        <div className="brain-actions">
          {r.status === 'planned' && <button className="button primary small" disabled={busy} onClick={() => onStartRoute(r.id)}><Play size={12} />Start route</button>}
          <button className="button secondary small" disabled={busy} onClick={() => onPlanRoute(r.id)}><Route size={12} />{r.mission ? 'Edit route' : 'Plan route'}</button>
        </div>
        <span className={'brain-mode ' + (ai.available ? 'ai' : 'reflex')} title={ai.reason}>
          {ai.available ? <><Brain size={12} /> AI agent · {ai.model}</> : <><Cpu size={12} /> Reflex rules · AI offline</>}
        </span>
      </div>
      <div className="brain-grid">
        <div className="sensors">
          <div className="sensor-title">LIVE SENSORS</div>
          <div className="sensor"><MapPin size={14} /><div><span>Map position</span><b>{r.street}</b><small>heading {compass(r.sensors.heading)} · {r.distance} m driven</small></div></div>
          <div className="sensor"><Satellite size={14} /><div><span>GPS</span><b>{r.sensors.gps ? `${r.sensors.gps[0].toFixed(5)}, ${r.sensors.gps[1].toFixed(5)}` : '—'}</b><small>±{r.sensors.gps_accuracy_m ?? 3} m accuracy</small></div></div>
          <div className={'sensor camera' + (cam ? ' alert' : '')}>
            <Camera size={14} />
            <div>
              <span>Front camera · 35 m</span>
              {cam ? <>
                <b>Object {cam.distance_m} m ahead</b>
                <p>“{cam.description}”</p>
                <div className="classifier"><span>classifier: {cam.classifier}</span><i style={{ width: `${cam.confidence * 100}%` }} /><em>{Math.round(cam.confidence * 100)}%</em></div>
              </> : <b className="clear">Clear</b>}
            </div>
          </div>
          <div className={'sensor' + (lidar ? ' alert' : '')}>
            <Radar size={14} />
            <div>
              <span>Lidar</span>
              {lidar ? <>
                <b>Gap {lidar.free_gap_m} m · robot needs {(lidar.robot_width_m + 0.1).toFixed(1)} m</b>
                <div className="gap-bar"><i style={{ width: `${gapRatio * 100}%` }} className={lidar.free_gap_m >= lidar.robot_width_m + 0.1 ? 'fits' : ''} /><u style={{ left: `${((lidar.robot_width_m + 0.1) / 1.5) * 100}%` }} /></div>
                <small>{lidar.moving_objects ? 'Moving objects tracked' : 'Static obstacle'}</small>
              </> : <b className="clear">No obstacle in range</b>}
            </div>
          </div>
          <div className="sensor"><Package size={14} /><div><span>Mission</span><b>{r.mission ? `Drawn route · ${r.mission.points.filter((p) => p.done).length}/${r.mission.points.length} points · ${r.mission.state}` : `${r.load.length}/${r.capacity} parcels on board`}</b><small>{next ? `${next.kind === 'waypoint' ? 'Route point' : next.kind === 'pickup' ? `Pick up #${next.order}` : `Drop off #${next.order}`} · ${next.place} · ${next.metres} m` : r.status === 'idle' ? 'Docked, waiting for orders' : 'Heading to the hub'}</small></div></div>
          <div className="sensor battery">
            <BatteryLow size={14} />
            <div>
              <span>Battery</span>
              <div className="battery-bar"><i style={{ width: `${r.battery}%` }} className={r.battery < 25 ? 'low' : ''} /></div>
              <small>{r.battery.toFixed(0)}%</small>
            </div>
          </div>
          <button className="button secondary small" disabled={busy || r.status === 'charging'} onClick={() => onLowBattery(r.id)}><BatteryLow size={13} />Simulate low battery</button>
        </div>
        <div className="thoughts">
          <div className="sensor-title">DECISIONS · SENSE → THINK → ACT</div>
          {r.status === 'thinking' && (
            <article className="thought thinking-card">
              <header><span className="trigger">Thinking…</span><span className="where">{r.street}</span></header>
              {cam && <blockquote>“{cam.description}”</blockquote>}
              <p className="analysis">{ai.available ? `${ai.model} is weighing waiting, passing, detours and the fleet's reports.` : 'Reflex rules are deciding.'}</p>
            </article>
          )}
          {r.thoughts.length === 0 && r.status !== 'thinking' && (
            <div className="empty-thoughts">
              <Brain size={26} />
              <b>No decisions yet</b>
              <p>Pick an obstacle type above the map and click on {r.id}'s dashed route. It only finds out when its camera sees it, then it decides on its own.</p>
            </div>
          )}
          {r.thoughts.map((t) => <ThoughtCard key={t.id} t={t} />)}
        </div>
      </div>
    </section>
  );
}
