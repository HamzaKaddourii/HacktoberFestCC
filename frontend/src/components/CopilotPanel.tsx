import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Send, ShieldCheck, Sparkles } from 'lucide-react';
import { api } from '../api';
import type { FleetState } from '../types';

type Message = { role: 'user' | 'assistant' | 'system'; text: string };
const SUGGESTIONS = ['Why did the last robot change its route?', 'Summarize the fleet status.', 'Make order 2 urgent.'];

export default function CopilotPanel({ ai }: { ai: FleetState['ai'] }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  // Scroll the chat box itself, never the page.
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [messages, busy]);

  const send = async (text = input) => {
    if (!text.trim() || busy) return;
    setInput('');
    setMessages((m) => [...m, { role: 'user', text }]);
    setBusy(true);
    try {
      const r = await api<{ available: boolean; message: string }>('/ai/chat', { message: text });
      setMessages((m) => [...m, { role: r.available ? 'assistant' : 'system', text: r.message }]);
    } catch (e) {
      setMessages((m) => [...m, { role: 'system', text: (e as Error).message }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel assistant-panel">
      <div className="panel-heading">
        <div className="heading-title"><Sparkles size={17} /><h2>Dispatcher copilot</h2></div>
        <i className={ai.available ? 'dot' : 'dot offline'} />
      </div>
      <div className={'ai-status ' + (ai.available ? '' : 'unavailable')}>
        <span>{ai.available ? `CONNECTED · ${ai.model.toUpperCase()}` : 'AI UNAVAILABLE'}</span>
        <p>{ai.available ? 'Talk to the fleet server: add orders, change priorities, close streets, ask why.' : ai.reason}</p>
      </div>
      <div className="chat-messages" ref={box}>
        {messages.length === 0 ? (
          <div className="chat-intro">
            <div className="ai-orb"><Sparkles size={23} /></div>
            <h3>Robots decide on the street.<br />You steer the fleet.</h3>
            <div className="suggestions">
              {SUGGESTIONS.map((t) => <button key={t} onClick={() => send(t)} disabled={busy}>{t}<ArrowRight size={13} /></button>)}
            </div>
          </div>
        ) : messages.map((m, i) => (
          <div className={'chat-message ' + m.role} key={i}>
            <span>{m.role === 'user' ? 'YOU' : m.role === 'system' ? 'SYSTEM' : ai.model.toUpperCase()}</span>
            <p>{m.text}</p>
          </div>
        ))}
        {busy && <div className="thinking">The copilot is reading the fleet state…</div>}
      </div>
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input aria-label="Message the copilot" placeholder="Ask or instruct the dispatcher…" value={input} onChange={(e) => setInput(e.target.value)} maxLength={2000} />
        <button aria-label="Send message" disabled={busy || !input.trim()}><Send size={16} /></button>
      </form>
      <p className="assistant-footnote"><ShieldCheck size={11} />Every instruction is validated against the map before it is applied</p>
    </section>
  );
}
