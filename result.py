from dataclasses import dataclass
# 
from typing import Generic, TypeVar

T = TypeVar("T")

@dataclass
class Error:
    message: str
    code: str | None = None
    details: dict | None = None


@dataclass
class Result(Generic[T]):
    """Generic success/error wrapper"""
    value: T | None = None
    error: Error | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None

    @property
    def is_error(self) -> bool:
        return self.error is not None


# Optional: helper functions to make creation cleaner
def Ok(value: T) -> Result[T]:
    return Result(value=value)


def Err(message: str, code: str | None = None, details: dict | None = None) -> Result:
    return Result(error=Error(message, code, details))
