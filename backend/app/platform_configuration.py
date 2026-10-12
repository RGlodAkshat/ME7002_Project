"""Validated, revisioned ontology/graph specification, shared by UI and MCP."""
from copy import deepcopy
from string import Formatter
from threading import RLock
import math

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import update

from .platform_models import Configuration, ConfigurationChange, Order, Task

STATE_LOCK = RLock()
CORE_TYPES = {"plant", "machine", "capability", "part", "variant", "product", "path", "stage", "guidance", "verification", "scrap"}
SEMANTICS = {
    "located_at": ({"machine", "product"}, {"plant"}),
    "has_capability": ({"machine"}, {"capability"}), "variant_of": ({"variant"}, {"part"}),
    "has_slot": ({"product"}, {"part"}), "uses_path": ({"product"}, {"path"}),
    "has_stage": ({"path"}, {"stage"}), "precedes": ({"stage"}, {"stage"}),
    "requires_capability": ({"stage"}, {"capability"}), "uses_guidance": ({"stage"}, {"guidance"}),
    "uses_verification": ({"stage"}, {"verification"}), "uses_scrap": ({"stage"}, {"scrap"}),
    "consumes": ({"stage"}, {"part"}),
}


class Graph:
    def __init__(self, specification: dict):
        self.spec = specification
        self.entities = {entity["id"]: entity for entity in specification["entities"]}
        self.links = specification["relationships"]

    def entity(self, entity_id: str) -> dict:
        return self.entities[entity_id]

    def related(self, source: str, relation: str) -> list[dict]:
        return [self.entity(link["target"]) for link in self.links if link["source"] == source and link["type"] == relation]

    def outgoing(self, source: str, relation: str) -> list[dict]:
        return [link for link in self.links if link["source"] == source and link["type"] == relation]

    def slots(self, product_id: str) -> list[dict]:
        slots = []
        for link in self.outgoing(product_id, "has_slot"):
            props = link.get("properties", {})
            part = self.entity(link["target"])
            variants = [self.entity(rel["source"]) for rel in self.links if rel["type"] == "variant_of" and rel["target"] == part["id"]]
            slots.append({"id": props["slot_id"], "label": props.get("label", part["name"]),
                          "quantity": props.get("quantity", 1), "configurable": props.get("configurable", True),
                          "part_id": part["id"], "variants": variants})
        return slots

    def ordered_stages(self, path_id: str) -> list[dict]:
        stages = self.related(path_id, "has_stage")
        ids = {stage["id"] for stage in stages}
        edges = [link for link in self.links if link["type"] == "precedes" and link["source"] in ids and link["target"] in ids]
        result = []
        done = set()
        while len(done) < len(ids):
            ready = [stage for stage in stages if stage["id"] not in done and all(edge["source"] in done for edge in edges if edge["target"] == stage["id"])]
            if not ready:
                raise ValueError(f"Path {path_id} contains a dependency cycle")
            result.extend(ready)
            done.update(stage["id"] for stage in ready)
        return result


def validate_specification(spec: dict) -> list[str]:
    try:
        return _validate_specification(spec)
    except (TypeError, ValueError, KeyError, AttributeError, IndexError):
        return ["Invalid specification structure: IDs must be strings and properties must use the documented types"]


