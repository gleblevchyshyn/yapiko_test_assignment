from datetime import datetime, time
from typing import NamedTuple

from .schemas import AmbiguousItem, Delivery, Item, LLMOutput, Mention, MenuItem, OptionChoice, ParseResponse

class SortedMentions(NamedTuple):
    items: list[Item]
    ambiguous: list[AmbiguousItem]
    unavailable: list[str]
    not_found: list[str]
    
OPEN_TIME = time(11, 0)
CLOSE_TIME = time(22, 0)
    

def calculate_total(items: list[Item], menu: dict[str, MenuItem]) -> int:
    total_sum = 0
    for item in items:
        menu_item = menu[item.sku]
        surcharge = 0
        
        for option_name, choice in item.options.items():
            surcharge += menu_item.options[option_name][choice]
            
        total_sum += (menu_item.price_uah + surcharge) * item.qty
    
    return total_sum

def resolve_options(chosen: list[OptionChoice], menu_item: MenuItem) -> dict[str, str]:
    result: dict[str, str] = {}
    
    for option_name, choices in menu_item.options.items():
        for choice_name, surcharge in choices.items():
            if surcharge == 0:
                result[option_name] = choice_name
                
    for option in chosen:
        choices = menu_item.options.get(option.name, {})
        if option.choice in choices:
            result[option.name] = option.choice
            
    return result
    

def sort_mentions(mentions: list[Mention], menu: dict[str, MenuItem], stop_list: set[str]) -> SortedMentions:
    items: list[Item] = []
    ambiguous: list[AmbiguousItem] = []
    unavailable: list[str] = []
    not_found: list[str] = []
    
    for mention in mentions:
        valid = list(dict.fromkeys(sku for sku in mention.candidates if sku in menu))
        if not valid:
            not_found.append(mention.text)
            continue
        
        if len(valid) > 1:
            ambiguous.append(AmbiguousItem(text=mention.text,
                                           qty=mention.qty,
                                           candidates=valid))
            continue
        sku = valid[0]
        if sku in stop_list:
            unavailable.append(sku)
            continue
        
        items.append(Item(sku=sku,
                          qty=mention.qty,
                          options=resolve_options(mention.options, menu[sku]),
                          comment=mention.comment))
        
    return SortedMentions(items=items,
                          ambiguous=ambiguous,
                          unavailable=unavailable,
                          not_found=not_found)
    
    
def normalize_time(raw: str | None) -> str | None:
    if raw is None:
        return None
    try:
        parsed = datetime.strptime(raw.strip(), "%H:%M").time()
    except ValueError:
        return None
    return parsed.strftime("%H:%M")


def is_within_schedule(value: str) -> bool:
    t = datetime.strptime(value, "%H:%M").time()
    return OPEN_TIME <= t <= CLOSE_TIME


def needs_clarification(sorted_mentions: SortedMentions, delivery: Delivery) -> bool:
    return any([
        bool(sorted_mentions.ambiguous),
        bool(sorted_mentions.unavailable),
        bool(sorted_mentions.not_found),
        delivery.type == "delivery" and not delivery.address,
        delivery.type is None,
        delivery.time and not is_within_schedule(delivery.time),
        not sorted_mentions.items
    ])
    
    
def build_response(llm_output: LLMOutput, menu: dict[str, MenuItem], stop_list: set[str]) -> ParseResponse:
    sorted_mentions = sort_mentions(llm_output.mentions, menu, stop_list)
    delivery = Delivery(type=llm_output.delivery_type,
                        address=llm_output.address,
                        time=normalize_time(llm_output.time))
    total = calculate_total(sorted_mentions.items, menu)
    clarification = needs_clarification(sorted_mentions, delivery)
    
    return ParseResponse(items=sorted_mentions.items,
                         ambiguous=sorted_mentions.ambiguous,
                         unavailable=sorted_mentions.unavailable,
                         not_found=sorted_mentions.not_found,
                         delivery=delivery,
                         payment=llm_output.payment,
                         persons=llm_output.persons,
                         total_uah=total,
                         needs_clarification=clarification
                         )