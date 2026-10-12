import { useCallback, useEffect, useState } from 'react';
import { api } from './api';
import { Button, Icon, Loading } from './components';
import type { Notify, Part, Task, User } from './types';

export function OperatorPage({ user, logout, notify }: { user: User; logout: () => void; notify: Notify }) {
  const [available, setAvailable] = useState(user.available);
  const [tasks, setTasks] = useState<Task[]>([]); const [loaded, setLoaded] = useState(false); const [error, setError] = useState('');
  const [step, setStep] = useState(0); const [verification, setVerification] = useState(false); const [busy, setBusy] = useState(false);
  const [quantity, setQuantity] = useState('0'); const [reason, setReason] = useState(''); const [scrapSaved, setScrapSaved] = useState(false);
  const load = useCallback(async () => { try { const [assigned, ownSession] = await Promise.all([api.tasks(), api.me()]); setTasks(assigned); setAvailable(ownSession.user.available); setError(''); setLoaded(true); } catch (err) { setError((err as Error).message); setLoaded(true); } }, []);
  useEffect(() => { void load(); const timer = window.setInterval(load, 5000); return () => window.clearInterval(timer); }, [load]);
  const task = tasks.find(item => item.status === 'in_progress' || item.status === 'rejected') || tasks[0];
  useEffect(() => { setStep(0); setVerification(false); setQuantity('0'); setReason(''); setScrapSaved(false); }, [task?.id, task?.machine_completed]);
  const action = async (run: () => Promise<unknown>) => { setBusy(true); try { await run(); await load(); } catch (err) { notify((err as Error).message, 'error'); } finally { setBusy(false); } };
  const toggleAvailability = async () => { await action(async () => { const value = await api.availability(!available); setAvailable(value.available); }); };
  const instructions = task?.instructions || [];
  const focusedPart = task?.parts?.find(part => instructions[step]?.includes(part.name));
  const waiting = task && ['awaiting_review', 'awaiting_verification', 'paused', 'queued'].includes(task.status);
  const scrapRecorded = scrapSaved || !!task?.scrap_report;
  const canComplete = !task?.scrap?.required || scrapRecorded;
  const hasEvidence = !!task?.evidence?.length && (task.status !== 'rejected' || task.has_fresh_evidence === true);
  const upload = (file?: File) => { if (!file || !task) return; void action(() => api.evidence(task.id, file)); };
  const complete = () => { if (!task) return; void action(() => api.complete(task.id)); };
  return <main className="operator-screen">
    <header className="operator-header"><div><span className="operator-monogram">{user.name.slice(0, 1).toUpperCase()}</span><span><b>{user.name}</b><small>Work guidance</small></span></div><div className="operator-header__actions"><button className={`availability-button ${available ? 'is-available' : ''}`} disabled={busy} aria-pressed={available} onClick={toggleAvailability}><i/>{available ? 'Available' : 'Unavailable'}</button><button className="icon-button" aria-label="Sign out" onClick={logout}><Icon name="logout"/></button></div></header>
    {!loaded ? <Loading/> : error ? <div className="error-panel" role="alert"><p>{error}</p><Button onClick={load}>Retry</Button></div> : !task ? <div className="operator-wait"><div className="guidance-orb"><Icon name={available ? 'check' : 'worker'} size={60}/></div><p className="eyebrow">{available ? 'Ready when you are' : 'Taking a pause'}</p><h1>{available ? 'You’re all caught up.' : 'You’re unavailable.'}</h1><p>{available ? 'Your next operation will appear here automatically.' : 'Switch to available when you’re ready for your next operation.'}</p></div> : waiting ? <div className="operator-wait"><div className="guidance-orb"><Icon name={task.status === 'paused' ? 'alert' : 'check'} size={60}/></div><p className="eyebrow">{task.product_name}</p><h1>{task.status === 'awaiting_review' ? 'Review in progress.' : task.status === 'awaiting_verification' ? 'Checking your work.' : task.status === 'paused' ? 'Operation paused.' : 'Preparing your next operation.'}</h1><p>{task.status === 'paused' ? 'Wait for the equipment to become available. Your progress is saved.' : 'We’ll show your next instruction as soon as it’s ready.'}</p><strong>{task.name}</strong></div> : <div className="guidance-work">
      <div className="guidance-context"><p className="eyebrow">{task.product_name}</p><h2>{task.name}</h2>{task.machine_name && <span className="machine-location"><Icon name="machine"/>{task.machine_name}</span>}</div>
      {task.kind === 'machine' && task.command_id && !task.machine_completed ? <section className="machine-running"><div className="guidance-orb"><Icon name="machine" size={50}/></div><h1>Equipment is running.</h1><p>Wait for this operation to finish. Your next instruction will appear automatically.</p></section> : !instructions.length ? <div className="error-panel"><h2>Work instructions unavailable.</h2><p>Contact your administrator before proceeding with this operation.</p></div> : !verification ? <>
        <div className="step-position"><span>Instruction {step + 1} of {instructions.length}</span><div>{instructions.map((_, index) => <i className={index <= step ? 'active' : ''} key={index}/>)}</div></div>
        <h1 className="current-instruction">{instructions[step]}</h1>
        {focusedPart && <div className="focused-part operator-parts"><PartCard part={focusedPart}/></div>}
        {!!task.parts?.length && <details className="parts-disclosure"><summary>All parts for this operation <span>{task.parts.length}</span></summary><div className="operator-parts">{task.parts.map((part, index) => <PartCard part={part} key={`${part.slot_id}-${index}`}/>)}</div></details>}
        {task.status === 'rejected' && <div className="inline-error"><b>Please correct your work</b><p>{task.verification_reason || 'The previous submission was rejected. Follow the instruction and submit again.'}</p></div>}
        {step === instructions.length - 1 && task.scrap && (task.kind !== 'machine' || task.machine_completed) && <details className="scrap-section" open={!!task.scrap.required && !scrapRecorded}><summary>Record material loss {task.scrap.required ? '(required)' : '(optional)'}</summary><div className="form-grid"><label>Quantity<input type="number" min="0" max={task.scrap.max_quantity} required value={quantity} onChange={e => setQuantity(e.target.value)}/></label><label>Reason{task.scrap.reasons?.length ? <select value={reason} onChange={e => setReason(e.target.value)}><option value="">Choose a reason</option>{task.scrap.reasons.map(item => <option key={item}>{item}</option>)}</select> : <input value={reason} onChange={e => setReason(e.target.value)}/>}</label></div><Button variant="secondary" disabled={busy || Number(quantity) < 0 || (Number(quantity) > 0 && !reason)} onClick={() => action(async () => { await api.scrap(task.id, Number(quantity), reason); setScrapSaved(true); })}>Save material loss</Button>{scrapRecorded && <p className="success-note">Recorded</p>}</details>}
        <div className="guidance-actions">{step > 0 && <Button variant="ghost" onClick={() => setStep(step - 1)}>Back</Button>}{step < instructions.length - 1 ? <Button onClick={() => setStep(step + 1)} icon="arrow">Next instruction</Button> : task.kind === 'machine' && !task.machine_completed ? <Button disabled={busy} onClick={() => action(() => api.run(task.id))} icon="machine">{busy ? 'Starting…' : 'Start equipment'}</Button> : task.verification ? <Button disabled={!canComplete} onClick={() => setVerification(true)} icon="camera">Verify this operation</Button> : <Button disabled={busy || !canComplete} onClick={complete} icon="check">{busy ? 'Saving…' : 'Operation complete'}</Button>}</div>
      </> : <section className="verification-focus">
        <p className="eyebrow">Verification required</p><h1>Show your completed work.</h1>
        {Array.isArray(task.verification?.instructions) ? <ul>{task.verification.instructions.map((instruction, index) => <li key={index}>{instruction}</li>)}</ul> : <p>{task.verification?.instructions || 'Take a clear photograph of the completed operation.'}</p>}
        {task.status === 'rejected' && !task.has_fresh_evidence && <p className="inline-error">Take a new photograph after correcting your work.</p>}
        <label className={`capture-button ${busy ? 'disabled' : ''}`}><Icon name="camera" size={32}/><b>{busy ? 'Saving photograph…' : task.evidence?.length ? 'Add another photograph' : 'Take a photograph'}</b><input aria-label="Take a photograph" type="file" accept="image/*" capture="environment" disabled={busy} onChange={e => { upload(e.target.files?.[0]); e.target.value = ''; }}/></label>
        {!!task.evidence?.length && <div className="evidence-grid">{task.evidence.map(item => <a href={item.url} target="_blank" rel="noreferrer" key={item.id}><img src={item.url} alt={item.name}/></a>)}</div>}
        <div className="guidance-actions"><Button variant="ghost" onClick={() => setVerification(false)}>Back</Button><Button disabled={busy || !hasEvidence || !canComplete} onClick={complete}>{busy ? 'Submitting…' : 'Submit for verification'}</Button></div>
      </section>}
    </div>}
  </main>;
}

function PartCard({ part }: { part: Part }) { return <article><div className="part-visual">{part.image_url ? <img src={part.image_url} alt={part.name}/> : <span style={{ background: part.color || '#cad8cc' }}><Icon name="box" size={32}/></span>}</div><div><b>{part.name}</b><small>Quantity {part.quantity}</small></div>{part.bin && <strong className="bin-label"><small>BIN</small>{part.bin}</strong>}</article>; }
