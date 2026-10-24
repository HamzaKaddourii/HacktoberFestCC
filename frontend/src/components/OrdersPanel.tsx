import { Box, Check, ChevronRight, Plus, Zap } from 'lucide-react';
import type { CityMap, Order } from '../types';

type Props = {
  map: CityMap;
  orders: Order[];
  busy: boolean;
  onSample: () => void;
  onNewOrder: () => void;
  newOrderLabel: string;
  onPriority: (id: number, priority: string) => void;
};

const STATUS: Record<Order['status'], string> = { queued: 'Waiting for a robot', assigned: 'Assigned', onboard: 'On board', delivered: 'Delivered' };

export default function OrdersPanel({ map, orders, busy, onSample, onNewOrder, newOrderLabel, onPriority }: Props) {
  const delivered = orders.filter((o) => o.status === 'delivered').length;
  const progress = orders.length ? Math.round((delivered / orders.length) * 100) : 0;

  return (
    <section className="panel queue-panel">
      <div className="panel-heading">
        <div className="heading-title"><Box size={17} /><h2>Orders</h2><span className="count">{orders.length - delivered}</span></div>
        <button className="add-button" aria-label={newOrderLabel} title={newOrderLabel} onClick={onNewOrder}><Plus size={17} /></button>
      </div>
      <div className="mission-progress"><span>Delivered <b>{progress}%</b></span><div><i style={{ width: progress + '%' }} /></div></div>
      <div className="queue-list">
        {!orders.length ? (
          <div className="empty-queue">
            <Box size={28} />
            <b>No orders yet</b>
            <p>Load six real orders from {map.name}, or pick a robot and draw its route on the map.</p>
            <button className="button primary" disabled={busy} onClick={onSample}><Plus size={14} />Load sample mission</button>
            <button className="button secondary" disabled={busy} onClick={onNewOrder}><Plus size={14} />{newOrderLabel}</button>
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
    </section>
  );
}
