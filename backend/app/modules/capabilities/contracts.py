from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class CapabilityScope(str, Enum):
    TENANT = "TENANT"
    STORE = "STORE"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True)
class CapabilityContract:
    """Versioned public contract for an independently evolvable capability."""

    key: str
    name: str
    version: str
    scope: CapabilityScope
    description: str
    requires: tuple[str, ...] = ()
    configuration_schema: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.key or self.key.lower() != self.key:
            raise ValueError("Capability keys must be non-empty lowercase identifiers.")
        if self.key in self.requires:
            raise ValueError(f"Capability {self.key} cannot depend on itself.")
