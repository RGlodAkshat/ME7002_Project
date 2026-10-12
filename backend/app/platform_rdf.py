"""Lossless Turtle context plus an explicit executable lab-ontology projection.

RDF is retained, not treated as a source of arbitrary executable Python or OWL
inferences. Only declared product/BOM/route semantics are projected into tasks.
"""
import json
import math

from rdflib import BNode, Graph as RDFGraph, Literal, Namespace
from rdflib.compare import to_canonical_graph
from rdflib.namespace import RDF, RDFS

from .platform_configuration import CORE_TYPES, SEMANTICS, PERSONNEL_SEMANTICS, validate_specification

MATERIAL = Namespace("http://smartfactory.lab/ontology/materials#")
METHOD = Namespace("http://smartfactory.lab/ontology/methods#")
MACHINE = Namespace("http://smartfactory.lab/ontology/machines#")


def _term(term):
    if isinstance(term, Literal):
        result = {"kind": "literal", "value": str(term)}
        if term.datatype:
            result["datatype"] = str(term.datatype)
        if term.language:
            result["language"] = term.language
        return result
    return {"kind": "bnode" if isinstance(term, BNode) else "iri", "value": str(term)}


def _identifier(term):
    return str(term).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def convert_turtle(text: str) -> dict:
    """Parse local Turtle without dereferencing imports; return portable config.

    ValueError means the RDF or its supported executable projection is invalid.
    Namespace declarations and all triples, including unmapped semantics, remain
    available in ``rdf`` for inspection/export and order snapshot provenance.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Turtle source must be nonempty text")
    source = RDFGraph()
    try:
        source.parse(data=text, format="turtle")
    except Exception as exc:
        raise ValueError("Invalid Turtle syntax") from exc
    canonical = to_canonical_graph(source)
    triples = sorted(
        [{"subject": _term(s), "predicate": _term(p), "object": _term(o)} for s, p, o in canonical],
        key=lambda row: json.dumps(row, sort_keys=True),
    )
    spec = {
        "schema_version": "1.0",
        "environment": {"id": "smart-factory-lab", "name": "Smart Factory Lab"},
        "ontology": {"entity_types": sorted(CORE_TYPES | {"workstation", "personnel_role", "skill", "qualification"}),
                     "relation_types": [{"id": name, "from_types": sorted(ends[0]), "to_types": sorted(ends[1])}
                                        for name, ends in sorted((SEMANTICS | PERSONNEL_SEMANTICS).items())]},
        "entities": [], "relationships": [], "constraints": [],
        "rdf": {"format": "rdf-triples-v1", "namespaces": {str(p): str(u) for p, u in source.namespaces()},
                "triples": triples, "projection": "smartfactory-lab-v1"},
    }
    identifiers = set()

    def value(node, predicate, default=None):
        values = list(source.objects(node, predicate))
        if len(values) > 1:
            raise ValueError(f"{_identifier(node)} has multiple {_identifier(predicate)} values")
        return values[0] if values else default

    def name(node):
        return str(value(node, RDFS.label, _identifier(node)))

    def entity(identifier, kind, label, properties=None, iri=None):
        if identifier in identifiers:
            raise ValueError(f"Ambiguous projected identifier: {identifier}")
        identifiers.add(identifier)
        props = properties or {}
        if iri:
            props["rdf_iri"] = str(iri)
        spec["entities"].append({"id": identifier, "type": kind, "name": label, "properties": props})

    def link(kind, origin, target, properties=None):
        spec["relationships"].append({"id": f"rdf-link-{len(spec['relationships']) + 1}",
                                      "type": kind, "source": origin, "target": target, "properties": properties or {}})

    entity("SmartFactoryLab", "plant", "Smart Factory Lab")
    entity("role-operator", "personnel_role", "Manufacturing operator", {"auth_role": "operator", "source": "platform-personnel-extension"})
    workstations = sorted(set(source.subjects(RDF.type, MACHINE.Workstation)), key=str)
    for workstation in workstations:
        wid = _identifier(workstation)
        entity(wid, "workstation", str(value(workstation, MACHINE.humanLabel, name(workstation))),
               {"operation_id": str(value(workstation, MACHINE.hasOperationID, "")),
                "station_type": str(value(workstation, MACHINE.hasStationType, "")),
                "operational": value(workstation, METHOD.isOperational, Literal(True)).toPython()}, workstation)
    active_workstations = sorted({value(step, METHOD.assignedToWorkstation) for product in source.subjects(RDF.type, MATERIAL.Product)
                                  for step in source.objects(product, MATERIAL.hasRouteStep)}, key=str)
    for workstation in active_workstations:
        wid = _identifier(workstation)
        label = str(value(workstation, MACHINE.humanLabel, name(workstation)))
        entity(f"skill-{wid}", "skill", f"{label} skill", {"workstation_id": wid, "source": "platform-personnel-extension"})
        entity(f"qualification-{wid}", "qualification", f"Qualified for {label}", {
            "workstation_id": wid, "source": "platform-personnel-extension",
            "description": "An administrator confirms local training and authorizes this operator for the configured process."})
        link("qualification_grants_skill", f"qualification-{wid}", f"skill-{wid}")
        link("role_allows_qualification", "role-operator", f"qualification-{wid}")

    machines = sorted(set(source.subjects(MACHINE.hasMachineID, None)), key=str)
    for machine in machines:
        mid = _identifier(machine)
        table = value(machine, MACHINE.hasTelemetryTable)
        main_program = value(machine, MACHINE.mainProgramPattern)
        programs = []
        for route_step in source.subjects(METHOD.assignedToMachine, machine):
            for program in source.subjects(MACHINE.requiredAtStep, route_step):
                if (program, RDF.type, MACHINE.SubCode) in source:
                    programs.append((int(value(program, MACHINE.executionOrder, 0)), str(value(program, MACHINE.hasProgramCode))))
        subprograms = [code for _, code in sorted(set(programs))]
        completion = {"kind": "manual_review"}
        if main_program and subprograms:
            completion = {"kind": "program_sequence", "status": "Running", "subprograms": subprograms,
                          "main_program": str(main_program), "program_column": "prog"}
        elif mid == "MC10":
            completion = {"kind": "falling_edge", "column": "Conveyor1_ON"}
        properties = {"workstation_id": _identifier(value(machine, MACHINE.servedByWorkstation, "")),
                      "machine_type": str(value(machine, MACHINE.hasMachineType, "")),
                      "initial_status": "available" if value(machine, METHOD.isOperational, Literal(True)).toPython() else "offline",
                      "telemetry": {"table": str(value(table, MACHINE.hasTableName, _identifier(table))) if table else f"telemetry_{mid}",
                                    "timestamp_column": "ts" if main_program else "Timestamp",
                                    "completion": completion}}
        if main_program:
            properties["telemetry"].update({"identity_column": "machine_id", "identity": mid})
        entity(mid, "machine", mid, properties, machine)
        entity(f"capability-{mid}", "capability", f"Configured {mid} process")
        link("located_at", mid, "SmartFactoryLab")
        link("has_capability", mid, f"capability-{mid}")

    components = sorted(set(source.subjects(RDF.type, MATERIAL.Component)), key=str)
    for component in components:
        cid = _identifier(component)
        color = str(value(component, MATERIAL.hasComponentColour, ""))
        entity(f"part-{cid}", "part", name(component), iri=component)
        entity(cid, "variant", f"{color.title()} {name(component)}".strip(),
               {"color": color, "bin": "", "component_id": cid, "aliases": [cid],
                "presentation_color": "#e8bc29" if cid in {"G1", "G2", "G3", "G4", "G5"} else color}, component)
        link("variant_of", cid, f"part-{cid}")

    products = sorted(set(source.subjects(RDF.type, MATERIAL.Product)), key=str)
    if not products:
        raise ValueError("No supported product declarations found in Turtle")
    for product in products:
        pid = _identifier(product)
        color = str(value(product, MATERIAL.hasProductColour, ""))
        entity(pid, "product", str(value(product, MATERIAL.hasProductName, name(product))),
               {"color": color, "aliases": [pid, color], "source": "TTL-defined fixed bill of materials"}, product)
        link("located_at", pid, "SmartFactoryLab")
        bom = value(product, MATERIAL.hasBOM)
        if bom is None:
            raise ValueError(f"{pid} has no BOM")
        parts = []
        for line in sorted(source.subjects(MATERIAL.partOfBOM, bom), key=str):
            component = value(line, MATERIAL.forComponent)
            quantity = float(value(line, MATERIAL.hasQuantity, 0))
            if component is None or not math.isfinite(quantity) or quantity <= 0 or not quantity.is_integer():
                raise ValueError(f"{pid}: only positive integral BOM quantities are supported")
            cid = _identifier(component)
            parts.append(cid)
            link("has_slot", pid, f"part-{cid}", {"slot_id": cid, "quantity": int(quantity), "configurable": False, "label": name(component)})
        if not parts:
            raise ValueError(f"{pid} BOM has no quantity lines")
        product_properties = next(item for item in spec["entities"] if item["id"] == pid)["properties"]
        product_properties["visual"] = _lab_visuals(parts)
        product_properties["visual_source"] = "illustrative lab-reference presentation; not CAD or manufacturing dimensions"
        path_id = f"route-{pid}"
        entity(path_id, "path", f"{pid} configured route")
        link("uses_path", pid, path_id)
        steps = sorted(source.objects(product, MATERIAL.hasRouteStep), key=lambda step: int(value(step, METHOD.hasOpSeq, 0)))
        for step in steps:
            sid = _identifier(step)
            workstation = value(step, METHOD.assignedToWorkstation)
            machine = value(step, METHOD.assignedToMachine)
            wid = _identifier(workstation)
            mid = _identifier(machine) if machine else None
            seq = int(value(step, METHOD.hasOpSeq, 0))
            label = str(value(workstation, MACHINE.humanLabel, name(workstation)))
            properties = {"kind": "machine" if machine else "manual",
                          "workstation_id": wid, "operation_sequence": seq,
                          "processing_time_seconds": float(value(step, METHOD.hasProcessingTimeSeconds, 0)),
                          "source_machine_id": mid, "detected_by_tags": sorted(_identifier(tag) for tag in source.objects(step, METHOD.detectedByTag))}
            if machine:
                properties["execution_mode"] = "observed"
            entity(sid, "stage", f"{wid} · {label}", properties, step)
            link("requires_skill", sid, f"skill-{wid}")
            link("requires_qualification", sid, f"qualification-{wid}")
            link("has_stage", path_id, sid)
            next_step = value(step, METHOD.nextStep)
            if next_step:
                link("precedes", sid, _identifier(next_step))
            if mid:
                link("requires_capability", sid, f"capability-{mid}")
            instructions = _instructions(wid, mid)
            if mid:
                # Open observation before any physical cycle; preparation and
                # physical work remain separate configurable guidance phases.
                count = 6 if wid in {"WS2", "WS3"} else 1
                instructions["preparation_instructions"] = instructions["instructions"][:count]
                instructions["instructions"] = instructions["instructions"][count:] + [
                    "When this order's complete operation is physically finished, submit evidence for specialist review. If database signals are incomplete, a trained specialist must confirm completion; Online alone is not proof."]
            guidance_id = f"guidance-{sid}"
            entity(guidance_id, "guidance", f"{pid} {wid} instructions", instructions)
            link("uses_guidance", sid, guidance_id)
            if not machine:
                for cid in parts:
                    link("consumes", sid, f"part-{cid}", {"slot_id": cid})
            elif wid in {"WS2", "WS3"}:
                # The poster and configured CNC subprogram sequences operate on
                # G1..G5. This is a guidance/BOM association, not unit-level RFID
                # provenance or a claim that a raw row identifies a physical gear.
                for cid in parts:
                    if cid in {"G1", "G2", "G3", "G4", "G5"}:
                        link("consumes", sid, f"part-{cid}", {"slot_id": cid})
            # All physical stages permit an explicit specialist review fallback.
            # Existing CNC publishers can drop subprograms and report only Online,
            # so strict program rules must never force fabricated completion.
            verification_id = f"verification-{sid}"
            entity(verification_id, "verification", f"{wid} process review", {
                "provider": "human", "instructions": "Compare the photo with this order's configured bill of materials and stage instructions. Reject missing or incorrect components; do not infer equipment safety or batch completion from a photo alone. For a machine stage, a trained specialist must confirm this order's complete batch was processed before approval.",
                "reference_images": [], "min_confidence": 80})
            link("uses_verification", sid, verification_id)
    errors = validate_specification(spec)
    if errors:
        raise ValueError("Invalid projected configuration: " + "; ".join(errors))
    return spec


def _lab_visuals(parts):
    """Illustrative hand-powered fan geometry, selected entirely by BOM slots."""
    roles = {prefix: next((part for part in parts if part.startswith(prefix)), None)
             for prefix in ("Cl", "Cu", "Bl", "H", "P1", "P2")}
    if not all(roles.values()) or not {"G1", "G2", "G3", "G4", "G5"} <= set(parts):
        return []
    result = []

    def primitive(slot, kind, position, scale, rotation=None):
        result.append({"slot_id": slot, "primitive": kind, "position": position,
                       "scale": scale, "rotation": rotation or [0, 0, 0]})

    # Open rails suggest the elongated perforated casing without hiding the
    # gear train behind a solid opaque slab. Measurements are drawing units.
    for role, depth in (("Cl", -0.19), ("Cu", 0.19)):
        slot = roles[role]
        for height in (-0.48, 0.48):
            primitive(slot, "box", [-0.25, height, depth], [4.1, 0.12, 0.13])
        for end in (-2.25, 1.75):
            primitive(slot, "box", [end, 0, depth], [0.12, 0.96, 0.13])
    gear_centers = [-1.65, -1.18, -0.57, 0.19, 1.12]
    gear_radii = [0.20, 0.27, 0.34, 0.42, 0.50]
    for index, (center, radius) in enumerate(zip(gear_centers, gear_radii), 1):
        slot = f"G{index}"
        primitive(slot, "cylinder", [center, 0, 0], [radius * 2, 0.16, radius * 2], [math.pi / 2, 0, 0])
        for tooth in range(12):
            angle = tooth * math.tau / 12
            primitive(slot, "box", [center + radius * math.cos(angle), radius * math.sin(angle), 0],
                      [radius * 0.28, radius * 0.24, 0.16], [0, 0, angle])
    # One blade assembly contains eight illustrative vanes, not eight BOM parts.
    blade = roles["Bl"]
    primitive(blade, "cylinder", [1.12, 0, 0.52], [0.34, 0.15, 0.34], [math.pi / 2, 0, 0])
    for vane in range(8):
        angle = vane * math.tau / 8
        primitive(blade, "box", [1.12 + 0.72 * math.cos(angle), 0.72 * math.sin(angle), 0.52],
                  [1.02, 0.24, 0.07], [0, 0, angle])
    handle = roles["H"]
    primitive(handle, "cylinder", [-1.65, 0, 0.53], [0.14, 0.65, 0.14], [math.pi / 2, 0, 0])
    primitive(handle, "box", [-1.65, -0.33, 0.81], [0.14, 0.66, 0.14])
    primitive(handle, "cylinder", [-1.65, -0.65, 0.96], [0.20, 0.38, 0.20], [math.pi / 2, 0, 0])
    primitive(roles["P1"], "cylinder", [-1.18, 0, 0.07], [0.09, 0.65, 0.09], [math.pi / 2, 0, 0])
    primitive(roles["P2"], "cylinder", [1.12, 0, 0.17], [0.13, 0.80, 0.13], [math.pi / 2, 0, 0])
    return result


def _instructions(workstation, machine):
    """Reference-poster guidance, deliberately separate from telemetry matching."""
    if workstation == "WS1":
        return {"instructions": ["Prepare the labeled tray for {product.name} at {workstation.name}. Identify its order/tracking tag and keep it with the tray.",
                                 "Use the configured quantities; stop and request review if the physical parts sheet differs.",
                                 "Place components in their labeled tray positions and capture the complete kit for review."],
                "part_instructions": ["Collect {part.quantity} × {part.name} ({part.slot_id}) from the matching labeled container. Verify its label and color before placing it in the tray."],
                "completion_instructions": ["After approval, follow the next assignment. Next operation: {next.stage.name}. Destination: {next.machine.name}."]}
    if workstation in {"WS2", "WS3"}:
        displayed = {"MC1": "MILL_MAIN.MPF", "MC2": "TURN_MAIN.MPF", "MC3": "O2000", "MC4": "O5000"}.get(machine, "the approved program")
        return {"instructions": ["Take the tagged tray with all five gears to {machine.name} at {workstation.name}.",
                                 "Scan this machine's RFID tag.",
                                 "Wait for the trolley's green indication. Stop if the indication is red.",
                                 f"The reference poster shows {displayed}. Before operating, have the lab supervisor confirm the currently approved program; do not run a program solely because it appears in a photograph.",
                                 ("On the Siemens HMI, use Program Manager and the Part Program list to select the supervisor-approved program. Confirm it is active before starting a cycle." if machine in {"MC1", "MC2"} else "On the Fanuc panel, use PROG and MAIN PROG to select the supervisor-approved main program. Confirm the displayed program and MEM mode before starting a cycle."),
                                 "Start observation in this interface when the assigned batch is ready, before its first physical cycle. This interface does not send CNC start or stop commands.",
                                 "Load Gear 1 using the approved fixture procedure.",
                                 "Press the machine's physical CYCLE START button. Keep clear of the guarded work area.",
                                 "Wait for the physical cycle to finish, then move Gear 1 to the finished area of the tray using the approved procedure.",
                                 "Repeat the approved loading and cycle procedure for G2, G3, G4 and G5, one gear at a time. Keep completed and unprocessed gears separate."],
                "completion_instructions": ["Wait for verified process completion for this batch. A live connection alone does not prove that all five gears were processed.",
                                            "Confirm all five gears are accounted for. After approval, follow the next assignment. Next operation: {next.stage.name}. Destination: {next.machine.name}."]}
    guidance = {
        "WS4": ["At WS4, perform manual assembly for {product.name} using this order's selected components and the local assembly reference.",
                "Check gear placement, casing alignment, handle and blade orientation before submitting an assembly photo. Keep the tracking tag with the batch."],
        "WS5": ["At WS5, prepare the assembled unit for the configured feeder/pressing setup. Attach the order's matching block tracking chip.",
                "Verify the block/product identity before loading {machine.name}. Operate the equipment only using the local approved procedure.",
                "Capture the completed setup for review; raw station levels alone are not proof that this order completed."],
        "WS6": ["Take the tagged product to the assigned small-pin press {machine.name}. Confirm the selected pin and product identity.",
                "Follow the local fixture and pressing procedure; keep clear of moving tooling. Submit evidence of the completed small-pin operation for review."],
        "WS7": ["Take the tagged product to the assigned big-pin press {machine.name}. Confirm this order's product, pin and machine assignment.",
                "Follow the approved local pressing procedure and submit the completed operation for review. Keep the tracking block attached for the next step."],
        "WS9": ["At WS9, perform final assembly for {product.name}. Account for all configured components and check casing, pins, handle and blade seating.",
                "Carry out the lab-approved functional check and capture a complete product photo. Request review for defects or missing parts.",
                                 "Follow the assigned final-assembly procedure. Do not add or bypass a machine operation on your own."]}
    instructions = guidance.get(workstation, [f"Follow the locally approved {workstation} procedure for {{product.name}} and obtain review before proceeding."])
    if machine:
        instructions = ["Take the tagged product to {machine.name} at {workstation.name}. Confirm that this is the machine assigned to this order before loading it.", *instructions]
    result = {"instructions": instructions}
    if workstation != "WS9":
        result["completion_instructions"] = ["After approval, follow the next assignment. Next operation: {next.stage.name}. Destination: {next.machine.name}."]
    return result
