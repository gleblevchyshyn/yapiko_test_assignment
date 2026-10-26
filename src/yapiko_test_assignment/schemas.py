from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

DeliveryType = Literal["delivery", "pickup"]
Payment = Literal["cash", "card_courier", "online"]


class Item(BaseModel):
    sku: str
    qty: int = Field(ge=1)
    options: dict[str, str] = Field(default_factory=dict)
    comment: str | None = None


class AmbiguousItem(BaseModel):
    text: str
    qty: int = Field(ge=1)
    candidates: list[str]


class Delivery(BaseModel):
    type: DeliveryType | None = None
    address: str | None = None
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


class ParseRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    now: datetime | None = None


class ParseResponse(BaseModel):
    items: list[Item] = Field(default_factory=list)
    ambiguous: list[AmbiguousItem] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    delivery: Delivery = Field(default_factory=Delivery)
    payment: Payment | None = None
    persons: int | None = Field(default=None, ge=1)
    total_uah: int = Field(ge=0)
    needs_clarification: bool
    
    
class MenuItem(BaseModel):
    sku: str
    category: str
    name: str
    weight: str
    pieces: int | None = None
    price_uah: int
    options: dict[str, dict[str, int]] = {}
    
    @field_validator("pieces", mode="before")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        return value or None
    
    @field_validator("options", mode="before")
    @classmethod
    def parse_options(cls, value: str | dict | None) -> dict:
        if not value:
            return {}
        if isinstance(value, dict):
            return value

        option_name, raw_choices = value.split(":", 1)
        choices = {}
        for raw_choice in raw_choices.split("|"):
            choice_name, surcharge = raw_choice.strip().rsplit(" ", 1)
            choices[choice_name] = int(surcharge)
        return {option_name.strip(): choices}