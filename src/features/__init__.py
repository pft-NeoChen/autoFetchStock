"""Feature engineering modules for profitability workflow."""

from src.features.availability import (
    AVAILABILITY_RULES,
    UnknownFeatureError,
    availability_of,
)
from src.features.chip_features import (
    chip_feature_providers,
    foreign_net_streak,
    margin_n_day_change,
    rolling_net_buy,
)
from src.features.corporate_actions import (
    CorporateActionEvent,
    apply_backward_adjustment,
)
from src.features.news_features import (
    NewsRecord,
    aggregate_news_by_day,
    assign_effective_date,
    news_feature_providers,
)
from src.features.price_features import (
    atr,
    daily_return,
    moving_average,
    price_feature_providers,
    rolling_volatility,
)
from src.features.store import (
    FeatureProvider,
    FeatureStore,
    FeatureValue,
    LookAheadError,
)
from src.features.volume_features import (
    classify_volume_severity,
    daily_volume_baseline,
    daily_volume_ratio,
    volume_feature_providers,
)

__all__ = [
    "AVAILABILITY_RULES",
    "CorporateActionEvent",
    "FeatureProvider",
    "FeatureStore",
    "FeatureValue",
    "LookAheadError",
    "NewsRecord",
    "UnknownFeatureError",
    "aggregate_news_by_day",
    "assign_effective_date",
    "news_feature_providers",
    "apply_backward_adjustment",
    "atr",
    "availability_of",
    "chip_feature_providers",
    "classify_volume_severity",
    "daily_return",
    "daily_volume_baseline",
    "daily_volume_ratio",
    "foreign_net_streak",
    "margin_n_day_change",
    "moving_average",
    "price_feature_providers",
    "rolling_net_buy",
    "rolling_volatility",
    "volume_feature_providers",
]
