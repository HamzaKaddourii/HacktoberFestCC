import { useState } from 'react';
import { Box, Check, ChevronRight, Plus, X, Zap } from 'lucide-react';
import type { CityMap, Order } from '../types';

type Props = {
  map: CityMap;
  orders: Order[];
  busy: boolean;
  onSample: () => void;
  onAdd: (pickup: string, dropoff: string, priority: string) => void;
  onPriority: (id: number, priority: string) => void;
};

const STATUS: Record<Order['status'], string> = { queued: 'Waiting for a robot', assigned: 'Assigned', onboard: 'On board', delivered: 'Delivered' };

export default function OrdersPanel({ map, orders, busy, onSample, onAdd, onPriority }: Props) {
  const pickups = map.places.filter((p) => p.role === 'pickup');
  const drops = map.places.filter((p) => p.role === 'dropoff');
  const [open, setOpen] = useState(false);
  const [pickup, setPickup] = useState(pickups[0]?.id ?? '');
  const [dropoff, setDropoff] = useState(drops[0]?.id ?? '');
  const [priority, setPriority] = useState('normal');
  const delivered = orders.filter((o) => o.status === 'delivered').length;
  const progress = orders.length ? Math.round((delivered / orders.length) * 100) : 0;

  return (
    <section className="panel queue-panel">
      <div className="panel-heading">
        <div className="heading-title"><Box size={17} /><h2>Orders</h2><span className="count">{orders.length - delivered}</span></div>
        <button className="add-button" aria-label="Add order" onClick={() => setOpen(true)}><Plus size={17} /></button>
      </div>
      <div className="mission-progress"><span>Delivered <b>{progress}%</b></span><div><i style={{ width: progress + '%' }} /></div></div>
      <div className="queue-list">
        {!orders.length ? (
          <div className="empty-queue">
            <Box size={28} />
            <b>No orders yet</b>
            <p>Load six real pickup → drop-off orders from {map.name}, or add your own.</p>
            <button className="button primary" disabled={busy} onClick={onSample}><Plus size={14} />Load sample mission</button>
          </div>
        ) : orders.map((o) => (
          <div className={'delivery' + (o.status === 'delivered' ? ' done' : '')} key={o.id}>
            <span className="station-badge">{o.status === 'delivered' ? <Check size={15} /> : `#${o.id}`}</span>
            <div>
              <b>{o.pickup_name} <ChevronRight size={11} /> {o.dropoff_name}</b>
              <span>{STATUS[o.status]}{o.robot && o.status !== 'delivered' ? ` · ${o.robot}` : ''}{o.delivered_at ? ` · ${o.delivered_at}` : ''}</span>
            </div>
            {o.status === 'delivered' ? <span className="delivered">Done</span> : (
              <button disabled={busy} title={o.priority === 'urgent' ? 'Make normal' : 'Make urgent'} className={'priority ' + o.priority}
                onClick={() => onPriority(o.id, o.priority === 'urgent' ? 'normal' : 'urgent')}>
                {o.priority === 'urgent' && <Zap size={10} />} {o.priority}
              </button>
            )}
          </div>
        ))}
      </div>
      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(false)}>
          <form className="modal panel" role="dialog" aria-modal="true" aria-label="Add order" onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => { e.preventDefault(); onAdd(pickup, dropoff, priority); setOpen(false); }}>
            <div className="panel-heading"><h2>New order</h2><button type="button" aria-label="Close" onClick={() => setOpen(false)}><X size={18} /></button></div>
            <p>The dispatcher assigns it to the best robot right away, even mid-mission.</p>
            <label>Pick up at<select value={pickup} onChange={(e) => setPickup(e.target.value)}>{pickups.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.kind}</option>)}</select></label>
            <label>Deliver to<select value={dropoff} onChange={(e) => setDropoff(e.target.value)}>{drops.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.kind}</option>)}</select></label>
            <label>Priority<select value={priority} onChange={(e) => setPriority(e.target.value)}><option value="normal">Normal</option><option value="urgent">Urgent: deliver as early as possible</option></select></label>
            <button className="button primary" disabled={busy}><Plus size={16} />Add & dispatch</button>
          </form>
        </div>
      )}
    </section>
  );
}
