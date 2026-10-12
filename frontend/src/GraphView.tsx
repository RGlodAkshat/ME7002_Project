import { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from './components';
import type { Entity, KnowledgeGraph, Relationship } from './types';

const label = (value: string) => value.replaceAll('_', ' ');
type Point = { x: number; y: number };
type Box = Point & { width: number; height: number };

/** One canvas, with a complete grouped overview and optional focused context. */
export function GraphView({ graph, editNode, editRelationship, title = 'Knowledge graph' }: { graph: KnowledgeGraph; editNode?: (node: Entity) => void; editRelationship?: (edge: Relationship) => void; title?: string }) {
  const [search, setSearch] = useState(''); const [type, setType] = useState('');
  const [focus, setFocus] = useState(graph.nodes[0]?.id || ''); const [selectedEdge, setSelectedEdge] = useState('');
  const [contextOnly, setContextOnly] = useState(false); const [viewport, setViewport] = useState<Box | null>(null);
  const svg = useRef<SVGSVGElement>(null); const drag = useRef<{ x: number; y: number; box: Box; moved: boolean } | null>(null); const dragged = useRef(false);
  useEffect(() => { if (!graph.nodes.some(node => node.id === focus)) setFocus(graph.nodes[0]?.id || ''); }, [graph.nodes, focus]);
  const node = graph.nodes.find(item => item.id === focus); const edge = graph.relationships.find(item => item.id === selectedEdge);
  const results = useMemo(() => graph.nodes.filter(item => (!type || item.type === type) && `${item.name} ${item.id}`.toLowerCase().includes(search.toLowerCase())), [graph.nodes, search, type]);
  const matches = new Set(results.map(item => item.id));
  const connections = graph.relationships.filter(item => item.source === focus || item.target === focus);
  const connected = new Set([focus, ...connections.flatMap(item => [item.source, item.target])]);
  const displayed = useMemo(() => contextOnly ? graph.nodes.filter(item => connected.has(item.id)) : graph.nodes, [graph.nodes, contextOnly, focus, graph.relationships]);
  const layout = useMemo(() => {
    const groups = [...new Set(displayed.map(item => item.type))].sort().map(type => ({ type, nodes: displayed.filter(item => item.type === type) }));
    const columns = groups.length > 2 ? 3 : Math.max(1, groups.length); const heights = Array(columns).fill(30) as number[];
    const positions = new Map<string, Point>(); const headings: { name: string; x: number; y: number }[] = [];
    groups.sort((a, b) => b.nodes.length - a.nodes.length || a.type.localeCompare(b.type)).forEach(group => {
      const column = heights.indexOf(Math.min(...heights)); const x = column * 760 + 25; const y = heights[column];
      headings.push({ name: `${label(group.type)} · ${group.nodes.length}`, x, y });
      group.nodes.forEach((item, index) => positions.set(item.id, { x: x + 115 + (index % 3) * 235, y: y + 75 + Math.floor(index / 3) * 95 }));
      heights[column] += 75 + Math.ceil(group.nodes.length / 3) * 95;
    });
    return { positions, headings, box: { x: -10, y: -10, width: columns * 760, height: Math.max(250, ...heights) } };
  }, [displayed]);
  const box = viewport || layout.box;
  useEffect(() => { setViewport(null); }, [contextOnly]);
  const choose = (id: string) => { if (dragged.current) return; setFocus(id); setSelectedEdge(''); };
  const zoom = (factor: number) => { const width = Math.max(260, Math.min(layout.box.width * 2, box.width * factor)); const height = box.height * width / box.width; setViewport({ x: box.x + (box.width - width) / 2, y: box.y + (box.height - height) / 2, width, height }); };
  const locate = () => { const point = layout.positions.get(focus); if (!point) return; const width = Math.max(300, Math.min(700, svg.current?.clientWidth || 700)); const height = width * (svg.current?.clientHeight || 600) / (svg.current?.clientWidth || 1000); setViewport({ x: point.x - width / 2, y: point.y - height / 2, width, height }); };
  const details = edge ? edge.properties : node?.properties;
  return <section className="card graph-explorer" aria-label={title}>
    <div className="section-heading"><div><h2>{title}</h2><p className="muted">{graph.nodes.length} definitions · {graph.relationships.length} connections. The full model is shown together; select any node or connection to inspect it.</p></div></div>
    <div className="graph-filters"><label>Find a definition<input aria-label="Find a definition" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Name or identifier"/></label><label>Definition type<select aria-label="Definition type" value={type} onChange={event => setType(event.target.value)}><option value="">All types</option>{[...new Set(graph.nodes.map(item => item.type))].sort().map(item => <option key={item} value={item}>{label(item)}</option>)}</select></label></div>
    <div className="graph-controls"><Button variant="secondary" onClick={() => { setContextOnly(false); setViewport(null); }}>Fit entire model</Button><Button variant="secondary" onClick={() => zoom(0.65)}>Zoom in</Button><Button variant="secondary" onClick={() => zoom(1.5)}>Zoom out</Button><Button variant="secondary" disabled={!node} onClick={locate}>Locate selected</Button><label className="checkbox-label"><input type="checkbox" checked={contextOnly} onChange={event => { setContextOnly(event.target.checked); setSelectedEdge(''); }}/>Selected context only</label></div>
    <p className="graph-hint muted">Drag to pan. Zoom to read labels. Search filters the list and highlights matches without hiding the rest of the model.</p>
    <div className="graph-layout"><div className="graph-results" role="list" aria-label="Graph definitions">{results.slice(0, 80).map(item => <button type="button" role="listitem" key={item.id} className={focus === item.id ? 'active' : ''} onClick={() => { dragged.current = false; choose(item.id); }}><b>{item.name}</b><small>{label(item.type)}</small></button>)}{results.length > 80 && <p className="muted">Showing 80 matches. Narrow your search.</p>}{!results.length && <p>No matching definitions.</p>}</div>
      <div className="graph-canvas"><svg ref={svg} viewBox={`${box.x} ${box.y} ${box.width} ${box.height}`} role="img" aria-label="Complete manufacturing graph; drag to pan" onPointerDown={event => { if (event.button !== 0) return; dragged.current = false; drag.current = { x: event.clientX, y: event.clientY, box, moved: false }; }} onPointerMove={event => { const current = drag.current; if (!current) return; const dx = event.clientX - current.x; const dy = event.clientY - current.y; if (Math.abs(dx) + Math.abs(dy) < 5 && !current.moved) return; current.moved = true; dragged.current = true; event.currentTarget.setPointerCapture(event.pointerId); const scale = Math.max(current.box.width / event.currentTarget.clientWidth, current.box.height / event.currentTarget.clientHeight); setViewport({ ...current.box, x: current.box.x - dx * scale, y: current.box.y - dy * scale }); }} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
        <defs><marker id="graph-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#78988b"/></marker></defs>
        {layout.headings.map(item => <text key={item.name} className="graph-group-label" x={item.x} y={item.y}>{item.name}</text>)}
        {graph.relationships.filter(item => layout.positions.has(item.source) && layout.positions.has(item.target)).map(item => { const from = layout.positions.get(item.source)!; const to = layout.positions.get(item.target)!; return <g key={item.id} role="button" tabIndex={0} aria-label={`Connection ${label(item.type)} ${item.id}`} className={selectedEdge === item.id || item.source === focus || item.target === focus ? 'graph-link-focused' : 'graph-link-background'} onClick={() => { if (!dragged.current) setSelectedEdge(item.id); }} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedEdge(item.id); } }}><title>{label(item.type)}</title><line className="graph-edge-hit" x1={from.x} y1={from.y} x2={to.x} y2={to.y}/><line className={selectedEdge === item.id ? 'graph-edge selected' : 'graph-edge'} x1={from.x} y1={from.y} x2={to.x} y2={to.y} markerEnd="url(#graph-arrow)"/></g>; })}
        {displayed.map(item => { const point = layout.positions.get(item.id)!; return <g key={item.id} role="button" tabIndex={0} aria-label={`Explore ${item.name}`} className={search || type ? matches.has(item.id) ? 'graph-match' : 'graph-muted' : ''} transform={`translate(${point.x},${point.y})`} onClick={() => choose(item.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); dragged.current = false; choose(item.id); } }}><title>{item.name} ({item.type})</title><rect x="-105" y="-33" width="210" height="66" rx="12" className={item.id === focus ? 'graph-node focused' : 'graph-node'}/><text textAnchor="middle" y="-2">{item.name.length > 27 ? `${item.name.slice(0, 25)}…` : item.name}</text><text textAnchor="middle" y="18" className="graph-node-type">{label(item.type)}</text></g>; })}
      </svg></div>
    </div>
    <div className="graph-inspector"><div className="section-heading"><div><p className="eyebrow">{edge ? 'Selected connection' : label(node?.type || 'Definition')}</p><h3>{edge ? label(edge.type) : node?.name || 'No definitions'}</h3><small>{edge?.id || node?.id}</small></div>{edge && editRelationship ? <Button variant="secondary" onClick={() => editRelationship(edge)}>Edit selected connection</Button> : node && editNode ? <Button variant="secondary" onClick={() => editNode(node)}>Edit selected definition</Button> : null}</div>{edge && <p>{graph.nodes.find(item => item.id === edge.source)?.name || edge.source} → {graph.nodes.find(item => item.id === edge.target)?.name || edge.target}</p>}{details && Object.keys(details).length > 0 && <details><summary>Properties & live state</summary><pre>{JSON.stringify(details, null, 2)}</pre></details>}
      <details><summary>Connections ({connections.length})</summary><div className="graph-connections">{connections.map(item => <button type="button" key={item.id} onClick={() => setSelectedEdge(item.id)}><b>{label(item.type)}</b><span>{graph.nodes.find(value => value.id === item.source)?.name || item.source} → {graph.nodes.find(value => value.id === item.target)?.name || item.target}</span></button>)}</div></details>
    </div>
  </section>;
}
