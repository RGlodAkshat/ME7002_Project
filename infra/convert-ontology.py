#!/usr/bin/env python3
"""Generate a validated portable configuration from a local Turtle source."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.platform_rdf import convert_turtle

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
specification = convert_turtle(args.source.read_text())
args.destination.write_text(json.dumps(specification, indent=2) + "\n")
print(f"Generated validated configuration: {len(specification['entities'])} definitions, {len(specification['rdf']['triples'])} source RDF triples.")
