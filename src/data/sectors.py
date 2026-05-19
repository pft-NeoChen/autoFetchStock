"""Sector / industry tag resolver for the stock-header tag strip.

``get_tags`` resolves the strip from Shioaji's ``Contract.category``
(mapped through ``_TWSE_CATEGORY_LABEL``). ``_SECTOR_MAP`` /
``get_sector`` remain for legacy callers (news summariser, etc.).
"""

import logging
from functools import lru_cache
from typing import List, Optional

logger = logging.getLogger("autofetchstock.sectors")

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


# TWSE official industry code → Chinese label.
# Source: 公開資訊觀測站「上市/上櫃公司產業類別」分類碼。
# Shioaji's `Contract.category` returns the same code string.
_TWSE_CATEGORY_LABEL: dict[str, str] = {
    "01": "水泥",
    "02": "食品",
    "03": "塑膠",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "08": "玻璃陶瓷",
    "09": "造紙",
    "10": "鋼鐵",
    "11": "橡膠",
    "12": "汽車",
    "13": "電子",
    "14": "建材營造",
    "15": "航運",
    "16": "觀光",
    "17": "金融保險",
    "18": "貿易百貨",
    "19": "綜合",
    "20": "其他",
    "21": "化學工業",
    "22": "生技醫療",
    "23": "油電燃氣",
    "24": "半導體",
    "25": "電腦及週邊",
    "26": "光電",
    "27": "通信網路",
    "28": "電子零組件",
    "29": "電子通路",
    "30": "資訊服務",
    "31": "其他電子",
    "32": "文化創意",
    "80": "管理股票",
}


@lru_cache(maxsize=1024)
def _category_label_from_shioaji(stock_id: str) -> Optional[str]:
    """Resolve a stock's TWSE category via Shioaji's Contract.category.

    Cached so repeated header refreshes don't keep poking Contract
    lookups. Cache is process-local — restart the app to refresh.
    Returns ``None`` when Shioaji is offline / the lookup fails / the
    category code is not in the mapping table.
    """
    try:
        from src.fetcher.shioaji_fetcher import ShioajiFetcher
    except Exception:
        return None
    try:
        fetcher = ShioajiFetcher()
    except Exception:
        return None
    code = fetcher.get_category(stock_id)
    if not code:
        return None
    return _TWSE_CATEGORY_LABEL.get(code) or _TWSE_CATEGORY_LABEL.get(code.zfill(2))


def get_tags(stock_id: str) -> List[str]:
    """Return the list of industry tags shown in the stock-header tag strip.

    Source: Shioaji ``Contract.category`` mapped through
    ``_TWSE_CATEGORY_LABEL``. Returns ``[]`` when Shioaji is offline or
    the lookup fails so the strip collapses.
    """
    label = _category_label_from_shioaji(str(stock_id))
    return [label] if label else []
