from typing import TypeVar, Optional

T = TypeVar('T')

def nullthrows(value: Optional[T]) -> T:
    if value is None:
        raise ValueError("Expected non-null value")
    return value