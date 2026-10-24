import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowRight, Ban, Bot, Brain, CircleHelp, Construction, Cpu, Download, Droplets, Eye, Footprints, LayoutDashboard,
  Map as MapIcon, Megaphone, Network, Package, Pause, Play, Radio, RotateCcw, Route, Sparkles, TriangleAlert, Truck, X,
} from 'lucide-react';
import { api, km } from './api';
import ActivityPanel from './components/ActivityPanel';
import BrainPanel from './components/BrainPanel';
import CopilotPanel from './components/CopilotPanel';
import DispatchPanel from './components/DispatchPanel';
import FleetMap from './components/FleetMap';
import FleetPanel from './components/FleetPanel';
import OrdersPanel from './components/OrdersPanel';
import type { CityMap, FleetState, LatLon } from './types';

const TOOLS = [
  { kind: 'pedestrians', label: 'Pedestrians', icon: Footprints },
  { kind: 'parked_vehicle', label: 'Parked van', icon: Truck },
  { kind: 'roadworks', label: 'Roadworks', icon: Construction },
  { kind: 'road_closure', label: 'Street closed', icon: Ban },
  { kind: 'sidewalk_obstacle', label: 'Small obstacle', icon: Package },
  { kind: 'flooding', label: 'Flooding', icon: Droplets },
];
const SPEEDS = [1, 4, 8, 16, 30];

function Metric({ icon, label, value, detail, tone }: { icon: React.ReactNode; label: string; value: React.ReactNode; detail: string; tone: string }) {
  return <div className="stat-card"><div className="stat-top"><span>{label}</span><i className={tone}>{icon}</i></div><strong>{value}</strong><p>{detail}</p></div>;
}

