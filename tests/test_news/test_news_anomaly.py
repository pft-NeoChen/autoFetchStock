"""
Unit tests for Phase 3c news event anomaly detection.
"""
from src.news.news_anomaly import mark_event_anomalies
from src.news.news_models import EventCluster


def test_mark_event_anomalies_flags_high_z_score():
    clusters = [
        EventCluster(
            event_id="evt",
            title="AI",
            daily_count={
                "20260421": 1,
                "20260422": 1,
                "20260423": 2,
                "20260424": 1,
                "20260425": 8,
            },
        )
    ]

    mark_event_anomalies(clusters)

    assert clusters[0].is_anomaly is True
    assert clusters[0].anomaly_score > 2
    assert "最新日文章數" in clusters[0].anomaly_reason


def test_mark_event_anomalies_does_not_flag_normal_volume():
    clusters = [
        EventCluster(
            event_id="evt",
            title="AI",
            daily_count={
                "20260421": 1,
                "20260422": 2,
                "20260423": 1,
                "20260424": 2,
                "20260425": 2,
            },
        )
    ]

    mark_event_anomalies(clusters)

    assert clusters[0].is_anomaly is False
    assert "未達爆量門檻" in clusters[0].anomaly_reason


def test_mark_event_anomalies_handles_insufficient_history():
    clusters = [
        EventCluster(
            event_id="evt",
            title="AI",
            daily_count={"20260424": 1, "20260425": 5},
        )
    ]

    mark_event_anomalies(clusters)

    assert clusters[0].is_anomaly is False
    assert clusters[0].anomaly_reason == "歷史資料不足"


def test_mark_event_anomalies_uses_fixed_threshold_when_stdev_zero():
    clusters = [
        EventCluster(
            event_id="evt",
            title="AI",
            daily_count={
                "20260421": 1,
                "20260422": 1,
                "20260423": 1,
                "20260424": 1,
                "20260425": 3,
            },
        )
    ]

    mark_event_anomalies(clusters)

    assert clusters[0].is_anomaly is True
    assert "固定基準" in clusters[0].anomaly_reason