def _validate_specification(spec: dict) -> list[str]:
    errors = []
    if not isinstance(spec, dict):
        return ["Specification must be an object"]
    if spec.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    environment = spec.get("environment")
    if not isinstance(environment, dict) or not all(isinstance(environment.get(key), str) and environment[key].strip() for key in ("id", "name")):
        errors.append("environment needs an id and name")
    ontology = spec.get("ontology", {})
    if not isinstance(ontology, dict):
        return errors + ["ontology must be an object"]
    types = ontology.get("entity_types", [])
    relations = ontology.get("relation_types", [])
    if not isinstance(types, list) or any(not isinstance(item, str) or not item for item in types) or len(set(types)) != len(types):
        return errors + ["entity_types must be unique nonempty strings"]
    if not CORE_TYPES <= set(types):
        errors.append("Ontology must declare the platform entity types")
    if not isinstance(relations, list) or any(not isinstance(item, dict) for item in relations):
        return errors + ["relation_types must be an array of declarations"]
    declarations = {}
    for item in relations:
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in declarations:
            errors.append("Relationship declaration IDs must be unique nonempty strings")
            continue
        declarations[identifier] = item
        for endpoint in ("from_types", "to_types"):
            values = item.get(endpoint)
            if not isinstance(values, list) or not values or any(value not in types for value in values):
                errors.append(f"{identifier}: {endpoint} must reference declared entity types")
    entities = spec.get("entities")
    links = spec.get("relationships")
    if not isinstance(entities, list) or not isinstance(links, list):
        return errors + ["entities and relationships must be arrays"]
    by_id = {}
    for entity in entities:
        if not isinstance(entity, dict):
            errors.append("Every entity must be an object")
            continue
        identifier = entity.get("id")
        if not isinstance(identifier, str) or not identifier or len(identifier) > 120 or identifier in by_id:
            errors.append("Entity IDs must be unique nonempty strings of at most 120 characters")
            continue
        by_id[identifier] = entity
        if entity.get("type") not in types:
            errors.append(f"{identifier}: unknown entity type")
        if not isinstance(entity.get("name"), str) or not entity["name"].strip() or len(entity["name"]) > 200:
            errors.append(f"{identifier}: a name of at most 200 characters is required")
        if not isinstance(entity.get("properties", {}), dict):
            errors.append(f"{identifier}: properties must be an object")
    if errors:
        return errors
    seen_links = set()
    for link in links:
        if not isinstance(link, dict):
            errors.append("Every relationship must be an object")
            continue
        identifier = link.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen_links:
            errors.append("Relationship IDs must be unique nonempty strings")
        seen_links.add(str(identifier))
        source, target = by_id.get(link.get("source")), by_id.get(link.get("target"))
        relation = declarations.get(link.get("type"))
        if not source or not target:
            errors.append(f"{identifier}: unknown source or target")
            continue
        if not relation:
            errors.append(f"{identifier}: undeclared relationship type")
            continue
        if source.get("type") not in relation.get("from_types", []) or target.get("type") not in relation.get("to_types", []):
            errors.append(f"{identifier}: endpoint types violate the ontology")
        semantics = SEMANTICS.get(link["type"])
        if semantics and (source.get("type") not in semantics[0] or target.get("type") not in semantics[1]):
            errors.append(f"{identifier}: invalid platform relationship endpoints")
        if not isinstance(link.get("properties", {}), dict):
            errors.append(f"{identifier}: properties must be an object")
    if errors:
        return errors
    graph = Graph(spec)
    for entity in entities:
        identifier, kind = entity["id"], entity["type"]
        props = entity.get("properties", {})
        if kind == "variant" and len([link for link in links if link["type"] == "variant_of" and link["source"] == identifier]) != 1:
            errors.append(f"{identifier}: each variant must belong to exactly one part")
        if kind == "variant":
            for key in ("bin", "image_url", "color"):
                if key in props and not isinstance(props[key], str):
                    errors.append(f"{identifier}: {key} must be a string")
            aliases = props.get("aliases", [])
            if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias for alias in aliases):
                errors.append(f"{identifier}: aliases must be nonempty strings")
        if kind == "stage":
            if props.get("kind") not in {"manual", "machine"}:
                errors.append(f"{identifier}: stage kind must be manual or machine")
            skills = props.get("required_skills", [])
            if not isinstance(skills, list) or any(not isinstance(skill, str) or not skill for skill in skills):
                errors.append(f"{identifier}: required_skills must be strings")
            if props.get("kind") == "machine" and not graph.related(identifier, "requires_capability"):
                errors.append(f"{identifier}: machine stages require a capability")
            guidance = graph.related(identifier, "uses_guidance")
            if not guidance or not (guidance[0].get("properties", {}).get("instructions") or guidance[0].get("properties", {}).get("part_instructions")):
                errors.append(f"{identifier}: stages require configured operator instructions")
            for relation in ("uses_guidance", "uses_verification", "uses_scrap"):
                if len(graph.related(identifier, relation)) > 1:
                    errors.append(f"{identifier}: only one {relation} relationship is supported")
        if kind in {"guidance", "verification"}:
            instructions = props.get("instructions", [])
            if kind == "verification" and isinstance(instructions, str):
                instructions = [instructions]
            if not isinstance(instructions, list) or any(not isinstance(line, str) for line in instructions):
                errors.append(f"{identifier}: instructions must be strings")
            if kind == "guidance":
                completion_instructions = props.get("completion_instructions", [])
                if not isinstance(completion_instructions, list) or any(not isinstance(line, str) for line in completion_instructions):
                    errors.append(f"{identifier}: completion_instructions must be strings")
                part_instructions = props.get("part_instructions", [])
                if not isinstance(part_instructions, list) or any(not isinstance(line, str) for line in part_instructions):
                    errors.append(f"{identifier}: part_instructions must be strings")
                else:
                    for instruction in part_instructions:
                        try:
                            for _, field, format_spec, conversion in Formatter().parse(instruction):
                                if field is not None and (field not in {"part.name", "part.quantity", "part.bin", "part.slot_id", "part.color"} or format_spec or conversion):
                                    errors.append(f"{identifier}: invalid part template placeholder")
                        except ValueError:
                            errors.append(f"{identifier}: malformed part instruction template")
        if kind == "verification":
            if props.get("provider") not in {"human", "openai"}:
                errors.append(f"{identifier}: verification provider must be human or openai")
            confidence = props.get("min_confidence", 80)
            if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 100:
                errors.append(f"{identifier}: min_confidence must be 0 to 100")
            images = props.get("reference_images", [])
            if not isinstance(images, list) or any(not isinstance(path, str) or ".." in path or path.startswith("/") for path in images):
                errors.append(f"{identifier}: reference_images must be relative reference asset names")
        if kind == "scrap":
            quantity = props.get("max_quantity", 0)
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
                errors.append(f"{identifier}: max_quantity must be a nonnegative integer")
            if not isinstance(props.get("required", False), bool):
                errors.append(f"{identifier}: required must be boolean")
            if not isinstance(props.get("reasons", []), list) or any(not isinstance(reason, str) for reason in props.get("reasons", [])):
                errors.append(f"{identifier}: reasons must be strings")
        if kind == "path":
            stages = graph.related(identifier, "has_stage")
            if not stages:
                errors.append(f"{identifier}: path needs at least one stage")
            if len({stage["id"] for stage in stages}) != len(stages):
                errors.append(f"{identifier}: duplicate stages in path")
            try:
                graph.ordered_stages(identifier)
            except ValueError as exc:
                errors.append(str(exc))
            ids = {stage["id"] for stage in stages}
            if any(link["type"] == "precedes" and link["target"] in ids and link["source"] not in ids for link in links):
                errors.append(f"{identifier}: dependencies must belong to the same path")
        if kind == "product":
            slot_links = graph.outgoing(identifier, "has_slot")
            slot_ids = []
            for link in slot_links:
                properties = link.get("properties", {})
                slot = properties.get("slot_id")
                if not isinstance(slot, str) or not slot or "." in slot or "{" in slot or "}" in slot:
                    errors.append(f"{identifier}: slot_id must be a nonempty template-safe string")
                slot_ids.append(slot)
                quantity = properties.get("quantity", 1)
                if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
                    errors.append(f"{identifier}: slot quantities must be positive integers")
                variants = [e for e in entities if e["type"] == "variant" and any(r["type"] == "variant_of" and r["source"] == e["id"] and r["target"] == link["target"] for r in links)]
                if not variants:
                    errors.append(f"{identifier}: slot {slot} has no variants")
                if properties.get("configurable", True) is False and len(variants) != 1:
                    errors.append(f"{identifier}: fixed slot {slot} must have exactly one variant")
            if len(set(slot_ids)) != len(slot_ids):
                errors.append(f"{identifier}: duplicate slot IDs")
            if not graph.outgoing(identifier, "uses_path"):
                errors.append(f"{identifier}: product needs a manufacturing path")
            visual = props.get("visual", [])
            if not isinstance(visual, list):
                errors.append(f"{identifier}: visual must be an array")
            else:
                for primitive in visual:
                    if not isinstance(primitive, dict) or primitive.get("slot_id") not in slot_ids or primitive.get("primitive") not in {"box", "cylinder", "sphere", "blade", "cone", "torus"}:
                        errors.append(f"{identifier}: visual primitive needs a known slot and supported primitive")
                        continue
                    for key in ("position", "rotation", "scale"):
                        value = primitive.get(key, [1, 1, 1] if key == "scale" else [0, 0, 0])
                        if not isinstance(value, list) or len(value) != 3 or any(not isinstance(number, (int, float)) or isinstance(number, bool) or not math.isfinite(number) or (key == "scale" and number <= 0) for number in value):
                            errors.append(f"{identifier}: visual {key} needs three finite numbers")
            if not errors:
                for link in graph.outgoing(identifier, "uses_path"):
                    conditions = link.get("properties", {}).get("conditions", {})
                    errors.extend(validate_selection_mapping(graph, identifier, conditions, "Path conditions"))
                    priority = link.get("properties", {}).get("priority", 0)
                    if not isinstance(priority, (int, float)):
                        errors.append(f"{identifier}: path priority must be numeric")
                    for stage in graph.related(link["target"], "has_stage"):
                        for consumed in graph.outgoing(stage["id"], "consumes"):
                            consumed_slot = consumed.get("properties", {}).get("slot_id")
                            if not any(slot_link["target"] == consumed["target"] and (not consumed_slot or slot_link["properties"]["slot_id"] == consumed_slot) for slot_link in slot_links):
                                errors.append(f"{stage['id']}: consumed part/slot is not in product {identifier}")
                        for guidance in graph.related(stage["id"], "uses_guidance"):
                            properties = guidance.get("properties", {})
                            for instruction in [*properties.get("instructions", []), *properties.get("completion_instructions", [])]:
                                try:
                                    for _, field, format_spec, conversion in Formatter().parse(instruction):
                                        if field is None:
                                            continue
                                        allowed = {"product.name", "parts", "machine.name"} | {f"parts.{slot}.{key}" for slot in slot_ids for key in ("name", "bin", "quantity", "color")}
                                        if field not in allowed or format_spec or conversion:
                                            errors.append(f"{guidance['id']}: unsupported template placeholder {{{field}}}")
                                except ValueError:
                                    errors.append(f"{guidance['id']}: malformed instruction template")
    constraints = spec.get("constraints", [])
    if not isinstance(constraints, list):
        errors.append("constraints must be an array")
    else:
        seen = set()
        for rule in constraints:
            if not isinstance(rule, dict):
                errors.append("Every constraint must be an object")
                continue
            if not rule.get("id") or rule["id"] in seen:
                errors.append("Constraint IDs must be unique")
            seen.add(str(rule.get("id")))
            product = by_id.get(rule.get("product_id"))
            if not product or product["type"] != "product":
                errors.append(f"{rule.get('id')}: constraint references unknown product")
                continue
            if rule.get("kind") not in {"requires", "excludes", "match_property"}:
                errors.append(f"{rule['id']}: unknown constraint kind")
            for key in ("when", "then"):
                errors.extend(validate_selection_mapping(graph, product["id"], rule.get(key, {}), rule["id"]))
            if rule.get("kind") == "requires" and not rule.get("then"):
                errors.append(f"{rule['id']}: requires must specify then selections")
            if rule.get("kind") == "excludes" and not rule.get("when"):
                errors.append(f"{rule['id']}: excludes must specify when selections")
            if rule.get("kind") == "match_property":
                slots = rule.get("slots", [])
                valid_slots = {slot["id"] for slot in graph.slots(product["id"])}
                if not isinstance(slots, list) or len(slots) < 2 or any(slot not in valid_slots for slot in slots) or not isinstance(rule.get("property"), str) or not rule["property"]:
                    errors.append(f"{rule['id']}: match_property requires known slots and a property")
    gateway = spec.get("gateway")
    if gateway is not None:
        if not isinstance(gateway, dict) or gateway.get("protocol") not in {"http", "https"} or not isinstance(gateway.get("host"), str) or not gateway["host"] or any(char in gateway["host"] for char in "/?#@") or not isinstance(gateway.get("port"), int) or isinstance(gateway.get("port"), bool) or not 1 <= gateway["port"] <= 65535:
            errors.append("gateway requires a host, port 1–65535 and http/https protocol")
    return errors


