from __future__ import annotations

import copy
import random
from itertools import permutations
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

    def test_live_nine_mex_state_scales_from_completed_economy_not_raw_markers(self) -> None:
        snapshot = portfolio_snapshot()
        snapshot["economy"].update(
            {
                "massIncome": 0.1,
                "massRequested": 0,
                "energyIncome": 2,
                "energyRequested": 0,
                "massStored": 400,
                "energyStored": 3000,
            }
        )
        snapshot["counts"].update(
            {"engineers": 16, "mexT1": 9, "mexT2": 0, "mexT3": 0}
        )
        snapshot["opportunities"].update(
            {"fundableBuilderJobs": 56, "constructionBacklog": 56}
        )

        plan = build_portfolio(snapshot)

        assert plan["engineerTarget"] == 13

    @pytest.mark.parametrize(
        ("completed_mex", "expected_target"),
        [(0, 4), (6, 10), (11, 15), (16, 16), (40, 16)],
    )
    def test_completed_mex_scales_the_early_engineer_target_to_adaptive_pace(
        self, completed_mex: int, expected_target: int
    ) -> None:
        snapshot = portfolio_snapshot(requests=[])
        snapshot["counts"].update(
            {"engineers": 0, "mexT1": completed_mex, "mexT2": 0, "mexT3": 0}
        )

        assert build_portfolio(snapshot)["engineerTarget"] == expected_target

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

    @pytest.mark.parametrize(
        ("energy_bank", "admitted"),
        [(4049.9, False), (4050, True)],
    )
    def test_long_tech_build_can_use_bank_plus_income_over_its_build_time(
        self, energy_bank: float, admitted: bool
    ) -> None:
        request = {
            **lane_request(
                "tech",
                mass_drain=1,
                energy_drain=6,
                mass_cost=900,
                energy_cost=5400,
                duration_ticks=900,
                optional=True,
            ),
            "allowHybrid": True,
        }
        snapshot = portfolio_snapshot(requests=[request])
        snapshot["economy"].update(
            {
                "massIncome": 0,
                "massRequested": 0,
                "energyIncome": 1.5,
                "energyRequested": 0,
                "massStored": 900,
                "energyStored": energy_bank,
            }
        )

        plan = build_portfolio(snapshot)

        assert plan["lanes"]["tech"]["admitted"] is admitted
        assert [grant["source"] for grant in plan["grants"]] == (
            ["hybrid"] if admitted else []
        )

    def test_ten_mex_tech_preempts_surplus_air_after_the_initial_air_package(self) -> None:
        requests = [
            lane_request(
                "energy_recovery", mass_drain=0.05, energy_drain=0,
                mass_cost=75, energy_cost=0, required=True,
            ),
            lane_request(
                "mex_rebuild", mass_drain=0.3, energy_drain=3,
                mass_cost=36, energy_cost=360, required=True,
            ),
            lane_request(
                "reclaim", mass_drain=0, energy_drain=0,
                mass_cost=0, energy_cost=0, required=True,
            ),
            lane_request(
                "land_production", mass_drain=0.28, energy_drain=3,
                mass_cost=56, energy_cost=600, required=True,
            ),
            lane_request(
                "air_production", mass_drain=0.2, energy_drain=9,
                mass_cost=50, energy_cost=2250, required=True,
            ),
            lane_request(
                "engineers", mass_drain=0.2, energy_drain=2,
                mass_cost=52, energy_cost=260,
            ),
            lane_request(
                "factory_growth", mass_drain=0.4, energy_drain=3.5,
                mass_cost=240, energy_cost=2100, optional=True,
            ),
            {
                **lane_request(
                    "tech", mass_drain=1, energy_drain=6,
                    mass_cost=900, energy_cost=5400,
                    duration_ticks=900, optional=True,
                ),
                "allowHybrid": True,
            },
        ]
        snapshot = portfolio_snapshot(requests=requests)
        snapshot["economy"].update(
            {
                "massIncome": 2.1,
                "massRequested": 0.76,
                "energyIncome": 20,
                "energyRequested": 10.23,
                "massStored": 1110,
                "energyStored": 4000,
                "massTrend": 1.34,
                "energyTrend": 9.77,
                "commitmentsIncludedInRequested": True,
            }
        )

        plan = build_portfolio(snapshot)

        assert plan["lanes"]["land_production"]["admitted"] is True
        assert plan["lanes"]["tech"]["admitted"] is True
        assert plan["lanes"]["air_production"]["admitted"] is False

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

    def test_lane_priority_not_caller_order_protects_required_combat_from_optional_work(self) -> None:
        land = lane_request(
            "land_production",
            mass_drain=0.28,
            energy_drain=3,
            mass_cost=56,
            energy_cost=600,
            required=True,
        )
        tech = lane_request(
            "tech",
            mass_drain=0.28,
            energy_drain=3,
            mass_cost=56,
            energy_cost=600,
            optional=True,
        )
        plans = []
        for requests in ([tech, land], [land, tech]):
            snapshot = portfolio_snapshot(requests=requests)
            snapshot["economy"].update(
                {
                    "massIncome": 0.28,
                    "massRequested": 0,
                    "energyIncome": 3,
                    "energyRequested": 0,
                    "massStored": 0,
                    "energyStored": 0,
                }
            )
            plans.append(build_portfolio(snapshot))

        assert plans[0] == plans[1]
        assert intent_by_id(plans[0], "land_production")["admitted"] is True
        assert intent_by_id(plans[0], "tech")["admitted"] is False

    @pytest.mark.parametrize(
        ("mass_income", "admitted_count"),
        ((0.699999, 1), (0.7, 2)),
    )
    def test_requested_load_model_does_not_double_subtract_active_commitments(
        self, mass_income: float, admitted_count: int
    ) -> None:
        request = lane_request(
            "factory_growth",
            mass_drain=0.35,
            energy_drain=4,
            mass_cost=210,
            energy_cost=2400,
        )
        snapshot = portfolio_snapshot(requests=[request])
        snapshot["economy"].update(
            {
                "massIncome": mass_income,
                "massRequested": 0.35,
                "energyIncome": 8,
                "energyRequested": 4,
                "massStored": 0,
                "energyStored": 0,
                "commitmentsIncludedInRequested": True,
            }
        )
        snapshot["commitments"] = [
            {
                "id": "already-requested",
                "lane": "factory_growth",
                "massDrain": 0.35,
                "energyDrain": 4,
            }
        ]

        plan = build_portfolio(snapshot)

        assert intent_by_id(plan, "factory_growth")["admittedCount"] == admitted_count
        assert plan["availableRecurringMass"] == pytest.approx(
            max(0, mass_income - 0.35)
        )
        expected_committed = 0.35 if admitted_count == 1 else 0.7
        assert plan["committedMassDrain"] == pytest.approx(expected_committed)

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

        assert high_plan["engineerTarget"] == low_plan["engineerTarget"]
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

    def test_missing_or_nonfinite_trends_fail_closed_but_finite_negative_stall_is_valid(self) -> None:
        for field in ("massTrend", "energyTrend"):
            for bad in (float("nan"), float("inf"), float("-inf"), "bad", None):
                snapshot = portfolio_snapshot()
                snapshot["economy"][field] = bad
                plan = build_portfolio(snapshot)
                assert plan["valid"] is False, (field, bad)
                assert not any(
                    lane.get("admitted") is True for lane in plan["lanes"].values()
                )

            missing = portfolio_snapshot()
            del missing["economy"][field]
            assert build_portfolio(missing)["valid"] is False

        negative = portfolio_snapshot()
        negative["economy"].update({"massTrend": -0.01, "energyTrend": -1})
        plan = build_portfolio(negative)
        assert plan["valid"] is True
        assert plan["stalled"] is True

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

    def test_one_exact_mex_budget_creates_one_consumable_grant_not_four_boolean_slots(self) -> None:
        request = lane_request(
            "mex_rebuild",
            mass_drain=0.3,
            energy_drain=3,
            mass_cost=36,
            energy_cost=360,
            required=True,
        )
        snapshot = portfolio_snapshot(requests=[request])
        snapshot["economy"].update(
            {
                "massIncome": 0,
                "massRequested": 0,
                "energyIncome": 0,
                "energyRequested": 0,
                "massStored": 36,
                "energyStored": 360,
            }
        )
        snapshot["opportunities"].update(
            {"fundableBuilderJobs": 12, "lostMex": 4}
        )

        plan = build_portfolio(snapshot)

        assert plan["fundedExpansionSlots"] == 1
        assert [
            (grant["requestId"], grant["lane"], grant["source"])
            for grant in plan["grants"]
        ] == [("mex_rebuild-1", "mex_rebuild", "bank")]
        assert plan["fundingLedger"] == {
            "recurringMass": 0,
            "recurringEnergy": 0,
            "bankMass": 0,
            "bankEnergy": 0,
        }

    def test_preserved_lost_mex_lane_without_resources_creates_no_spendable_grant(self) -> None:
        request = lane_request(
            "mex_rebuild",
            mass_drain=0.3,
            energy_drain=3,
            mass_cost=36,
            energy_cost=360,
            required=True,
        )
        snapshot = portfolio_snapshot(requests=[request])
        snapshot["economy"].update(
            {
                "massIncome": 0,
                "massRequested": 0,
                "energyIncome": 0,
                "energyRequested": 0,
                "massStored": 0,
                "energyStored": 0,
            }
        )
        snapshot["opportunities"].update(
            {"fundableBuilderJobs": 12, "lostMex": 1}
        )

        plan = build_portfolio(snapshot)

        assert plan["lanes"]["mex_rebuild"]["preserved"] is True
        assert len(plan["grants"]) == 0
        assert plan["fundedExpansionSlots"] == 0

    def test_recurring_and_bank_funds_produce_distinct_rolling_operation_grants(self) -> None:
        requests = [
            {
                **lane_request(
                    "mex_rebuild",
                    mass_drain=0.3,
                    energy_drain=3,
                    mass_cost=36,
                    energy_cost=360,
                    required=True,
                ),
                "id": request_id,
            }
            for request_id in ("mex-a", "mex-b")
        ]
        snapshot = portfolio_snapshot(requests=requests)
        snapshot["economy"].update(
            {
                "massIncome": 0.3,
                "massRequested": 0,
                "energyIncome": 3,
                "energyRequested": 0,
                "massStored": 36,
                "energyStored": 360,
            }
        )
        snapshot["opportunities"]["fundableBuilderJobs"] = 2

        plan = build_portfolio(snapshot)

        assert [grant["requestId"] for grant in plan["grants"]] == [
            "mex-a",
            "mex-b",
        ]
        assert [grant["source"] for grant in plan["grants"]] == [
            "recurring",
            "bank",
        ]
        assert plan["fundedExpansionSlots"] == 2
        assert plan["fundingLedger"] == {
            "recurringMass": 0,
            "recurringEnergy": 0,
            "bankMass": 0,
            "bankEnergy": 0,
        }


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
            "bootstrapEscortTokens": ["aa:1", "tank:1"],
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
        assert "bootstrapEscortTokens" not in region

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

    def test_site_quarantine_maximizes_cardinality_under_all_input_orders(self) -> None:
        engineers = [
            {"token": "72:2", "position": [11, 0, 20], "available": True},
            {"token": "73:1", "position": [39, 0, 40], "available": True},
        ]
        sites = [
            mass_site("near", 12, 20, region="near-region"),
            mass_site("far", 40, 40, region="far-region"),
        ]

        for reverse_engineers in (False, True):
            for reverse_sites in (False, True):
                ordered_engineers = copy.deepcopy(engineers)
                ordered_sites = copy.deepcopy(sites)
                if reverse_engineers:
                    ordered_engineers.reverse()
                if reverse_sites:
                    ordered_sites.reverse()
                jobs = invoke(
                    MODULE,
                    GLOBAL,
                    "PlanExpansion",
                    {
                        "fundedExpansionSlots": 2,
                        "engineers": ordered_engineers,
                        "sites": ordered_sites,
                        "regions": [],
                        "blockedActorTokensBySite": {"near": {"72:2": True}},
                    },
                )["jobs"]

                assert {job["siteKey"]: job["actorToken"] for job in jobs} == {
                    "near": "73:1",
                    "far": "72:2",
                }

    def test_three_way_constraints_maximize_cardinality_under_all_permutations(
        self,
    ) -> None:
        engineers = [
            {"token": "eng-a", "position": [150, 0, 0], "available": True},
            {"token": "eng-b", "position": [101, 0, 0], "available": True},
            {"token": "eng-c", "position": [200, 0, 0], "available": True},
        ]
        sites = [
            mass_site("site-a", 0, 0, region="region-a"),
            mass_site("site-b", 100, 0, region="region-b"),
            mass_site("site-c", 200, 0, region="region-c"),
        ]
        blocked = {
            "site-a": {"eng-a": True, "eng-b": True},
            "site-b": {"eng-a": True},
        }

        for engineer_order in permutations(engineers):
            for site_order in permutations(sites):
                jobs = invoke(
                    MODULE,
                    GLOBAL,
                    "PlanExpansion",
                    {
                        "fundedExpansionSlots": 3,
                        "engineers": copy.deepcopy(engineer_order),
                        "sites": copy.deepcopy(site_order),
                        "regions": [],
                        "blockedActorTokensBySite": blocked,
                    },
                )["jobs"]

                assert {job["siteKey"]: job["actorToken"] for job in jobs} == {
                    "site-a": "eng-c",
                    "site-b": "eng-b",
                    "site-c": "eng-a",
                }

    @pytest.mark.parametrize(
        ("engineer_count", "sites", "expected"),
        (
            (0, [mass_site("a", 10, 0)], 0),
            (2, [], 0),
            (1, [mass_site("a", 10, 0), mass_site("b", 20, 0)], 1),
            (
                2,
                [
                    mass_site("a", 10, 0),
                    mass_site("b", 20, 0),
                    mass_site("c", 30, 0),
                ],
                2,
            ),
            (3, [mass_site("a", 10, 0)], 1),
            (
                3,
                [
                    mass_site("a", 10, 0, region="shared"),
                    mass_site("b", 20, 0, region="shared"),
                ],
                1,
            ),
        ),
    )
    def test_expansion_matching_is_bounded_by_actors_sites_and_regions(
        self,
        engineer_count: int,
        sites: list[dict[str, Any]],
        expected: int,
    ) -> None:
        jobs = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 4,
                "engineers": [
                    {
                        "token": f"eng-{index}",
                        "position": [0, 0, 0],
                        "available": True,
                    }
                    for index in range(engineer_count)
                ],
                "sites": sites,
                "regions": [],
            },
        )["jobs"]

        assert len(jobs) == expected

    def test_equal_cost_matching_has_one_stable_actor_site_assignment(self) -> None:
        engineers = [
            {"token": "eng-a", "position": [0, 0, 0], "available": True},
            {"token": "eng-b", "position": [0, 0, 0], "available": True},
        ]
        sites = [
            mass_site("site-a", 10, 0, region="region-a"),
            mass_site("site-b", 0, 10, region="region-b"),
        ]
        observed = []

        for engineer_order in permutations(engineers):
            for site_order in permutations(sites):
                jobs = invoke(
                    MODULE,
                    GLOBAL,
                    "PlanExpansion",
                    {
                        "fundedExpansionSlots": 2,
                        "engineers": copy.deepcopy(engineer_order),
                        "sites": copy.deepcopy(site_order),
                        "regions": [],
                    },
                )["jobs"]
                observed.append(
                    {job["siteKey"]: job["actorToken"] for job in jobs}
                )

        assert observed == [observed[0]] * len(observed)
        assert observed[0] == {"site-a": "eng-a", "site-b": "eng-b"}

    def test_maximum_cardinality_then_minimizes_global_total_distance(self) -> None:
        engineers = [
            {"token": "eng-a", "position": [0, 0, 0], "available": True},
            {"token": "eng-b", "position": [10, 0, 0], "available": True},
        ]
        sites = [
            mass_site("site-x", 9, 0, region="region-x"),
            mass_site("site-y", 20, 0, region="region-y"),
        ]

        for engineer_order in permutations(engineers):
            for site_order in permutations(sites):
                jobs = invoke(
                    MODULE,
                    GLOBAL,
                    "PlanExpansion",
                    {
                        "fundedExpansionSlots": 2,
                        "engineers": copy.deepcopy(engineer_order),
                        "sites": copy.deepcopy(site_order),
                        "regions": [],
                    },
                )["jobs"]

                assert {job["siteKey"]: job["actorToken"] for job in jobs} == {
                    "site-x": "eng-a",
                    "site-y": "eng-b",
                }

    def test_four_slot_kernel_retains_required_fourth_ranked_edge(self) -> None:
        engineers = [
            {"token": token, "position": [0, 0, 0], "available": True}
            for token in ("eng-a", "eng-b", "eng-c", "eng-d")
        ]
        sites = [
            mass_site(f"site-{index}", index, 0, region=f"region-{index}")
            for index in range(1, 7)
        ]
        blocked = {
            "site-1": {"eng-c": True, "eng-d": True},
            "site-2": {"eng-b": True, "eng-d": True},
            "site-3": {"eng-b": True, "eng-c": True},
        }
        for site in ("site-4", "site-5", "site-6"):
            blocked[site] = {"eng-b": True, "eng-c": True, "eng-d": True}

        jobs = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 4,
                "engineers": engineers,
                "sites": sites,
                "regions": [],
                "blockedActorTokensBySite": blocked,
            },
        )["jobs"]

        assert len(jobs) == 4
        assert {job["actorToken"] for job in jobs} == {
            "eng-a",
            "eng-b",
            "eng-c",
            "eng-d",
        }
        assert next(job for job in jobs if job["actorToken"] == "eng-a")[
            "siteKey"
        ] == "site-4"

    def test_lost_mex_priority_survives_remote_escort_feasibility(self) -> None:
        result = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 1,
                "controlledRadius": 60,
                "engineers": [
                    {"token": "eng", "position": [0, 0, 0], "available": True}
                ],
                "sites": [
                    mass_site("new", 1, 0, region="new"),
                    mass_site("lost", 100, 0, region="lost", lost=True),
                ],
                "regions": [],
                "escorts": [
                    {"token": "aa", "role": "anti_air", "available": True},
                    {"token": "tank", "role": "tank", "available": True},
                ],
            },
        )

        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["siteKey"] == "lost"
        assert result["jobs"][0]["kind"] == "rebuild_mex"
        assert result["jobs"][0]["escortTokens"] == ["aa", "tank"]

    def test_same_region_local_fallback_survives_remote_candidate_quota(self) -> None:
        result = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 1,
                "controlledRadius": 60,
                "engineers": [
                    {"token": "eng", "position": [0, 0, 0], "available": True}
                ],
                "sites": [
                    mass_site("local", 1, 0, region="shared"),
                    mass_site("lost-remote", 100, 0, region="shared", lost=True),
                ],
                "regions": [],
                "escorts": [],
            },
        )

        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["siteKey"] == "local"
        assert result["jobs"][0]["requiresEscort"] is False
        assert result["denials"] == {}

    @pytest.mark.parametrize("duplicate_kind", ("engineer", "site"))
    def test_duplicate_actor_or_site_identity_cannot_create_two_jobs(
        self, duplicate_kind: str
    ) -> None:
        engineers = [
            {"token": "eng-a", "position": [0, 0, 0], "available": True},
            {"token": "eng-b", "position": [5, 0, 0], "available": True},
        ]
        sites = [
            mass_site("site-a", 10, 0, region="region-a"),
            mass_site("site-b", 20, 0, region="region-b"),
        ]
        if duplicate_kind == "engineer":
            engineers[1] = {
                "token": "eng-a",
                "position": [5, 0, 0],
                "available": True,
            }
        else:
            sites[1] = mass_site("site-a", 20, 0, region="other-region")

        observed = []
        for reverse_engineers in (False, True):
            for reverse_sites in (False, True):
                ordered_engineers = copy.deepcopy(engineers)
                ordered_sites = copy.deepcopy(sites)
                if reverse_engineers:
                    ordered_engineers.reverse()
                if reverse_sites:
                    ordered_sites.reverse()
                observed.append(
                    invoke(
                        MODULE,
                        GLOBAL,
                        "PlanExpansion",
                        {
                            "fundedExpansionSlots": 2,
                            "engineers": ordered_engineers,
                            "sites": ordered_sites,
                            "regions": [],
                        },
                    )["jobs"]
                )

        assert observed == [{}] * len(observed)

    @pytest.mark.parametrize("duplicate_kind", ("engineer", "site"))
    def test_exact_duplicate_actor_or_site_identity_deduplicates_stably(
        self, duplicate_kind: str
    ) -> None:
        engineer = {
            "token": "eng",
            "position": [0, 0, 0],
            "available": True,
        }
        site = mass_site("site", 10, 0, region="region")
        engineers = [copy.deepcopy(engineer)]
        sites = [copy.deepcopy(site)]
        if duplicate_kind == "engineer":
            engineers.append(copy.deepcopy(engineer))
        else:
            sites.append(copy.deepcopy(site))

        observed = []
        for reverse_engineers in (False, True):
            for reverse_sites in (False, True):
                ordered_engineers = copy.deepcopy(engineers)
                ordered_sites = copy.deepcopy(sites)
                if reverse_engineers:
                    ordered_engineers.reverse()
                if reverse_sites:
                    ordered_sites.reverse()
                observed.append(
                    invoke(
                        MODULE,
                        GLOBAL,
                        "PlanExpansion",
                        {
                            "fundedExpansionSlots": 2,
                            "engineers": ordered_engineers,
                            "sites": ordered_sites,
                            "regions": [],
                        },
                    )["jobs"]
                )

        assert observed == [observed[0]] * len(observed)
        assert len(observed[0]) == 1
        assert observed[0][0]["actorToken"] == "eng"
        assert observed[0][0]["siteKey"] == "site"

    @pytest.mark.parametrize("malformed_side", ("engineer", "site"))
    def test_matching_rejects_malformed_positions_without_throwing(
        self, malformed_side: str
    ) -> None:
        engineer = {
            "token": "eng",
            "position": [0, 0, 0],
            "available": True,
        }
        site = mass_site("site", 10, 0, region="region")
        if malformed_side == "engineer":
            engineer["position"] = [float("nan"), 0, 0]
        else:
            site["position"] = [10, 0]

        result = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 1,
                "engineers": [engineer],
                "sites": [site],
                "regions": [],
            },
        )

        assert result == {"jobs": {}, "denials": {}}

    def test_matching_ignores_reserved_unreachable_and_disconnected_sites(self) -> None:
        reserved = mass_site("reserved", 1, 0, region="reserved-region")
        reserved["reserved"] = True
        unreachable = mass_site("unreachable", 2, 0, region="unreachable-region")
        unreachable["reachable"] = False
        unbuildable = mass_site("unbuildable", 4, 0, region="unbuildable-region")
        unbuildable["buildable"] = False
        owned = mass_site("owned", 5, 0, region="owned-region", owned=True)
        jobs = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 2,
                "engineers": [
                    {"token": "eng-a", "position": [0, 0, 0], "available": True},
                    {"token": "eng-b", "position": [5, 0, 0], "available": True},
                ],
                "sites": [
                    reserved,
                    unreachable,
                    unbuildable,
                    owned,
                    mass_site("valid-a", 10, 0, region="valid-a"),
                    mass_site("valid-b", 20, 0, region="valid-b"),
                    mass_site("disconnected", 3, 0, region="disconnected"),
                    mass_site("suspended", 6, 0, region="suspended"),
                ],
                "regions": [
                    {"key": "disconnected", "connected": False},
                    {"key": "suspended", "state": "suspended"},
                ],
            },
        )["jobs"]

        assert {job["siteKey"] for job in jobs} == {"valid-a", "valid-b"}

    def test_matching_filters_incomplete_dead_unowned_and_unavailable_actors(self) -> None:
        actor_template = {
            "position": [0, 0, 0],
            "available": True,
            "complete": True,
            "live": True,
            "owned": True,
        }
        engineers = [
            {**actor_template, "token": "incomplete", "complete": False},
            {**actor_template, "token": "dead", "live": False},
            {**actor_template, "token": "captured", "owned": False},
            {**actor_template, "token": "busy", "available": False},
            {**actor_template, "token": "valid", "position": [50, 0, 0]},
        ]

        jobs = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 1,
                "engineers": engineers,
                "sites": [mass_site("site", 1, 0)],
                "regions": [],
            },
        )["jobs"]

        assert [job["actorToken"] for job in jobs] == ["valid"]

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

    def test_multiple_remote_regions_bind_disjoint_land_and_aa_escort_pairs(self) -> None:
        snapshot = {
            "fundedExpansionSlots": 2,
            "controlledRadius": 60,
            "engineers": [
                {"token": "eng-a", "position": [0, 0, 0], "available": True},
                {"token": "eng-b", "position": [10, 0, 0], "available": True},
            ],
            "sites": [
                mass_site("a", 300, 0, region="region-a"),
                mass_site("b", 400, 0, region="region-b"),
            ],
            "regions": [
                {"key": "region-a", "state": "planned"},
                {"key": "region-b", "state": "planned"},
            ],
            "escorts": [
                {"token": "aa-a", "role": "anti_air", "available": True},
                {"token": "aa-b", "role": "anti_air", "available": True},
                {"token": "tank-a", "role": "tank", "available": True},
                {"token": "tank-b", "role": "tank", "available": True},
            ],
        }

        jobs = invoke(MODULE, GLOBAL, "PlanExpansion", snapshot)["jobs"]

        assert len(jobs) == 2
        assert set(jobs[0]["escortTokens"]).isdisjoint(jobs[1]["escortTokens"])
        assert len({token for job in jobs for token in job["escortTokens"]}) == 4

    def test_remote_actor_site_and_escort_pairing_is_permutation_stable(self) -> None:
        engineers = [
            {"token": "eng-a", "position": [0, 0, 0], "available": True},
            {"token": "eng-b", "position": [10, 0, 0], "available": True},
        ]
        sites = [
            mass_site("site-a", 300, 0, region="region-a"),
            mass_site("site-b", 400, 0, region="region-b"),
        ]
        escorts = [
            {"token": "aa-a", "role": "anti_air", "available": True},
            {"token": "aa-b", "role": "anti_air", "available": True},
            {"token": "tank-a", "role": "tank", "available": True},
            {"token": "tank-b", "role": "tank", "available": True},
        ]
        observed = []

        for reverse_engineers in (False, True):
            for reverse_sites in (False, True):
                for reverse_escorts in (False, True):
                    ordered_engineers = copy.deepcopy(engineers)
                    ordered_sites = copy.deepcopy(sites)
                    ordered_escorts = copy.deepcopy(escorts)
                    if reverse_engineers:
                        ordered_engineers.reverse()
                    if reverse_sites:
                        ordered_sites.reverse()
                    if reverse_escorts:
                        ordered_escorts.reverse()
                    jobs = invoke(
                        MODULE,
                        GLOBAL,
                        "PlanExpansion",
                        {
                            "fundedExpansionSlots": 2,
                            "controlledRadius": 60,
                            "engineers": ordered_engineers,
                            "sites": ordered_sites,
                            "regions": [],
                            "escorts": ordered_escorts,
                        },
                    )["jobs"]
                    observed.append(
                        sorted(
                            (
                                job["siteKey"],
                                job["actorToken"],
                                tuple(job["escortTokens"]),
                            )
                            for job in jobs
                        )
                    )

        assert observed == [observed[0]] * len(observed)
        assert len({token for job in observed[0] for token in job[2]}) == 4

    def test_remote_matching_is_bounded_by_disjoint_complete_escort_pairs(self) -> None:
        jobs = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 3,
                "controlledRadius": 60,
                "engineers": [
                    {"token": "eng-a", "position": [0, 0, 0], "available": True},
                    {"token": "eng-b", "position": [5, 0, 0], "available": True},
                    {"token": "eng-c", "position": [10, 0, 0], "available": True},
                ],
                "sites": [
                    mass_site("site-a", 300, 0, region="region-a"),
                    mass_site("site-b", 400, 0, region="region-b"),
                    mass_site("site-c", 500, 0, region="region-c"),
                ],
                "regions": [],
                "escorts": [
                    {"token": "aa-a", "role": "anti_air", "available": True},
                    {"token": "aa-b", "role": "anti_air", "available": True},
                    {"token": "tank-a", "role": "tank", "available": True},
                    {"token": "tank-b", "role": "tank", "available": True},
                    {"token": "tank-extra", "role": "tank", "available": True},
                ],
            },
        )["jobs"]

        assert len(jobs) == 2
        escort_tokens = [token for job in jobs for token in job["escortTokens"]]
        assert len(escort_tokens) == 4
        assert len(set(escort_tokens)) == 4

    def test_one_escort_identity_cannot_fill_both_roles_or_multiple_pairs(self) -> None:
        result = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 2,
                "controlledRadius": 60,
                "engineers": [
                    {"token": "eng-a", "position": [0, 0, 0], "available": True},
                    {"token": "eng-b", "position": [5, 0, 0], "available": True},
                ],
                "sites": [
                    mass_site("site-a", 300, 0, region="region-a"),
                    mass_site("site-b", 400, 0, region="region-b"),
                ],
                "regions": [],
                "escorts": [
                    {"token": "shared", "role": "anti_air", "available": True},
                    {"token": "shared", "role": "tank", "available": True},
                    {"token": "tank", "role": "tank", "available": True},
                ],
            },
        )

        assert result["jobs"] == {}
        assert len(result["denials"]) == 2

    def test_remote_capacity_denials_never_conflict_with_issued_jobs(self) -> None:
        result = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 3,
                "controlledRadius": 60,
                "engineers": [
                    {"token": "eng-a", "position": [0, 0, 0], "available": True},
                    {"token": "eng-b", "position": [5, 0, 0], "available": True},
                    {"token": "eng-c", "position": [10, 0, 0], "available": True},
                ],
                "sites": [
                    mass_site("site-a", 300, 0, region="region-a"),
                    mass_site("site-b", 400, 0, region="region-b"),
                    mass_site("site-c", 500, 0, region="region-c"),
                ],
                "regions": [],
                "escorts": [
                    {"token": "aa", "role": "anti_air", "available": True},
                    {"token": "tank", "role": "tank", "available": True},
                ],
            },
        )

        assert len(result["jobs"]) == 1
        assert len(result["denials"]) == 2
        assert {job["siteKey"] for job in result["jobs"]}.isdisjoint(
            denial["siteKey"] for denial in result["denials"]
        )
        assert len({denial["siteKey"] for denial in result["denials"]}) == 2
        assert {denial["reason"] for denial in result["denials"]} == {
            "escort_not_ready"
        }

    def test_remote_denial_survives_augmenting_actor_reassignment(self) -> None:
        result = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 2,
                "controlledRadius": 60,
                "engineers": [
                    {"token": "eng-a", "position": [0, 0, 0], "available": True},
                    {"token": "eng-b", "position": [0, 0, 0], "available": True},
                ],
                "sites": [
                    mass_site("local", 0, 0, region="local"),
                    mass_site("remote", 100, 0, region="remote"),
                ],
                "regions": [],
                "blockedActorTokensBySite": {"remote": {"eng-b": True}},
                "escorts": [],
            },
        )

        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["siteKey"] == "local"
        assert len(result["denials"]) == 1
        assert result["denials"][0]["siteKey"] == "remote"
        assert result["denials"][0]["actorToken"] == "eng-a"

    def test_nonrepresentable_remote_gap_emits_one_truthful_aggregate_denial(
        self,
    ) -> None:
        result = invoke(
            MODULE,
            GLOBAL,
            "PlanExpansion",
            {
                "fundedExpansionSlots": 3,
                "controlledRadius": 5,
                "engineers": [
                    {"token": "e0", "position": [5, 0, 0], "available": True},
                    {"token": "e1", "position": [0, 0, 0], "available": True},
                    {"token": "e2", "position": [10, 0, 0], "available": True},
                    {"token": "e3", "position": [14, 0, 0], "available": True},
                ],
                "sites": [
                    mass_site("s0", 2, 0, region="r0"),
                    mass_site("s1", 10, 0, region="r1"),
                    mass_site("s2", 1, 0, region="r2"),
                ],
                "regions": [],
                "blockedActorTokensBySite": {
                    "s0": {"e1": True},
                    "s1": {"e1": True, "e2": True, "e3": True},
                    "s2": {"e2": True},
                },
                "escorts": [],
            },
        )

        assert len(result["jobs"]) == 2
        assert result["denials"] == [
            {
                "id": "expansion:escort-capacity",
                "reason": "escort_capacity_limited",
                "blockedCount": 1,
            }
        ]

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
        assert without_screen["denials"][0]["id"] == "mex:remote:remote"
        assert without_screen["denials"][0]["actorToken"] == "eng"
        assert without_screen["denials"][0]["regionKey"] == "remote"
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

    def test_reclaim_skips_high_value_wreck_outside_the_engineers_live_vision(self) -> None:
        snapshot = {
            "regions": [
                {"key": "home", "state": "secured", "position": [0, 0, 0], "radius": 80},
            ],
            "engineers": [
                {"token": "eng", "position": [0, 0, 0], "available": True},
            ],
            "candidates": [
                {
                    "key": "far-high",
                    "position": [70, 0, 0],
                    "mass": 500,
                    "visible": True,
                    "live": True,
                    "visionRadius": 32,
                },
                {
                    "key": "near-low",
                    "position": [10, 0, 0],
                    "mass": 40,
                    "visible": True,
                    "live": True,
                    "visionRadius": 32,
                },
            ],
        }

        jobs = invoke(MODULE, GLOBAL, "PlanReclaim", snapshot)["jobs"]

        assert [(job["actorToken"], job["targetKey"]) for job in jobs] == [
            ("eng", "near-low"),
        ]

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
                    "ordered": True,
                    "orderedActorToken": "eng-1:1",
                    "orderedAttempt": 0,
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
        assert "ordered" not in released["jobs"]["mex:front:1"]
        assert "orderedActorToken" not in released["jobs"]["mex:front:1"]
        assert "orderedAttempt" not in released["jobs"]["mex:front:1"]
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

    def test_retryable_job_observes_external_site_completion_once(self) -> None:
        ledger = {
            "jobs": {
                "mex:front:1": {
                    "id": "mex:front:1",
                    "kind": "rebuild_mex",
                    "phase": "retryable",
                    "failureReason": "actor_unavailable",
                    "actorToken": "eng-1:1",
                    "actorLineage": {"eng-1": "eng-1:1"},
                    "targetKey": "front-1",
                    "retryCount": 1,
                }
            }
        }
        completed_snapshot = {
            "tick": 300,
            "newJobs": [],
            "actors": [
                {
                    "token": "eng-1:2",
                    "role": "engineer",
                    "complete": True,
                    "live": True,
                    "owned": True,
                    "available": True,
                    "canBuild": {"mass_extractor": True},
                    "position": [90, 0, 0],
                }
            ],
            "targets": [
                {
                    "key": "front-1",
                    "live": True,
                    "completed": True,
                    "position": [100, 0, 0],
                }
            ],
        }

        completed = invoke(
            MODULE, GLOBAL, "UpdateJobLedger", ledger, completed_snapshot
        )
        repeated = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            completed,
            {**completed_snapshot, "tick": 301},
        )

        completed_job = completed["jobs"]["mex:front:1"]
        assert completed_job["phase"] == "completed"
        assert "failureReason" not in completed_job
        assert completed_job["actorLineage"] == {"eng-1": "eng-1:1"}
        assert len(completed["releasedActorTokens"]) == 0
        assert repeated["jobs"]["mex:front:1"] == completed_job
        assert len(repeated["releasedActorTokens"]) == 0

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
            {
                "token": "eng-1:1",
                "role": "tank",
                "complete": True,
                "live": True,
                "owned": True,
                "canBuild": {"mass_extractor": True},
                "position": [20, 0, 0],
            },
            {
                "token": "eng-1:1",
                "role": "engineer",
                "complete": False,
                "live": True,
                "owned": True,
                "canBuild": {"mass_extractor": True},
                "position": [20, 0, 0],
            },
            {
                "token": "eng-1:1",
                "role": "engineer",
                "complete": True,
                "live": True,
                "owned": True,
                "canBuild": {"mass_extractor": False},
                "position": [20, 0, 0],
            },
            {
                "token": "eng-1:1",
                "role": "engineer",
                "complete": True,
                "live": True,
                "owned": True,
                "canBuild": {"mass_extractor": True},
            },
            {
                "token": "eng-1:1",
                "role": "engineer",
                "complete": True,
                "live": True,
                "owned": True,
                "canBuild": {"mass_extractor": True},
                "position": [float("nan"), 0, 0],
            },
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
                            "role": "engineer",
                            "complete": True,
                            "live": True,
                            "owned": True,
                            "available": True,
                            "canBuild": {"mass_extractor": True},
                            "position": [90, 0, 0],
                        },
                        {
                            "token": "eng-far:1",
                            "role": "engineer",
                            "complete": True,
                            "live": True,
                            "owned": True,
                            "available": True,
                            "canBuild": {"mass_extractor": True},
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

    def test_job_replacement_rejects_every_ineligible_or_recycled_actor_and_chooses_nearest_capable_engineer(self) -> None:
        ledger = {
            "jobs": {
                "mex:front:1": {
                    "id": "mex:front:1",
                    "kind": "build_mex",
                    "phase": "travelling",
                    "actorToken": "original:1",
                    "targetKey": "front-1",
                    "deadlineTick": 900,
                    "lastProgressTick": 100,
                    "remainingDistance": 100,
                    "retryCount": 0,
                    "ordered": True,
                    "orderedActorToken": "original:1",
                    "orderedAttempt": 0,
                }
            }
        }
        base = {
            "role": "engineer",
            "complete": True,
            "live": True,
            "owned": True,
            "available": True,
            "canBuild": {"mass_extractor": True},
        }
        actors = [
            {**base, "token": "original:1", "live": False, "position": [0, 0, 0]},
            {**base, "token": "original:2", "position": [99, 0, 0]},
            {**base, "token": "tank:1", "role": "tank", "position": [98, 0, 0]},
            {**base, "token": "factory:1", "role": "land_factory", "position": [97, 0, 0]},
            {**base, "token": "dead:1", "live": False, "position": [96, 0, 0]},
            {**base, "token": "captured:1", "owned": False, "position": [95, 0, 0]},
            {**base, "token": "unfinished:1", "complete": False, "position": [94, 0, 0]},
            {**base, "token": "busy:1", "available": False, "position": [93, 0, 0]},
            {
                **base,
                "token": "incapable:1",
                "canBuild": {"mass_extractor": False},
                "position": [92, 0, 0],
            },
            {**base, "token": "missing-position:1"},
            {**base, "token": "nan-position:1", "position": [float("nan"), 0, 0]},
            {**base, "token": "missing-generation", "position": [91, 0, 0]},
            {**base, "token": "valid-near:3", "position": [80, 0, 0]},
            {**base, "token": "valid-far:1", "position": [20, 0, 0]},
        ]

        result = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            ledger,
            {
                "tick": 200,
                "newJobs": [],
                "actors": actors,
                "targets": [
                    {"key": "front-1", "live": True, "position": [100, 0, 0]}
                ],
            },
        )

        job = result["jobs"]["mex:front:1"]
        assert job["actorToken"] == "valid-near:3"
        assert job["phase"] == "travelling"
        assert job["retryCount"] == 1
        assert "ordered" not in job
        assert "orderedActorToken" not in job
        assert "orderedAttempt" not in job
        assert result["releasedActorTokens"] == ["original:1"]

    def test_job_replacement_fails_closed_when_no_complete_owned_mex_capable_engineer_exists(self) -> None:
        ledger = {
            "jobs": {
                "mex:front:1": {
                    "id": "mex:front:1",
                    "kind": "rebuild_mex",
                    "phase": "travelling",
                    "actorToken": "original:1",
                    "targetKey": "front-1",
                    "deadlineTick": 900,
                    "retryCount": 0,
                }
            }
        }

        result = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            ledger,
            {
                "tick": 200,
                "newJobs": [],
                "actors": [
                    {
                        "token": "original:2",
                        "role": "engineer",
                        "complete": True,
                        "live": True,
                        "owned": True,
                        "available": True,
                        "canBuild": {"mass_extractor": True},
                        "position": [99, 0, 0],
                    },
                    {
                        "token": "near-tank:1",
                        "role": "tank",
                        "complete": True,
                        "live": True,
                        "owned": True,
                        "available": True,
                        "canBuild": {"mass_extractor": True},
                        "position": [98, 0, 0],
                    },
                ],
                "targets": [
                    {"key": "front-1", "live": True, "position": [100, 0, 0]}
                ],
            },
        )

        job = result["jobs"]["mex:front:1"]
        assert job["phase"] == "retryable"
        assert job["failureReason"] == "actor_unavailable"
        assert job["retryCount"] == 1

    def test_active_job_claim_reassigns_a_conflicting_new_job_to_an_exact_free_engineer(self) -> None:
        ledger = {
            "epoch": 1,
            "jobs": {
                "mex:a": {
                    "id": "mex:a",
                    "kind": "build_mex",
                    "actorToken": "eng-1:1",
                    "targetKey": "site-a",
                    "phase": "travelling",
                    "deadlineTick": 900,
                    "lastProgressTick": 100,
                    "remainingDistance": 100,
                    "retryCount": 0,
                }
            },
        }
        incoming = {
            "id": "mex:b",
            "kind": "build_mex",
            "actorToken": "eng-1:1",
            "targetKey": "site-b",
            "position": [200, 0, 0],
            "estimatedTravelTicks": 300,
        }
        actors = [
            {
                "token": "eng-1:1",
                "role": "engineer",
                "complete": True,
                "live": True,
                "owned": True,
                "available": True,
                "canBuild": {"mass_extractor": True},
                "position": [100, 0, 0],
            },
            {
                "token": "eng-2:1",
                "role": "engineer",
                "complete": True,
                "live": True,
                "owned": True,
                "available": True,
                "canBuild": {"mass_extractor": True},
                "position": [190, 0, 0],
            },
        ]
        targets = [
            {"key": "site-a", "live": True, "position": [0, 0, 0]},
            {"key": "site-b", "live": True, "position": [200, 0, 0]},
        ]

        result = invoke(
            MODULE,
            GLOBAL,
            "UpdateJobLedger",
            ledger,
            {"tick": 200, "newJobs": [incoming], "actors": actors, "targets": targets},
        )

        active = [
            job
            for job in result["jobs"].values()
            if job["phase"] not in {"completed", "retryable", "cancelled"}
        ]
        assert result["jobs"]["mex:a"]["actorToken"] == "eng-1:1"
        assert result["jobs"]["mex:b"]["actorToken"] == "eng-2:1"
        assert len({job["actorToken"] for job in active}) == len(active) == 2

    def test_conflicting_new_job_without_free_exact_engineer_is_rejected_atomically(self) -> None:
        incoming_jobs = [
            {
                "id": job_id,
                "kind": "build_mex",
                "actorToken": "eng-1:1",
                "targetKey": site,
                "position": position,
                "estimatedTravelTicks": 300,
            }
            for job_id, site, position in (
                ("mex:a", "site-a", [100, 0, 0]),
                ("mex:b", "site-b", [200, 0, 0]),
            )
        ]
        actor = {
            "token": "eng-1:1",
            "role": "engineer",
            "complete": True,
            "live": True,
            "owned": True,
            "available": True,
            "canBuild": {"mass_extractor": True},
            "position": [0, 0, 0],
        }
        targets = [
            {"key": "site-a", "live": True, "position": [100, 0, 0]},
            {"key": "site-b", "live": True, "position": [200, 0, 0]},
        ]
        results = []
        for ordered in (incoming_jobs, list(reversed(incoming_jobs))):
            results.append(
                invoke(
                    MODULE,
                    GLOBAL,
                    "UpdateJobLedger",
                    {"jobs": {}},
                    {
                        "tick": 100,
                        "newJobs": ordered,
                        "actors": [actor],
                        "targets": targets,
                    },
                )
            )

        assert results[0] == results[1]
        active = [
            job
            for job in results[0]["jobs"].values()
            if job["phase"] not in {"completed", "retryable", "cancelled"}
        ]
        rejected = [
            job for job in results[0]["jobs"].values()
            if job["phase"] == "retryable"
        ]
        assert [(job["id"], job["actorToken"]) for job in active] == [
            ("mex:a", "eng-1:1")
        ]
        assert rejected[0]["id"] == "mex:b"
        assert rejected[0]["failureReason"] == "actor_already_claimed"

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
            "mex": [
                {"key": f"mex-{index}", "tier": 2 if index < 2 else 1}
                for index in range(8)
            ],
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

    def test_two_staggered_t2_mex_upgrades_precede_the_land_hq(self) -> None:
        before_mex_tech = {
            "economyHealthy": True,
            "techFunded": True,
            "t2HqComplete": False,
            "landFactories": [
                {"token": "land-a", "tier": 1, "idle": True},
                {"token": "land-b", "tier": 1, "idle": True},
            ],
            "mex": [
                {"key": f"mex-{index}", "tier": 1, "upgrading": False}
                for index in range(10)
            ],
            "activeMexUpgrades": 0,
        }
        after_two_upgrades = copy.deepcopy(before_mex_tech)
        after_two_upgrades["mex"][0]["tier"] = 2
        after_two_upgrades["mex"][1]["tier"] = 2

        mex_plan = invoke(MODULE, GLOBAL, "PlanTech", before_mex_tech)
        hq_plan = invoke(MODULE, GLOBAL, "PlanTech", after_two_upgrades)

        assert mex_plan["hqAction"] == "hold"
        assert mex_plan["mexUpgradeSiteKeys"] == ["mex-0"]
        assert mex_plan["mexUpgradeRolesBySite"]["mex-0"] == "mass_extractor_t2"
        assert hq_plan["hqAction"] == "start_t2"
        assert not hq_plan["mexUpgradeSiteKeys"]

    def test_t2_hq_counts_busy_functioning_t1_lane_while_selecting_only_idle_upgrade_source(self) -> None:
        snapshot = {
            "tick": 5700,
            "economyHealthy": True,
            "techFunded": True,
            "t2HqComplete": False,
            "landFactories": [
                {
                    "token": "busy-lane",
                    "tier": 1,
                    "idle": False,
                    "live": True,
                    "complete": True,
                    "functioning": True,
                },
                {
                    "token": "idle-source",
                    "tier": 1,
                    "idle": True,
                    "live": True,
                    "complete": True,
                    "functioning": True,
                },
                {
                    "token": "dead-nearer",
                    "tier": 1,
                    "idle": True,
                    "live": False,
                    "complete": True,
                    "functioning": True,
                },
                {
                    "token": "unfinished",
                    "tier": 1,
                    "idle": True,
                    "live": True,
                    "complete": False,
                    "functioning": True,
                },
            ],
            "mex": [
                {"key": "mex-t2-a", "tier": 2},
                {"key": "mex-t2-b", "tier": 2},
            ],
        }

        plan = invoke(MODULE, GLOBAL, "PlanTech", snapshot)

        assert plan["hqAction"] == "start_t2"
        assert plan["hqSourceToken"] == "idle-source"
        assert plan["remainingT1ProductionLanes"] == 1

        snapshot["landFactories"] = snapshot["landFactories"][1:]
        blocked = invoke(MODULE, GLOBAL, "PlanTech", snapshot)
        assert blocked["hqAction"] == "hold"
        assert blocked["hqDenialReason"] == "preserve_final_t1_lane"

    def test_t2_hq_does_not_count_an_already_upgrading_factory_as_a_t1_production_lane(self) -> None:
        snapshot = {
            "economyHealthy": True,
            "techFunded": True,
            "t2HqComplete": False,
            "landFactories": [
                {
                    "token": "already-upgrading",
                    "tier": 1,
                    "idle": False,
                    "live": True,
                    "complete": True,
                    "functioning": True,
                    "upgrading": True,
                },
                {
                    "token": "last-t1-lane",
                    "tier": 1,
                    "idle": True,
                    "live": True,
                    "complete": True,
                    "functioning": True,
                    "upgrading": False,
                },
            ],
            "mex": [
                {"key": "mex-t2-a", "tier": 2},
                {"key": "mex-t2-b", "tier": 2},
            ],
        }

        plan = invoke(MODULE, GLOBAL, "PlanTech", snapshot)

        assert plan["hqAction"] == "hold"
        assert plan["hqDenialReason"] == "preserve_final_t1_lane"
        assert plan["remainingT1ProductionLanes"] == 1

    def test_funded_completed_t2_hq_admits_one_support_lane_without_consuming_final_t1_lane(self) -> None:
        ready = {
            "tick": 6200,
            "economyHealthy": True,
            "techFunded": True,
            "t2HqComplete": True,
            "t2SupportFactoryCount": 0,
            "landFactories": [
                {"token": "land-a", "tier": 1, "idle": True},
                {"token": "land-b", "tier": 1, "idle": True},
                {"token": "hq", "tier": 2, "idle": True, "hq": True},
            ],
            "mex": [],
        }

        plan = invoke(MODULE, GLOBAL, "PlanTech", ready)

        assert plan["supportAction"] == "start_t2_support"
        assert plan["supportSourceToken"] == "land-a"
        assert plan["supportUpgradeRole"] == "land_factory_t2_support"
        assert plan["remainingT1ProductionLanes"] == 1

        one_t1 = copy.deepcopy(ready)
        one_t1["landFactories"] = one_t1["landFactories"][1:]
        blocked = invoke(MODULE, GLOBAL, "PlanTech", one_t1)
        assert blocked["supportAction"] == "hold"
        assert blocked["supportDenialReason"] == "preserve_final_t1_lane"

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
