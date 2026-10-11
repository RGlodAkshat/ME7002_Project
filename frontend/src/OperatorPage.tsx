import { ChangeEvent, useEffect, useMemo, useState } from 'react';
import { api } from './api';
import { Button, Card, Empty, Icon, Loading, PageHeader, Status } from './components';
import type { Operator, Task } from './types';

function instructions(value?: string[] | string): string[] {
  if (Array.isArray(value)) return value;
  return value ? value.split('\n').filter(Boolean) : ['Review the work order and required components.', 'Follow the posted station safety procedure.', 'Confirm the result before completing this task.'];
}

export function OperatorPage({ refreshKey, notify }: { refreshKey: number; notify: (message: string, kind?: 'success' | 'error') => void }) {
  const [operators, setOperators] = useState<Operator[]>([]);
  const [operatorId, setOperatorId] = useState('');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [handoff, setHandoff] = useState('');

  useEffect(() => { api.getOperators().then(items => { setOperators(items); setOperatorId(current => current || String(items[0]?.id ?? '')); }).catch(error => notify((error as Error).message, 'error')); }, []);
  const load = async () => {
    if (!operatorId) { setLoading(false); return; }
    setLoading(true);
    try { const items = await api.getTasks(operatorId); setTasks(items); setSelectedId(current => items.some(item => String(item.id) === String(current)) ? current : String(items[0]?.id ?? '')); }
    catch (error) { notify((error as Error).message, 'error'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [operatorId, refreshKey]);
  const selected = useMemo(() => tasks.find(item => String(item.id) === String(selectedId)), [tasks, selectedId]);
  const action = async (kind: 'accept' | 'start' | 'complete') => {
    if (!selected) return; setBusy(true);
    try { await api.taskAction(selected.id, kind); notify(`Task ${kind === 'complete' ? 'completed' : `${kind}ed`}.`, 'success'); await load(); }
    catch (error) { notify((error as Error).message, 'error'); }
    finally { setBusy(false); }
  };
  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; if (!file || !selected) return; setBusy(true);
    try { await api.uploadEvidence(selected.id, file); notify('Evidence photo uploaded.', 'success'); await load(); }
    catch (error) { notify((error as Error).message, 'error'); }
    finally { event.target.value = ''; setBusy(false); }
  };
  const doHandoff = async () => {
    if (!selected || !handoff) return; setBusy(true);
    try { await api.handoffTask(selected.id, handoff); notify('Handoff request sent.', 'success'); setHandoff(''); await load(); }
    catch (error) { notify((error as Error).message, 'error'); }
    finally { setBusy(false); }
  };
  const verify = async () => {
    if (!selected) return; setBusy(true);
    try { await api.verifyTask(selected.id); notify('Verification started. The result will update automatically.', 'success'); await load(); }
    catch (error) { notify((error as Error).message, 'error'); }
    finally { setBusy(false); }
  };
  const availableActions = selected?.status.toLowerCase();

  return <>
    <PageHeader eyebrow="Operator station" title="Your work, clearly sequenced." description="Complete assigned tasks, capture evidence, and hand off without losing production context." action={<label className="operator-switch"><span>Working as</span><select value={operatorId} onChange={event => setOperatorId(event.target.value)}>{operators.map(operator => <option value={operator.id} key={operator.id}>{operator.name}</option>)}</select></label>}/>
    <div className="operator-layout">
      <Card className="task-rail"><div className="section-heading"><div><p className="eyebrow">Queue</p><h2>Assigned tasks</h2></div><span className="count">{tasks.length}</span></div>{loading ? <Loading/> : tasks.length ? <div className="task-list">{tasks.map((task, index) => <button key={task.id} className={`task-list__item ${String(task.id) === String(selectedId) ? 'active' : ''}`} onClick={() => setSelectedId(String(task.id))}><span className="task-list__number">{task.position ?? task.sequence ?? index + 1}</span><span><b>{task.name}</b><small>Order #{task.order_id}</small></span><Status value={task.status}/></button>)}</div> : <Empty title="Queue is clear" body="New work will appear here when dependencies are complete."/>}</Card>
      <div className="task-workspace">{selected ? <>
        <Card className="task-hero"><div className="task-hero__top"><div><div className="task-meta"><span>Order #{selected.order_id}</span>{(selected.machine_name || selected.machine?.name) && <span><Icon name="machine" size={15}/>{selected.machine_name || selected.machine?.name}</span>}</div><h2>{selected.name}</h2><p>{selected.description || 'Follow the instructions below and record completion.'}</p></div><Status value={selected.status}/></div><div className="task-actions">{['ready', 'assigned'].includes(availableActions || '') && selected.kind !== 'machine' && <Button onClick={() => action('accept')} disabled={busy} icon="check">Accept task</Button>}{['ready', 'assigned'].includes(availableActions || '') && selected.kind === 'machine' && <Button onClick={() => action('start')} disabled={busy} icon="arrow">Start machine task</Button>}{['accepted'].includes(availableActions || '') && selected.kind !== 'machine' && <Button onClick={() => action('start')} disabled={busy} icon="arrow">Start work</Button>}{['in_progress', 'started', 'rejected'].includes(availableActions || '') && selected.kind !== 'machine' && <Button onClick={() => action('complete')} disabled={busy} icon="check">{availableActions === 'rejected' ? 'Resubmit for verification' : 'Mark complete'}</Button>}{selected.kind === 'machine' && !['ready', 'assigned'].includes(availableActions || '') && <span className="machine-wait"><Icon name="machine" size={17}/> Completion is reported by the machine gateway</span>}<Button variant="ghost" onClick={load} icon="refresh">Refresh</Button></div></Card>
        <div className="operator-detail-grid"><Card><div className="section-heading"><div><p className="eyebrow">Standard work</p><h2>Step instructions</h2></div></div><ol className="instructions">{instructions(selected.instructions).map((step, index) => <li key={index}><span>{index + 1}</span><p>{step}</p></li>)}</ol></Card><div className="side-stack">
          <Card><p className="eyebrow">Verification</p><h3>{selected.requires_verification ? 'Photo evidence required' : 'Operator confirmation'}</h3><p className="muted">{selected.requires_verification ? 'Capture a clear image of the completed work. The workflow waits for approval.' : 'No image is required for this task.'}</p>{selected.requires_verification && ['assigned', 'in_progress', 'rejected'].includes(selected.status.toLowerCase()) && <label className={`upload ${busy ? 'disabled' : ''}`}><Icon name="camera" size={24}/><span><b>Capture or upload photo</b><small>JPG or PNG</small></span><input type="file" accept="image/*" capture="environment" onChange={upload} disabled={busy}/></label>}{selected.requires_verification && ['awaiting_verification', 'evidence_submitted'].includes(selected.status.toLowerCase()) && <Button variant="secondary" onClick={verify} disabled={busy} icon="check">Run verification</Button>}{selected.verification_status && <Status value={selected.verification_status}/>}</Card>
          <Card><p className="eyebrow">Handoff</p><h3>Pass work safely</h3><p className="muted">The next qualified operator receives the task with its complete history.</p><div className="handoff"><select value={handoff} onChange={event => setHandoff(event.target.value)}><option value="">Select operator</option>{operators.filter(item => String(item.id) !== String(operatorId) && item.available !== false && (!selected.required_skill || item.skills?.includes(selected.required_skill))).map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select><Button variant="secondary" onClick={doHandoff} disabled={!handoff || busy} icon="arrow">Handoff</Button></div></Card>
        </div></div>
      </> : !loading && <Card><Empty icon="worker" title="Select an assigned task" body="Choose an item from your queue to see step guidance and controls."/></Card>}</div>
    </div>
  </>;
}