def validate_selection_mapping(graph: Graph, product_id: str, selections: dict, label: str) -> list[str]:
    if not isinstance(selections, dict):
        return [f"{label}: selections must be an object"]
    slots = {slot["id"]: slot for slot in graph.slots(product_id)}
    return [f"{label}: invalid variant {variant} for slot {slot}" for slot, variant in selections.items()
            if slot not in slots or variant not in {item["id"] for item in slots[slot]["variants"]}]


def get_configuration(db: Session) -> dict:
    row = db.get(Configuration, 1)
    return {"revision": row.revision if row else 0, "specification": deepcopy(row.specification) if row else None}


def acquire_state_lock(db: Session) -> None:
    """One database row serializes reservation transactions, also across workers."""
    db.execute(update(Configuration).where(Configuration.id == 1).values(revision=Configuration.revision))
    db.expire_all()


def apply_configuration(db: Session, specification: dict, expected_revision: int, actor=None) -> dict:
    specification = deepcopy(specification)
    for collection in ("entities", "relationships"):
        for item in specification.get(collection, []) if isinstance(specification.get(collection), list) else []:
            if isinstance(item, dict):
                item.setdefault("properties", {})
    errors = validate_specification(specification)
    if errors:
        raise HTTPException(400, "; ".join(errors))
    with STATE_LOCK:
        acquire_state_lock(db)
        wrapper = get_configuration(db)
        if wrapper["revision"] != expected_revision:
            raise HTTPException(409, "Configuration changed. Reload before applying your edits.")
        previous = wrapper["specification"]
        if previous and previous["environment"]["id"] != specification["environment"]["id"] and db.query(Order).filter(Order.status != "completed").first():
            raise HTTPException(409, "Finish active orders before replacing the manufacturing environment")
        if previous and previous.get("gateway") != specification.get("gateway") and db.query(Task).filter(Task.command_id.is_not(None), Task.machine_completed.is_(False), Task.status != "completed").first():
            raise HTTPException(409, "Wait for running machine cycles to finish before changing the gateway")
        machine_ids = {e["id"] for e in specification["entities"] if e["type"] == "machine"}
        reserved = db.query(Task).filter(Task.machine_id.is_not(None), Task.status != "completed").all()
        if any(task.machine_id not in machine_ids for task in reserved):
            raise HTTPException(409, "A machine used by an active order cannot be removed")
        result = db.execute(update(Configuration).where(Configuration.id == 1, Configuration.revision == expected_revision)
                            .values(specification=deepcopy(specification), revision=expected_revision + 1))
        if result.rowcount != 1:
            raise HTTPException(409, "Configuration changed. Reload before applying your edits.")
        db.add(ConfigurationChange(revision=expected_revision + 1, actor=actor))
        db.flush()
        from .platform_service import schedule
        schedule(db)
        db.commit()
        return get_configuration(db)
