"""Malformed imported graph fields must produce validation errors, never crash."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.platform_configuration import validate_specification


@pytest.fixture
def imported_specification():
    return json.loads((Path(__file__).resolve().parents[2] / "configs/examples/lab-fan.json").read_text())


@pytest.mark.parametrize("path,value", [
    (("relationships", 0, "source"), []),
    (("relationships", 0, "target"), {}),
    (("relationships", 0, "type"), []),
    (("constraints", 0, "id"), []),
    (("constraints", 0, "product_id"), {}),
    (("constraints", 0, "slots"), [["base"]]),
    (("constraints", 0, "property"), {}),
    (("entities", 0, "type"), {}),
    (("ontology", "relation_types", 0, "from_types"), [None]),
    (("gateway", "port"), True),
])
def test_invalid_import_fields_return_errors(imported_specification, path, value):
    specification = deepcopy(imported_specification)
    cursor = specification
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    assert validate_specification(specification), f"Malformed field {path} must be rejected"
