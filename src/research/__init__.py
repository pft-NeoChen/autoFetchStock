"""Research-only helpers.

Production signal modules must not import this package. Strategies that pass
research gates should be promoted into ``src.signals.rules`` explicitly.
"""

from src.research.event_study import (
    EventStudyResult,
    GateVerdict,
    compute_forward_returns,
    evaluate_event_study_gate,
    event_study,
)

__all__ = [
    "EventStudyResult",
    "GateVerdict",
    "compute_forward_returns",
    "evaluate_event_study_gate",
    "event_study",
]
