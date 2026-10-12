#!/usr/bin/env python3
"""Render every asserted Turtle triple into one offline interactive graph.

Run with backend/.venv/bin/python infra/render-ontology.py from smart-operator.
Requires rdflib and the bundled docs/ontology-graph/vis-network.min.js.
"""
import json
from pathlib import Path

from rdflib import BNode, Graph, Literal, RDF, OWL
from rdflib.compare import to_canonical_graph

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'smart_factory_v2_modular_3_final_updated.ttl'
OUTPUT = ROOT / 'docs' / 'ontology-graph'


def main():
    original = Graph().parse(SOURCE, format='turtle')
    graph = to_canonical_graph(original)
    terms = sorted(set(graph.subjects()) | set(graph.objects()), key=lambda t: t.n3())
    ids = {term: index for index, term in enumerate(terms)}

    def label(term):
        if isinstance(term, Literal):
            return str(term)
        if isinstance(term, BNode):
            return '_:' + str(term)
        return original.namespace_manager.normalizeUri(term)

    nodes = []
    for term in terms:
        types = set(graph.objects(term, RDF.type))
        group = ('literal' if isinstance(term, Literal) else
                 'blank' if isinstance(term, BNode) else
                 'class' if OWL.Class in types else
                 'property' if types & {OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty, RDF.Property} else
                 'individual' if OWL.NamedIndividual in types else 'resource')
        full = label(term)
        nodes.append(dict(id=ids[term], label=full if len(full) <= 65 else full[:62] + '…',
                          fullLabel=full, term=term.n3(), group=group))
    edges = [dict(id=i, **{'from': ids[s], 'to': ids[o]}, label=label(p), predicate=str(p))
             for i, (s, p, o) in enumerate(sorted(graph, key=lambda t: tuple(v.n3() for v in t)))]
    data = dict(source=SOURCE.name, triples=len(graph), nodes=nodes, edges=edges,
                namespaces={prefix: str(uri) for prefix, uri in original.namespaces()})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'ontology-graph.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    template = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Complete smart factory ontology</title>
