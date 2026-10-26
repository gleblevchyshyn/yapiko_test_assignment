from pathlib import Path
from csv import DictReader
import json

from .schemas import MenuItem

def load_menu(path: Path) -> dict[str, MenuItem]:
    menu: dict[str, MenuItem] = {}

    with open(path, encoding="utf-8-sig", newline="") as file:
       for row in DictReader(file):
           item = MenuItem.model_validate(row)
           if item.sku in menu:
               raise ValueError(f"Duplicate SKU in menu: {item.sku}")
           
           menu[item.sku] = item
        
    return menu


def load_stop_list(path: Path) -> set[str]:
    with open(path, encoding="utf-8") as file:
      data = json.load(file)
      
    return set(data['unavailable_skus'])
