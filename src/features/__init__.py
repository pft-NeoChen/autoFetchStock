"""Feature engineering modules for profitability workflow."""

from src.features.availability import (
    AVAILABILITY_RULES,
    UnknownFeatureError,
    availability_of,
)
from src.features.corporate_actions import (
    CorporateActionEvent,
    apply_backward_adjustment,
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
    "UnknownFeatureError",
    "apply_backward_adjustment",
    "atr",
    "availability_of",
    "classify_volume_severity",
    "daily_return",
    "daily_volume_baseline",
    "daily_volume_ratio",
    "moving_average",
    "price_feature_providers",
    "rolling_volatility",
    "volume_feature_providers",
]
