import { useEffect, useMemo, useState } from 'react';
import { api } from './api';
import { Button, Card, Empty, Icon, Loading, PageHeader, Status } from './components';
import type { GatewaySettings, Machine, Operator, Order, Verification } from './types';

type Tab = 'floor' | 'orders' | 'reviews' | 'settings';

export function SupervisorPage({ refreshKey, notify }: { refreshKey: number; notify: (message: string, kind?: 'success' | 'error') => void }) {
  const [tab, setTab] = useState<Tab>('floor');
  const [machines, setMachines] = useState<Machine[]>([]);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [verifications, setVerifications] = useState<Verification[]>([]);
  const [gateway, setGateway] = useState<GatewaySettings>({ host: 'mock-devices', port: 9002, protocol: 'http', use_mock: true });
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [reviewReason, setReviewReason] = useState<Record<string, string>>({});

  const load = async () => {
    setLoading(true);
    const results = await Promise.allSettled([api.getMachines(), api.getOperators(), api.getOrders(), api.getVerifications(), api.getGatewaySettings()]);
    if (results[0].status === 'fulfilled') setMachines(results[0].value);
    if (results[1].status === 'fulfilled') setOperators(results[1].value);
    if (results[2].status === 'fulfilled') setOrders(results[2].value);
    if (results[3].status === 'fulfilled') setVerifications(results[3].value);
    if (results[4].status === 'fulfilled') setGateway(results[4].value);
    const failed = results.filter(result => result.status === 'rejected').length;
    if (failed) notify(`${failed} supervisor data source${failed > 1 ? 's are' : ' is'} unavailable.`, 'error');
    setLoading(false);
  };
  useEffect(() => { load(); }, [refreshKey]);

  const setMachineStatus = async (machine: Machine, status: string) => {
    setBusy(`machine-${machine.id}`);
    try { await api.setMachineStatus(machine.id, status); notify(`${machine.name} is now ${status}.`, 'success'); await load(); }
    catch (error) { notify((error as Error).message, 'error'); } finally { setBusy(''); }
  };
  const completeMachine = async (machine: Machine) => {
    setBusy(`machine-${machine.id}`);
    try { await api.mockMachineComplete(machine.id); notify(`Completion event sent for ${machine.name}.`, 'success'); await load(); }
    catch (error) { notify((error as Error).message, 'error'); } finally { setBusy(''); }
  };
  const toggleOperator = async (operator: Operator) => {
    setBusy(`operator-${operator.id}`);
    try { await api.setOperatorAvailability(operator.id, operator.available === false); notify(`${operator.name}'s availability was updated.`, 'success'); await load(); }
    catch (error) { notify((error as Error).message, 'error'); } finally { setBusy(''); }
  };
  const review = async (item: Verification, outcome: 'approve' | 'reject') => {
    setBusy(`review-${item.id}`);
    try { await api.reviewVerification(item.id, outcome, reviewReason[item.id] || 'Reviewed by supervisor'); notify(`Verification ${outcome === 'approve' ? 'approved' : 'rejected'}.`, 'success'); await load(); }
    catch (error) { notify((error as Error).message, 'error'); } finally { setBusy(''); }
  };
  const saveGateway = async () => {
    setBusy('gateway-save');
    try { const saved = await api.updateGatewaySettings(gateway); setGateway(saved); notify('Machine gateway settings saved.', 'success'); }
    catch (error) { notify((error as Error).message, 'error'); } finally { setBusy(''); }
  };
  const testGateway = async () => {
    setBusy('gateway-test'); setTestResult(null);
    try { const result = await api.testGateway(); const ok = Boolean(result.reachable ?? result.ok ?? result.success ?? result.status === 'connected'); setTestResult({ ok, text: result.error ?? result.message ?? `${result.status ?? (ok ? 'Connected' : 'Connection failed')}${result.latency_ms ? ` · ${result.latency_ms} ms` : ''}` }); }
    catch (error) { setTestResult({ ok: false, text: (error as Error).message }); } finally { setBusy(''); }
  };

  const activeOrders = useMemo(() => orders.filter(item => !['completed', 'cancelled'].includes(item.status.toLowerCase())), [orders]);
  const unavailableMachines = useMemo(() => machines.filter(item => !['available', 'idle', 'online'].includes(item.status.toLowerCase())), [machines]);

  return <>
    <PageHeader eyebrow="Control room" title="Keep production moving." description="Monitor the floor, intervene in exceptions, and test every integration from one place." action={<Button variant="secondary" icon="refresh" onClick={load}>Refresh floor</Button>}/>
    <div className="metrics"><Card><span className="metric-icon metric-icon--green"><Icon name="box"/></span><div><strong>{activeOrders.length}</strong><span>Active orders</span></div></Card><Card><span className="metric-icon metric-icon--amber"><Icon name="alert"/></span><div><strong>{verifications.length}</strong><span>Awaiting review</span></div></Card><Card><span className="metric-icon metric-icon--blue"><Icon name="worker"/></span><div><strong>{operators.filter(item => item.available !== false).length}/{operators.length}</strong><span>Operators available</span></div></Card><Card><span className="metric-icon metric-icon--red"><Icon name="machine"/></span><div><strong>{unavailableMachines.length}</strong><span>Machine exceptions</span></div></Card></div>
    <nav className="subnav" aria-label="Supervisor views">{([['floor', 'Live floor'], ['orders', 'Orders'], ['reviews', `Manual review${verifications.length ? ` (${verifications.length})` : ''}`], ['settings', 'Gateway settings']] as [Tab, string][]).map(([key, label]) => <button className={tab === key ? 'active' : ''} aria-current={tab === key ? 'page' : undefined} onClick={() => setTab(key)} key={key}>{label}</button>)}</nav>
    {loading ? <Card><Loading/></Card> : <>
      {tab === 'floor' && <div className="supervisor-grid"><Card><div className="section-heading"><div><p className="eyebrow">Resources</p><h2>Machines</h2></div></div>{machines.length ? <div className="machine-list">{machines.map(machine => <article className="machine-row" key={machine.id}><span className="machine-row__icon"><Icon name="machine"/></span><div><div className="machine-row__title"><h3>{machine.name}</h3><Status value={machine.status}/></div><p>{machine.capabilities?.join(' · ') || machine.adapter || 'Manufacturing resource'}{machine.current_task_id ? ` · Task #${machine.current_task_id}` : ''}</p></div><div className="machine-row__actions"><select aria-label={`${machine.name} status`} value={machine.status} onChange={event => setMachineStatus(machine, event.target.value)} disabled={busy === `machine-${machine.id}`}><option value="available">Available</option><option value="down">Down</option><option value="maintenance">Maintenance</option></select><Button variant="ghost" onClick={() => completeMachine(machine)} disabled={busy === `machine-${machine.id}`}>Simulate completion</Button></div></article>)}</div> : <Empty icon="machine" title="No machines registered" body="Machine adapters will appear here once connected."/>}</Card><Card><div className="section-heading"><div><p className="eyebrow">People</p><h2>Operator availability</h2></div></div>{operators.length ? <div className="people-list">{operators.map(operator => <article key={operator.id}><span className="avatar">{operator.name.split(' ').map(part => part[0]).slice(0, 2).join('')}</span><div><h3>{operator.name}</h3><p>{operator.skills?.join(' · ') || 'General operations'}</p></div><label className="switch"><input type="checkbox" checked={operator.available !== false} onChange={() => toggleOperator(operator)} disabled={busy === `operator-${operator.id}`}/><span/><em>{operator.available !== false ? 'Available' : 'Unavailable'}</em></label></article>)}</div> : <Empty icon="worker" title="No operators" body="Operators will appear after demo data is loaded."/>}</Card></div>}
      {tab === 'orders' && <Card><div className="section-heading"><div><p className="eyebrow">Production</p><h2>Order workflows</h2></div></div>{orders.length ? <div className="order-table"><div className="order-table__head"><span>Order</span><span>Configuration</span><span>Current step</span><span>Progress</span><span>Status</span></div>{orders.map(order => { const completed = order.tasks?.filter(task => task.status === 'completed').length ?? 0; const progress = order.progress ?? (order.tasks?.length ? Math.round(completed / order.tasks.length * 100) : 0); const current = order.current_step ?? order.tasks?.find(task => task.status !== 'completed')?.name ?? 'Awaiting workflow'; return <article key={order.id}><span data-label="Order"><b>#{order.id}</b><small>{order.customer_name || 'Demo customer'}</small></span><span data-label="Configuration">{order.configuration?.color || 'Standard'} fan</span><span data-label="Current step">{current}</span><span data-label="Progress"><span className="progress"><i style={{ width: `${Math.max(0, Math.min(100, progress))}%` }}/></span><small>{progress}%</small></span><span data-label="Status"><Status value={order.status}/></span></article>; })}</div> : <Empty title="No orders yet" body="Confirmed customer orders will appear here."/>}</Card>}
      {tab === 'reviews' && <Card><div className="section-heading"><div><p className="eyebrow">Human-in-the-loop</p><h2>Verification review</h2></div></div>{verifications.length ? <div className="review-grid">{verifications.map(item => <article className="review-card" key={item.id}>{item.evidence_url ? <img src={item.evidence_url} alt={`Evidence for task ${item.task_id}`}/> : <div className="review-card__placeholder"><Icon name="camera" size={32}/><span>Evidence image</span></div>}<div className="review-card__body"><div><span>Task #{item.task_id}</span>{item.confidence != null && <span>AI confidence {Math.round(item.confidence * (item.confidence <= 1 ? 100 : 1))}%</span>}</div><h3>{item.reason || 'Requires supervisor decision'}</h3><textarea placeholder="Add a review note" value={reviewReason[item.id] || ''} onChange={event => setReviewReason(current => ({ ...current, [item.id]: event.target.value }))}/><div><Button onClick={() => review(item, 'approve')} disabled={busy === `review-${item.id}`} icon="check">Approve</Button><Button variant="danger" onClick={() => review(item, 'reject')} disabled={busy === `review-${item.id}`} icon="alert">Reject</Button></div></div></article>)}</div> : <Empty icon="check" title="Review queue is clear" body="AI exceptions and requested human checks will appear here."/>}</Card>}
      {tab === 'settings' && <div className="settings-layout"><Card><div className="section-heading"><div><p className="eyebrow">Integration</p><h2>Machine gateway PC</h2></div><Status value={gateway.status ?? (gateway.reachable ? 'online' : gateway.use_mock ? 'mock' : 'configured')}/></div><p className="muted settings-intro">The backend connects to this single lab gateway. Operator phones and browsers never connect to manufacturing devices directly.</p><div className="settings-form"><label className="field field--grow"><span>Host or IP address</span><input value={gateway.host} onChange={event => setGateway(current => ({ ...current, host: event.target.value }))} placeholder="192.168.0.50"/></label><label className="field"><span>Port</span><input type="number" min="1" max="65535" value={gateway.port} onChange={event => setGateway(current => ({ ...current, port: Number(event.target.value) }))}/></label><label className="field"><span>Protocol</span><select value={gateway.protocol} onChange={event => setGateway(current => ({ ...current, protocol: event.target.value as 'http' }))}><option value="http">HTTP</option></select></label><label className="mock-toggle"><span><b>Use mock gateway</b><small>Route machine events through the built-in simulator.</small></span><span className="switch"><input type="checkbox" checked={gateway.use_mock} onChange={event => setGateway(current => ({ ...current, use_mock: event.target.checked }))}/><span/></span></label></div>{testResult && <div className={`connection-result ${testResult.ok ? 'success' : 'error'}`}><Icon name={testResult.ok ? 'check' : 'alert'}/><span>{testResult.text}</span></div>}<div className="settings-actions"><Button onClick={saveGateway} disabled={!gateway.host || !gateway.port || Boolean(busy)} icon="check">{busy === 'gateway-save' ? 'Saving…' : 'Save settings'}</Button><Button variant="secondary" onClick={testGateway} disabled={Boolean(busy)} icon="wifi">{busy === 'gateway-test' ? 'Testing…' : 'Test connection'}</Button></div></Card><Card className="architecture-note"><span><Icon name="wifi" size={28}/></span><h3>One stable boundary</h3><p>The gateway adapter isolates real lab protocols from workflow logic. Switch from mock to the physical PC here—no UI or workflow changes required.</p><div className="mini-flow"><span>Devices</span><i>→</i><span>Gateway PC</span><i>→</i><span>Backend</span><i>→</i><span>This browser</span></div></Card></div>}
    </>}
  </>;
}
