import { Network, Radio } from 'lucide-react';
import { km } from '../api';
import type { FleetState } from '../types';

function Bars({ label, optimized, greedy }: { label: string; optimized: number; greedy: number }) {
  const max = Math.max(optimized, greedy, 1);
  const gain = greedy ? ((greedy - optimized) / greedy) * 100 : 0;
  return (
    <div className="bars">
      <div className="bars-head"><span>{label}</span><b className={gain >= 0 ? 'good' : 'bad'}>{gain >= 0 ? '−' : '+'}{Math.abs(gain).toFixed(0)}%</b></div>
      <div className="bar"><span>OR-Tools</span><i style={{ width: `${(optimized / max) * 100}%` }} className="opt" /><em>{km(optimized)}</em></div>
      <div className="bar"><span>Greedy</span><i style={{ width: `${(greedy / max) * 100}%` }} /><em>{km(greedy)}</em></div>
    </div>
  );
}

export default function DispatchPanel({ state }: { state: FleetState }) {
  const plan = state.metrics.plan;
  return (
    <section className="panel dispatch-panel">
      <div className="panel-heading">
        <div className="heading-title"><Network size={17} /><h2>Dispatcher server</h2></div>
        <span className="subtle-tag">OR-Tools VRP</span>
      </div>
      {plan ? <>
        <Bars label="Fleet distance (latest plan)" optimized={plan.optimized.distance} greedy={plan.greedy.distance} />
        <Bars label="Last delivery done after" optimized={plan.optimized.makespan} greedy={plan.greedy.makespan} />
        <p className="footnote">Same open orders, robots and known obstacles. Greedy = each order goes to the robot whose route ends closest. Heuristic search, no optimality guarantee.</p>
      </> : <p className="footnote">Load a mission to see the plan comparison.</p>}
      <div className="metric-pair">
        <span>Plans <b>{state.metrics.dispatches}</b></span>
        <span>Re-routes <b>{state.metrics.reroutes}</b></span>
        <span>Robot reports <b>{state.metrics.reports}</b></span>
      </div>
      <div className="knowledge">
        <div className="sensor-title">FLEET MAP · SHARED KNOWLEDGE</div>
        {state.knowledge.length === 0 ? <p className="footnote">Nothing reported. Hidden obstacles stay unknown until a robot sees one.</p> :
          state.knowledge.map((k) => (
            <div className="report" key={k.hazard}>
              <Radio size={12} />
              <div><b>{k.message}</b><span>by {k.by} · {k.blocks ? 'blocks the street' : 'passable'} · {k.expires_in === null ? 'until cleared' : `expires in ${k.expires_in}s`}</span></div>
            </div>
          ))}
      </div>
    </section>
  );
}
