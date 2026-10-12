from pathlib import Path

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL

from app.platform_configuration import Graph as ConfigurationGraph, validate_specification
from app.platform_rdf import convert_turtle

SOURCE = Path(__file__).resolve().parents[2] / "smart_factory_v2_modular_3_final_updated.ttl"


@pytest.fixture(scope="module")
def specification():
    return convert_turtle(SOURCE.read_text())


def test_lossless_rdf_and_valid_projection(specification):
    original = Graph().parse(SOURCE, format="turtle")
    assert len(specification["rdf"]["triples"]) == len(original)
    terms = specification["rdf"]["triples"]
    assert any(row["object"].get("datatype") for row in terms)
    assert any(row["object"]["value"] == str(OWL.Class) for row in terms)
    reconstructed = Graph()
    def term(data):
        if data["kind"] == "literal":
            return Literal(data["value"], datatype=data.get("datatype"), lang=data.get("language"))
        return BNode(data["value"]) if data["kind"] == "bnode" else URIRef(data["value"])
    for row in terms:
        reconstructed.add(tuple(term(row[key]) for key in ("subject", "predicate", "object")))
    assert isomorphic(original, reconstructed)
    assert validate_specification(specification) == []


def test_routes_bom_and_authoritative_programs(specification):
    graph = ConfigurationGraph(specification)
    assert {entity["id"] for entity in graph.entities.values() if entity["type"] == "product"} == {"PR1", "PR2", "PR3", "PR4"}
    for product in ("PR1", "PR2", "PR3", "PR4"):
        stages = graph.ordered_stages(f"route-{product}")
        assert len(stages) == 8
        assert [stage["properties"]["workstation_id"] for stage in stages] == ["WS1", "WS2", "WS3", "WS4", "WS5", "WS6", "WS7", "WS9"]
        assert len(graph.slots(product)) == 11
        assert all(slot["quantity"] == 1 and not slot["configurable"] for slot in graph.slots(product))
    assert graph.entity("MC2")["properties"]["telemetry"]["completion"]["main_program"] == "MILLMAIN"
    assert graph.entity("MC3")["properties"]["telemetry"]["completion"]["subprograms"] == ["O2001", "O2002", "O2003", "O2004", "O2005"]
    assert graph.entity("MC10")["properties"]["initial_status"] == "offline"
    assert graph.entity("RS-PR3-6")["properties"]["source_machine_id"] == "MC7"
    assert graph.entity("RS-PR2-7")["properties"]["source_machine_id"] == "MC9"


def test_observation_only_and_guidance_kept_separate(specification):
    graph = ConfigurationGraph(specification)
    stages = [e for e in graph.entities.values() if e["type"] == "stage"]
    assert all(e["properties"].get("execution_mode") == "observed" for e in stages if e["properties"]["kind"] == "machine")
    properties = graph.entity("guidance-RS-PR1-3")["properties"]
    instruction = " ".join(properties["instructions"] + properties["preparation_instructions"])
    assert "TURN_MAIN.MPF" in instruction
    assert "does not send CNC start or stop commands" in instruction
    for mid in ("MC5", "MC6", "MC7", "MC8", "MC9"):
        assert graph.entity(mid)["properties"]["telemetry"]["completion"]["kind"] == "manual_review"
        telemetry = graph.entity(mid)["properties"]["telemetry"]
        assert telemetry["table"] == f"telemetry_{mid}"
        assert telemetry["timestamp_column"] == "Timestamp"
        assert "identity_column" not in telemetry and "identity" not in telemetry
    assert graph.related("RS-PR1-5", "uses_verification")[0]["properties"]["provider"] == "human"
    assert graph.related("RS-PR1-2", "uses_verification")[0]["properties"]["provider"] == "human"


def test_invalid_source_is_rejected():
    for text in ("", "not turtle!", "@prefix x: <https://example.org/> . x:s x:p x:o ."):
        with pytest.raises(ValueError):
            convert_turtle(text)


def test_typed_literals_and_namespaces_survive(specification):
    rows = specification["rdf"]["triples"]
    assert any(row["object"] == {"kind": "literal", "value": "false", "datatype": "http://www.w3.org/2001/XMLSchema#boolean"} for row in rows)
    assert specification["rdf"]["namespaces"]["sfmatl"] == "http://smartfactory.lab/ontology/materials#"
    assert convert_turtle(SOURCE.read_text()) == specification


def test_invalid_bom_quantity_rejected():
    text = SOURCE.read_text().replace("sfmatl:hasQuantity 1.0", "sfmatl:hasQuantity 1.5", 1)
    with pytest.raises(ValueError, match="integral BOM"):
        convert_turtle(text)


def test_illustrative_geometry_uses_actual_bom_and_preserves_source_colors(specification):
    graph = ConfigurationGraph(specification)
    for product in ("PR1", "PR2", "PR3", "PR4"):
        properties = graph.entity(product)["properties"]
        slots = {slot["id"] for slot in graph.slots(product)}
        assert {descriptor["slot_id"] for descriptor in properties["visual"]} == slots
        assert all(descriptor["primitive"] in {"box", "cylinder"} for descriptor in properties["visual"])
        assert "not CAD or manufacturing dimensions" in properties["visual_source"]
    # Reference display does not falsely add an RDF hasComponentColour fact.
    assert graph.entity("G1")["properties"]["color"] == ""
    assert graph.entity("G1")["properties"]["presentation_color"] == "#e8bc29"
    for stage_id in ("RS-PR1-2", "RS-PR1-3"):
        assert {link["properties"]["slot_id"] for link in graph.outgoing(stage_id, "consumes")} == {"G1", "G2", "G3", "G4", "G5"}
