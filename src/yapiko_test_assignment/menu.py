from pathlib import Path
from csv import DictReader
import logging
import json

from .schemas import MenuItem


logger = logging.getLogger(__name__)


class StopListProvider:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._mtime: float | None = None
        self._skus: set[str] = set()
        self.get()

    def get(self) -> set[str]:
        mtime = self._path.stat().st_mtime
        if mtime != self._mtime:
            self._skus = load_stop_list(self._path)
            self._mtime = mtime
            logger.info("Stop list loaded: %s", sorted(self._skus))
        return self._skus


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

    return set(data["unavailable_skus"])
