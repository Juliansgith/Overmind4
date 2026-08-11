from __future__ import annotations

import copy
import random
from typing import Any

import pytest

from adaptive_parity_helpers import (
    director_path,
    director_present,
    intent_by_id,
    invoke,
)


MODULE = "MacroDirector.lua"
GLOBAL = "MacroDirector"


def lane_request(
    lane_id: str,
    *,
    mass_drain: float,
    energy_drain: float,
    mass_cost: float,
    energy_cost: float,
    duration_ticks: int = 300,
    required: bool = False,
    optional: bool = False,
) -> dict[str, Any]:
    return {
        "id": f"{lane_id}-1",
        "lane": lane_id,
        "massDrain": mass_drain,
        "energyDrain": energy_drain,
        "massCost": mass_cost,
        "energyCost": energy_cost,
        "durationTicks": duration_ticks,
        "required": required,
        "optional": optional,
    }


def portfolio_snapshot(**updates: Any) -> dict[str, Any]:
    requests = [
        lane_request(
            "energy_recovery",
            mass_drain=0.05,
            energy_drain=0,
            mass_cost=75,
            energy_cost=0,
            required=True,
        ),
        lane_request(
            "mex_rebuild",
            mass_drain=0.3,
            energy_drain=3,
            mass_cost=36,
            energy_cost=360,
            required=True,
        ),
        lane_request(
            "reclaim",
            mass_drain=0,
            energy_drain=0,
            mass_cost=0,
            energy_cost=0,
            required=True,
        ),
        lane_request(
            "engineers",
            mass_drain=0.2,
            energy_drain=2,
            mass_cost=52,
            energy_cost=260,
        ),
        lane_request(
            "land_production",
            mass_drain=0.28,
            energy_drain=3,
            mass_cost=56,
            energy_cost=600,
            required=True,
        ),
        lane_request(
            "air_production",
            mass_drain=0.2,
            energy_drain=9,
            mass_cost=50,
            energy_cost=2250,
            required=True,
        ),
        lane_request(
            "factory_growth",
            mass_drain=0.35,
            energy_drain=4,
            mass_cost=210,
            energy_cost=2400,
            optional=True,
        ),
        lane_request(
            "tech",
            mass_drain=1.017391,
            energy_drain=7.913043,
            mass_cost=1170,
            energy_cost=9100,
            duration_ticks=1150,
            optional=True,
        ),
    ]
    snapshot: dict[str, Any] = {
        "tick": 6000,
        "mapSizeKm": 20,
        "economy": {
            "valid": True,
            "massIncome": 5,
            "energyIncome": 80,
            "massRequested": 1,
            "energyRequested": 20,
            "massStored": 700,
            "energyStored": 7000,
            "massStoredRatio": 0.8,
            "energyStoredRatio": 0.8,
            "massTrend": 1,
            "energyTrend": 5,
            "surplusTicks": 600,
        },
        "counts": {
            "engineers": 8,
            "mexT1": 12,
            "mexT2": 0,
            "mexT3": 0,
            "landFactoriesT1": 3,
            "landFactoriesT2": 0,
            "airFactoriesT1": 1,
            "idleFactories": 1,
        },
        "opportunities": {
            "publicMassMarkers": 24,
            "fundableBuilderJobs": 6,
            "distinctRegions": 3,
            "reclaimJobs": 3,
            "lostMex": 1,
        },
        "requests": requests,
        "commitments": [],
        "campaign": {"state": "idle", "ownedCombatRatio": 0},
    }
    snapshot.update(updates)
    return snapshot


def build_portfolio(snapshot: dict[str, Any]) -> dict[str, Any]:
    return invoke(MODULE, GLOBAL, "BuildPortfolio", snapshot)


def test_macro_director_is_a_dedicated_runtime_module() -> None:
    assert director_path(MODULE).is_file()


