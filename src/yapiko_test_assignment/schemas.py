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
    

class OptionChoice(BaseModel):
    name: str = Field(description="Option name exactly as in the menu, e.g. 'Борт'.")
    choice: str = Field(description="Chosen value exactly as in the menu, e.g. 'Сирний'.")    


class Mention(BaseModel):
    text: str = Field(
        description=(
            "Exact fragment of the customer's message that refers to this dish, "
            "copied as written (same language, same word form)."
        )
    )
    qty: int = Field(
        default=1,
        ge=1,
        description=(
            "Number of units ordered. Default 1 if not stated. "
            "If an amount is given in volume or weight, convert it to the number "
            "of menu units using the item's size from the menu."
        ),
    )
    candidates: list[str] = Field(
        default_factory=list,
        description=(
            "SKUs from the menu that match this mention. "
            "One SKU if the match is clear; several SKUs if the description fits "
            "multiple dishes equally well; empty list if no dish in the menu matches. "
            "Use only SKUs present in the menu. Never invent SKUs."
        ),
    )
    options: list[OptionChoice] = Field(
        default_factory=list,
        description=(
            "Options explicitly chosen by the customer. "
            "Names and choices must be copied exactly from the menu. "
            "Leave empty if the customer did not specify an option."
        ),
    )
    comment: str | None = Field(
        default=None,
        description=(
            "Customer's request to modify this specific dish (e.g. 'no onion'), "
            "in the customer's words. May appear anywhere in the message. Null if none."
        ),
    )


class LLMOutput(BaseModel):
    mentions: list[Mention] = Field(
        default_factory=list,
        description=(
            "Every specific dish or drink the customer wants to order, "
            "including ones not found in the menu. "
            "Do not include service requests (e.g. napkins, cutlery) "
            "or general preferences without a specific dish (e.g. a request for recommendations)."
        ),
    )
    delivery_type: DeliveryType | None = Field(
        default=None,
        description=(
            "'delivery' if the customer gives a delivery address or asks for delivery; "
            "'pickup' if the customer says they will pick up the order; "
            "null if it is unclear."
        ),
    )
    address: str | None = Field(
        default=None,
        description=(
            "Delivery address, or pickup location for pickup, as written by the customer. "
            "Null if no concrete address is given (e.g. the customer refers to a previous order)."
        ),
    )
    time: str | None = Field(
        default=None,
        description=(
            "Requested delivery or pickup time in HH:MM 24-hour format. "
            "Null if not specified or if the customer asks for 'as soon as possible'."
        ),
    )
    payment: Payment | None = Field(
        default=None,
        description=(
            "'cash' for cash; 'card_courier' for card payment to the courier; "
            "'online' for online payment. Null if not mentioned."
        ),
    )
    persons: int | None = Field(
        default=None,
        ge=1,
        description="Number of people, only if the customer states it explicitly. Null otherwise.",
    )