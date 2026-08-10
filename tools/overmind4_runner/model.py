from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


MOD_UID = "0d46fbb2-beeb-4bde-b3c6-8bac28232a4b"
FAF_COMMIT = "602185eb0753d205080313cc294d5665b49681cb"
FAF_BUILD = 3836

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SAFE_MAP_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ValidationError(ValueError):
    """A run would be ambiguous, unsafe, or outside the supported slice."""


def validate_identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValidationError(
            f"{field} must be 1-64 ASCII letters, digits, underscores, or hyphens"
        )
    return value


def validate_map_identifier(value: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_MAP_IDENTIFIER.fullmatch(value)
        or ".." in value
    ):
        raise ValidationError(
            "map must be a safe vault identifier (version suffixes such as .v0004 are allowed)"
        )
    return value


def _bounded_integer(value: Any, field: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValidationError(f"{field} must be an integer from {low} through {high}")
    return value


@dataclass(frozen=True)
class AISpec:
    slot: int
    key: str
    faction: int
    team: int

    def __post_init__(self) -> None:
        _bounded_integer(self.slot, "AI slot", 1, 16)
        validate_identifier(self.key, "AI key")
        _bounded_integer(self.faction, "AI faction", 1, 4)
        _bounded_integer(self.team, "AI team", 1, 16)

    @property
    def wire(self) -> str:
        return f"{self.slot}:{self.key}:{self.faction}:{self.team}"

    @classmethod
    def parse(cls, value: str) -> "AISpec":
        if not isinstance(value, str):
            raise ValidationError("AI spec must be text")
        fields = value.split(":")
        if len(fields) != 4:
            raise ValidationError("AI spec must be slot:key:faction:team")
        try:
            slot, faction, team = int(fields[0]), int(fields[2]), int(fields[3])
        except ValueError as error:
            raise ValidationError("AI slot, faction, and team must be integers") from error
        return cls(slot=slot, key=fields[1], faction=faction, team=team)


@dataclass(frozen=True)
class RunConfig:
    map_id: str = "SCMP_007"
    seed: int = 7777
    speed: int = 25
    sim_time_limit: int = 1800
    wall_time_limit: int = 300
    our_ai: str = "overmind4"
    opponent_ai: str = "easy"
    our_faction: int = 1
    opponent_faction: int = 1
    our_slot: int = 1
    opponent_slot: int = 2
    our_team: int = 1
    opponent_team: int = 2
    unit_cap: int = 1000

    def __post_init__(self) -> None:
        validate_map_identifier(self.map_id)
        _bounded_integer(self.seed, "seed", 0, 2_147_483_647)
        _bounded_integer(self.speed, "speed", 1, 100)
        _bounded_integer(self.sim_time_limit, "sim-time", 1, 86_400)
        _bounded_integer(self.wall_time_limit, "wall-time", 1, 86_400)
        validate_identifier(self.our_ai, "our AI key")
        validate_identifier(self.opponent_ai, "opponent AI key")
        _bounded_integer(self.our_faction, "our faction", 1, 4)
        _bounded_integer(self.opponent_faction, "opponent faction", 1, 4)
        _bounded_integer(self.our_slot, "our slot", 1, 16)
        _bounded_integer(self.opponent_slot, "opponent slot", 1, 16)
        _bounded_integer(self.our_team, "our team", 1, 16)
        _bounded_integer(self.opponent_team, "opponent team", 1, 16)
        _bounded_integer(self.unit_cap, "unit cap", 1, 10_000)
        if self.our_slot == self.opponent_slot:
            raise ValidationError("the two AIs require distinct slots")
        if self.our_team == self.opponent_team:
            raise ValidationError("the two AIs require opposing teams")

    @property
    def ai_specs(self) -> tuple[AISpec, AISpec]:
        return (
            AISpec(self.our_slot, self.our_ai, self.our_faction, self.our_team),
            AISpec(
                self.opponent_slot,
                self.opponent_ai,
                self.opponent_faction,
                self.opponent_team,
            ),
        )

    def document(self) -> dict[str, Any]:
        return asdict(self)