@pytest.mark.skipif(not director_present(MODULE), reason="MacroDirector RED module missing")
class TestFundedPortfolio:
    def test_plan_exposes_every_persistent_lane_with_stable_ids(self) -> None:
        plan = build_portfolio(portfolio_snapshot())

        assert plan["valid"] is True
        assert set(plan["lanes"]) == {
            "energy_recovery",
            "mex_rebuild",
            "reclaim",
            "engineers",
            "land_production",
            "air_production",
            "factory_growth",
            "tech",
        }

    @pytest.mark.parametrize(
        ("available_mass", "admitted"),
        [(0.279999, False), (0.28, True)],
    )
    def test_recurring_admission_uses_the_exact_requested_drain_boundary(
        self, available_mass: float, admitted: bool
    ) -> None:
        request = lane_request(
            "land_production",
            mass_drain=0.28,
            energy_drain=3,
            mass_cost=56,
            energy_cost=600,
            required=True,
        )
        snapshot = portfolio_snapshot(requests=[request])
        snapshot["economy"].update(
            {
                "massIncome": available_mass,
                "massRequested": 0,
                "energyIncome": 3,
                "energyRequested": 0,
                "massStored": 0,
                "energyStored": 0,
            }
        )

        lane = intent_by_id(build_portfolio(snapshot), "land_production")
        assert lane["admitted"] is admitted

    @pytest.mark.parametrize(
        ("bank_mass", "admitted"),
        [(55.999, False), (56, True)],
    )
    def test_absolute_bank_can_fund_one_exact_lane_without_becoming_recurring_income(
        self, bank_mass: float, admitted: bool
    ) -> None:
        request = lane_request(
            "land_production",
            mass_drain=0.28,
            energy_drain=3,
            mass_cost=56,
            energy_cost=600,
            required=True,
        )
        snapshot = portfolio_snapshot(requests=[request])
        snapshot["economy"].update(
            {
                "massIncome": 0,
                "massRequested": 0,
                "energyIncome": 0,
                "energyRequested": 0,
                "massStored": bank_mass,
                "energyStored": 600,
            }
        )

        plan = build_portfolio(snapshot)
        lane = intent_by_id(plan, "land_production")
        assert lane["admitted"] is admitted
        assert plan["availableRecurringMass"] == 0

    def test_active_commitments_are_deducted_before_new_work_is_admitted(self) -> None:
        request = lane_request(
            "factory_growth",
            mass_drain=0.35,
            energy_drain=4,
            mass_cost=210,
            energy_cost=2400,
            optional=True,
        )
        snapshot = portfolio_snapshot(requests=[request])
        snapshot["economy"].update(
            {
                "massIncome": 0.7,
                "massRequested": 0,
                "energyIncome": 8,
                "energyRequested": 0,
                "massStored": 0,
                "energyStored": 0,
            }
        )
        snapshot["commitments"] = [
            {
                "id": "existing-factory",
                "lane": "factory_growth",
                "massDrain": 0.35,
                "energyDrain": 4,
                "remainingMass": 105,
                "remainingEnergy": 1200,
            }
        ]

        plan = build_portfolio(snapshot)

        assert intent_by_id(plan, "factory_growth")["admittedCount"] == 2
        assert plan["committedMassDrain"] == pytest.approx(0.7)
        assert plan["committedEnergyDrain"] == pytest.approx(8)

    def test_full_bank_and_sustained_unused_income_scale_engineers_and_factories(self) -> None:
        low = portfolio_snapshot()
        low["economy"].update(
            {
                "massIncome": 1,
                "massRequested": 0.9,
                "massStored": 0,
                "energyStored": 0,
                "surplusTicks": 0,
            }
        )
        high = portfolio_snapshot()
        high["opportunities"].update(
            {
                "fundableBuilderJobs": 12,
                "constructionBacklog": 14,
                "landProductionBacklog": 9,
                "airProductionBacklog": 5,
            }
        )
        high["economy"].update(
            {
                "massIncome": 12,
                "massRequested": 2,
                "energyIncome": 250,
                "energyRequested": 40,
                "massStored": 4000,
                "energyStored": 40000,
                "surplusTicks": 900,
            }
        )

        low_plan = build_portfolio(low)
        high_plan = build_portfolio(high)

        assert high_plan["engineerTarget"] > low_plan["engineerTarget"]
        assert high_plan["factoryTarget"] > low_plan["factoryTarget"]
        assert high_plan["landFactoryTarget"] > low_plan["landFactoryTarget"]
        assert high_plan["airFactoryTarget"] > low_plan["airFactoryTarget"]
        assert (
            high_plan["factoryTarget"]
            == high_plan["landFactoryTarget"] + high_plan["airFactoryTarget"]
        )
        assert high_plan["engineerTarget"] <= 32
        assert high_plan["factoryTarget"] <= 16

        # Hold funding capacity constant so each actionable backlog remains a
        # causal input rather than marker volume or the rich economy alone.
        capacity = portfolio_snapshot()
        capacity["economy"].update(
            {
                "massIncome": 8,
                "massRequested": 1,
                "energyIncome": 160,
                "energyRequested": 20,
                "massStored": 1000,
                "energyStored": 10000,
                "surplusTicks": 600,
            }
        )
        capacity["opportunities"].update(
            {
                "fundableBuilderJobs": 0,
                "constructionBacklog": 0,
                "landProductionBacklog": 0,
                "airProductionBacklog": 0,
            }
        )
        baseline = build_portfolio(capacity)
        backlog_cases = (
            ("fundableBuilderJobs", "engineerTarget"),
            ("constructionBacklog", "engineerTarget"),
            ("landProductionBacklog", "landFactoryTarget"),
            ("airProductionBacklog", "airFactoryTarget"),
        )
        scaled_by_opportunity = {}
        for opportunity, target in backlog_cases:
            with_backlog = copy.deepcopy(capacity)
            with_backlog["opportunities"][opportunity] = 12
            scaled = build_portfolio(with_backlog)
            scaled_by_opportunity[opportunity] = scaled
            assert scaled[target] > baseline[target], (opportunity, target)
        assert (
            scaled_by_opportunity["landProductionBacklog"]["airFactoryTarget"]
            == baseline["airFactoryTarget"]
        )
        assert (
            scaled_by_opportunity["airProductionBacklog"]["landFactoryTarget"]
            == baseline["landFactoryTarget"]
        )

    def test_stall_preserves_recovery_and_combat_while_shrinking_optional_work(self) -> None:
        snapshot = portfolio_snapshot()
        snapshot["economy"].update(
            {
                "massIncome": 0.7,
                "massRequested": 2,
                "energyIncome": 5,
                "energyRequested": 30,
                "massStored": 80,
                "energyStored": 100,
                "massStoredRatio": 0.05,
                "energyStoredRatio": 0.02,
                "massTrend": -1,
                "energyTrend": -10,
                "surplusTicks": 0,
            }
        )

        plan = build_portfolio(snapshot)

        assert intent_by_id(plan, "energy_recovery")["admitted"] is True
        assert intent_by_id(plan, "land_production")["preserved"] is True
        assert intent_by_id(plan, "factory_growth")["admitted"] is False
        assert intent_by_id(plan, "tech")["admitted"] is False

    def test_malformed_or_nonfinite_economy_fails_closed_without_throwing(self) -> None:
        bad_values = [float("nan"), float("inf"), -1, "malformed", None]
        for field in (
            "massIncome",
            "energyIncome",
            "massRequested",
            "energyRequested",
            "massStored",
            "energyStored",
        ):
            for bad in bad_values:
                snapshot = portfolio_snapshot()
                snapshot["economy"][field] = bad
                plan = build_portfolio(snapshot)
                assert plan["valid"] is False, (field, bad)
                assert all(
                    lane.get("admitted") is not True
                    for lane in plan.get("lanes", {}).values()
                ), (field, bad)

    def test_raw_public_marker_volume_cannot_inflate_funded_targets(self) -> None:
        targets = []
        for marker_count in (0, 24, 240, 2400):
            snapshot = portfolio_snapshot()
            snapshot["opportunities"]["publicMassMarkers"] = marker_count
            snapshot["opportunities"]["fundableBuilderJobs"] = 2
            plan = build_portfolio(snapshot)
            targets.append(
                (
                    plan["engineerTarget"],
                    plan["landFactoryTarget"],
                    plan["airFactoryTarget"],
                )
            )

        assert targets == [targets[0]] * len(targets)

    def test_opportunity_and_target_counts_stay_bounded_from_5_to_40km(self) -> None:
        for map_size, public_markers in ((5, 16), (10, 48), (20, 160), (40, 640)):
            snapshot = portfolio_snapshot(mapSizeKm=map_size)
            snapshot["opportunities"].update(
                {"publicMassMarkers": public_markers, "fundableBuilderJobs": 100}
            )
            plan = build_portfolio(snapshot)
            assert 0 <= plan["fundedExpansionSlots"] <= 4, map_size
            assert 1 <= plan["engineerTarget"] <= 32, map_size
            assert 1 <= plan["factoryTarget"] <= 16, map_size
            assert 1 <= plan["landFactoryTarget"] <= 12, map_size
            assert 1 <= plan["airFactoryTarget"] <= 4, map_size

    def test_campaign_state_never_serializes_independent_macro_lanes(self) -> None:
        snapshot = portfolio_snapshot()
        snapshot["campaign"] = {"state": "active", "ownedCombatRatio": 0.55}

        plan = build_portfolio(snapshot)

        for lane_id in (
            "energy_recovery",
            "mex_rebuild",
            "reclaim",
            "engineers",
            "land_production",
            "air_production",
        ):
            assert intent_by_id(plan, lane_id)["admitted"] is True, lane_id


