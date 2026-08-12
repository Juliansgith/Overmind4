from __future__ import annotations

from typing import Any

import pytest

from test_controller import make_harness
from test_policy import lua_value, plain


SITE_KEY = "Mass:12000:20000"
JOB_ID = f"mex:region:near:{SITE_KEY}"


def _job() -> dict[str, Any]:
    return {
        "id": JOB_ID,
        "kind": "build_mex",
        "actorToken": "11:1",
        "actorLineage": {"11": "11:1"},
        "targetKey": SITE_KEY,
        "siteKey": SITE_KEY,
        "regionKey": "region:near",
        "position": [12, 3, 20],
        "phase": "travelling",
        "retryCount": 1,
    }


def _prepare(harness: Any) -> None:
    harness.lua.execute("Policy.Decide = function() return {} end")
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(
                entityId=11,
                blueprintId="uel0105",
                canBuild={"ueb1103": True},
            )
        ]
    )
    harness.lua.globals().directorResults.macroPlan = lua_value(
        harness.lua,
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "grants": [
                {
                    "requestId": "mex-1",
                    "lane": "mex_rebuild",
                    "source": "bank",
                }
            ],
            "regions": [],
            "intents": [],
        },
    )
    harness.lua.globals().directorResults.expansionPlan = lua_value(
        harness.lua, {"jobs": [_job()], "denials": []}
    )
    harness.lua.globals().directorResults.jobLedger = lua_value(
        harness.lua, {"jobs": {JOB_ID: _job()}}
    )


@pytest.mark.parametrize("remaining", [1, 299, 300])
def test_blocked_expansion_site_is_not_reissued_during_backoff(
    remaining: int,
) -> None:
    harness = make_harness()
    _prepare(harness)
    harness.brain.tick = 100
    harness.controller.blockedSites[SITE_KEY] = 100 + remaining

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 0
    job_input = plain(harness.calls.macroUpdateJobLedger[1].snapshot)
    assert not job_input["newJobs"]


def test_expansion_site_becomes_eligible_at_exact_backoff_boundary() -> None:
    harness = make_harness()
    _prepare(harness)
    harness.brain.tick = 400
    harness.controller.blockedSites[SITE_KEY] = 400

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb1103"
    job_input = plain(harness.calls.macroUpdateJobLedger[1].snapshot)
    assert [job["siteKey"] for job in job_input["newJobs"]] == [SITE_KEY]


def test_blocked_site_does_not_prevent_an_unrelated_expansion_job() -> None:
    harness = make_harness()
    _prepare(harness)
    second = _job()
    second.update(
        {
            "id": "mex:region:far:Mass:40000:40000",
            "actorToken": "12:1",
            "actorLineage": {"12": "12:1"},
            "targetKey": "Mass:40000:40000",
            "siteKey": "Mass:40000:40000",
            "regionKey": "region:far",
            "position": [40, 3, 40],
        }
    )
    harness.brain.units[2] = harness.unit(
        entityId=12,
        blueprintId="uel0105",
        canBuild={"ueb1103": True},
    )
    harness.lua.globals().directorResults.expansionPlan = lua_value(
        harness.lua, {"jobs": [_job(), second], "denials": []}
    )
    harness.lua.globals().directorResults.jobLedger = lua_value(
        harness.lua, {"jobs": {JOB_ID: _job(), second["id"]: second}}
    )
    harness.controller.blockedSites[SITE_KEY] = 300

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert plain(harness.calls.buildMobile[1].position)[0] == 40