export default function App() {
  const [state, setState] = useState<FleetState | null>(null);
  const [map, setMap] = useState<CityMap | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(false);
  const [selected, setSelected] = useState('RM-1');
  const [autoFocus, setAutoFocus] = useState(true);
  const [armed, setArmed] = useState<string | null>(null);
  const [announced, setAnnounced] = useState(false);
  const [showGraph, setShowGraph] = useState(true);
  const [help, setHelp] = useState(false);
  const mutation = useRef(false);
  const version = useRef(0);
  const lastThought = useRef(0);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        if (!mutation.current) {
          const v = version.current;
          const s = await api<FleetState>('/state');
          if (!stopped && !mutation.current && v === version.current) {
            setState(s);
            setOnline(true);
          }
        }
      } catch {
        if (!stopped) setOnline(false);
      } finally {
        if (!stopped) timer = setTimeout(poll, 250);
      }
    };
    poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (online && !map) api<CityMap>('/map').then((m) => { setMap(m); setError(''); }).catch(() => setError('Backend unavailable. Start FastAPI on port 8000.'));
  }, [online, map]);

  // Follow the action: when any robot starts thinking or makes a new decision, show its brain.
  useEffect(() => {
    if (!state || !autoFocus) return;
    const thinking = state.robots.find((r) => r.status === 'thinking');
    const newest = state.robots.flatMap((r) => r.thoughts.slice(0, 1)).sort((a, b) => b.id - a.id)[0];
    if (thinking && thinking.id !== selected) setSelected(thinking.id);
    else if (newest && newest.id > lastThought.current) {
      lastThought.current = newest.id;
      setSelected(newest.robot);
    }
  }, [state, autoFocus, selected]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setArmed(null);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const action = useCallback(async (url: string, body: unknown = {}, method?: string) => {
    if (mutation.current) return;
    mutation.current = true;
    version.current++;
    setBusy(true);
    setError('');
    try {
      setState(await api<FleetState>(url, body, method));
      setOnline(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  }, []);

  const place = (p: LatLon) => {
    if (!armed) return;
    action('/hazards', { lat: p[0], lon: p[1], kind: armed, announced });
  };

  const exportMission = () => {
    if (!state) return;
    const blob = new Blob([JSON.stringify({ simulation: true, city: map?.name, exported_at: new Date().toISOString(), ...state }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'routemind-mission.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const m = state?.metrics;
  const robot = state?.robots.find((r) => r.id === selected) ?? state?.robots[0];
  const tool = TOOLS.find((t) => t.kind === armed);

  return (
    <div className="app-shell">
      <aside className="rail">
        <div className="brand-mark"><Route size={25} /></div>
        <div className="rail-links">
          <button aria-label="Overview" title="Overview" className="active" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}><LayoutDashboard size={21} /></button>
          <button aria-label="City map" title="City map" onClick={() => scrollTo('map-panel')}><MapIcon size={21} /></button>
          <button aria-label="Robot brain" title="Robot brain" onClick={() => scrollTo('brain')}><Brain size={21} /></button>
        </div>
        <button title="Demo guide" aria-label="Demo guide" onClick={() => setHelp(true)}><CircleHelp size={21} /></button>
        <div className="avatar">RM</div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <a className="wordmark" href="/">RouteMind <span>AI</span></a>
          <span className="divider" />
          <span className="breadcrumb">Fleet control · {map?.name ?? '…'}</span>
          <div className="header-right">
            <span className="demo-badge">SIMULATION</span>
            {state && <span className={'brain-mode ' + (state.ai.available ? 'ai' : 'reflex')} title={state.ai.reason}>{state.ai.available ? <><Brain size={12} /> Robot brains: {state.ai.model}</> : <><Cpu size={12} /> Robot brains: reflex rules</>}</span>}
            <span className="connection"><i className={online ? 'dot' : 'dot offline'} />{online ? 'System online' : 'Connecting'}</span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">OPERATIONS / {map?.name.toUpperCase() ?? 'CITY'}</div>
              <h1>Fleet control{state && <span className="live-pill"><i className="dot" />{state.status} · {state.clock}</span>}</h1>
              <p>Sidewalk robots on real streets. Each one sees, thinks and decides for itself; the server coordinates the fleet.</p>
            </div>
            <button className="button secondary" onClick={exportMission} disabled={!state}><Download size={15} />Export mission</button>
          </div>
          {error && <div className="error" role="alert"><TriangleAlert size={17} />{error}<button aria-label="Dismiss error" onClick={() => setError('')}><X size={16} /></button></div>}
          {!state || !map || !robot || !m ? (
            <div className="loading"><Bot size={42} /><h2>Connecting to the fleet server</h2><p>Waiting for the FastAPI simulation at localhost:8000.</p></div>
          ) : <>
            <section className="stats-grid">
              <Metric icon={<Package />} label="Orders delivered" value={<>{m.delivered}<small> / {m.orders}</small></>} detail={`${m.active} robots on the street`} tone="green" />
              <Metric icon={<Route />} label="Fleet distance" value={<>{(m.fleet_distance / 1000).toFixed(2)}<small> km</small></>} detail="Real street metres (OpenStreetMap)" tone="blue" />
              <Metric icon={<Brain />} label="Robot decisions" value={<>{m.ai_decisions + m.reflex_decisions}</>}
                detail={`${m.ai_decisions} AI agent${m.avg_ai_ms ? ` (avg ${(m.avg_ai_ms / 1000).toFixed(1)} s)` : ''} · ${m.reflex_decisions} reflex`} tone="purple" />
              <Metric icon={<Radio />} label="Shared reports" value={<>{m.reports}</>} detail={`${m.reroutes} re-routes · ${m.hazards_seen} obstacles in view`} tone="amber" />
            </section>
            <div className="dashboard-grid">
              <div className="main-column">
                <section id="map-panel" className="panel map-panel">
                  <div className="panel-heading">
                    <div className="heading-title"><MapIcon size={18} /><h2>Live city map</h2><span className="subtle-tag">{map.name}</span></div>
                    <span className={'status-pill ' + state.status}><i className="dot" />{state.status}</span>
                  </div>
                  <div className="map-toolbar">
                    <div className="tools">
                      <span className="tools-label">Drop an obstacle:</span>
                      {TOOLS.map((t) => (
                        <button key={t.kind} className={'tool' + (armed === t.kind ? ' selected' : '')} onClick={() => setArmed(armed === t.kind ? null : t.kind)} title={`Place: ${t.label}`}>
                          <t.icon size={13} />{t.label}
                        </button>
                      ))}
                    </div>
                    <div className="tools">
                      <button className={'toggle' + (!announced ? ' selected' : '')} onClick={() => setAnnounced(false)} title="Robots must discover it with their sensors"><Eye size={12} />Surprise</button>
                      <button className={'toggle' + (announced ? ' selected' : '')} onClick={() => setAnnounced(true)} title="The server knows in advance and re-routes the fleet"><Megaphone size={12} />City notice</button>
                      <button className={'toggle' + (showGraph ? ' selected' : '')} onClick={() => setShowGraph(!showGraph)} title="The street graph the robots read"><Network size={12} />Road graph</button>
                    </div>
                  </div>
                  <div className="map-wrap">
                    <FleetMap map={map} state={state} selected={robot.id} onSelect={(id) => { setSelected(id); setAutoFocus(false); }}
                      armed={armed} onPlace={place} onRemoveHazard={(id) => action(`/hazards/${id}`, undefined, 'DELETE')} showGraph={showGraph} />
                    {tool && <div className="edit-hint">Click a street to place <b>{tool.label}</b> · {announced ? 'city notice: the server knows it' : 'surprise: robots must see it'} · Esc to stop</div>}
                  </div>
                  <div className="map-legend">
                    <span><i className="legend-line" />Planned route</span>
                    <span><i className="legend-cone" />Camera range</span>
                    <span><i className="legend-pin pickup">P</i>Pickup</span>
                    <span><i className="legend-pin dropoff">D</i>Drop-off</span>
                    <span><i className="legend-hz hidden" />Hidden obstacle</span>
                    <span><i className="legend-hz reported" />On fleet map</span>
                  </div>
                  <div className="simulation-controls">
                    <button className="button primary" disabled={busy || !online} onClick={() => action(state.running ? '/simulation/pause' : '/simulation/start')}>
                      {state.running ? <Pause size={16} /> : <Play size={16} />}{state.running ? 'Pause fleet' : state.time ? 'Resume fleet' : 'Start fleet'}
                    </button>
                    <div className="speed" role="group" aria-label="Simulation speed">
                      {SPEEDS.map((s) => <button key={s} className={state.speed === s ? 'selected' : ''} disabled={busy} onClick={() => action('/simulation/speed', { speed: s })}>×{s}</button>)}
                    </div>
                    <button className="button secondary" disabled={busy || !online} onClick={() => action('/dispatch')}><Sparkles size={16} />Re-optimise</button>
                    <button className="icon-button" aria-label="Reset simulation" title="Reset simulation" disabled={busy} onClick={() => { lastThought.current = 0; setAutoFocus(true); action('/simulation/reset'); }}><RotateCcw size={17} /></button>
                    <label className="follow"><input type="checkbox" checked={autoFocus} onChange={(e) => setAutoFocus(e.target.checked)} />Follow decisions</label>
                  </div>
                </section>
                <BrainPanel robot={robot} ai={state.ai} busy={busy} onLowBattery={(id) => action(`/robots/${id}/battery`, { level: 24 })} />
                <div className="lower-grid">
                  <OrdersPanel map={map} orders={state.orders} busy={busy} onSample={() => action('/mission/sample')}
                    onAdd={(pickup, dropoff, priority) => action('/orders', { pickup, dropoff, priority })}
                    onPriority={(id, priority) => action(`/orders/${id}/priority`, { priority })} />
                  <ActivityPanel events={state.events} robots={state.robots} />
                </div>
              </div>
              <aside className="right-column">
                <FleetPanel robots={state.robots} selected={robot.id} onSelect={(id) => { setSelected(id); setAutoFocus(false); }} />
                <DispatchPanel state={state} />
                <CopilotPanel ai={state.ai} />
              </aside>
            </div>
            <footer>
              <span><i className="dot" />RouteMind fleet engine <span className="footer-sep">/</span>{state.robots.length} robots · {km(m.fleet_distance)} driven · {map.attribution}, fetched {map.fetched}</span>
              <span>OpenStreetMap <b>+</b> A* <b>+</b> OR-Tools <b>+</b> onboard AI agents</span>
            </footer>
          </>}
        </main>
      </div>
      {help && (
        <div className="modal-backdrop" onClick={() => setHelp(false)}>
          <div className="modal panel" role="dialog" aria-modal="true" aria-label="Demo guide" onClick={(e) => e.stopPropagation()}>
            <div className="panel-heading"><h2>Your demo, step by step</h2><button aria-label="Close guide" onClick={() => setHelp(false)}><X size={18} /></button></div>
            <ol>
              <li>Load the sample mission: six real orders. The dispatcher splits them across the robots.</li>
              <li>Start the fleet. Every robot follows the real streets of {map?.name}.</li>
              <li>Pick <b>Roadworks</b> and click a street on a robot's dashed route, ahead of it. Nobody knows it is there.</li>
              <li>The robot's camera cone turns amber when it sees it. It stops and its brain decides; read why in Robot brain.</li>
              <li>Try <b>Pedestrians</b> (it usually waits), <b>Small obstacle</b> (passes slowly) and a <b>Parked van</b> with an urgent parcel.</li>
              <li>Switch to <b>City notice</b> for a closure the server knows in advance: the fleet re-routes before anyone sees it.</li>
              <li>Simulate low battery, or ask the copilot why a robot changed its route.</li>
            </ol>
            <p>With GEMINI_API_KEY in .env the decisions come from the AI agent; without it the reflex rules decide. Every decision says which one made it.</p>
            <button className="button primary" onClick={() => setHelp(false)}>Got it <ArrowRight size={15} /></button>
          </div>
        </div>
      )}
    </div>
  );
}
