from dataclasses import asdict, dataclass
from typing import Any


PREFERRED_PLATFORM_IDS = (
    "hqchip", "ichunt", "allchips", "szlcsc", "hqbuy", "bomman",
)

PLATFORMS = (
    ("hqchip", "华秋"),
    ("ichunt", "猎芯"),
    ("allchips", "硬之城"),
    ("szlcsc", "立创"),
    ("hqbuy", "华强"),
    ("bomman", "圣禾堂"),
    ("digikey", "Digi-Key"),
    ("mouser", "Mouser"),
    ("ickey", "云汉芯城"),
    ("ickeyvip", "芯晶采"),
    ("findchips", "FindChips"),
    ("icgoo", "ICGOO商城"),
)

PLATFORM_NAMES = dict(PLATFORMS)


@dataclass(frozen=True)
class Settings:
    node: str
    fast_cli: str
    chrome: str
    chrome_profile: str


@dataclass(frozen=True)
class CollectionRequest:
    model: str
    platform: str
    brand: str = ""
    brand_variants: tuple[str, ...] = ()
    min_buy_qty: int | None = None
    max_results: int = 100


@dataclass(frozen=True)
class CaptureRequest:
    item_id: str
    url: str
    filename: str


@dataclass(frozen=True)
class InputRow:
    row_number: int
    sku: str
    model: str
    brand: str
    supply_price: float | None
    moq: int | None


@dataclass
class ItemResult:
    row_number: int
    sku: str
    model: str
    status: str
    reason: str
    platform: str = ""
    platform_name: str = ""
    url: str = ""
    matched_model: str = ""
    matched_brand: str = ""
    quantity: float | None = None
    price: float | None = None
    screenshot: str = ""
    screenshot_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ItemResult":
        return cls(**value)
