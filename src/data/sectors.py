"""Phase 3.6 sector stub for stock headline pills.

STUB: replace with TWSE industry classification fetch in Phase 7.
"""

from typing import Optional

_SECTOR_MAP: dict[str, str] = {
    "2330": "半導體",
    "2317": "電子代工",
    "2454": "半導體",
    "3037": "PCB",
    "2412": "電信",
    "1301": "塑膠",
    "2603": "航運",
    "2882": "金融",
    "1101": "水泥",
    "2002": "鋼鐵",
    "6505": "石化",
    "3008": "光學",
    "2891": "金融",
    "2615": "航運",
    "8046": "PCB",
    "3661": "IC設計",
    "6488": "IC設計",
    "2207": "汽車",
    "9910": "運動用品",
}


def get_sector(stock_id: str) -> Optional[str]:
    """Return a deterministic sector label for the headline pill."""
    return _SECTOR_MAP.get(str(stock_id))