def mass_site(
    key: str,
    x: float,
    z: float,
    *,
    region: str | None = None,
    lost: bool = False,
    owned: bool = False,
    value: float = 2,
) -> dict[str, Any]:
    return {
        "key": key,
        "position": [x, 0, z],
        "reachable": True,
        "buildable": True,
        "reserved": False,
        "lost": lost,
        "owned": owned,
        "value": value,
        "regionKey": region,
    }


@pytest.mark.skipif(not director_present(MODULE), reason="MacroDirector RED module missing")
class TestRegionalMacro:
    def test_public_mass_clustering_is_deterministic_under_input_permutation(self) -> None:
        sites = [
            mass_site("a-2", 20, 24),
            mass_site("b-1", 220, 220),
            mass_site("a-1", 20, 20),
            mass_site("b-2", 224, 220),
        ]
        expected = invoke(MODULE, GLOBAL, "ClusterRegions", sites, {"radius": 32})

        for seed in range(8):
            shuffled = copy.deepcopy(sites)
            random.Random(seed).shuffle(shuffled)
            assert invoke(
                MODULE, GLOBAL, "ClusterRegions", shuffled, {"radius": 32}
            ) == expected
        assert [region["memberKeys"] for region in expected] == [
            ["a-1", "a-2"],
            ["b-1", "b-2"],
        ]

    def test_region_lifecycle_is_explicit_from_planned_through_retake(self) -> None:
        region: dict[str, Any] = {
            "key": "region-a",
            "state": "planned",
            "lossCount": 0,
        }
        transitions = (
            ("package_ordered", "establishing"),
            ("package_complete", "secured"),
            ("enemy_pressure", "contested"),
            ("package_lost", "lost"),
            ("retake_funded", "retake"),
            ("package_complete", "secured"),
        )

        for index, (event, expected) in enumerate(transitions, 1):
            region = invoke(
                MODULE,
                GLOBAL,
                "AdvanceRegion",
                region,
                {"event": event, "tick": index * 100},
            )
            assert region["state"] == expected

        assert region["productionAnchor"] is True
        assert region["reclaimAnchor"] is True

    def test_expansion_rebuilds_lost_mex_before_nearer_new_site(self) -> None:
        snapshot = {
            "fundedExpansionSlots": 1,
            "engineers": [
                {"token": "eng-1", "position": [0, 0, 0], "available": True}
            ],
            "sites": [
                mass_site("new-near", 10, 0, region="home"),
                mass_site("lost-far", 80, 0, region="front", lost=True),
            ],
            "regions": [{"key": "front", "state": "secured"}],
            "escorts": [{"token": "tank-1", "available": True}],
        }

        result = invoke(MODULE, GLOBAL, "PlanExpansion", snapshot)

        assert result["jobs"][0]["siteKey"] == "lost-far"
        assert result["jobs"][0]["kind"] == "rebuild_mex"

    def test_expansion_uses_global_nearest_eligible_engineer_not_token_order(self) -> None:
        unreachable = mass_site("unreachable", 2, 0, region="region-a")
        unreachable["reachable"] = False
        reserved = mass_site("reserved", 4, 0, region="region-a")
        reserved["reserved"] = True
        snapshot = {
            "fundedExpansionSlots": 1,
            "engineers": [
                {"token": "eng-a", "position": [300, 0, 0], "available": True},
                {"token": "eng-z", "position": [22, 0, 0], "available": True},
            ],
            "sites": [
                unreachable,
                reserved,
                mass_site("disconnected", 6, 0, region="region-b"),
                mass_site("site", 20, 0, region="region-a"),
            ],
            "regions": [
                {"key": "region-a", "state": "planned", "connected": True},
                {"key": "region-b", "state": "planned", "connected": False},
            ],
            "escorts": [{"token": "tank-1", "available": True}],
        }

        result = invoke(MODULE, GLOBAL, "PlanExpansion", snapshot)

        assert result["jobs"][0]["actorToken"] == "eng-z"
        assert result["jobs"][0]["siteKey"] == "site"

    def test_multiple_funded_slots_choose_distinct_sites_and_regions(self) -> None:
        snapshot = {
            "fundedExpansionSlots": 2,
            "engineers": [
                {"token": "eng-a", "position": [0, 0, 0], "available": True},
                {"token": "eng-b", "position": [400, 0, 0], "available": True},
            ],
            "sites": [
                mass_site("a-1", 20, 0, region="region-a", value=3),
                mass_site("a-2", 24, 0, region="region-a", value=2),
                mass_site("b-1", 380, 0, region="region-b", value=3),
            ],
            "regions": [
                {"key": "region-a", "state": "planned"},
                {"key": "region-b", "state": "planned"},
            ],
            "escorts": [
                {"token": "tank-a", "available": True},
                {"token": "tank-b", "available": True},
            ],
        }

        jobs = invoke(MODULE, GLOBAL, "PlanExpansion", snapshot)["jobs"]

        assert len(jobs) == 2
        assert len({job["siteKey"] for job in jobs}) == 2
        assert {job["regionKey"] for job in jobs} == {"region-a", "region-b"}
        assert len({job["actorToken"] for job in jobs}) == 2

    def test_active_region_package_persists_factory_radar_defenses_and_garrison(self) -> None:
        plan = invoke(
            MODULE,
            GLOBAL,
            "PlanRegionPackage",
            {"key": "region-a", "state": "establishing", "position": [100, 0, 100]},
            {
                "completedRoles": ["mass_extractor", "mass_extractor"],
                "pendingRoles": [],
                "enemyAirPressure": True,
            },
        )

        assert set(plan["requiredRoles"]) == {
            "radar",
            "static_anti_air",
            "point_defense",
            "land_factory",
        }
        assert plan["garrisonMinimum"] >= 4
        assert plan["garrisonAntiAirMinimum"] >= 1
        assert plan["persistent"] is True

    @pytest.mark.parametrize(
        ("prior_losses", "suspended"),
        [(1, False), (2, True)],
    )
    def test_repeated_recent_loss_suspends_unsafe_region_at_exact_third_loss(
        self, prior_losses: int, suspended: bool
    ) -> None:
        region = {
            "key": "unsafe",
            "state": "contested",
            "lossCount": prior_losses,
            "firstLossTick": 1000,
            "suspendedUntilTick": 0,
        }

        updated = invoke(
            MODULE,
            GLOBAL,
            "AdvanceRegion",
            region,
            {"event": "package_lost", "tick": 2200},
        )

        assert (updated["state"] == "suspended") is suspended
        assert (updated.get("suspendedUntilTick", 0) > 2200) is suspended

    def test_remote_engineer_cannot_depart_until_a_bound_land_and_aa_screen_exists(self) -> None:
        base = {
            "fundedExpansionSlots": 1,
            "controlledRadius": 60,
            "engineers": [
                {"token": "eng", "position": [0, 0, 0], "available": True}
            ],
            "sites": [mass_site("remote", 300, 0, region="remote")],
            "regions": [{"key": "remote", "state": "planned"}],
        }

        without_screen = invoke(
            MODULE, GLOBAL, "PlanExpansion", {**base, "escorts": []}
        )
        with_screen = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                **base,
                "escorts": [
                    {"token": "tank", "role": "tank", "available": True},
                    {"token": "aa", "role": "anti_air", "available": True},
                ],
            },
        )

        assert len(without_screen["jobs"]) == 0
        assert without_screen["denials"][0]["reason"] == "escort_not_ready"
        assert with_screen["jobs"][0]["escortTokens"] == ["aa", "tank"]

    def test_reclaim_is_region_local_deterministic_unique_and_revalidated(self) -> None:
        snapshot = {
            "regions": [
                {"key": "home", "state": "secured", "position": [0, 0, 0], "radius": 80},
                {"key": "front", "state": "secured", "position": [200, 0, 0], "radius": 80},
            ],
            "engineers": [
                {"token": "eng-home", "position": [0, 0, 0], "available": True},
                {"token": "eng-front", "position": [200, 0, 0], "available": True},
            ],
            "candidates": [
                {"key": "front-low", "position": [205, 0, 0], "mass": 20, "visible": True, "live": True},
                {"key": "home-high", "position": [10, 0, 0], "mass": 100, "visible": True, "live": True},
                {"key": "hidden", "position": [5, 0, 0], "mass": 500, "visible": False, "live": True},
                {"key": "outside", "position": [500, 0, 0], "mass": 500, "visible": True, "live": True},
                {"key": "gone", "position": [6, 0, 0], "mass": 500, "visible": True, "live": False},
            ],
        }

        jobs = invoke(MODULE, GLOBAL, "PlanReclaim", snapshot)["jobs"]

        assert [(job["actorToken"], job["targetKey"]) for job in jobs] == [
            ("eng-front", "front-low"),
            ("eng-home", "home-high"),
        ]
        assert len({job["targetKey"] for job in jobs}) == len(jobs)
        assert all(job["requiresLiveVisionRevalidation"] is True for job in jobs)

        for seed in range(4):
            permuted = copy.deepcopy(snapshot)
            random.Random(seed).shuffle(permuted["candidates"])
            random.Random(seed + 20).shuffle(permuted["engineers"])
            assert invoke(MODULE, GLOBAL, "PlanReclaim", permuted)["jobs"] == jobs

        revalidated = copy.deepcopy(snapshot)
        for candidate in revalidated["candidates"]:
            if candidate["key"] == "front-low":
                candidate["live"] = False
            elif candidate["key"] == "home-high":
                candidate["visible"] = False
        assert len(invoke(MODULE, GLOBAL, "PlanReclaim", revalidated)["jobs"]) == 0

    def test_remote_expansion_backlog_does_not_consume_each_regions_reclaim_lane(self) -> None:
        snapshot = portfolio_snapshot()
        snapshot["opportunities"].update(
            {"fundableBuilderJobs": 4, "remoteExpansionBacklog": 20, "reclaimJobs": 2}
        )

        plan = build_portfolio(snapshot)

        assert intent_by_id(plan, "reclaim")["admitted"] is True
        assert intent_by_id(plan, "reclaim")["admittedCount"] >= 2

    def test_job_ledger_persists_travel_and_refreshes_only_on_real_progress(self) -> None:
        first = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            {"jobs": {}},
            {
                "tick": 100,
                "newJobs": [
                    {
                        "id": "mex:front:1",
                        "kind": "build_mex",
                        "actorToken": "eng-1:1",
                        "targetKey": "front-1",
                        "estimatedTravelTicks": 500,
                    }
                ],
                "actors": [
                    {
                        "token": "eng-1:1",
                        "live": True,
                        "owned": True,
                        "position": [0, 0, 0],
                    }
                ],
                "targets": [
                    {
                        "key": "front-1",
                        "live": True,
                        "position": [100, 0, 0],
                    }
                ],
            },
        )
        job = first["jobs"]["mex:front:1"]

        assert job["phase"] == "travelling"
        assert job["actorToken"] == "eng-1:1"
        assert job["deadlineTick"] >= 600
        assert job["lastProgressTick"] == 100
        assert job["remainingDistance"] == pytest.approx(100)

        progressed = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            first,
            {
                "tick": 250,
                "newJobs": [],
                "actors": [
                    {
                        "token": "eng-1:1",
                        "live": True,
                        "owned": True,
                        "position": [40, 0, 0],
                    }
                ],
                "targets": [
                    {
                        "key": "front-1",
                        "live": True,
                        "position": [100, 0, 0],
                    }
                ],
            },
        )
        next_job = progressed["jobs"]["mex:front:1"]

        assert next_job["lastProgressTick"] == 250
        assert next_job["remainingDistance"] == pytest.approx(60)
        assert next_job["retryCount"] == 0

        unchanged = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            progressed,
            {
                "tick": 300,
                "newJobs": [],
                "actors": [
                    {
                        "token": "eng-1:1",
                        "live": True,
                        "owned": True,
                        "position": [40, 0, 0],
                    }
                ],
                "targets": [
                    {
                        "key": "front-1",
                        "live": True,
                        "position": [100, 0, 0],
                    }
                ],
            },
        )["jobs"]["mex:front:1"]
        assert unchanged["lastProgressTick"] == 250
        assert unchanged["deadlineTick"] == next_job["deadlineTick"]

    @pytest.mark.parametrize(
        ("progress_field", "last_field", "initial", "advanced"),
        (
            ("fractionComplete", "lastFraction", 0.20, 0.35),
            ("workProgress", "lastWorkProgress", 12, 19),
        ),
        ids=("fraction", "work"),
    )
    def test_building_job_refreshes_only_on_real_construction_progress_and_releases_at_exact_stall_bound(
        self,
        progress_field: str,
        last_field: str,
        initial: float,
        advanced: float,
    ) -> None:
        ledger = {
            "jobs": {
                "mex:front:1": {
                    "id": "mex:front:1",
                    "kind": "build_mex",
                    "phase": "building",
                    "actorToken": "eng-1:1",
                    "targetKey": "front-1",
                    "deadlineTick": 500,
                    "lastProgressTick": 100,
                    last_field: initial,
                    "retryCount": 0,
                }
            }
        }

        def observation(tick: int, fraction: float) -> dict[str, Any]:
            return {
                "tick": tick,
                "newJobs": [],
                "actors": [
                    {
                        "token": "eng-1:1",
                        "live": True,
                        "owned": True,
                        "position": [100, 0, 0],
                    }
                ],
                "targets": [
                    {
                        "key": "front-1",
                        "live": True,
                        "completed": False,
                        "position": [100, 0, 0],
                        progress_field: fraction,
                    }
                ],
            }

        unchanged = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            ledger,
            observation(300, initial),
        )
        unchanged_job = unchanged["jobs"]["mex:front:1"]
        assert unchanged_job["phase"] == "building"
        assert unchanged_job["lastProgressTick"] == 100
        assert unchanged_job["deadlineTick"] == 500
        assert unchanged_job[last_field] == pytest.approx(initial)

        progressed = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            unchanged,
            observation(400, advanced),
        )
        progressed_job = progressed["jobs"]["mex:front:1"]
        assert progressed_job["phase"] == "building"
        assert progressed_job["lastProgressTick"] == 400
        assert progressed_job[last_field] == pytest.approx(advanced)
        assert progressed_job["deadlineTick"] > 500

        stalled = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            progressed,
            observation(progressed_job["deadlineTick"] - 1, advanced),
        )
        stalled_job = stalled["jobs"]["mex:front:1"]
        assert stalled_job["phase"] == "building"
        assert stalled_job["lastProgressTick"] == 400
        assert stalled_job["deadlineTick"] == progressed_job["deadlineTick"]

        released = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            stalled,
            observation(progressed_job["deadlineTick"], advanced),
        )
        released_job = released["jobs"]["mex:front:1"]
        assert released_job["phase"] == "retryable"
        assert released_job["failureReason"] == "construction_stalled"
        assert released_job["retryCount"] == 1
        assert released["releasedActorTokens"] == ["eng-1:1"]

    def test_job_ledger_stall_deadline_releases_once_and_makes_job_retryable(self) -> None:
        ledger = {
            "jobs": {
                "mex:front:1": {
                    "id": "mex:front:1",
                    "kind": "build_mex",
                    "phase": "travelling",
                    "actorToken": "eng-1:1",
                    "targetKey": "front-1",
                    "deadlineTick": 600,
                    "lastProgressTick": 100,
                    "remainingDistance": 100,
                    "retryCount": 0,
                }
            }
        }
        observation = {
            "tick": 601,
            "newJobs": [],
            "actors": [
                {
                    "token": "eng-1:1",
                    "live": True,
                    "owned": True,
                    "position": [0, 0, 0],
                }
            ],
            "targets": [
                {"key": "front-1", "live": True, "position": [100, 0, 0]}
            ],
        }

        released = invoke(
            MODULE, GLOBAL, "UpdateJobLedger", ledger, observation
        )
        repeated = invoke(
            MODULE, GLOBAL, "UpdateJobLedger", released, {**observation, "tick": 602}
        )

        assert released["jobs"]["mex:front:1"]["phase"] == "retryable"
        assert released["jobs"]["mex:front:1"]["retryCount"] == 1
        assert released["releasedActorTokens"] == ["eng-1:1"]
        assert len(repeated["releasedActorTokens"]) == 0
        assert repeated["jobs"]["mex:front:1"]["retryCount"] == 1

        progressing = copy.deepcopy(ledger)
        progressing["jobs"]["mex:front:1"]["phase"] = "progressing"
        completed_observation = copy.deepcopy(observation)
        completed_observation["tick"] = 300
        completed_observation["targets"][0]["completed"] = True
        completed = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            progressing,
            completed_observation,
        )
        assert completed["jobs"]["mex:front:1"]["phase"] == "completed"
        assert completed["jobs"]["mex:front:1"]["retryCount"] == 0
        assert completed["releasedActorTokens"] == ["eng-1:1"]

        gone_observation = copy.deepcopy(observation)
        gone_observation["tick"] = 300
        gone_observation["targets"][0]["live"] = False
        gone = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            progressing,
            gone_observation,
        )
        assert gone["jobs"]["mex:front:1"]["phase"] == "retryable"
        assert gone["jobs"]["mex:front:1"]["failureReason"] == "target_gone"
        assert gone["jobs"]["mex:front:1"]["retryCount"] == 1
        assert gone["releasedActorTokens"] == ["eng-1:1"]

    def test_job_ledger_generation_death_and_capture_reassign_nearest_exact_survivor(self) -> None:
        base = {
            "jobs": {
                "mex:front:1": {
                    "id": "mex:front:1",
                    "kind": "build_mex",
                    "phase": "travelling",
                    "actorToken": "eng-1:1",
                    "targetKey": "front-1",
                    "deadlineTick": 900,
                    "lastProgressTick": 100,
                    "remainingDistance": 80,
                    "retryCount": 0,
                }
            }
        }
        target = {"key": "front-1", "live": True, "position": [100, 0, 0]}
        invalid_actors = (
            {"token": "eng-1:1", "live": False, "owned": True, "position": [20, 0, 0]},
            {"token": "eng-1:1", "live": True, "owned": False, "position": [20, 0, 0]},
            {"token": "eng-1:2", "live": True, "owned": True, "position": [20, 0, 0]},
        )

        for invalid in invalid_actors:
            result = invoke(
                MODULE,
                GLOBAL,
                "UpdateJobLedger",
                copy.deepcopy(base),
                {
                    "tick": 200,
                    "newJobs": [],
                    "actors": [
                        invalid,
                        {
                            "token": "eng-near:1",
                            "live": True,
                            "owned": True,
                            "available": True,
                            "position": [90, 0, 0],
                        },
                        {
                            "token": "eng-far:1",
                            "live": True,
                            "owned": True,
                            "available": True,
                            "position": [0, 0, 0],
                        },
                    ],
                    "targets": [target],
                },
            )
            job = result["jobs"]["mex:front:1"]
            assert job["actorToken"] == "eng-near:1", invalid
            assert job["retryCount"] == 1, invalid
            assert "eng-1:1" in result["releasedActorTokens"], invalid

    def test_t2_hq_milestone_has_no_hydro_dependency_and_keeps_one_t1_lane(self) -> None:
        ready = {
            "tick": 5700,
            "economyHealthy": True,
            "techFunded": True,
            "hydroAvailable": False,
            "landFactories": [
                {"token": "land-a", "tier": 1, "idle": True},
                {"token": "land-b", "tier": 1, "idle": True},
            ],
            "mex": [{"key": f"mex-{index}", "tier": 1} for index in range(8)],
        }
        one_lane = copy.deepcopy(ready)
        one_lane["landFactories"] = one_lane["landFactories"][:1]

        plan = invoke(MODULE, GLOBAL, "PlanTech", ready)
        blocked = invoke(MODULE, GLOBAL, "PlanTech", one_lane)

        assert plan["hqAction"] == "start_t2"
        assert plan["hqSourceToken"] == "land-a"
        assert plan["remainingT1ProductionLanes"] == 1
        assert set(plan["t2ProductionRoles"]) == {
            "t2_direct_fire",
            "t2_anti_air",
        }
        assert blocked["hqAction"] == "hold"
        assert blocked["hqDenialReason"] == "preserve_final_t1_lane"

    @pytest.mark.parametrize(
        ("healthy", "t3_action"),
        [(False, "hold"), (True, "admit")],
    )
    def test_mex_upgrades_are_staggered_and_t3_requires_healthy_funded_milestones(
        self, healthy: bool, t3_action: str
    ) -> None:
        snapshot = {
            "tick": 12000,
            "economyHealthy": healthy,
            "techFunded": healthy,
            "t2HqComplete": True,
            "t2MobileCount": 35,
            "landFactories": [
                {"token": "land-t1", "tier": 1, "idle": True},
                {"token": "land-t2", "tier": 2, "idle": True},
            ],
            "mex": [
                {"key": f"mex-{index:02d}", "tier": 1, "upgrading": False}
                for index in range(10)
            ],
            "activeMexUpgrades": 0,
        }

        plan = invoke(MODULE, GLOBAL, "PlanTech", snapshot)

        assert len(plan["mexUpgradeSiteKeys"]) <= 1
        assert plan["t3Action"] == t3_action
