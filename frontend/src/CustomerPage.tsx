import { FormEvent, useEffect, useMemo, useState } from 'react';
import { api } from './api';
import { Button, Card, Empty, Icon, Loading, PageHeader } from './components';
import type { Catalog, Configuration, Order } from './types';

const fallbackCatalog: Catalog = {
  name: 'Smart Fan',
  attributes: [
    { key: 'color', label: 'Finish colour', options: [
      { value: 'red', label: 'Signal Red', color_hex: '#d4463c', product_code: 'PR1', bin: 'Red component bin' },
      { value: 'green', label: 'Process Green', color_hex: '#3f7d5a', product_code: 'PR2', bin: 'Green component bin' },
      { value: 'blue', label: 'IIT Blue', color_hex: '#2855c5', product_code: 'PR3', bin: 'Blue component bin' },
      { value: 'white', label: 'Studio White', color_hex: '#deded7', product_code: 'PR4', bin: 'White component bin' },
    ]},
  ],
};

type Chat = { role: 'user' | 'assistant'; content: string };

export function CustomerPage({ notify }: { notify: (message: string, kind?: 'success' | 'error') => void }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [configuration, setConfiguration] = useState<Partial<Configuration>>({});
  const [validated, setValidated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [order, setOrder] = useState<Order | null>(null);
  const [mode, setMode] = useState<'configure' | 'chat'>('configure');
  const [chat, setChat] = useState<Chat[]>([{ role: 'assistant', content: 'Tell me which finish you prefer. I can help choose the right colour variant.' }]);
  const [message, setMessage] = useState('');
  const [chatReady, setChatReady] = useState(false);
  const [customerName, setCustomerName] = useState('Demo Customer');

  useEffect(() => {
    api.getCatalog().then(setCatalog).catch(() => {
      setCatalog(fallbackCatalog);
      notify('Catalog service unavailable — showing demo options.', 'error');
    }).finally(() => setLoading(false));
  }, []);

  const attributes = catalog?.attributes ?? [];
  const complete = Boolean(configuration.color);
  const color = useMemo(() => attributes.find(a => a.key === 'color')?.options.find(o => o.value === configuration.color), [attributes, configuration.color]);

  const select = (key: string, value: string | number) => {
    setConfiguration(prev => ({ ...prev, [key]: value }));
    setValidated(false);
  };
  const validate = async () => {
    if (!complete) return;
    setBusy(true);
    try {
      const result = await api.validateConfiguration(configuration as Configuration);
      setValidated(result.valid);
      notify(result.valid ? 'Configuration is manufacturing-ready.' : result.message || result.errors?.join(', ') || 'Configuration is not compatible.', result.valid ? 'success' : 'error');
    } catch (error) { notify((error as Error).message, 'error'); }
    finally { setBusy(false); }
  };
  const placeOrder = async () => {
    setBusy(true);
    try { const created = await api.createOrder(configuration as Configuration, customerName.trim()); setOrder(created); notify('Order released to production.', 'success'); }
    catch (error) { notify((error as Error).message, 'error'); }
    finally { setBusy(false); }
  };
  const send = async (event: FormEvent) => {
    event.preventDefault();
    if (!message.trim() || busy) return;
    const outgoing: Chat = { role: 'user', content: message.trim() };
    const history = [...chat, outgoing]; setChat(history); setMessage(''); setBusy(true);
    try {
      const response = await api.converse(outgoing.content, configuration);
      const proposed = response.proposed_configuration ?? response.configuration;
      if (proposed) { setConfiguration(prev => ({ ...prev, ...proposed })); setValidated(false); }
      setChatReady(Boolean(response.requires_confirmation));
      setChat(current => [...current, { role: 'assistant', content: response.reply ?? response.message ?? 'I updated the proposed configuration.' }]);
    } catch (error) { setChat(current => [...current, { role: 'assistant', content: `I couldn't reach the assistant: ${(error as Error).message}` }]); }
    finally { setBusy(false); }
  };
  const confirmChatOrder = async () => {
    if (!configuration.color || !customerName.trim()) return;
    setBusy(true);
    try {
      const response = await api.converse('Confirm and place this order.', configuration, true, customerName.trim());
      if (!response.order_id) throw new Error('The order service did not return an order ID.');
      setOrder({ id: response.order_id, status: 'in_progress', configuration });
      setChatReady(false);
      notify('Order released to production.', 'success');
    } catch (error) { notify((error as Error).message, 'error'); }
    finally { setBusy(false); }
  };

  if (loading) return <Loading/>;
  if (order) return <div className="success-view"><div className="success-view__mark"><Icon name="check" size={40}/></div><p className="eyebrow">Order confirmed</p><h1>Your fan is headed to the floor.</h1><p>Order <strong>#{order.id}</strong> has been converted into a manufacturing workflow. Operators will receive each task as it becomes ready.</p><div className="success-view__detail"><span>Variant <b>{color?.product_code ?? 'Standard'}</b></span><span>Colour <b>{configuration.color}</b></span><span>Status <b>{order.status || 'queued'}</b></span></div><Button variant="secondary" onClick={() => { setOrder(null); setConfiguration({}); setValidated(false); }}>Configure another fan</Button></div>;

  return <>
    <PageHeader eyebrow="Customer studio" title="Choose your fan." description="Select a finish. Every variant uses the same proven fan design and production process." action={<div className="segmented" aria-label="Configuration mode"><button className={mode === 'configure' ? 'active' : ''} onClick={() => setMode('configure')}><Icon name="settings" size={16}/> Configure</button><button className={mode === 'chat' ? 'active' : ''} onClick={() => setMode('chat')}><Icon name="chat" size={16}/> Ask AI</button></div>}/>
    <div className="customer-grid">
      <div>
        {mode === 'configure' ? <Card className="configurator">
          {attributes.length ? attributes.filter(attribute => attribute.key === 'color').map(attribute => <fieldset className="option-group" key={attribute.key}><legend><span>{attribute.label}</span><small>Select one product variant</small></legend><div className={`option-grid option-grid--${attribute.key}`}>{attribute.options.map(option => {
            const selected = configuration[attribute.key as keyof Configuration] === option.value;
            return <button className={`option ${selected ? 'selected' : ''}`} onClick={() => select(attribute.key, option.value)} type="button" key={String(option.id ?? option.value)} aria-pressed={selected}>{option.color_hex && <span className="swatch" style={{ background: option.color_hex }}/>}<span><b>{option.label}</b>{option.description && <small>{option.description}</small>}</span>{selected && <span className="option__check"><Icon name="check" size={14}/></span>}</button>;
          })}</div></fieldset>) : <Empty title="No product options" body="The catalog has no configurable attributes yet."/>}
        </Card> : <Card className="chat-panel"><div className="chat-log" aria-live="polite">{chat.map((item, index) => <div className={`chat-message chat-message--${item.role}`} key={index}><span>{item.role === 'assistant' ? 'FG' : 'You'}</span><p>{item.content}</p></div>)}{busy && <div className="chat-thinking"><i/><i/><i/></div>}</div>{chatReady && <Button onClick={confirmChatOrder} disabled={busy || !customerName.trim()} icon="cart">Confirm & place this order</Button>}<form className="chat-form" onSubmit={send}><label className="sr-only" htmlFor="chat-input">Describe your fan</label><input id="chat-input" value={message} onChange={e => setMessage(e.target.value)} placeholder="e.g. I want a blue fan"/><Button type="submit" disabled={!message.trim() || busy} icon="arrow">Send</Button></form></Card>}
      </div>
      <aside className="order-summary">
        <Card><p className="eyebrow">Your configuration</p><div className="product-visual" style={{ '--fan-color': color?.color_hex ?? '#b7bdb8' } as React.CSSProperties}><div className="fan-art"><span/><i/><i/><i/><i/><i/><i/></div></div><dl><div><dt>Product</dt><dd>{catalog?.name ?? 'Smart Fan'}</dd></div><div><dt>Variant</dt><dd>{color?.product_code ?? 'Not selected'}</dd></div><div><dt>Colour</dt><dd>{color?.label ?? 'Not selected'}</dd></div>{(color?.bom || color?.bin) && <div><dt>Kit bins</dt><dd>{color.bom?.join(', ') ?? color.bin}</dd></div>}</dl><label className="field field--compact"><span>Customer name</span><input value={customerName} onChange={event => setCustomerName(event.target.value)} /></label><div className={`readiness ${complete ? 'readiness--ready' : ''}`}><Icon name={complete ? 'check' : 'alert'} size={18}/><span>{validated ? 'Validated and ready to order' : complete ? 'Ready for compatibility check' : 'Choose a colour'}</span></div>{!validated ? <Button onClick={validate} disabled={!complete || busy} icon="check">{busy ? 'Checking…' : 'Check compatibility'}</Button> : <Button onClick={placeOrder} disabled={busy || !customerName.trim()} icon="cart">{busy ? 'Creating workflow…' : 'Confirm & place order'}</Button>}</Card>
      </aside>
    </div>
  </>;
}