<style>
*{box-sizing:border-box}body{margin:0;font:14px system-ui;color:#182338;background:#f6f8fc}header{padding:16px 22px;background:#fff;border-bottom:1px solid #dbe2ec}h1{font-size:21px;margin:0 0 6px}p{margin:6px 0}button,input,select{font:inherit;padding:7px;border:1px solid #b5c1d3;border-radius:5px;background:white}button{cursor:pointer}.controls{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}main{display:flex;height:calc(100vh - 155px);min-height:400px}#graph{flex:1;min-width:0}aside{width:310px;overflow:auto;padding:16px;background:white;border-left:1px solid #dbe2ec}#details{white-space:pre-wrap;overflow-wrap:anywhere;font:12px ui-monospace,monospace}.legend span{display:inline-block;margin:4px 10px 4px 0}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px}@media(max-width:700px){main{height:75vh}aside{width:210px}header{padding:10px}}
</style>
<header><h1>Complete smart factory ontology</h1><p id="counts"></p><div class="controls"><input id="search" aria-label="Search RDF terms" placeholder="Search any RDF term"><select id="matches" aria-label="Search results"><option>Search results</option></select><button id="fit">Fit all</button><button id="labels">Hide edge labels</button><button id="physics">Resume layout</button><button id="export">Export PNG</button></div><p id="status">Laying out the complete graph…</p></header>
<main><div id="graph"></div><aside><b>One graph · all asserted triples</b><p>Scroll to zoom; drag to pan or move a node. Click a node to inspect every incoming and outgoing triple. Search selects a node while keeping the full graph present.</p><div class="legend" id="legend"></div><p>Shared RDF literal values appear once, with every relationship retained. Prefixes abbreviate full IRIs. No inferred triples are added.</p><div id="details">Select a node or relationship.</div></aside></main>
<script>__LIBRARY__</script>
<script>
const data=__DATA__;
const colors={class:'#7c63d5',property:'#e5a238',individual:'#3e90d5',resource:'#4bae91',literal:'#c4cedc',blank:'#d774a2'};
document.getElementById('counts').textContent=`${data.source} · ${data.nodes.length.toLocaleString()} nodes · ${data.triples.toLocaleString()} triples · ${new Set(data.edges.map(e=>e.predicate)).size} predicates`;
for(const [kind,color] of Object.entries(colors)){const s=document.createElement('span');s.innerHTML=`<i class="dot" style="background:${color}"></i>${kind}`;document.getElementById('legend').append(s)}
const nodes=new vis.DataSet(data.nodes.map(n=>({...n,color:colors[n.group],shape:n.group==='literal'?'box':'dot',size:n.group==='class'?17:9})));
const edges=new vis.DataSet(data.edges);
const network=new vis.Network(document.getElementById('graph'),{nodes,edges},{nodes:{font:{size:11},borderWidth:1},edges:{arrows:{to:{enabled:true,scaleFactor:.4}},font:{size:9,align:'middle'},color:{color:'#aab5c6',highlight:'#e55d48'},smooth:false,width:.6},layout:{randomSeed:42,improvedLayout:false},physics:{solver:'barnesHut',barnesHut:{gravitationalConstant:-6500,springLength:150,springConstant:.025,avoidOverlap:.3},stabilization:{iterations:100}},interaction:{hover:false,hideEdgesOnDrag:true,keyboard:true}});
let physics=true,labels=true;
function stop(){physics=false;network.setOptions({physics:{enabled:false}});document.getElementById('physics').textContent='Resume layout';document.getElementById('status').textContent='All nodes and triples are present. Layout paused for inspection.'}
network.once('stabilizationIterationsDone',()=>{stop();network.fit()});
document.getElementById('fit').onclick=()=>network.fit({animation:true});
document.getElementById('physics').onclick=()=>{physics=!physics;network.setOptions({physics:{enabled:physics}});document.getElementById('physics').textContent=physics?'Pause layout':'Resume layout'};
document.getElementById('labels').onclick=()=>{labels=!labels;edges.update(data.edges.map(e=>({id:e.id,label:labels?e.label:''})));document.getElementById('labels').textContent=labels?'Hide edge labels':'Show edge labels'};
const details=document.getElementById('details');
function inspect(id){const n=data.nodes[id],links=data.edges.filter(e=>e.from===id||e.to===id);details.textContent=n.term+'\n\n'+links.length+' incident triples\n\n'+links.map(e=>data.nodes[e.from].term+'\n  <'+e.predicate+'>\n  '+data.nodes[e.to].term).join('\n\n')}
network.on('click',p=>{if(p.nodes.length)inspect(p.nodes[0]);else if(p.edges.length){const e=data.edges[p.edges[0]];details.textContent=data.nodes[e.from].term+'\n<'+e.predicate+'>\n'+data.nodes[e.to].term}});
const matches=document.getElementById('matches');document.getElementById('search').oninput=e=>{const q=e.target.value.trim().toLowerCase();matches.replaceChildren();const hits=q?data.nodes.filter(n=>(n.fullLabel+' '+n.term).toLowerCase().includes(q)):[];const first=document.createElement('option');first.textContent=hits.length+' matches';first.value='';matches.append(first);for(const n of hits){const o=document.createElement('option');o.value=n.id;o.textContent=n.fullLabel;matches.append(o)}};
matches.onchange=()=>{if(matches.value==='')return;const id=Number(matches.value);network.selectNodes([id]);network.focus(id,{scale:1.3,animation:true});inspect(id)};
document.getElementById('export').onclick=()=>{network.redraw();const a=document.createElement('a');a.download='ontology-graph.png';a.href=document.querySelector('#graph canvas').toDataURL('image/png');a.click()};
</script></html>'''
    # Escape less-than signs so RDF literals cannot terminate the script element.
    payload = json.dumps(data).replace('<', '\\u003c')
    library = (OUTPUT / 'vis-network.min.js').read_text(encoding='utf-8')
    (OUTPUT / 'ontology-graph.html').write_text(template.replace('__LIBRARY__', library).replace('__DATA__', payload), encoding='utf-8')
    assert len(edges) == len(original)
    assert {n['term'] for n in nodes} == {t.n3() for t in terms}
    print(f'Created {OUTPUT / "ontology-graph.html"}: {len(nodes)} nodes, {len(edges)} triples')


if __name__ == '__main__':
    main()
