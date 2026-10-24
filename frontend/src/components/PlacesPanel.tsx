import { useState } from 'react';
import { Eraser, MapPin, Plus, Trash2, X } from 'lucide-react';
import type { Order, Place } from '../types';

type PanelProps = { places: Place[]; orders: Order[]; adding: boolean; busy: boolean; onAdd: () => void; onEdit: (id: string) => void; onClear: () => void };

export function PlacesPanel({ places, orders, adding, busy, onAdd, onEdit, onClear }: PanelProps) {
  const used = new Set(orders.filter((o) => o.status !== 'delivered').flatMap((o) => [o.pickup, o.dropoff]));
  // Your own points first, then pickups, then drop-offs.
  const sorted = [...places].sort((a, b) =>
    Number(b.kind === 'custom point') - Number(a.kind === 'custom point') || a.role.localeCompare(b.role) * -1 || a.name.localeCompare(b.name));
  return (
    <section className="panel places-panel">
      <div className="panel-heading">
        <div className="heading-title"><MapPin size={17} /><h2>Points</h2><span className="count">{places.length}</span></div>
        <div className="places-actions">
          <button className="rb-clear" disabled={busy || !places.length} onClick={onClear} title="Delete every point that no unfinished order uses"><Eraser size={12} />Clear all</button>
          <button className={'add-button' + (adding ? ' armed' : '')} aria-label="Add a point on the map" title="Add a point on the map" onClick={onAdd}><Plus size={17} /></button>
        </div>
      </div>
      {adding && <p className="footnote">Click on the map where the new point should be.</p>}
      <div className="place-list">
        {sorted.map((p) => (
          <button key={p.id} className="place-row" onClick={() => onEdit(p.id)} title="Rename, change type or delete">
            <span className={'place-pin ' + p.role + ' active' + (p.kind === 'custom point' ? ' custom' : '')}>{p.role === 'pickup' ? 'P' : 'D'}</span>
            <div><b>{p.name}</b><span>{p.id} · {p.kind}{used.has(p.id) ? ' · in an open order' : ''}</span></div>
          </button>
        ))}
      </div>
    </section>
  );
}

type ModalProps = {
  place?: Place;                 // editing an existing point; absent when creating one
  fixedRole?: 'pickup' | 'dropoff';   // creating a point for a specific step of a new order
  busy: boolean;
  onSave: (name: string, role: 'pickup' | 'dropoff') => void;
  onDelete?: () => void;
  onClose: () => void;
};

export function PlaceModal({ place, fixedRole, busy, onSave, onDelete, onClose }: ModalProps) {
  const [name, setName] = useState(place?.name ?? '');
  const [role, setRole] = useState<'pickup' | 'dropoff'>(place?.role ?? fixedRole ?? 'dropoff');
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal panel" role="dialog" aria-modal="true" aria-label={place ? 'Edit point' : 'New point'} onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => { e.preventDefault(); if (name.trim()) onSave(name.trim(), role); }}>
        <div className="panel-heading"><h2>{place ? `Edit ${place.id}` : 'New point'}</h2><button type="button" aria-label="Close" onClick={onClose}><X size={18} /></button></div>
        <p>{place ? `${place.kind}. A point used by an unfinished order can be renamed, but not deleted or switched to another type.` : 'The point snaps to the nearest street corner so robots can reach it.'}</p>
        <label>Name<input autoFocus value={name} maxLength={40} onChange={(e) => setName(e.target.value)} placeholder="e.g. Hackathon stand" /></label>
        <label>Type
          <select value={role} disabled={!!fixedRole} onChange={(e) => setRole(e.target.value as 'pickup' | 'dropoff')}>
            <option value="pickup">Pickup: robots collect parcels here</option>
            <option value="dropoff">Drop-off: robots deliver here</option>
          </select>
        </label>
        <button className="button primary" disabled={busy || !name.trim()}><MapPin size={15} />{place ? 'Save changes' : 'Add point'}</button>
        {onDelete && <button type="button" className="button danger" disabled={busy} onClick={onDelete}><Trash2 size={15} />Delete point</button>}
      </form>
    </div>
  );
}
