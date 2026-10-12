# Complete ontology graph

Open `ontology-graph.html` directly in a browser. It is self-contained and works offline.

The graph contains all 3,354 asserted triples from `../../smart_factory_v2_modular_3_final_updated.ttl`, with 1,607 distinct subject/object nodes and 108 predicates represented as directed, labeled edges. Classes, properties, individuals, other resources, and literal values all appear together. Identical RDF terms share a node; literal datatypes and language tags are preserved in node details and the JSON export. No inference, filtering, or domain-level aggregation is applied.

Allow the initial layout to settle, then zoom, pan, search, and select nodes or edges to inspect full RDF terms and incident triples. Fit all restores the comprehensive view. Edge labels can be toggled for readability without removing triples. PNG export captures the current viewport; `ontology-graph.json` retains the complete graph independently of the viewport.

Regenerate from the repository root:

```sh
backend/.venv/bin/python infra/render-ontology.py
```

The generator requires RDFLib from the backend environment. The vendored vis-network 9.1.9 library retains its license header and is embedded into the generated HTML. `preview.png` is a browser screenshot of the full graph.
