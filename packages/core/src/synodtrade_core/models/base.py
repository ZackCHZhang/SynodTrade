"""Common base and field types for domain models."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class CoreModel(BaseModel):
    """Immutable, strict-shape base for records passed between packages."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _upper_symbol(value: str) -> str:
    value = value.strip().upper()
    if not value:
        raise ValueError("symbol must not be empty")
    return value


Symbol = Annotated[str, AfterValidator(_upper_symbol)]
Money = Annotated[Decimal, Field(allow_inf_nan=False)]
NonNegativeMoney = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
PositiveMoney = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Quantity = Annotated[Decimal, Field(allow_inf_nan=False)]
PositiveQuantity = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Probability = Annotated[float, Field(ge=0.0, le=1.0)]
SentimentScore = Annotated[float, Field(ge=-1.0, le=1.0)]
