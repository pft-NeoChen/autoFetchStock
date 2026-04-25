"""
Pure-statistical anomaly detection for news event clusters.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import List

from src.news.news_models import EventCluster


def mark_event_anomalies(
    clusters: List[EventCluster],
    min_history_days: int = 3,
    z_threshold: float = 2.0,
) -> List[EventCluster]:
    """
    Mark clusters whose latest-day article count is unusually high.

    The function mutates and returns the provided clusters. Missing days inside
    a cluster's observed date range are counted as zero so sparse histories do
    not overstate the baseline.
    """
    for cluster in clusters:
        _mark_one_cluster(cluster, min_history_days, z_threshold)
    return clusters


def _mark_one_cluster(
    cluster: EventCluster,
    min_history_days: int,
    z_threshold: float,
) -> None:
    cluster.is_anomaly = False
    cluster.anomaly_score = 0.0
    cluster.anomaly_reason = ""

    counts = cluster.daily_count or {}
    dates = sorted(_parse_day(day) for day in counts if _parse_day(day) is not None)
    if len(dates) < 2:
        cluster.anomaly_reason = "歷史資料不足"
        return

    latest_day = dates[-1]
    first_day = dates[0]
    baseline_days = []
    day = first_day
    while day < latest_day:
        baseline_days.append(day.strftime("%Y%m%d"))
        day += timedelta(days=1)

    if len(baseline_days) < min_history_days:
        cluster.anomaly_reason = "歷史資料不足"
        return

    baseline = [int(counts.get(day, 0) or 0) for day in baseline_days]
    latest_key = latest_day.strftime("%Y%m%d")
    latest_count = int(counts.get(latest_key, 0) or 0)
    mean = statistics.mean(baseline)
    stdev = statistics.pstdev(baseline)

    if stdev > 0:
        z_score = (latest_count - mean) / stdev
        cluster.anomaly_score = round(z_score, 2)
        if z_score > z_threshold:
            cluster.is_anomaly = True
            cluster.anomaly_reason = (
                f"最新日文章數 {latest_count}，高於過去基準 {mean:.1f}（z={z_score:.2f}）"
            )
        else:
            cluster.anomaly_reason = f"未達爆量門檻（z={z_score:.2f}）"
        return

    threshold = max(3, mean * 2)
    cluster.anomaly_score = float(latest_count)
    if latest_count >= threshold:
        cluster.is_anomaly = True
        cluster.anomaly_reason = (
            f"最新日文章數 {latest_count}，高於固定基準 {threshold:.1f}"
        )
    else:
        cluster.anomaly_reason = f"未達爆量門檻（固定基準 {threshold:.1f}）"


def _parse_day(day: str):
    try:
        return datetime.strptime(str(day), "%Y%m%d").date()
    except ValueError:
        return None
