from enum import Enum
from typing import TypeVar

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


EnumT = TypeVar("EnumT", bound=Enum)


class EnumString(TypeDecorator):
    """Persist Python string enums as canonical VARCHAR columns.

    PostgreSQL receives ordinary strings (avoiding native-enum migration drift),
    while application code always receives the declared Enum class.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_class: type[EnumT], length: int = 50) -> None:
        self.enum_class = enum_class
        super().__init__(length=length)

    def process_bind_param(self, value: EnumT | str | None, dialect):
        if value is None:
            return None
        return value.value if isinstance(value, self.enum_class) else str(value)

    def process_result_value(self, value: str | None, dialect):
        if value is None:
            return None
        return self.enum_class(value)
