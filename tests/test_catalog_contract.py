from __future__ import annotations

import re

from conftest import execute, source


EXPECTED_IDS = {
    "acu": "uel0001",
    "engineer": "uel0105",
    "t2_engineer": "uel0208",
    "land_factory": "ueb0101",
    "power_generator": "ueb1101",
    "power_generator_t2": "ueb1201",
    "hydrocarbon": "ueb1102",
    "mass_extractor": "ueb1103",
    "scout": "uel0101",
    "artillery": "uel0103",
    "anti_air": "uel0104",
    "lab": "uel0106",
    "tank": "uel0201",
}


def test_catalog_is_the_only_blueprint_id_authority() -> None:
    lua = execute("lua/AI/Overmind4/Catalog.lua")
    catalog = lua.globals().Catalog

    assert {role: catalog.IdFor(role) for role in EXPECTED_IDS} == EXPECTED_IDS
    assert {blueprint: catalog.RoleFor(blueprint) for role, blueprint in EXPECTED_IDS.items()} == {
        blueprint: role for role, blueprint in EXPECTED_IDS.items()
    }


def test_catalog_normalizes_case_and_fails_closed() -> None:
    lua = execute("lua/AI/Overmind4/Catalog.lua")
    catalog = lua.globals().Catalog

    assert catalog.RoleFor("UEL0201") == "tank"
    assert catalog.RoleFor("not-a-blueprint") is None
    assert catalog.RoleFor(None) is None
    assert catalog.IdFor("unknown-role") is None


def test_blueprint_literals_do_not_leak_into_policy_or_controller() -> None:
    combined = "\n".join(
        (
            source("lua/AI/Overmind4/Policy.lua"),
            source("lua/AI/Overmind4/Controller.lua"),
        )
    ).lower()

    for blueprint in EXPECTED_IDS.values():
        assert re.search(rf"\b{re.escape(blueprint)}\b", combined) is None
