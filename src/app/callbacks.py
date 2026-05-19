"""
Dash callbacks for autoFetchStock.

This module implements all Dash callback functions:
- Stock search and selection
- Tab switching
- K-line period changes
- Auto-update mechanism
- OHLC hover display
- Error handling
"""

import logging
import time
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from dash import callback, Output, Input, State, no_update, html, dcc, ctx, ALL
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from src.models import (
    KlinePeriod,
    PriceDirection,
    IntradayTick,
    RealtimeQuote,
    MarketIndexEntry,
    IndustryPulseEntry,
    BreadthSummary,
    ChipKpiCard,
    FundamentalsSnapshot,
    Advisor,
    AdvisorBullet,
    AdvisorDimension,
    StockEvent,
    MinuteKBar,
    SpikeSeverity,
)
from src.exceptions import (
    ConnectionTimeoutError,
    InvalidDataError,
    StockNotFoundError,
    ServiceUnavailableError,
)
from src.data.market_indices import (
    fetch_breadth_summary,
    fetch_industry_pulse,
    fetch_market_strip,
    split_strip_entries,
)
from src.data.advisor import build_advisor
from src.data.events import build_stock_event_timeline
from src.data.chips_kpi import build_chips_kpi
from src.data.fundamentals import get_fundamentals
from src.data.sectors import get_sector, get_tags
from src.data.spark import render_spark
from src.app.intraday_guard import quote_timestamp_matches_trade_date

logger = logging.getLogger("autofetchstock.app")


class CallbackManager:
    """
    Manages Dash callbacks and their dependencies.

    This class holds references to the application components
    (fetcher, storage, processor, renderer, scheduler) and
    registers all callbacks with the Dash app.
    """

    def __init__(
        self,
        app,
        fetcher,
        storage,
        processor,
        renderer,
        scheduler,
        shioaji_fetcher=None,
        on_init_volume=None,
        get_buffered_ticks=None,
        news_processor=None,
        chips_storage=None,
        index_fetcher=None,
        spike_detection_store=None,
    ):
        """
        Initialize callback manager.

        Args:
            app: Dash application instance
            fetcher: DataFetcher instance
            storage: DataStorage instance
            processor: DataProcessor instance
            renderer: ChartRenderer instance
            scheduler: Scheduler instance
            shioaji_fetcher: ShioajiFetcher instance (optional)
            on_init_volume: Callback to initialize volume cache (optional)
            get_buffered_ticks: Callback to get ticks currently in memory buffer
            news_processor: NewsProcessor instance (optional)
        """
        self.app = app
        self.fetcher = fetcher
        self.shioaji_fetcher = shioaji_fetcher
        self.on_init_volume = on_init_volume
        self.get_buffered_ticks = get_buffered_ticks
        self.storage = storage
        self.processor = processor
        self.renderer = renderer
        self.scheduler = scheduler
        self.news_processor = news_processor
        self.chips_storage = chips_storage
        self.index_fetcher = index_fetcher
        self.spike_detection_store = spike_detection_store
        self._current_stock_id: Optional[str] = None
        self._current_stock_name: Optional[str] = None
        # Per-stock cache for WatchlistRow sparklines: load_daily_data
        # touches disk; refreshing 26 favorites every second would trash
        # the FS. 60s TTL is enough since daily closes only change once
        # per day. Phase 3.5 #1.
        self._spark_cache: Dict[str, Tuple[float, List[float]]] = {}

    def register_callbacks(self) -> None:
        """Register all Dash callbacks."""
        self._register_search_callbacks()
        self._register_tab_callbacks()
        self._register_period_callbacks()
        self._register_update_callbacks()
        self._register_hover_callbacks()
        self._register_error_callbacks()
        self._register_favorites_callbacks()
        self._register_news_callbacks()
        self._register_phase35_callbacks()
        self._register_right_rail_callbacks()
        self._register_advisor_callbacks()
        self._register_events_tab_callbacks()
        self._register_alert_bar_callbacks()
        self._register_volume_spike_callbacks()
        self._register_stock_stats_callbacks()
        logger.info("All callbacks registered")

    def _register_right_rail_callbacks(self) -> None:
        """Register Phase 4.5 right-rail tab switching callbacks."""

        @self.app.callback(
            Output("rr-tab-chips", "className"),
            Output("rr-tab-ai", "className"),
            Output("rr-tab-signal", "className"),
            Output("rr-tab-fund", "className"),
            Output("rr-tab-news", "className"),
            Output("right-rail-panel-chips", "className"),
            Output("right-rail-panel-ai", "className"),
            Output("right-rail-panel-signal", "className"),
            Output("right-rail-panel-fund", "className"),
            Output("right-rail-panel-news", "className"),
            Output("right-rail-active-tab", "data"),
            Input("rr-tab-chips", "n_clicks"),
            Input("rr-tab-ai", "n_clicks"),
            Input("rr-tab-signal", "n_clicks"),
            Input("rr-tab-fund", "n_clicks"),
            Input("rr-tab-news", "n_clicks"),
            State("right-rail-active-tab", "data"),
            prevent_initial_call=True,
        )
        def switch_right_rail_tab(_chips, _ai, _signal, _fund, _news, current):
            tab_by_id = {
                "rr-tab-chips": "chips",
                "rr-tab-ai": "ai",
                "rr-tab-signal": "signal",
                "rr-tab-fund": "fund",
                "rr-tab-news": "news",
            }
            active = tab_by_id.get(ctx.triggered_id, current or "chips")

            def _tab_cls(key: str) -> str:
                base = "right-rail-tab"
                return f"{base} active" if key == active else base

            def _panel_cls(key: str) -> str:
                base = "right-rail-panel"
                if key == active:
                    return f"{base} right-rail-panel-active"
                return f"{base} right-rail-panel-hidden"

            return (
                _tab_cls("chips"),
                _tab_cls("ai"),
                _tab_cls("signal"),
                _tab_cls("fund"),
                _tab_cls("news"),
                _panel_cls("chips"),
                _panel_cls("ai"),
                _panel_cls("signal"),
                _panel_cls("fund"),
                _panel_cls("news"),
                active,
            )

    def _register_advisor_callbacks(self) -> None:
        """Register Phase 5 AI advisor right-rail callbacks."""

        # Phase 7.4 — clientside skeleton swap on stock change.
        # Avoids stale advisor data lingering while LLM call is in flight.
        # Tracks last seen stock_id in window state so the swap only fires
        # when current_stock actually changes (not on every news-store tick).
        self.app.clientside_callback(
            """
            function(appState) {
                if (!appState) return window.dash_clientside.no_update;
                var stock = appState.current_stock || null;
                window._lastAdvisorStock = window._lastAdvisorStock || null;
                if (stock === window._lastAdvisorStock) {
                    return window.dash_clientside.no_update;
                }
                window._lastAdvisorStock = stock;
                if (!stock) {
                    return window.dash_clientside.no_update;
                }
                var name = appState.current_stock_name || stock;
                return [
                    {
                        namespace: 'dash_html_components',
                        type: 'Div',
                        props: {
                            className: 'ai-panel-empty ai-panel-empty-loading',
                            children: [
                                {namespace: 'dash_html_components', type: 'Div',
                                 props: {className: 'ai-panel-empty-icon', children: '⌛'}},
                                {namespace: 'dash_html_components', type: 'Div',
                                 props: {className: 'ai-panel-empty-message',
                                         children: '正在分析 ' + stock + ' ' + name + '…'}},
                                {namespace: 'dash_html_components', type: 'Div',
                                 props: {className: 'ai-panel-empty-hint',
                                         children: '首次查詢約 5–15 秒；後續快取命中即時顯示。'}},
                            ],
                        },
                    },
                ];
            }
            """,
            Output("ai-panel", "children", allow_duplicate=True),
            Input("app-state-store", "data"),
            prevent_initial_call=True,
        )

        self.app.clientside_callback(
            """
            function(appState, pathname) {
                if (pathname !== '/advisor') return window.dash_clientside.no_update;
                if (!appState) return window.dash_clientside.no_update;
                var stock = appState.current_stock || null;
                window._lastAdvisorCanvasStock = window._lastAdvisorCanvasStock || null;
                if (stock === window._lastAdvisorCanvasStock) {
                    return window.dash_clientside.no_update;
                }
                window._lastAdvisorCanvasStock = stock;
                if (!stock) {
                    return window.dash_clientside.no_update;
                }
                var name = appState.current_stock_name || stock;
                return {
                    namespace: 'dash_html_components',
                    type: 'Div',
                    props: {
                        className: 'advisor-empty',
                        children: [
                            {namespace: 'dash_html_components', type: 'Div',
                             props: {className: 'advisor-empty-icon', children: '⌛'}},
                            {namespace: 'dash_html_components', type: 'Div',
                             props: {className: 'advisor-empty-title',
                                     children: '正在分析 ' + stock + ' ' + name}},
                            {namespace: 'dash_html_components', type: 'Div',
                             props: {className: 'advisor-empty-desc',
                                     children: 'AI 顧問首次分析約需 5–15 秒，請稍候…'}},
                        ],
                    },
                };
            }
            """,
            Output("advisor-canvas", "children", allow_duplicate=True),
            Input("app-state-store", "data"),
            Input("url", "pathname"),
            prevent_initial_call=True,
        )

        @self.app.callback(
            Output("ai-panel", "children"),
            Input("app-state-store", "data"),
            Input("news-data-store", "data"),
            prevent_initial_call=False,
        )
        def update_ai_panel(app_state: Optional[dict], news_data: Optional[dict]):
            stock_id = (app_state or {}).get("current_stock")
            if not stock_id:
                favs = (app_state or {}).get("favorites") or []
                return _render_ai_panel_empty(
                    "尚未選擇股票",
                    favorites=favs,
                    state="no_stock",
                )

            stock_name = (app_state or {}).get("current_stock_name") or stock_id
            articles: List[dict] = []
            if news_data:
                articles = _extract_articles_from_run(
                    news_data,
                    "ALL",
                    stock_id,
                    stock_name,
                )

            quote = None
            try:
                if self.fetcher:
                    get_cached_quote = getattr(self.fetcher, "get_cached_quote", None)
                    if callable(get_cached_quote):
                        quote = get_cached_quote(stock_id)
                    if quote is None:
                        quote = self.fetcher.fetch_realtime_quote(stock_id, blocking=False)
            except Exception as exc:
                logger.debug("advisor quote fetch failed for %s: %s", stock_id, exc)

            cards = build_chips_kpi(stock_id, self.chips_storage)
            fundamentals = get_fundamentals(stock_id)
            closes = self._load_daily_closes(stock_id)
            advisor = build_advisor(
                stock_id,
                articles=articles,
                chip_cards=cards,
                fundamentals=fundamentals,
                quote=quote,
                daily_closes=closes,
            )
            coverage = _compute_advisor_coverage(articles, cards, fundamentals, quote, closes)
            return _render_ai_panel(advisor, stock_id, stock_name, coverage=coverage)

        # ── Phase 6 — /advisor full-canvas (Variant AI-2) ────────────────
        @self.app.callback(
            Output("advisor-canvas", "children"),
            Input("app-state-store", "data"),
            Input("news-data-store", "data"),
            Input("url", "pathname"),
            prevent_initial_call=False,
        )
        def update_advisor_canvas(
            app_state: Optional[dict],
            news_data: Optional[dict],
            pathname: Optional[str],
        ):
            if pathname != "/advisor":
                raise PreventUpdate

            stock_id = (app_state or {}).get("current_stock")
            if not stock_id:
                favs = (app_state or {}).get("favorites") or []
                return _render_advisor_canvas_empty(favs)

            stock_name = (app_state or {}).get("current_stock_name") or stock_id
            articles: List[dict] = []
            if news_data:
                articles = _extract_articles_from_run(
                    news_data, "ALL", stock_id, stock_name,
                )

            quote = None
            try:
                if self.fetcher:
                    get_cached_quote = getattr(self.fetcher, "get_cached_quote", None)
                    if callable(get_cached_quote):
                        quote = get_cached_quote(stock_id)
                    if quote is None:
                        quote = self.fetcher.fetch_realtime_quote(stock_id, blocking=False)
            except Exception as exc:
                logger.debug("advisor-canvas quote fetch failed for %s: %s", stock_id, exc)

            cards = build_chips_kpi(stock_id, self.chips_storage)
            fundamentals = get_fundamentals(stock_id)
            closes = self._load_daily_closes(stock_id)
            advisor = build_advisor(
                stock_id,
                articles=articles,
                chip_cards=cards,
                fundamentals=fundamentals,
                quote=quote,
                daily_closes=closes,
            )
            coverage = _compute_advisor_coverage(articles, cards, fundamentals, quote, closes)
            return _render_advisor_canvas(
                advisor, stock_id, stock_name,
                quote=quote,
                articles=articles,
                cards=cards,
                fundamentals=fundamentals,
                daily_closes=closes,
                daily_ohlc=self._load_daily_ohlc(stock_id),
                coverage=coverage,
            )

    def _load_daily_closes(self, stock_id: str, limit: int = 80) -> List[float]:
        """Load recent daily closes for advisor technical scoring."""
        if not self.storage or not stock_id:
            return []
        try:
            daily = self.storage.load_daily_data(stock_id)
        except Exception as exc:
            logger.debug("advisor daily load failed for %s: %s", stock_id, exc)
            return []
        closes: List[float] = []
        for row in (getattr(daily, "daily_data", None) or [])[-limit:]:
            close = getattr(row, "close", None)
            if isinstance(close, (int, float)):
                closes.append(float(close))
        return closes

    def _load_daily_ohlc(
        self, stock_id: str, limit: int = 120
    ) -> List[Tuple[float, float, float]]:
        """Return recent (high, low, close) tuples for KD/RSI calc."""
        if not self.storage or not stock_id:
            return []
        try:
            daily = self.storage.load_daily_data(stock_id)
        except Exception as exc:
            logger.debug("advisor daily ohlc load failed for %s: %s", stock_id, exc)
            return []
        out: List[Tuple[float, float, float]] = []
        for row in (getattr(daily, "daily_data", None) or [])[-limit:]:
            h = getattr(row, "high", None)
            l = getattr(row, "low", None)
            c = getattr(row, "close", None)
            if isinstance(h, (int, float)) and isinstance(l, (int, float)) and isinstance(c, (int, float)):
                out.append((float(h), float(l), float(c)))
        return out

    def _register_alert_bar_callbacks(self) -> None:
        """Phase 6.5 — DESIGN_SPEC §7 stale-data & connection-lost banner.

        Two paths surface as alerts:
        - **Stale data**: during market hours, if the latest tick for the
          current stock is >5 s old (Shioaji subscription stalled or TWSE
          fallback hung). Amber.
        - **Connection lost**: Shioaji socket dropped after a successful
          login, or scheduler consecutive_failures crossed the threshold.
          Red. Surfaces a 重新連線 button that re-runs login.
        """

        @self.app.callback(
            Output("system-alert-bar", "children"),
            Output("system-alert-bar", "className"),
            Output("system-alert-bar", "style"),
            Input("auto-update-interval", "n_intervals"),
            Input("app-state-store", "data"),
            prevent_initial_call=False,
        )
        def update_alert_bar(_n, app_state):
            level, message = self._eval_alert_state(app_state or {})
            if level is None:
                return [], "system-alert-bar", {"display": "none"}

            children = [
                html.Span("●", className=f"alert-dot alert-dot-{level}"),
                html.Span(message, className="alert-message"),
            ]
            if level == "error":
                children.append(html.Button(
                    "重新連線",
                    id="alert-reconnect-button",
                    className="alert-reconnect-button",
                    n_clicks=0,
                ))
            else:
                # keep the button id mounted (hidden) so the reconnect
                # callback's Input target always exists.
                children.append(html.Button(
                    "",
                    id="alert-reconnect-button",
                    className="alert-reconnect-button",
                    n_clicks=0,
                    style={"display": "none"},
                ))

            return (
                children,
                f"system-alert-bar system-alert-{level}",
                {"display": "flex"},
            )

        @self.app.callback(
            Output("alert-reconnect-button", "n_clicks"),
            Input("alert-reconnect-button", "n_clicks"),
            prevent_initial_call=True,
        )
        def reconnect_clicked(n_clicks):
            if not n_clicks:
                raise PreventUpdate
            try:
                if self.shioaji_fetcher and not self.shioaji_fetcher.is_connected:
                    self.shioaji_fetcher.login()
                    logger.info("alert-bar reconnect: shioaji re-login attempted")
            except Exception as exc:
                logger.warning("alert-bar reconnect failed: %s", exc)
            return 0  # reset counter; next tick re-evaluates state

    def _eval_alert_state(self, app_state: dict) -> Tuple[Optional[str], str]:
        """Return (level, message). level in {None, 'warn', 'error'}."""
        # Connection-lost takes priority.
        try:
            shioaji_connected = bool(
                self.shioaji_fetcher and self.shioaji_fetcher.is_connected
            )
        except Exception:
            shioaji_connected = False
        shioaji_configured = bool(self.shioaji_fetcher)

        try:
            status = self.scheduler.get_status() if self.scheduler else None
            consecutive_failures = int(getattr(status, "consecutive_failures", 0) or 0)
        except Exception:
            consecutive_failures = 0

        if shioaji_configured and not shioaji_connected:
            return "error", "Shioaji 連線中斷，即時報價不可用"
        if consecutive_failures >= 3:
            return "error", f"資料抓取連續失敗 {consecutive_failures} 次，已暫停排程"

        # Stale check only meaningful during market hours and when a stock
        # is selected. Outside market hours stale data is expected.
        try:
            is_open = bool(self.scheduler and self.scheduler.is_market_open())
        except Exception:
            is_open = False
        if not is_open:
            return None, ""

        stock_id = (app_state or {}).get("current_stock")
        if not stock_id:
            return None, ""

        quote = None
        try:
            if self.fetcher:
                get_cached_quote = getattr(self.fetcher, "get_cached_quote", None)
                if callable(get_cached_quote):
                    quote = get_cached_quote(stock_id)
        except Exception:
            quote = None
        if quote is None or not getattr(quote, "timestamp", None):
            return None, ""

        ts = quote.timestamp
        try:
            if ts.tzinfo is None:
                age = (datetime.now() - ts).total_seconds()
            else:
                age = (datetime.now(ts.tzinfo) - ts).total_seconds()
        except Exception:
            return None, ""

        if age > 5:
            return "warn", f"資料延遲 {int(age)} 秒，等待下一筆"
        return None, ""

    # ── Volume Spike Panel ─────────────────────────────────────────────────

    # Track the most recent spike timestamp per stock that has been pushed
    # as a notification, to avoid re-pushing the same minute on every tick.
    _spike_notification_window_seconds: int = 90

    def _register_volume_spike_callbacks(self) -> None:
        """Render volume spike rows from the in-memory SpikeDetectionStore.

        Triggered by the 60s dcc.Interval AND by stock changes so the
        panel refreshes immediately when the user switches favorites.
        Also pushes browser-notification payloads for fresh HIGH+ spikes.
        """
        # Per-instance state for notification dedupe. Keys are stock_id,
        # values are ISO timestamp strings of the most recent pushed spike.
        self._last_pushed_spike_ts: Dict[str, str] = {}

        @self.app.callback(
            Output("volume-spike-list", "children"),
            Input("volume-spike-interval", "n_intervals"),
            Input("app-state-store", "data"),
            prevent_initial_call=False,
        )
        def update_volume_spike_panel(_n, app_state):
            try:
                stock_id = (app_state or {}).get("current_stock")
                if not stock_id:
                    return [html.Div("請先選擇股票", className="no-data")]
                if self.spike_detection_store is None:
                    return [html.Div("尚無爆量", className="no-data")]
                bars = self.spike_detection_store.get_recent(stock_id, n=20)
                if not bars:
                    return [html.Div("尚無爆量", className="no-data")]
                rows = []
                last_date = None
                for b in bars:
                    bar_date = b.timestamp.date()
                    if bar_date != last_date:
                        rows.append(_render_spike_date_divider(bar_date))
                        last_date = bar_date
                    rows.append(_render_volume_spike_row(b))
                return rows
            except Exception as exc:
                logger.error("update_volume_spike_panel failed: %s", exc)
                return [html.Div("資料載入錯誤", className="no-data")]

        @self.app.callback(
            Output("spike-notification-store", "data"),
            Input("volume-spike-interval", "n_intervals"),
            Input("app-state-store", "data"),
            prevent_initial_call=True,
        )
        def push_spike_notification(_n, app_state):
            """
            Compose a Notification payload for the latest HIGH+ spike
            within the last `_spike_notification_window_seconds` seconds
            on the *currently-viewed* stock. Skipped outside trading hours
            and when the same minute has already been pushed.
            """
            try:
                if self.spike_detection_store is None:
                    return no_update
                if self.scheduler is not None and not self.scheduler.is_market_open():
                    return no_update
                stock_id = (app_state or {}).get("current_stock")
                if not stock_id:
                    return no_update

                bars = self.spike_detection_store.get_recent(stock_id, n=1)
                if not bars:
                    return no_update
                bar = bars[0]
                if bar.spike_severity not in (
                    SpikeSeverity.HIGH, SpikeSeverity.EXTREME
                ):
                    return no_update

                now = datetime.now(_VOLUME_SPIKE_TZ)
                if bar.timestamp.tzinfo is None:
                    bar_ts = bar.timestamp.replace(tzinfo=_VOLUME_SPIKE_TZ)
                else:
                    bar_ts = bar.timestamp
                age = (now - bar_ts).total_seconds()
                if age > self._spike_notification_window_seconds or age < -60:
                    return no_update

                ts_iso = bar_ts.isoformat()
                if self._last_pushed_spike_ts.get(stock_id) == ts_iso:
                    return no_update

                payload = _build_spike_notification_payload(stock_id, bar)
                self._last_pushed_spike_ts[stock_id] = ts_iso
                logger.info(
                    "spike notification queued: %s @ %s severity=%s",
                    stock_id, bar_ts.strftime("%H:%M"),
                    bar.spike_severity.value,
                )
                return payload
            except Exception as exc:
                logger.error("push_spike_notification failed: %s", exc)
                return no_update

        # Clientside: turn the store payload into a desktop Notification.
        # Permission is requested lazily on first payload (rather than on
        # page load) so we don't prompt users who never see a HIGH spike.
        self.app.clientside_callback(
            """
            function(data) {
                if (!data || !data.title) {
                    return window.dash_clientside.no_update;
                }
                if (!('Notification' in window)) {
                    return window.dash_clientside.no_update;
                }
                if (Notification.permission === 'default') {
                    Notification.requestPermission();
                    return window.dash_clientside.no_update;
                }
                if (Notification.permission !== 'granted') {
                    return window.dash_clientside.no_update;
                }
                try {
                    new Notification(data.title, {
                        body: data.body || '',
                        tag: data.tag || '',
                        icon: data.icon || '/assets/favicon.ico',
                        requireInteraction: false,
                    });
                } catch (err) {
                    console.warn('spike notification failed', err);
                }
                return window.dash_clientside.no_update;
            }
            """,
            Output("spike-notification-store", "data", allow_duplicate=True),
            Input("spike-notification-store", "data"),
            prevent_initial_call=True,
        )

    def _register_events_tab_callbacks(self) -> None:
        """Phase 6.4 — fill the per-stock event timeline tab."""

        @self.app.callback(
            Output("events-window-store", "data"),
            Output("events-window-btn-today", "className"),
            Output("events-window-btn-3", "className"),
            Output("events-window-btn-all", "className"),
            Input("events-window-btn-today", "n_clicks"),
            Input("events-window-btn-3", "n_clicks"),
            Input("events-window-btn-all", "n_clicks"),
            State("events-window-store", "data"),
            prevent_initial_call=False,
        )
        def update_events_window(_n_today, _n3, _n_all, current):
            # Window encoded as days back: 0=當日, 3=近 3 日, 999=全部.
            base = "events-window-chip"
            active = "events-window-chip events-window-chip-active"
            triggered = ctx.triggered_id
            if triggered == "events-window-btn-today":
                return 0, active, base, base
            if triggered == "events-window-btn-3":
                return 3, base, active, base
            if triggered == "events-window-btn-all":
                return 999, base, base, active

            cur = current if current in (0, 3, 999) else 3
            if cur == 0:
                return 0, active, base, base
            if cur == 999:
                return 999, base, base, active
            return 3, base, active, base

        @self.app.callback(
            Output("stock-events-timeline", "children"),
            Output("stock-events-summary", "children"),
            Input("app-state-store", "data"),
            Input("news-events-store", "data"),
            Input("events-window-store", "data"),
            prevent_initial_call=False,
        )
        def update_stock_events_timeline(app_state, news_events_data, window):
            stock_id = (app_state or {}).get("current_stock")
            if not stock_id:
                return [html.Div("請先選擇股票", className="events-empty")], "請先選擇股票"

            stock_name = (app_state or {}).get("current_stock_name") or stock_id
            # window encoding: 0 = 當日, 3 = 近 3 日, 999 = 全部.
            try:
                window_days = int(window) if window is not None else 3
            except (TypeError, ValueError):
                window_days = 3
            if window_days not in (0, 3, 999):
                window_days = 3

            articles_by_url = self._load_articles_by_url(days=min(max(window_days, 1), 14))
            events = build_stock_event_timeline(
                stock_id,
                news_events_data or {},
                window_days=window_days,
                articles_by_url=articles_by_url,
            )
            if window_days == 0:
                window_label = "當日"
            elif window_days >= 999:
                window_label = "全部"
            else:
                window_label = f"近 {window_days} 日"
            if not events:
                return (
                    [html.Div(f"{window_label}無相關事件", className="events-empty")],
                    f"{stock_name} {stock_id} · {window_label}無事件",
                )

            news_total = sum(e.news_count for e in events)
            anomaly_n = sum(1 for e in events if e.is_anomaly)
            summary_text = (
                f"{stock_name} {stock_id} · {window_label} "
                f"{len(events)} 件事件 · {news_total} 則新聞"
            )
            if anomaly_n:
                summary_text += f" · 爆量 {anomaly_n}"

            return _render_stock_events_timeline(events), summary_text

    def _load_articles_by_url(self, days: int = 7) -> Dict[str, dict]:
        """Build a URL → article-meta map covering the last ``days`` days.

        Cached for 60 s to avoid re-walking the daily news files on every
        events-tab callback fire.
        """
        cache = getattr(self, "_articles_by_url_cache", None)
        now = time.time()
        if cache and now - cache[0] < 60 and cache[2] == days:
            return cache[1]

        out: Dict[str, dict] = {}
        if self.storage:
            today = date.today()
            start = (today - timedelta(days=days)).strftime("%Y%m%d")
            end = today.strftime("%Y%m%d")
            try:
                for art in self.storage.iter_news_articles(start, end):
                    url = getattr(art, "url", "") or ""
                    if not url:
                        continue
                    out[url] = {
                        "title": getattr(art, "title", "") or "",
                        "source": getattr(art, "source", "") or "",
                        "published_at": (
                            art.published_at.isoformat()
                            if getattr(art, "published_at", None)
                            else ""
                        ),
                        "impact_score": float(getattr(art, "impact_score", 0.0) or 0.0),
                        "impact_direction": getattr(art, "impact_direction", "neutral"),
                        "related_stock_ids": list(
                            getattr(art, "related_stock_ids", []) or []
                        ),
                    }
            except Exception as exc:
                logger.debug("events tab article hydrate failed: %s", exc)

        self._articles_by_url_cache = (now, out, days)
        return out

    def _get_spark_values(self, stock_id: str) -> List[float]:
        """Return the last 20 daily closes for the WatchlistRow sparkline,
        cached for 60 s. Returns an empty list if no history is on disk —
        callers should fall back to a seeded line so every row still has
        a visible spark.
        """
        now = time.time()
        cached = self._spark_cache.get(stock_id)
        if cached and now - cached[0] < 60:
            return cached[1]
        closes: List[float] = []
        try:
            daily = self.storage.load_daily_data(stock_id)
            if daily and daily.daily_data:
                closes = [d.close for d in daily.daily_data[-20:] if d.close]
        except Exception:
            closes = []
        self._spark_cache[stock_id] = (now, closes)
        return closes

    def _build_favorite_kbar(self, quote: Optional[RealtimeQuote]) -> html.Div:
        """Build a compact day-candle marker for the favorites list."""
        bar_height = 28
        body_class = "price-flat"
        wick_top = 2
        wick_height = bar_height - 4
        body_top = (bar_height // 2) - 2
        body_height = 4

        if quote:
            current_price = quote.current_price
            open_price = (
                quote.open_price
                if quote.open_price is not None and quote.open_price > 0
                else (quote.previous_close or current_price)
            )
            high_candidates = [p for p in (quote.high_price, open_price, current_price) if p and p > 0]
            low_candidates = [p for p in (quote.low_price, open_price, current_price) if p and p > 0]
            high_price = max(high_candidates) if high_candidates else current_price
            low_price = min(low_candidates) if low_candidates else current_price

            if current_price > open_price:
                body_class = "price-up"
            elif current_price < open_price:
                body_class = "price-down"

            if high_price > low_price:
                usable_height = bar_height - 4
                price_range = high_price - low_price
                body_high = max(open_price, current_price)
                body_low = min(open_price, current_price)
                body_top = round(((high_price - body_high) / price_range) * usable_height) + 2
                body_height = max(4, round(((body_high - body_low) / price_range) * usable_height))
                max_top = max(2, bar_height - 2 - body_height)
                body_top = min(max(body_top, 2), max_top)

        return html.Div(
            className="favorite-item-kbar",
            children=[
                html.Span(
                    className=f"favorite-kbar-wick {body_class}",
                    style={"top": f"{wick_top}px", "height": f"{wick_height}px"},
                ),
                html.Span(
                    className=f"favorite-kbar-body {body_class}",
                    style={"top": f"{body_top}px", "height": f"{body_height}px"},
                ),
            ],
        )

    def _render_favorite_item(
        self,
        favorite: dict,
        current_stock: Optional[str],
        signal_map: Optional[Dict[str, dict]] = None,
        anomaly_set: Optional[set] = None,
    ) -> html.Div:
        """Render a single watchlist row.

        Phase 3.5: 4-column grid (dot / name+id+anomaly / spark / price+pct).
        Mirrors design/afs/layout-variants.jsx::WatchlistRow.
        """
        stock_id = favorite["id"]
        stock_name = favorite.get("name", stock_id)
        is_active = stock_id == current_stock

        quote = None
        price_text = "--"
        pct_text = ""
        direction_cls = "flat"
        item_class = f"favorite-item watch-row{' active' if is_active else ''}"

        try:
            if self.fetcher:
                get_cached_quote = getattr(self.fetcher, "get_cached_quote", None)
                if callable(get_cached_quote):
                    quote = get_cached_quote(stock_id)
                if quote is None:
                    quote = self.fetcher.fetch_realtime_quote(stock_id, blocking=False)
            if quote:
                price_text = f"{quote.current_price:.2f}"
                if quote.change_amount > 0:
                    direction_cls = "up"
                elif quote.change_amount < 0:
                    direction_cls = "down"
                sign = "+" if quote.change_percent >= 0 else ""
                pct_text = f"{sign}{quote.change_percent:.2f}%"

                if quote.limit_up_price > 0 and quote.current_price >= quote.limit_up_price:
                    item_class += " limit-up-bg"
                elif quote.limit_down_price > 0 and quote.current_price <= quote.limit_down_price:
                    item_class += " limit-down-bg"
        except Exception:
            quote = None

        # Phase 3.6: sentiment drives the dot; event text is kept as tooltip
        # data only so the row grid remains clean and does not overlap sparks.
        sig = (signal_map or {}).get(stock_id) or {}
        sig_kind = sig.get("sentiment") or sig.get("signal", "neutral")
        dot_kind = {
            "up": "up",
            "down": "down",
            "neutral": "neutral",
            "bullish": "up",
            "bearish": "down",
        }.get(sig_kind, "neutral")
        is_anomaly = bool(anomaly_set and stock_id in anomaly_set)
        event_label = sig.get("event_label") or ("爆量" if is_anomaly else "")
        dot_title = " · ".join(
            part for part in [event_label, sig.get("reason", "")] if part
        )

        # Spark from real recent closes when available; seeded fallback
        # otherwise so every row keeps a visible line on first load.
        recent_closes = self._get_spark_values(stock_id)
        try:
            seed = int(stock_id)
        except (TypeError, ValueError):
            seed = abs(hash(stock_id)) % 100_000 or 1
        spark_dir = direction_cls
        if recent_closes and len(recent_closes) >= 2 and direction_cls == "flat":
            # Direction inference: last vs first sample, only when realtime
            # quote didn't already classify it.
            spark_dir = "up" if recent_closes[-1] >= recent_closes[0] else "down"
        spark_node = render_spark(
            recent_closes if recent_closes else None,
            direction=spark_dir,
            w=56,
            h=20,
            seed=seed,
        )

        # Column 2 — name + id stay on the same row, matching the layout-B
        # reference. The name can wrap, but the code is not stacked below it.
        name_row_children: List[Any] = [
            html.Div(
                className="watch-name-row",
                children=[
                    html.Span(stock_name, className="watch-name"),
                    html.Span(stock_id, className="watch-code num"),
                ],
            ),
        ]

        children: List[Any] = [
            html.Span(
                className=f"signal-dot {dot_kind} watch-dot",
                title=dot_title,
            ),
            html.Div(
                className="watch-name-col",
                children=name_row_children,
            ),
            html.Div(spark_node, className="watch-spark-col"),
            html.Div(
                className="watch-price-col",
                children=[
                    html.Div(price_text, className=f"num watch-price {direction_cls}"),
                    html.Div(pct_text, className=f"num watch-pct {direction_cls}"),
                ],
            ),
        ]

        return html.Div(
            id={"type": "favorite-item", "index": stock_id},
            className=item_class,
            children=children,
            n_clicks=0,
            draggable="true",
            **{"data-stock-id": stock_id},
        )

    def _register_favorites_callbacks(self) -> None:
        """Register favorites related callbacks."""

        @self.app.callback(
            Output("app-state-store", "data", allow_duplicate=True),
            Input("main-container", "id"),
            State("app-state-store", "data"),
            prevent_initial_call='initial_duplicate'
        )
        def load_initial_favorites(_, current_state: dict):
            """Load favorites from storage on initial load."""
            favorites = self.storage.load_favorites()
            if not favorites:
                return no_update
            
            new_state = current_state.copy()
            new_state["favorites"] = favorites
            
            # Subscribe to Shioaji for all favorites
            if self.shioaji_fetcher and self.shioaji_fetcher.is_connected:
                for fav in favorites:
                    self.shioaji_fetcher.subscribe(fav["id"])
            
            # Also add all favorites to scheduler for background fetching (fallback)
            for fav in favorites:
                self.scheduler.add_stock_job(fav["id"])
                
            return new_state

        @self.app.callback(
            Output("app-state-store", "data", allow_duplicate=True),
            Output("stock-star-toggle", "className"),
            Input("stock-star-toggle", "n_clicks"),
            State("app-state-store", "data"),
            prevent_initial_call=True
        )
        def on_star_click(n_clicks: int, current_state: dict):
            """Handle clicking the favorite star button."""
            if n_clicks is None:
                raise PreventUpdate

            stock_id = current_state.get("current_stock")
            if not stock_id:
                raise PreventUpdate

            favorites = current_state.get("favorites", [])
            
            # Check if already in favorites
            fav_ids = [f["id"] for f in favorites]
            is_favorite = stock_id in fav_ids

            if is_favorite:
                # Remove from favorites
                favorites = [f for f in favorites if f["id"] != stock_id]
                star_class = "star-button"
                # Unsubscribe from Shioaji if not current stock
                # (But current_stock IS stock_id here, so we might want to keep subscription for main view)
                # Ideally, main view manages its own subscription.
                # If we remove from favorites, we just let it be. 
                # If user navigates away, main view subscription logic handles it.
                logger.info(f"Removed {stock_id} from favorites")
            else:
                # Add to favorites
                favorites.append({
                    "id": stock_id,
                    "name": self._current_stock_name or stock_id
                })
                star_class = "star-button active"
                # Subscribe to Shioaji
                if self.shioaji_fetcher and self.shioaji_fetcher.is_connected:
                    self.shioaji_fetcher.subscribe(stock_id)
                logger.info(f"Added {stock_id} to favorites")

            # Update state and save to storage
            new_state = current_state.copy()
            new_state["favorites"] = favorites
            self.storage.save_favorites(favorites)

            return new_state, star_class

        @self.app.callback(
            Output("favorites-list", "children"),
            Input("app-state-store", "data"),
            Input("favorites-update-interval", "n_intervals"),
            Input("news-data-store", "data"),
            Input("news-events-store", "data"),
        )
        def render_favorites_list(
            app_state: dict,
            n_intervals: int,
            news_data: Optional[dict],
            news_events: Optional[dict],
        ):
            """Render the favorites list sidebar.

            Phase 3: merges per-stock sentiment signals + anomaly flags
            into each row (dot + optional pill).
            """
            favorites = app_state.get("favorites", [])
            current_stock = app_state.get("current_stock")

            if not favorites:
                return html.Div("尚未加入最愛", className="no-favorites")

            signal_map: Dict[str, dict] = {}
            for s in (news_data or {}).get("favorite_signals") or []:
                sid = s.get("stock_id")
                if sid:
                    signal_map[str(sid)] = s
            anomaly_set = _collect_anomaly_stock_ids(news_events)

            return [
                self._render_favorite_item(fav, current_stock, signal_map, anomaly_set)
                for fav in favorites
            ]

        @self.app.callback(
            Output("stock-search-input", "value", allow_duplicate=True),
            Output("stock-search-button", "n_clicks", allow_duplicate=True),
            Input({"type": "ai-empty-fav-pick", "stock": ALL}, "n_clicks"),
            Input({"type": "advisor-empty-fav-pick", "stock": ALL}, "n_clicks"),
            State("stock-search-button", "n_clicks"),
            prevent_initial_call=True,
        )
        def on_advisor_empty_fav_pick(ai_clicks, adv_clicks, current_search_clicks):
            """Phase 7.4 — chip click in AI/advisor empty state triggers normal search flow."""
            if not (any(ai_clicks or []) or any(adv_clicks or [])):
                raise PreventUpdate
            triggered = ctx.triggered_id
            if not triggered or not isinstance(triggered, dict):
                raise PreventUpdate
            stock_id = triggered.get("stock")
            if not stock_id:
                raise PreventUpdate
            return stock_id, (current_search_clicks or 0) + 1

        @self.app.callback(
            Output("stock-search-input", "value", allow_duplicate=True),
            Output("stock-search-button", "n_clicks"),
            Input({"type": "favorite-item", "index": ALL}, "n_clicks"),
            State("stock-search-button", "n_clicks"),
            prevent_initial_call=True
        )
        def on_favorite_click(n_clicks_list, current_search_clicks):
            """Handle clicking an item in the favorites list."""
            if not any(n_clicks_list):
                raise PreventUpdate

            # Find which item was clicked
            triggered = ctx.triggered_id
            if not triggered or not isinstance(triggered, dict):
                raise PreventUpdate
            
            stock_id = triggered.get("index")
            if not stock_id:
                raise PreventUpdate

            # Set search input and trigger search button
            return stock_id, (current_search_clicks or 0) + 1

        # ── Drag-and-drop reorder ────────────────────────────────────────────

        # Clientside: on hidden button click, read window._favoritesOrder and
        # push it into the store so the Python callback can persist it.
        self.app.clientside_callback(
            """
            function(n) {
                if (!window._favoritesOrder) {
                    return window.dash_clientside.no_update;
                }
                var order = window._favoritesOrder;
                window._favoritesOrder = null;
                return order;
            }
            """,
            Output("favorites-order-store", "data"),
            Input("favorites-reorder-btn", "n_clicks"),
            prevent_initial_call=True,
        )

        @self.app.callback(
            Output("app-state-store", "data", allow_duplicate=True),
            Input("favorites-order-store", "data"),
            State("app-state-store", "data"),
            prevent_initial_call=True,
        )
        def on_favorites_reorder(new_order, app_state):
            """Persist drag-and-drop reordered favorites list."""
            if not new_order or not app_state:
                raise PreventUpdate

            current_favorites = app_state.get("favorites", [])
            fav_map = {f["id"]: f for f in current_favorites}

            # Rebuild list in dropped order; keep any IDs not in new_order at end
            reordered = [fav_map[sid] for sid in new_order if sid in fav_map]
            seen = set(new_order)
            for fav in current_favorites:
                if fav["id"] not in seen:
                    reordered.append(fav)

            self.storage.save_favorites(reordered)
            logger.info(f"Favorites reordered: {[f['id'] for f in reordered]}")

            new_state = dict(app_state)
            new_state["favorites"] = reordered
            return new_state

        @self.app.callback(
            Output("stock-search-input", "value", allow_duplicate=True),
            Output("stock-search-button", "n_clicks", allow_duplicate=True),
            Input({"type": "match-item", "index": ALL}, "n_clicks"),
            State("stock-search-button", "n_clicks"),
            prevent_initial_call=True
        )
        def on_match_item_click(n_clicks_list, current_search_clicks):
            """Handle clicking an item in the search match list."""
            if not any(n_clicks_list):
                raise PreventUpdate

            # Find which item was clicked
            triggered = ctx.triggered_id
            if not triggered or not isinstance(triggered, dict):
                raise PreventUpdate
            
            stock_id = triggered.get("index")
            if not stock_id:
                raise PreventUpdate

            # Set search input and trigger search button
            return stock_id, (current_search_clicks or 0) + 1

    def _register_search_callbacks(self) -> None:
        """Register stock search related callbacks."""

        @self.app.callback(
            Output("stock-match-list", "children"),
            Output("stock-match-list", "style"),
            Input("stock-search-input", "value"),
            prevent_initial_call=True
        )
        def on_search_input(search_value: str):
            """Handle search input changes (REQ-012)."""
            logger.debug(f"Search input: '{search_value}'")
            if not search_value or len(search_value.strip()) < 1:
                return [], {"display": "none"}

            try:
                results = self.fetcher.search_stock(search_value)
                logger.debug(f"Search returned {len(results)} results")

                if not results:
                    return [
                        html.Div("查無符合的股票", className="match-item")
                    ], {"display": "block"}

                items = [
                    html.Div(
                        id={"type": "match-item", "index": stock.stock_id},
                        className="match-item",
                        children=[
                            html.Span(stock.stock_id, className="match-item-id"),
                            html.Span(stock.stock_name, className="match-item-name"),
                        ],
                        n_clicks=0,
                    )
                    for stock in results[:10]
                ]

                return items, {"display": "block"}

            except Exception as e:
                logger.error(f"Search error: {e}")
                return [
                    html.Div(f"搜尋發生錯誤", className="match-item")
                ], {"display": "block"}

        @self.app.callback(
            Output("stock-name-display", "children"),
            Output("stock-id-display", "children"),
            Output("stock-sector-display", "children"),
            Output("stock-price-display", "children"),
            Output("stock-price-display", "className"),
            Output("stock-change-display", "children"),
            Output("stock-change-display", "className"),
            Output("stock-volume-display", "children"),
            Output("app-state-store", "data"),
            Output("auto-update-interval", "disabled"),
            Output("stock-match-list", "style", allow_duplicate=True),
            Output("intraday-chart", "figure", allow_duplicate=True),
            Output("kline-chart", "figure", allow_duplicate=True),
            Output("stock-star-toggle", "className", allow_duplicate=True),
            Input("stock-search-button", "n_clicks"),
            State("stock-search-input", "value"),
            State("app-state-store", "data"),
            State("period-selector", "value"),
            prevent_initial_call=True
        )
        def on_search_submit(n_clicks: int, search_value: str, current_state: dict, period_value: str):
            """Handle search button click - select a stock."""
            if not n_clicks or not search_value:
                raise PreventUpdate

            # Phase 4 (N2) — guard against race with load_initial_favorites:
            # when stock-card click navigates from /news → /?stock=NNN, this
            # callback may fire before favorites are loaded into state, which
            # would then drop them from the persisted store.
            current_state = current_state or {}
            if not current_state.get("favorites"):
                try:
                    favs = self.storage.load_favorites() or []
                    if favs:
                        current_state = dict(current_state)
                        current_state["favorites"] = favs
                except Exception as e:
                    logger.debug(f"load_favorites in on_search_submit failed: {e}")

            try:
                # Resolve submit text into a concrete stock first. Exact names
                # such as "國巨" should map to the underlying stock code.
                stock = self.fetcher.resolve_stock(search_value)
                stock_id = stock.stock_id

                # Fetch realtime quote (blocking is fine for search submit)
                quote = self.fetcher.fetch_realtime_quote(stock_id)

                # Initialize volume cache with current TWSE total volume
                if self.on_init_volume:
                    self.on_init_volume(stock_id, quote.total_volume)

                # Check if in favorites (Needed for unsubscription logic)
                favorites = current_state.get("favorites", [])
                fav_ids = [f["id"] for f in favorites]

                # Subscribe to Shioaji streaming if available
                is_using_shioaji = False
                if self.shioaji_fetcher and self.shioaji_fetcher.is_connected:
                    # Unsubscribe previous if changed AND not in favorites
                    if self._current_stock_id and self._current_stock_id != stock_id:
                        # If previous stock is a favorite, keep subscription!
                        if self._current_stock_id not in fav_ids:
                            self.shioaji_fetcher.unsubscribe(self._current_stock_id)
                    
                    is_using_shioaji = bool(self.shioaji_fetcher.subscribe(stock_id))

                    # Switch the 1Hz Quote snapshot stream onto the newly
                    # selected stock so its `timestamp` keeps advancing even
                    # without trades — fixes stale-data alert on illiquid
                    # names. Quota stays at 1 msg/s regardless of watchlist
                    # size because set_active_quote drops the previous sub.
                    if is_using_shioaji and self.scheduler and self.scheduler.is_market_open():
                        try:
                            self.shioaji_fetcher.set_active_quote(stock_id)
                        except Exception as exc:
                            logger.debug(f"set_active_quote({stock_id}) failed: {exc}")

                # Update internal state
                self._current_stock_id = stock_id
                self._current_stock_name = quote.stock_name

                # Check if in favorites (for star button)
                is_favorite = any(f["id"] == stock_id for f in favorites)
                star_class = "star-button active" if is_favorite else "star-button"

                # Save as intraday tick for chart (Immediate update)
                # Skip if using Shioaji (AppController handles streaming ticks)
                if not is_using_shioaji:
                    self._save_quote_as_tick(quote)

                # Add to scheduler for background updates
                self.scheduler.add_stock_job(stock_id)

                # Update app state - Trigger background sync via 'needs_history_sync'
                new_state = current_state.copy() if current_state else {}
                new_state["current_stock"] = stock_id
                new_state["current_stock_name"] = quote.stock_name or stock.stock_name
                new_state["needs_history_sync"] = stock_id  # Flag to trigger sync callback

                # Determine price direction class
                direction_class = self._get_direction_class(quote.direction)
                change_text = f"{'+' if quote.change_amount >= 0 else ''}{quote.change_amount:.2f} ({'+' if quote.change_percent >= 0 else ''}{quote.change_percent:.2f}%)"

                # Render intraday chart with CURRENT local data (Fast)
                intraday_data = self.storage.load_intraday_data(stock_id, date.today())
                big_orders_items = []
                
                if intraday_data and intraday_data.ticks:
                    df = self.processor.prepare_intraday_data(intraday_data.ticks)
                    intraday_figure = self.renderer.render_intraday_chart(
                        df,
                        f"{quote.stock_name} ({stock_id})",
                        quote.previous_close,
                        uirevision=stock_id
                    )
                    
                    # Generate Big Orders List (Newest at Top)
                    if "is_big_buy" in df.columns:
                        big_orders = df[df["is_big_buy"] | df["is_big_sell"]]
                        # Reverse iteration to show newest first
                        for _, row in big_orders.iloc[::-1].iterrows():
                            is_buy = row["is_big_buy"]
                            vol_class = "big-order-volume big-buy" if is_buy else "big-order-volume big-sell"
                            time_str = row["time"].strftime("%H:%M:%S") if isinstance(row["time"], datetime) else str(row["time"])
                            
                            big_orders_items.append(
                                html.Div(
                                    className="big-order-item",
                                    children=[
                                        html.Span(time_str, className="big-order-time"),
                                        html.Span(f"{row['tick_vol_calc']:.0f}", className=vol_class),
                                    ]
                                )
                            )
                        if not big_orders_items:
                            big_orders_items = [html.Div("尚無大戶資料", className="no-data")]
                else:
                    intraday_figure = self.renderer.render_empty_chart("載入中...")
                    big_orders_items = [html.Div("尚無大戶資料", className="no-data")]

                # Render K-line chart with EXISTING local data (Fast)
                daily_file = self.storage.load_daily_data(stock_id)
                if daily_file and daily_file.daily_data:
                    period_map = {
                        "daily": KlinePeriod.DAILY,
                        "weekly": KlinePeriod.WEEKLY,
                        "monthly": KlinePeriod.MONTHLY,
                        "min_1": KlinePeriod.MIN_1,
                        "min_5": KlinePeriod.MIN_5,
                        "min_15": KlinePeriod.MIN_15,
                        "min_30": KlinePeriod.MIN_30,
                        "min_60": KlinePeriod.MIN_60,
                    }
                    period = period_map.get(period_value, KlinePeriod.DAILY)
                    kline_df = self.processor.prepare_kline_data(
                        daily_file.daily_data, 
                        period,
                        realtime_quote=quote
                    )
                    kline_figure = self.renderer.render_kline_chart(
                        kline_df,
                        f"{quote.stock_name} ({stock_id})",
                        period.display_name,
                        uirevision=stock_id
                    )
                else:
                    # If no daily data yet, still try to render a 1-day chart with just the quote
                    kline_df = self.processor.prepare_kline_data(
                        [], 
                        KlinePeriod.DAILY,
                        realtime_quote=quote
                    )
                    if not kline_df.empty:
                        kline_figure = self.renderer.render_kline_chart(
                            kline_df,
                            f"{quote.stock_name} ({stock_id})",
                            "日K",
                            uirevision=stock_id
                        )
                    else:
                        kline_figure = self.renderer.render_empty_chart("同步資料中...")

                tag_pills = [
                    html.Span(t, className="pill pill-industry stock-tag-pill")
                    for t in get_tags(stock_id)
                ]
                return (
                    quote.stock_name,  # stock name
                    stock_id,  # stock id (no parentheses; sector pill follows)
                    tag_pills,  # multi-tag strip
                    f"{quote.current_price:,.2f}",  # price
                    f"stock-price num {direction_class}",  # price class
                    change_text,  # change
                    f"stock-change num {direction_class}",  # change class
                    f"{quote.total_volume:,} 張",  # volume
                    new_state,  # app state
                    False,  # enable auto-update
                    {"display": "none"},  # hide match list
                    intraday_figure,  # intraday chart
                    kline_figure,  # kline chart
                    star_class,  # star toggle class
                )

            except StockNotFoundError:
                logger.warning(f"Stock not found: {search_value}")
                empty_fig = self.renderer.render_empty_chart("查無此股票")
                return (
                    "--", "", "", "--", "stock-price", "", "stock-change",
                    "--", no_update, True, {"display": "none"},
                    empty_fig, empty_fig, "star-button"
                )

            except Exception as e:
                logger.error(f"Error fetching stock: {e}")
                error_fig = self.renderer.render_empty_chart("搜尋發生錯誤")
                return (
                    "--", "", "", "--", "stock-price", "", "stock-change",
                    "--", no_update, True, {"display": "none"},
                    error_fig, error_fig, "star-button"
                )

        @self.app.callback(
            Output("kline-chart", "figure", allow_duplicate=True),
            Output("app-state-store", "data", allow_duplicate=True),
            Input("app-state-store", "data"),
            State("period-selector", "value"),
            prevent_initial_call=True
        )
        def sync_history_data(app_state: dict, period_value: str):
            """Background sync of historical data (Incremental update)."""
            stock_id = app_state.get("needs_history_sync")
            if not stock_id:
                raise PreventUpdate

            logger.info(f"Starting background history sync for {stock_id}")
            
            # Fetch and save missing history (Smart Cache)
            # This is the heavy operation
            self._fetch_and_save_daily_history(stock_id, self._current_stock_name or stock_id)
            
            # After sync, clear the flag to prevent re-triggering
            new_state = app_state.copy()
            new_state.pop("needs_history_sync", None)
            
            # Load the updated data and render
            daily_file = self.storage.load_daily_data(stock_id)
            if daily_file:
                # Fetch latest quote to merge
                try:
                    quote = self.fetcher.fetch_realtime_quote(stock_id)
                except:
                    quote = None

                period_map = {
                    "daily": KlinePeriod.DAILY,
                    "weekly": KlinePeriod.WEEKLY,
                    "monthly": KlinePeriod.MONTHLY,
                    "min_1": KlinePeriod.MIN_1,
                    "min_5": KlinePeriod.MIN_5,
                    "min_15": KlinePeriod.MIN_15,
                    "min_30": KlinePeriod.MIN_30,
                    "min_60": KlinePeriod.MIN_60,
                }
                period = period_map.get(period_value, KlinePeriod.DAILY)
                df = self.processor.prepare_kline_data(
                    daily_file.daily_data, 
                    period,
                    realtime_quote=quote
                )
                figure = self.renderer.render_kline_chart(
                    df,
                    f"{daily_file.stock_name} ({stock_id})",
                    period.display_name,
                    uirevision=stock_id
                )
                logger.info(f"Background sync complete for {stock_id}")
                return figure, new_state
            
            return no_update, new_state

    def _register_tab_callbacks(self) -> None:
        """Register tab switching callbacks."""

        @self.app.callback(
            Output("intraday-chart", "figure"),
            Input("main-tabs", "value"),
            State("app-state-store", "data"),
            prevent_initial_call=True
        )
        def on_tab_switch_intraday(active_tab: str, app_state: dict):
            """Handle switch to intraday tab (REQ-031)."""
            if active_tab != "intraday":
                raise PreventUpdate

            stock_id = app_state.get("current_stock") if app_state else None
            if not stock_id:
                return self.renderer.render_empty_chart("請選擇股票")

            try:
                # Get intraday data
                from datetime import date
                intraday_data = self.storage.load_intraday_data(stock_id, date.today())

                if intraday_data and intraday_data.ticks:
                    df = self.processor.prepare_intraday_data(intraday_data.ticks)
                    return self.renderer.render_intraday_chart(
                        df,
                        f"{intraday_data.stock_name} ({stock_id})",
                        intraday_data.previous_close,
                        uirevision=stock_id
                    )
                else:
                    return self.renderer.render_empty_chart("暫無分時資料")

            except Exception as e:
                logger.error(f"Error rendering intraday chart: {e}")
                return self.renderer.render_empty_chart(f"載入失敗: {str(e)}")

    def _register_period_callbacks(self) -> None:
        """Register K-line period change callbacks."""

        @self.app.callback(
            Output("kline-chart", "figure"),
            Input("period-selector", "value"),
            Input("main-tabs", "value"),
            State("app-state-store", "data"),
            prevent_initial_call=True
        )
        def on_period_change(period_value: str, active_tab: str, app_state: dict):
            """Handle K-line period change (REQ-055, REQ-056)."""
            if active_tab != "kline":
                raise PreventUpdate

            stock_id = app_state.get("current_stock") if app_state else None
            if not stock_id:
                return self.renderer.render_empty_chart("請選擇股票")

            try:
                # Map period value to KlinePeriod
                period_map = {
                    "daily": KlinePeriod.DAILY,
                    "weekly": KlinePeriod.WEEKLY,
                    "monthly": KlinePeriod.MONTHLY,
                    "min_1": KlinePeriod.MIN_1,
                    "min_5": KlinePeriod.MIN_5,
                    "min_15": KlinePeriod.MIN_15,
                    "min_30": KlinePeriod.MIN_30,
                    "min_60": KlinePeriod.MIN_60,
                }
                period = period_map.get(period_value, KlinePeriod.DAILY)
                period_label = period.display_name

                # Load daily data
                daily_file = self.storage.load_daily_data(stock_id)

                if daily_file:
                    # Fetch latest quote for the current day
                    try:
                        quote = self.fetcher.fetch_realtime_quote(stock_id)
                    except:
                        quote = None

                    df = self.processor.prepare_kline_data(
                        daily_file.daily_data, 
                        period,
                        realtime_quote=quote
                    )
                    return self.renderer.render_kline_chart(
                        df,
                        f"{daily_file.stock_name} ({stock_id})",
                        period_label,
                        uirevision=stock_id
                    )
                else:
                    return self.renderer.render_empty_chart("暫無K線資料")

            except Exception as e:
                logger.error(f"Error rendering K-line chart: {e}")
                return self.renderer.render_empty_chart(f"載入失敗: {str(e)}")

        @self.app.callback(
            Output("kline-chart", "figure", allow_duplicate=True),
            Input("kline-chart", "relayoutData"),
            State("app-state-store", "data"),
            State("period-selector", "value"),
            prevent_initial_call=True
        )
        def on_kline_zoom(relayout_data: dict, app_state: dict, period_value: str):
            """Handle K-line chart zoom/pan to load more historical data."""
            if not relayout_data:
                raise PreventUpdate

            stock_id = app_state.get("current_stock") if app_state else None
            if not stock_id:
                raise PreventUpdate

            # Check if this is a zoom/pan event with x-axis range
            x_range_start = None
            if "xaxis.range[0]" in relayout_data:
                x_range_start = relayout_data["xaxis.range[0]"]
            elif "xaxis.range" in relayout_data:
                x_range_start = relayout_data["xaxis.range"][0]

            if not x_range_start:
                raise PreventUpdate

            try:
                # Parse the start date from the range
                if isinstance(x_range_start, str):
                    # Handle various datetime string formats from Plotly
                    try:
                        # Try standard ISO format first
                        requested_start = datetime.fromisoformat(x_range_start.replace("Z", "+00:00")).date()
                    except ValueError:
                        # Handle format like '2025-06-28 13:29:01.7266'
                        # Extract just the date part
                        date_part = x_range_start.split(" ")[0].split("T")[0]
                        requested_start = datetime.strptime(date_part, "%Y-%m-%d").date()
                else:
                    raise PreventUpdate

                # Load current data to check earliest date
                daily_file = self.storage.load_daily_data(stock_id)
                if not daily_file or not daily_file.daily_data:
                    raise PreventUpdate

                # Find earliest date in current data
                earliest_date = min(record.date for record in daily_file.daily_data)

                # If requested start is before our earliest data, fetch more
                if requested_start >= earliest_date:
                    # We already have data for this range
                    raise PreventUpdate

                logger.info(f"Fetching more history: requested {requested_start}, have {earliest_date}")

                # Calculate months to fetch (from requested start to our earliest)
                months_to_fetch = []
                current = requested_start
                while current < earliest_date:
                    months_to_fetch.append((current.year, current.month))
                    # Move to next month
                    if current.month == 12:
                        current = date(current.year + 1, 1, 1)
                    else:
                        current = date(current.year, current.month + 1, 1)

                # Fetch missing months (limit to 12 months at a time)
                all_records = []
                for year, month in months_to_fetch[:12]:
                    try:
                        logger.info(f"Fetching {stock_id} for {year}/{month}...")
                        records = self.fetcher.fetch_daily_history(stock_id, year, month)
                        if records:
                            all_records.extend(records)
                            logger.info(f"Got {len(records)} records for {year}/{month}")
                    except Exception as e:
                        logger.warning(f"Failed to fetch {year}/{month}: {e}")
                        continue

                # Save new records
                if all_records:
                    self.storage.save_daily_data(
                        stock_id,
                        daily_file.stock_name,
                        all_records
                    )
                    logger.info(f"Saved {len(all_records)} new historical records for {stock_id}")
                else:
                    logger.warning(f"No new records fetched for {stock_id}")

                # Re-render chart with all data (including newly fetched)
                period_map = {
                    "daily": KlinePeriod.DAILY,
                    "weekly": KlinePeriod.WEEKLY,
                    "monthly": KlinePeriod.MONTHLY,
                    "min_1": KlinePeriod.MIN_1,
                    "min_5": KlinePeriod.MIN_5,
                    "min_15": KlinePeriod.MIN_15,
                    "min_30": KlinePeriod.MIN_30,
                    "min_60": KlinePeriod.MIN_60,
                }
                period = period_map.get(period_value, KlinePeriod.DAILY)

                # Reload data with new records
                daily_file = self.storage.load_daily_data(stock_id)
                if daily_file and daily_file.daily_data:
                    df = self.processor.prepare_kline_data(daily_file.daily_data, period)
                    logger.info(f"Re-rendering chart with {len(df)} data points")
                    return self.renderer.render_kline_chart(
                        df,
                        f"{daily_file.stock_name} ({stock_id})",
                        period.display_name,
                        uirevision=stock_id
                    )

                raise PreventUpdate

            except PreventUpdate:
                raise
            except Exception as e:
                logger.warning(f"Zoom handler error: {e}")
                raise PreventUpdate

    def _register_update_callbacks(self) -> None:
        """Register auto-update callbacks."""

        @self.app.callback(
            Output("stock-price-display", "children", allow_duplicate=True),
            Output("stock-price-display", "className", allow_duplicate=True),
            Output("stock-change-display", "children", allow_duplicate=True),
            Output("stock-change-display", "className", allow_duplicate=True),
            Output("stock-volume-display", "children", allow_duplicate=True),
            Output("intraday-chart", "figure", allow_duplicate=True),
            Output("kline-chart", "figure", allow_duplicate=True),
            Output("big-orders-list", "children", allow_duplicate=True),
            Output("best-five-prices-body", "children", allow_duplicate=True),
            Output("bidask-ratio-inner", "style", allow_duplicate=True),
            Output("ask-total-vol", "children", allow_duplicate=True),
            Output("bid-total-vol", "children", allow_duplicate=True),
            Input("auto-update-interval", "n_intervals"),
            State("app-state-store", "data"),
            State("main-tabs", "value"),
            State("period-selector", "value"),
            prevent_initial_call=True
        )
        def on_auto_update(n_intervals: int, app_state: dict, active_tab: str, period_value: str):
            """Handle automatic updates (REQ-044)."""
            stock_id = app_state.get("current_stock") if app_state else None

            if not stock_id:
                return (
                    no_update, no_update, no_update, no_update,
                    no_update, no_update, no_update, no_update,
                    no_update, no_update, no_update, no_update,
                )

            try:
                # Fetch realtime quote (non-blocking)
                # If Shioaji has data, it returns immediately.
                # If falling back to TWSE, it returns None if rate limit hit.
                quote = self.fetcher.fetch_realtime_quote(stock_id, blocking=False)

                if quote is None:
                    # Rate limit hit (TWSE) or no data available yet
                    return (
                        no_update, no_update, no_update, no_update,
                        no_update, no_update, no_update, no_update,
                        no_update, no_update, no_update, no_update,
                    )

                direction_class = self._get_direction_class(quote.direction)
                change_text = f"{'+' if quote.change_amount >= 0 else ''}{quote.change_amount:.2f} ({'+' if quote.change_percent >= 0 else ''}{quote.change_percent:.2f}%)"

                # Shioaji tick callback stores real transaction times. Do not
                # turn Shioaji quote snapshots into fake ticks at poll time.
                if not (self.shioaji_fetcher and self.shioaji_fetcher.is_subscribed(stock_id)):
                    self._save_quote_as_tick(quote)

                # OPTIMIZATION: Update charts every 2 seconds (n_intervals % 2 == 0)
                # Text updates (price, time) happen every second.
                intraday_figure = no_update
                big_orders_items = no_update
                kline_figure = no_update
                five_prices_body = no_update
                bidask_ratio_style = no_update
                ask_total_text = no_update
                bid_total_text = no_update

                if n_intervals % 2 == 0:
                    # Update intraday chart if on intraday tab OR if we need Big Orders (which needs intraday data)
                    # Note: Big Orders list is always visible, so we usually need to load this.
                    # Optimization: Only load if we are on intraday tab OR (it's time to update big orders and we want them)
                    # Let's keep loading it every 2s for Big Orders.
                    
                    intraday_data = self.storage.load_intraday_data(stock_id, date.today())
                    
                    # --- REAL-TIME TICK BUFFER MERGE ---
                    # To keep the UI perfectly real-time while disk writes are batched (every 5s),
                    # we must fetch any ticks currently waiting in the memory buffer.
                    all_ticks = []
                    if intraday_data and intraday_data.ticks:
                        all_ticks.extend(intraday_data.ticks)
                        
                    if self.get_buffered_ticks:
                        buffered_ticks = self.get_buffered_ticks(stock_id)
                        if buffered_ticks:
                            all_ticks.extend(buffered_ticks)
                    
                    if all_ticks:
                        df = self.processor.prepare_intraday_data(all_ticks)
                        
                        # Only render intraday chart if tab is active
                        if active_tab == "intraday":
                            intraday_figure = self.renderer.render_intraday_chart(
                                df,
                                f"{quote.stock_name} ({stock_id})",
                                quote.previous_close,
                                uirevision=stock_id
                            )
                        
                        # Generate Big Orders List — Phase 3.5: 3-column tape
                        # (時間 / 張數 / 金額); newest at top.
                        big_orders_items = []

                        if "is_big_buy" in df.columns:
                            big_orders = df[df["is_big_buy"] | df["is_big_sell"]]
                            for _, row in big_orders.iloc[::-1].iterrows():
                                is_buy = bool(row["is_big_buy"])
                                vol_calc = float(row.get("tick_vol_calc", 0) or 0)
                                price_val = float(row.get("price", 0) or 0)
                                amt_val = vol_calc * price_val * 1000  # 張 → 股 → 金額
                                time_str = (
                                    row["time"].strftime("%H:%M:%S")
                                    if isinstance(row["time"], datetime)
                                    else str(row["time"])
                                )
                                side_cls = "up" if is_buy else "down"
                                signed_vol = f"+{vol_calc:.0f}" if is_buy else f"-{vol_calc:.0f}"
                                big_orders_items.append(
                                    html.Div(
                                        className=f"big-order-item {side_cls}",
                                        children=[
                                            html.Span(time_str, className="num big-order-time"),
                                            html.Span(
                                                signed_vol,
                                                className=f"num big-order-volume {side_cls}",
                                            ),
                                            html.Span(
                                                f"{amt_val:,.0f}",
                                                className=f"num big-order-amt {side_cls}",
                                            ),
                                        ],
                                    )
                                )
                            if not big_orders_items:
                                big_orders_items = [html.Div("尚無大戶資料", className="no-data")]
                    else:
                        if active_tab == "intraday":
                            intraday_figure = self.renderer.render_empty_chart("載入中...")
                        big_orders_items = [html.Div("尚無大戶資料", className="no-data")]

                    # Update K-line chart if on K-line tab
                    if active_tab == "kline":
                        daily_file = self.storage.load_daily_data(stock_id)
                        if daily_file:
                            period_map = {
                                "daily": KlinePeriod.DAILY,
                                "weekly": KlinePeriod.WEEKLY,
                                "monthly": KlinePeriod.MONTHLY,
                                "min_1": KlinePeriod.MIN_1,
                                "min_5": KlinePeriod.MIN_5,
                                "min_15": KlinePeriod.MIN_15,
                                "min_30": KlinePeriod.MIN_30,
                                "min_60": KlinePeriod.MIN_60,
                            }
                            period = period_map.get(period_value, KlinePeriod.DAILY)
                            
                            # Merge live quote into K-line
                            kline_df = self.processor.prepare_kline_data(
                                daily_file.daily_data, 
                                period,
                                realtime_quote=quote
                            )
                            kline_figure = self.renderer.render_kline_chart(
                                kline_df,
                                f"{quote.stock_name} ({stock_id})",
                                period.display_name,
                                uirevision=stock_id
                            )

                    # Update Best Five Prices
                    bidask = self.shioaji_fetcher.get_last_bidask(stock_id) if self.shioaji_fetcher else None
                    if bidask and bidask.get("bid_price") and bidask.get("ask_price"):
                        bid_prices = bidask["bid_price"]
                        bid_volumes = bidask["bid_volume"]
                        ask_prices = bidask["ask_price"]
                        ask_volumes = bidask["ask_volume"]
                        # 合計 sums visible 5 levels — Shioaji
                        # *_side_total_vol unreliable in sim and sometimes
                        # zero in prod bidask events.
                        bid_side_total = sum(int(v or 0) for v in bid_volumes)
                        ask_side_total = sum(int(v or 0) for v in ask_volumes)

                        # Build five-level rows — Phase 3.5: each cell carries
                        # an inline linear-gradient soft-fill proportional to
                        # its volume share, mirroring atoms layout-variants.jsx
                        # ::Best5Mini.
                        rows = []
                        levels = min(5, len(bid_prices), len(ask_prices))
                        max_v = 1
                        for i in range(levels):
                            bv = bid_volumes[i] if i < len(bid_volumes) else 0
                            av = ask_volumes[i] if i < len(ask_volumes) else 0
                            if bv > max_v: max_v = bv
                            if av > max_v: max_v = av
                        for i in range(levels):
                            bv = bid_volumes[i] if i < len(bid_volumes) else 0
                            av = ask_volumes[i] if i < len(ask_volumes) else 0
                            bid_pct = (bv / max_v * 100) if max_v else 0
                            ask_pct = (av / max_v * 100) if max_v else 0
                            bid_bg = (
                                f"linear-gradient(to left, var(--up-soft) "
                                f"{bid_pct:.1f}%, transparent {bid_pct:.1f}%)"
                            )
                            ask_bg = (
                                f"linear-gradient(to right, var(--down-soft) "
                                f"{ask_pct:.1f}%, transparent {ask_pct:.1f}%)"
                            )
                            rows.append(
                                html.Div(
                                    className="five-price-row",
                                    children=[
                                        html.Div(
                                            className="five-price-cell five-cell-bid",
                                            style={"background": bid_bg},
                                            children=[
                                                html.Span(f"{bv:,}", className="num five-bid-vol"),
                                                html.Span(
                                                    f"{bid_prices[i]:.2f}",
                                                    className="num five-bid-price up",
                                                ),
                                            ],
                                        ),
                                        html.Div(
                                            className="five-price-cell five-cell-ask",
                                            style={"background": ask_bg},
                                            children=[
                                                html.Span(
                                                    f"{ask_prices[i]:.2f}",
                                                    className="num five-ask-price down",
                                                ),
                                                html.Span(f"{av:,}", className="num five-ask-vol"),
                                            ],
                                        ),
                                    ],
                                )
                            )
                        five_prices_body = rows

                        # Bid/Ask ratio bar
                        total = ask_side_total + bid_side_total
                        ratio_pct = (ask_side_total / total * 100) if total > 0 else 50
                        bidask_ratio_style = {"width": f"{ratio_pct:.1f}%"}
                        ask_total_text = f"{ask_side_total:,}"
                        bid_total_text = f"{bid_side_total:,}"

                return (
                    f"{quote.current_price:,.2f}",
                    f"stock-price num {direction_class}",
                    change_text,
                    f"stock-change num {direction_class}",
                    f"{quote.total_volume:,} 張",
                    intraday_figure,
                    kline_figure,
                    big_orders_items,
                    five_prices_body,
                    bidask_ratio_style,
                    ask_total_text,
                    bid_total_text,
                )

            except Exception as e:
                logger.warning(f"Auto-update failed: {e}")
                return (
                    no_update, no_update, no_update, no_update,
                    no_update, no_update, no_update, no_update,
                    no_update, no_update, no_update, no_update,
                )

    def _register_hover_callbacks(self) -> None:
        """Register chart hover callbacks."""

        @self.app.callback(
            Output("ohlc-open", "children"),
            Output("ohlc-high", "children"),
            Output("ohlc-low", "children"),
            Output("ohlc-close", "children"),
            Output("ohlc-volume", "children"),
            Input("kline-chart", "hoverData"),
            prevent_initial_call=True
        )
        def on_kline_hover(hover_data: dict):
            """Handle K-line chart hover (REQ-058)."""
            if not hover_data or "points" not in hover_data:
                return "--", "--", "--", "--", "--"

            try:
                point = hover_data["points"][0]
                customdata = point.get("customdata", {})

                if isinstance(customdata, dict):
                    return (
                        f"{customdata.get('open', '--'):.2f}" if customdata.get('open') else "--",
                        f"{customdata.get('high', '--'):.2f}" if customdata.get('high') else "--",
                        f"{customdata.get('low', '--'):.2f}" if customdata.get('low') else "--",
                        f"{customdata.get('close', '--'):.2f}" if customdata.get('close') else "--",
                        f"{customdata.get('volume', '--'):,}" if customdata.get('volume') else "--",
                    )
            except Exception as e:
                logger.debug(f"Hover data parse error: {e}")

            return "--", "--", "--", "--", "--"

    def _register_error_callbacks(self) -> None:
        """Register error handling callbacks."""

        @self.app.callback(
            Output("error-message-display", "style"),
            Input("error-close-button", "n_clicks"),
            prevent_initial_call=True
        )
        def on_error_close(n_clicks: int):
            """Handle error message close button."""
            return {"display": "none"}

    def _register_stock_stats_callbacks(self) -> None:
        """Phase 7 — wire the StockHeader 7-stat strip.

        Drives off the existing 1Hz `auto-update-interval` plus app-state
        changes. Reads the last RealtimeQuote (non-blocking) so the call
        is cheap when Shioaji has pushed a tick, and falls back to the
        cached fundamentals snapshot for PE. 外資持股 has no data source
        yet — left as "--" so the cell stays visible without lying about
        a value.
        """

        @self.app.callback(
            Output("stock-stat-open",    "children"),
            Output("stock-stat-open",    "className"),
            Output("stock-stat-high",    "children"),
            Output("stock-stat-high",    "className"),
            Output("stock-stat-low",     "children"),
            Output("stock-stat-low",     "className"),
            Output("stock-stat-prev",    "children"),
            Output("stock-stat-pe",      "children"),
            Output("stock-volume-display", "className", allow_duplicate=True),
            Output("stock-stat-foreign", "children"),
            Output("stock-stat-foreign", "className"),
            Input("auto-update-interval", "n_intervals"),
            Input("app-state-store", "data"),
            prevent_initial_call="initial_duplicate",
        )
        def update_stock_stats(_n_intervals: int, app_state: Optional[dict]):
            base_cls = "stat-value num"
            placeholder = (
                "--", base_cls,
                "--", base_cls,
                "--", base_cls,
                "--",
                "--",
                base_cls,
                "--", base_cls,
            )
            stock_id = (app_state or {}).get("current_stock") if app_state else None
            if not stock_id:
                return placeholder

            try:
                quote = self.fetcher.fetch_realtime_quote(stock_id, blocking=False)
            except Exception as exc:
                logger.debug(f"update_stock_stats quote fetch failed: {exc}")
                quote = None

            def _fmt_price(v: Optional[float]) -> str:
                if v is None or v == 0:
                    return "--"
                return f"{v:,.2f}"

            def _dir(diff: float) -> str:
                if diff > 0:
                    return "up"
                if diff < 0:
                    return "down"
                return "flat"

            open_txt = _fmt_price(quote.open_price)     if quote else "--"
            high_txt = _fmt_price(quote.high_price)     if quote else "--"
            low_txt  = _fmt_price(quote.low_price)      if quote else "--"
            prev_txt = _fmt_price(quote.previous_close) if quote else "--"

            prev_close = (quote.previous_close or 0) if quote else 0
            # 開盤 vs 昨收 → 跳空方向 (gap up/down)
            if quote and quote.open_price and prev_close:
                open_cls = f"{base_cls} {_dir(quote.open_price - prev_close)}"
            else:
                open_cls = base_cls
            # 最高 / 最低 / 成交量 → 跟當日漲跌方向 (change_amount) 同向
            day_dir = _dir(quote.change_amount) if quote else "flat"
            high_cls = f"{base_cls} {day_dir}" if quote else base_cls
            low_cls  = f"{base_cls} {day_dir}" if quote else base_cls
            vol_cls = f"num stock-volume-value stat-value {day_dir}" if quote \
                else "num stock-volume-value stat-value"

            pe_txt = "--"
            try:
                snap = get_fundamentals(stock_id)
                if snap and snap.pe:
                    pe_txt = f"{snap.pe:.2f}"
            except Exception as exc:
                logger.debug(f"update_stock_stats fundamentals failed: {exc}")

            # 外資 = 外資買賣超 (T86 三大法人) via ChipsStorage. Header
            # cell mirrors the 籌碼面 panel's "外資" card value_text + direction
            # so the user sees the same number/colour in both places.
            foreign_txt = "--"
            foreign_dir = "flat"
            try:
                cards = build_chips_kpi(stock_id, self.chips_storage)
                for c in cards:
                    if c.key == "foreign":
                        foreign_txt = c.value_text or "--"
                        foreign_dir = c.direction or "flat"
                        break
            except Exception as exc:
                logger.debug(f"update_stock_stats chips failed: {exc}")
            foreign_cls = f"{base_cls} {foreign_dir}"

            return (
                open_txt, open_cls,
                high_txt, high_cls,
                low_txt,  low_cls,
                prev_txt,
                pe_txt,
                vol_cls,
                foreign_txt, foreign_cls,
            )

    def _get_direction_class(self, direction: PriceDirection) -> str:
        """Get CSS class for price direction."""
        if direction == PriceDirection.UP:
            return "price-up"
        elif direction == PriceDirection.DOWN:
            return "price-down"
        return "price-flat"

    def show_error(self, message: str, error_type: str = "error") -> None:
        """
        Show error message in the UI.

        Args:
            message: Error message to display
            error_type: "error", "warning", or "info"
        """
        # This would be called programmatically
        # In Dash, we'd need to use a Store + callback pattern
        logger.error(f"UI Error ({error_type}): {message}")

    def _load_news_store_data(self, force_refresh: bool = False) -> Optional[dict]:
        """Load latest news, or run a fresh collection for manual refresh."""
        run_result = None
        if force_refresh and self.news_processor:
            run_result = self.news_processor.run()
        else:
            run_result = self.storage.load_latest_news()

        if run_result is None:
            return None
        return run_result.to_dict()

    def _load_news_events_store_data(self) -> Optional[dict]:
        """Load the latest news event timeline sidecar."""
        event_file = self.storage.load_news_events()
        if event_file is None:
            return None
        return event_file.to_dict()

    def _save_quote_as_tick(self, quote: RealtimeQuote) -> None:
        """
        Save a realtime quote as an intraday tick.

        This accumulates price data for the intraday chart.

        Args:
            quote: RealtimeQuote to convert and save
        """
        try:
            if getattr(quote, "is_simtrade", False):
                logger.debug(f"Skip saving simtrade quote for {quote.stock_id}")
                return
            trade_date = date.today()
            if not quote_timestamp_matches_trade_date(quote, trade_date):
                logger.debug(
                    "Skip saving stale quote for %s: timestamp=%s trade_date=%s",
                    quote.stock_id,
                    quote.timestamp,
                    trade_date,
                )
                return

            # Load previous ticks to calculate volume delta and price trend (REQ-FixVolume0)
            last_accumulated_volume = 0
            last_price = quote.previous_close # Default to prev close if no ticks
            
            existing_data = self.storage.load_intraday_data(quote.stock_id, trade_date)
            stream_sum = 0
            has_accumulated_anchor = False
            
            if existing_data and existing_data.ticks:
                last_tick = existing_data.ticks[-1]
                last_price = last_tick.price
                
                # Search backwards for last non-zero accumulated volume
                # And sum up the volume of Shioaji ticks (acc=0) in between
                for t in reversed(existing_data.ticks):
                    if t.accumulated_volume > 0:
                        last_accumulated_volume = t.accumulated_volume
                        has_accumulated_anchor = True
                        break
                    
                    # Skip odd lots for stream sum (they are shares, but quote.total_volume is lots)
                    if getattr(t, 'is_odd', False):
                        continue
                        
                    stream_sum += t.volume

            # Calculate actual volume since last poll
            latest_tick_volume = max(0, int(getattr(quote, "tick_volume", 0) or 0))
            if quote.total_volume >= last_accumulated_volume:
                if has_accumulated_anchor:
                    delta = quote.total_volume - last_accumulated_volume
                    # Deduplicate: Subtract volume already captured by stream ticks
                    tick_volume = max(0, delta - stream_sum)
                else:
                    # A first snapshot's cumulative volume is not one trade.
                    # Keep the total as accumulated_volume, but only use the
                    # source's latest single-trade volume for per-tick volume.
                    tick_volume = latest_tick_volume
            else:
                tick_volume = latest_tick_volume

            # Determine buy/sell volume based on Price Trend (Primary) -> Bid/Ask (Secondary)
            buy_volume = 0.0
            sell_volume = 0.0
            
            if quote.current_price > last_price:
                # Price Up -> Dominant Buy
                buy_volume = float(tick_volume)
            elif quote.current_price < last_price:
                # Price Down -> Dominant Sell
                sell_volume = float(tick_volume)
            else:
                # Price Unchanged -> Check Bid/Ask
                if quote.best_ask and quote.current_price >= quote.best_ask:
                    buy_volume = float(tick_volume)
                elif quote.best_bid and quote.current_price <= quote.best_bid:
                    sell_volume = float(tick_volume)
                else:
                    # Indeterminate -> Split
                    buy_volume = tick_volume / 2.0
                    sell_volume = tick_volume / 2.0

            # If this is the first data point (gap fill from 0 to Current Total), do not bias Buy/Sell power
            # We preserve tick_volume for the Total Volume chart, but neutralize Buy/Sell Power
            if last_accumulated_volume == 0:
                buy_volume = 0.0
                sell_volume = 0.0

            tick = IntradayTick(
                time=quote.timestamp.time() if quote.timestamp else datetime.now().time(),
                price=quote.current_price,
                volume=tick_volume,
                buy_volume=buy_volume,
                sell_volume=sell_volume,
                accumulated_volume=quote.total_volume,
                timestamp=quote.timestamp or datetime.now(),
            )

            self.storage.save_intraday_data(
                stock_id=quote.stock_id,
                stock_name=quote.stock_name,
                trade_date=trade_date,
                previous_close=quote.previous_close,
                ticks=[tick],
            )
            logger.debug(f"Saved intraday tick for {quote.stock_id}: {quote.current_price} (V:{tick_volume}, B:{buy_volume}, S:{sell_volume})")
        except Exception as e:
            logger.warning(f"Failed to save intraday tick: {e}")

    def _fetch_and_save_daily_history(self, stock_id: str, stock_name: str) -> None:
        """
        Fetch and save historical daily OHLC data for K-line chart.

        Fetches the last 3 months of data to populate the K-line chart.

        Args:
            stock_id: Stock ID
            stock_name: Stock name
        """
        try:
            today = date.today()
            all_records = []

            # Fetch last 6 months of data for initial load
            for months_ago in range(6):
                year = today.year
                month = today.month - months_ago
                if month <= 0:
                    month += 12
                    year -= 1

                try:
                    records = self.fetcher.fetch_daily_history(stock_id, year, month)
                    if records:
                        all_records.extend(records)
                        logger.debug(f"Fetched {len(records)} records for {stock_id} ({year}/{month})")
                except Exception as e:
                    logger.warning(f"Failed to fetch history for {year}/{month}: {e}")
                    continue

            # Save all records
            if all_records:
                self.storage.save_daily_data(stock_id, stock_name, all_records)
                logger.info(f"Saved {len(all_records)} daily records for {stock_id}")

        except Exception as e:
            logger.warning(f"Failed to fetch daily history for {stock_id}: {e}")

    # ── News callbacks ───────────────────────────────────────────────────────

    def _register_news_callbacks(self) -> None:
        """
        Register all news-related callbacks.

        TASK-153: URL routing → page-content
        TASK-154: Main page stock-filtered news tab
        TASK-155: /news page category view + manual refresh
        TASK-156: Ticker bar rotation (5 s)
        """
        from src.app.layout import (
            create_advisor_page_layout,
            create_main_page_layout,
            create_news_page_layout,
        )

        # ── TASK-153  Routing ────────────────────────────────────────────────
        @self.app.callback(
            Output("page-content", "children"),
            Input("url", "pathname"),
        )
        def route_page(pathname: str):
            """Swap page-content based on URL pathname."""
            if pathname == "/news":
                return create_news_page_layout()
            if pathname == "/advisor":
                return create_advisor_page_layout()
            return create_main_page_layout()

        # ── News data store refresh ──────────────────────────────────────────
        # Loads latest news into the shared store so all news callbacks
        # can read from it without hitting storage independently.
        @self.app.callback(
            Output("news-data-store", "data"),
            Input("news-ticker-interval", "n_intervals"),
            Input("news-refresh-button", "n_clicks", allow_optional=True),
            prevent_initial_call=False,
        )
        def refresh_news_store(n_intervals, n_clicks):
            """Load latest news run result into the shared data store."""
            manual_refresh = ctx.triggered_id == "news-refresh-button" and bool(n_clicks)
            try:
                return self._load_news_store_data(force_refresh=manual_refresh)
            except Exception as e:
                logger.warning(f"Failed to load latest news: {e}")
                return no_update

        # ── Phase 3b event timeline store refresh ───────────────────────────
        @self.app.callback(
            Output("news-events-store", "data"),
            Input("news-ticker-interval", "n_intervals"),
            Input("news-refresh-button", "n_clicks", allow_optional=True),
            prevent_initial_call=False,
        )
        def refresh_news_events_store(n_intervals, n_clicks):
            """Load latest news event timeline into a dedicated store."""
            try:
                return self._load_news_events_store_data()
            except Exception as e:
                logger.warning(f"Failed to load news events: {e}")
                return no_update

        # ── Phase 4.5  Stock news in layout-B right rail ─────────────────────
        @self.app.callback(
            Output("right-rail-news-content", "children"),
            Input("news-data-store", "data"),
            Input("app-state-store", "data"),
            prevent_initial_call=False,
        )
        def update_right_rail_news(news_data: dict, app_state: dict):
            """Render per-stock impact news in the layout-B right rail."""
            if not news_data:
                return html.Div("尚無新聞資料", className="no-news")

            current_stock = (app_state or {}).get("current_stock")
            if not current_stock:
                return html.Div("請先選擇股票", className="no-news")

            current_stock_name = (app_state or {}).get("current_stock_name")
            articles = _extract_articles_from_run(
                news_data,
                "ALL",
                current_stock,
                current_stock_name,
            )
            if not articles:
                return html.Div(f"目前無 {current_stock} 相關新聞", className="no-news")

            return _render_right_rail_news_list(articles, stock_id=current_stock)

        # ── Phase 4 (N2) filter buttons → set filter state + active style ──
        @self.app.callback(
            Output("news-filter-state", "data"),
            Output("news-filter-btn-all",     "className"),
            Output("news-filter-btn-up",      "className"),
            Output("news-filter-btn-down",    "className"),
            Output("news-filter-btn-neutral", "className"),
            Output("news-filter-btn-fav",     "className"),
            Input("news-filter-btn-all",     "n_clicks"),
            Input("news-filter-btn-up",      "n_clicks"),
            Input("news-filter-btn-down",    "n_clicks"),
            Input("news-filter-btn-neutral", "n_clicks"),
            Input("news-filter-btn-fav",     "n_clicks"),
            State("news-filter-state", "data"),
            prevent_initial_call=False,
        )
        def update_filter_state(_a, _u, _d, _n, _f, current):
            mapping = {
                "news-filter-btn-all":     "ALL",
                "news-filter-btn-up":      "UP",
                "news-filter-btn-down":    "DOWN",
                "news-filter-btn-neutral": "NEUTRAL",
                "news-filter-btn-fav":     "FAVORITES",
            }
            trig = ctx.triggered_id
            value = mapping.get(trig, current or "ALL")

            def _cls(v: str) -> str:
                base = "news-filter-chip"
                if v == value:
                    base += " news-filter-chip-active"
                return base

            return (
                value,
                _cls("ALL"), _cls("UP"), _cls("DOWN"),
                _cls("NEUTRAL"), _cls("FAVORITES"),
            )

        # ── Phase 4 (N2) sort buttons → toggle direction / switch field ──
        @self.app.callback(
            Output("news-sort-state", "data"),
            Output("news-sort-btn-impact", "children"),
            Output("news-sort-btn-time",   "children"),
            Output("news-sort-btn-heat",   "children"),
            Output("news-sort-btn-impact", "className"),
            Output("news-sort-btn-time",   "className"),
            Output("news-sort-btn-heat",   "className"),
            Input("news-sort-btn-impact", "n_clicks"),
            Input("news-sort-btn-time",   "n_clicks"),
            Input("news-sort-btn-heat",   "n_clicks"),
            State("news-sort-state", "data"),
            prevent_initial_call=False,
        )
        def update_sort_state(_i, _t, _h, current):
            current = current or {"field": "IMPACT", "direction": "desc"}
            trig = ctx.triggered_id
            mapping = {
                "news-sort-btn-impact": "IMPACT",
                "news-sort-btn-time":   "TIME",
                "news-sort-btn-heat":   "HEAT",
            }
            new_field = mapping.get(trig)
            if new_field is None:
                # initial fire — keep current state
                state = current
            elif new_field == current.get("field"):
                # toggle direction on same field
                state = {
                    "field": new_field,
                    "direction": "asc" if current.get("direction") == "desc" else "desc",
                }
            else:
                # switch field, default desc
                state = {"field": new_field, "direction": "desc"}

            arrow = "↓" if state["direction"] == "desc" else "↑"
            labels = {
                "IMPACT": f"影響 {arrow}",
                "TIME":   f"時間 {arrow}",
                "HEAT":   f"熱度 {arrow}",
            }

            def _label(field: str) -> str:
                if field == state["field"]:
                    return labels[field]
                # inactive — always show ↓ as neutral hint
                return {"IMPACT": "影響 ↓", "TIME": "時間 ↓", "HEAT": "熱度 ↓"}[field]

            def _cls(field: str) -> str:
                base = "news-sort-chip"
                if field == state["field"]:
                    base += " news-sort-chip-active"
                return base

            return (
                state,
                _label("IMPACT"), _label("TIME"), _label("HEAT"),
                _cls("IMPACT"), _cls("TIME"), _cls("HEAT"),
            )

        # ── TASK-155  /news page (Phase 4 — N2 impact feed) ──────────────────
        @self.app.callback(
            Output("news-impact-feed", "children"),
            Output("news-last-updated", "children"),
            Input("news-filter-state", "data"),
            Input("news-sort-state", "data"),
            Input("news-data-store", "data"),
            Input("news-events-store", "data"),
            Input("app-state-store", "data"),
            prevent_initial_call=False,
        )
        def update_news_page(filter_value: str, sort_state: dict, news_data: dict, events_data: dict, app_state: dict):
            """Render impact-ranked news feed on /news page (Variant N2)."""
            filter_value = filter_value or "ALL"
            sort_state = sort_state or {"field": "IMPACT", "direction": "desc"}
            if not news_data:
                return html.Div("尚無新聞資料", className="no-news"), "最後更新：--"

            run_at = news_data.get("run_at", "")
            try:
                from datetime import datetime as _dt
                ts = _dt.fromisoformat(run_at)
                updated_str = f"最後更新：{ts.strftime('%Y-%m-%d %H:%M')}"
            except Exception:
                updated_str = "最後更新：--"

            favorites = (app_state or {}).get("favorites", []) or []
            favorite_ids = {
                f.get("id") if isinstance(f, dict) else getattr(f, "stock_id", None)
                for f in favorites
            }
            favorite_ids.discard(None)

            articles = _extract_articles_from_run(news_data, "ALL", stock_filter=None)
            articles = _apply_impact_filter(articles, filter_value, favorite_ids)
            if not articles:
                return html.Div("無符合條件的新聞", className="no-news"), updated_str

            return _render_impact_feed(
                articles, events_data, self.fetcher, self.storage, sort_state,
            ), updated_str

        # ── Phase 4 (N2)  ?stock= URL → trigger search ───────────────────────
        # Stock-card clicks navigate to /?stock={sid}. Clientside callback
        # detects the query, fills the search input, clicks search-button,
        # then clears the query so back-nav doesn't re-fire.
        self.app.clientside_callback(
            """
            function(search) {
                if (!search || !search.startsWith('?stock=')) {
                    return window.dash_clientside.no_update;
                }
                const sid = decodeURIComponent(search.substring(7));
                if (!sid) return window.dash_clientside.no_update;
                const tryFire = (attempt) => {
                    const input = document.getElementById('stock-search-input');
                    const btn = document.getElementById('stock-search-button');
                    if (input && btn) {
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        setter.call(input, sid);
                        input.dispatchEvent(new Event('input', {bubbles: true}));
                        setTimeout(() => btn.click(), 250);
                    } else if (attempt < 30) {
                        setTimeout(() => tryFire(attempt + 1), 100);
                    }
                };
                // Wait a bit for main page init callbacks (favorites load) to settle.
                setTimeout(() => tryFire(0), 200);
                return '';
            }
            """,
            Output("url", "search"),
            Input("url", "search"),
            prevent_initial_call=True,
        )

        # ── Phase 4 (N2)  Right rail ─────────────────────────────────────────
        @self.app.callback(
            Output("news-right-rail", "children"),
            Input("news-data-store", "data"),
            Input("news-events-store", "data"),
            prevent_initial_call=False,
        )
        def update_news_right_rail(news_data: dict, events_data: dict):
            if not news_data:
                return html.Div("尚無新聞資料", className="rail-loading")
            # Use unfiltered article set for rail aggregates
            articles = _extract_articles_from_run(news_data, "ALL", stock_filter=None)
            return _render_right_rail(articles, news_data, events_data)

        # ── TASK-156  News ticker ────────────────────────────────────────────
        @self.app.callback(
            Output("news-ticker-content", "children"),
            Output("news-ticker-bar", "style"),
            Input("news-ticker-interval", "n_intervals"),
            State("news-data-store", "data"),
            State("app-state-store", "data"),
            prevent_initial_call=False,
        )
        def rotate_ticker(n_intervals: int, news_data: dict, app_state: dict):
            """Phase 3.5 — render up to 5 inline headlines on the bottom
            ribbon (24px). Single-line nowrap; marquee animation is a
            Phase 6 enhancement.
            """
            if not news_data:
                return "--", {"display": "none"}

            current_stock = (app_state or {}).get("current_stock")
            current_stock_name = (app_state or {}).get("current_stock_name")
            headlines = _collect_ticker_headlines(news_data, current_stock, current_stock_name)
            if not headlines:
                return "--", {"display": "none"}

            # Relayout — render each headline with a category chip whose
            # variant class drives the color (國際/科技/財經/台股 …).
            cat_class_map = {
                "國際": "news-cat-intl",
                "科技": "news-cat-tech",
                "財經": "news-cat-finance",
                "台股": "news-cat-twse",
            }
            items: List[Any] = []
            for i, h in enumerate(headlines[:8]):
                cat = h.get("category") or ""
                chip_cls = "news-ticker-chip " + cat_class_map.get(cat, "news-cat-default")
                items.append(
                    html.Span(
                        children=[
                            html.Span(cat, className=chip_cls),
                            html.Span(h["title"], className="news-ticker-headline"),
                        ],
                        className="news-ticker-item",
                    )
                )
            return items, {"display": "flex"}

        # ── Phase 1 今日重點卡片（/news 頁） ──────────────────────────────────
        @self.app.callback(
            Output("global-brief-card", "children"),
            Input("news-data-store", "data"),
            prevent_initial_call=False,
        )
        def render_global_brief(news_data: dict):
            if not news_data or not news_data.get("global_brief"):
                return html.Div("今日重點尚未產生", className="global-brief-empty")
            return _render_global_brief_card(news_data["global_brief"])

        # ── Phase 3 (Variant 3b) inline signal banner（主頁股票資訊條） ─────
        @self.app.callback(
            Output("stock-signal-banner", "className"),
            Output("stock-signal-banner", "children"),
            Input("app-state-store", "data"),
            Input("news-data-store", "data"),
            Input("news-events-store", "data"),
            prevent_initial_call=False,
        )
        def render_stock_signal_banner(
            app_state: Optional[dict],
            news_data: Optional[dict],
            news_events: Optional[dict],
        ):
            current_stock = (app_state or {}).get("current_stock")
            if not current_stock:
                return "signal-banner signal-banner-hidden", []

            sig: Optional[dict] = None
            for s in (news_data or {}).get("favorite_signals") or []:
                if str(s.get("stock_id")) == str(current_stock):
                    sig = s
                    break

            anomaly_set = _collect_anomaly_stock_ids(news_events)
            is_anomaly = current_stock in anomaly_set

            # Hide entirely when there is neither signal nor anomaly to surface.
            if not sig and not is_anomaly:
                return "signal-banner signal-banner-hidden", []

            if not sig:
                return "signal-banner signal-banner-hidden", []

            sig_kind = (sig or {}).get("sentiment") or (sig or {}).get("signal", "neutral")
            pill_label = (sig or {}).get("sentiment_label") or {
                "up": "利多",
                "down": "利空",
                "neutral": "中性",
                "bullish": "利多",
                "bearish": "利空",
            }.get(sig_kind, "中性")
            pill_cls = {
                "up": "pill-up",
                "down": "pill-down",
                "bullish": "pill-up",
                "bearish": "pill-down",
            }.get(sig_kind, "pill-neu")

            # Compact inline form per StockHeadline redesign: sentiment
            # pill follows the sector pill. Event labels stay out of the
            # headline to avoid conflating semantics.
            reason = (sig or {}).get("reason") or ""
            children: List[Any] = [
                html.Span(pill_label, className=f"pill {pill_cls}", title=reason),
            ]

            return "signal-banner signal-banner-inline", children

        # ── Phase 1 自選股訊號列（主頁） ──────────────────────────────────────
        @self.app.callback(
            Output("favorite-signal-strip", "children"),
            Input("news-data-store", "data"),
            Input("news-events-store", "data"),
            Input("app-state-store", "data"),
            prevent_initial_call=False,
        )
        def render_favorite_signals(news_data: dict, news_events: dict, app_state: dict):
            if not news_data:
                return ""
            signals = news_data.get("favorite_signals") or []
            if not signals:
                return ""
            return _render_favorite_signal_strip(signals, news_events)

        # ── Phase 2 市場情緒儀表板（/news 頁） ────────────────────────────────
        @self.app.callback(
            Output("market-sentiment-gauge", "children"),
            Input("news-data-store", "data"),
            prevent_initial_call=False,
        )
        def render_sentiment_gauge(news_data: dict):
            brief = (news_data or {}).get("global_brief") or {}
            if not brief or brief.get("failed"):
                return html.Div(
                    "市場情緒尚未產生",
                    className="market-sentiment-empty",
                )
            return _render_sentiment_gauge(brief)

        # ── Phase 2 板塊熱度圖（/news 頁） ────────────────────────────────────
        @self.app.callback(
            Output("sector-heatmap", "children"),
            Input("news-data-store", "data"),
            prevent_initial_call=False,
        )
        def render_sector_heatmap(news_data: dict):
            brief = (news_data or {}).get("global_brief") or {}
            sectors = brief.get("sector_heats") or []
            if not sectors:
                return html.Div(
                    "板塊熱度尚未產生",
                    className="sector-heatmap-empty",
                )
            return _render_sector_heatmap(sectors)

        # ── Phase 3b 議題演進 timeline（/news 頁） ───────────────────────────
        @self.app.callback(
            Output("event-timeline", "children"),
            Input("news-events-store", "data"),
            prevent_initial_call=False,
        )
        def render_event_timeline(news_events: dict):
            return _render_event_timeline(news_events)

        # ── Phase 3d RAG chat（/news 頁） ────────────────────────────────────
        @self.app.callback(
            Output("news-chat-history", "data"),
            Output("news-chat-messages", "children"),
            Output("news-chat-input", "value"),
            Input("news-chat-submit", "n_clicks"),
            State("news-chat-input", "value"),
            State("news-chat-history", "data"),
            prevent_initial_call=False,
        )
        def submit_chat_message(n_clicks, query: str, history: list):
            history = history or []
            if not n_clicks:
                return history, _render_news_chat_messages(history), ""
            query = (query or "").strip()
            if not query:
                return history, _render_news_chat_messages(history), ""
            next_history = history + [{"role": "user", "content": query}]
            if self.news_processor:
                answer = self.news_processor.answer_news_question(query, next_history)
                answer_dict = answer.to_dict()
            else:
                answer_dict = {
                    "answer": "目前無法使用新聞問答",
                    "citations": [],
                    "failed": True,
                }
            next_history.append({
                "role": "assistant",
                "content": answer_dict.get("answer", ""),
                "citations": answer_dict.get("citations", []),
                "failed": answer_dict.get("failed", False),
            })
            return next_history, _render_news_chat_messages(next_history), ""

    # ── Phase 3.5 — Information Density callbacks ───────────────────────
    def _register_phase35_callbacks(self) -> None:
        """Register MarketStrip + ChipsKpi callbacks (Phase 3.5)."""

        # Phase 7.4 — clientside skeleton swap for right-rail fund/chip
        # panel. First-time fundamentals fetch hits 3 endpoints (IIH +
        # MOPS + TPEX, ~5-8s) so we replace stale content immediately
        # when current_stock changes; server callback overwrites when
        # ready. Same pattern as ai-panel.
        self.app.clientside_callback(
            """
            function(appState) {
                if (!appState) return window.dash_clientside.no_update;
                var stock = appState.current_stock || null;
                window._lastFundStock = window._lastFundStock || null;
                if (stock === window._lastFundStock) {
                    return window.dash_clientside.no_update;
                }
                window._lastFundStock = stock;
                if (!stock) {
                    return window.dash_clientside.no_update;
                }
                var name = appState.current_stock_name || stock;
                return [
                    {
                        namespace: 'dash_html_components',
                        type: 'Div',
                        props: {
                            className: 'right-rail-fund-loading',
                            children: [
                                {namespace: 'dash_html_components', type: 'Div',
                                 props: {className: 'fund-loading-icon', children: '⌛'}},
                                {namespace: 'dash_html_components', type: 'Div',
                                 props: {className: 'fund-loading-text',
                                         children: '載入 ' + stock + ' ' + name + ' 籌碼與基本面…'}},
                            ],
                        },
                    },
                ];
            }
            """,
            Output("right-rail-fund-content", "children", allow_duplicate=True),
            Input("app-state-store", "data"),
            prevent_initial_call=True,
        )

        @self.app.callback(
            Output("market-strip", "children"),
            Output("market-strip-industry", "children"),
            Output("market-strip-breadth", "children"),
            Output("market-strip-below-row1", "children"),
            Output("market-strip-below-row2", "children"),
            Input("market-strip-interval", "n_intervals"),
            prevent_initial_call=False,
        )
        def update_market_strip(_n):
            entries = fetch_market_strip(
                shioaji_fetcher=self.shioaji_fetcher,
                index_fetcher=self.index_fetcher,
            )
            header, row1, row2 = split_strip_entries(entries)
            industries = fetch_industry_pulse(
                shioaji_fetcher=self.shioaji_fetcher,
                index_fetcher=self.index_fetcher,
            )
            breadth = fetch_breadth_summary(index_fetcher=self.index_fetcher)
            return (
                _render_market_strip(header, ""),
                _render_industry_pulse(industries),
                _render_breadth_row(breadth),
                _render_strip_cards(row1),
                _render_strip_cards(row2),
            )

        @self.app.callback(
            Output("right-rail-fund-content", "children"),
            Input("app-state-store", "data"),
            prevent_initial_call=False,
        )
        def update_right_rail_fund_content(app_state):
            stock_id = (app_state or {}).get("current_stock")
            cards = build_chips_kpi(stock_id, self.chips_storage)
            fundamentals = get_fundamentals(stock_id)
            children: List[Any] = [
                html.Div(
                    className="chips-kpi-grid",
                    children=[_render_chip_kpi_card(card) for card in cards],
                ),
                _render_fundamentals_strip(fundamentals),
            ]
            return children

        @self.app.callback(
            Output("best5-market-pill", "children"),
            Output("best5-market-pill", "className"),
            Input("market-strip-interval", "n_intervals"),
            prevent_initial_call=False,
        )
        def update_best5_market_pill(_n):
            """Toggle the Best5 panel header pill between 盤中 / 盤後 based
            on real scheduler market hours. Piggybacks on the 30s
            market-strip interval to avoid yet another timer."""
            try:
                is_open = bool(self.scheduler and self.scheduler.is_market_open())
            except Exception:
                is_open = False
            if is_open:
                return _session_pill_children("盤中"), "session-pill session-live sidebar-title-pill"
            return _session_pill_children("盤後"), "session-pill session-closed sidebar-title-pill"

        @self.app.callback(
            Output("header-session-pill", "children"),
            Output("header-session-pill", "className"),
            Output("market-clock", "children"),
            Output("market-countdown", "children"),
            Input("auto-update-interval", "n_intervals"),
            prevent_initial_call=False,
        )
        def update_header_clock(_n):
            now = datetime.now()
            clock = now.strftime("%H:%M:%S")
            open_at = now.replace(hour=9, minute=0, second=0, microsecond=0)
            close_at = now.replace(hour=13, minute=30, second=0, microsecond=0)
            is_weekday = now.weekday() < 5
            if is_weekday and open_at <= now <= close_at:
                label = "盤中"
                pill_cls = "session-pill session-live"
                countdown = f"收盤倒數 {_fmt_duration(close_at - now)}"
            elif is_weekday and now < open_at:
                label = "盤前"
                pill_cls = "session-pill session-pre"
                countdown = f"開盤倒數 {_fmt_duration(open_at - now)}"
            else:
                label = "盤後"
                pill_cls = "session-pill session-closed"
                countdown = "已收盤"
            return _session_pill_children(label), pill_cls, clock, countdown


# ── Module-level news helper functions ──────────────────────────────────────

_CATEGORY_DISPLAY = {
    "INTERNATIONAL": "國際",
    "FINANCIAL": "財經",
    "TECH": "科技",
    "STOCK_TW": "台股",
    "STOCK_US": "美股",
}

_TW_TIMEZONE = ZoneInfo("Asia/Taipei")


def _format_news_time(value: str, fmt: str = "%m/%d %H:%M") -> str:
    """Format a news timestamp in Asia/Taipei for UI display."""
    if not value:
        return "--"
    try:
        published_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return value[:16] if fmt.startswith("%m/%d") else value[:5]

    if published_at.tzinfo is None:
        local_time = published_at.replace(tzinfo=_TW_TIMEZONE)
    else:
        local_time = published_at.astimezone(_TW_TIMEZONE)
    return local_time.strftime(fmt)


def _render_ai_panel_empty(
    message: str,
    favorites: Optional[List[dict]] = None,
    state: str = "no_stock",
) -> html.Div:
    """Render the empty / loading state inside the AI tab.

    state: ``no_stock`` (default), ``loading`` — drives styling.
    favorites: list of {"id", "name"} dicts; rendered as quick-pick chips
    so the user can select without leaving the AI tab.
    """
    children = [
        html.Div(
            className="ai-panel-empty-icon",
            children=["⌛" if state == "loading" else "✦"],
        ),
        html.Div(message, className="ai-panel-empty-message"),
    ]
    favs = favorites or []
    if state == "no_stock" and favs:
        children.append(html.Div("從我的最愛快選一檔：", className="ai-panel-empty-hint"))
        children.append(
            html.Div(
                className="ai-panel-empty-favs",
                children=[
                    html.Button(
                        f"{f.get('id', '')}  {f.get('name', '')}".strip(),
                        id={"type": "ai-empty-fav-pick", "stock": f.get("id", "")},
                        n_clicks=0,
                        className="ai-empty-fav-chip",
                    )
                    for f in favs[:8]
                    if f.get("id")
                ],
            )
        )
    elif state == "no_stock":
        children.append(
            html.Div(
                "在頂部搜尋框輸入股票代號或名稱開始。",
                className="ai-panel-empty-hint",
            )
        )
    return html.Div(children, className=f"ai-panel-empty ai-panel-empty-{state}")


def _render_advisor_canvas_empty(favorites: Optional[List[dict]]) -> html.Div:
    """Phase 7.4 — empty state for /advisor canvas with quick-pick favorites."""
    favs = favorites or []
    children = [
        html.Div("✦", className="advisor-empty-icon"),
        html.Div("尚未選擇股票", className="advisor-empty-title"),
        html.Div(
            "AI 顧問需要一檔股票才能產生分析。從下方我的最愛快選，或在頂部搜尋框輸入代號。",
            className="advisor-empty-desc",
        ),
    ]
    if favs:
        children.append(
            html.Div(
                className="advisor-empty-favs",
                children=[
                    html.Button(
                        f"{f.get('id', '')}  {f.get('name', '')}".strip(),
                        id={"type": "advisor-empty-fav-pick", "stock": f.get("id", "")},
                        n_clicks=0,
                        className="advisor-empty-fav-chip",
                    )
                    for f in favs[:12]
                    if f.get("id")
                ],
            )
        )
    return html.Div(children, className="advisor-empty")


def _compute_advisor_coverage(
    articles: Sequence[dict],
    chip_cards: Sequence[ChipKpiCard],
    fundamentals: Optional[FundamentalsSnapshot],
    quote: Optional[RealtimeQuote],
    daily_closes: Sequence[float],
) -> dict:
    """Phase 7.5 — measure how many advisor inputs have real data."""
    chip_real = sum(1 for c in chip_cards if c.value_text and c.value_text != "--")
    fund_total = 5  # eps_q, eps_yoy, gross_margin, gm_delta, pe
    fund_real = 0
    if fundamentals:
        fund_real = sum(1 for v in (
            fundamentals.eps_q,
            fundamentals.eps_yoy,
            fundamentals.gross_margin,
            fundamentals.gm_delta,
            fundamentals.pe,
        ) if v is not None)
    return {
        "news": len(articles or []),
        "chip": (chip_real, len(chip_cards or [])),
        "fund": (fund_real, fund_total),
        "tech": bool(quote) and len(daily_closes or []) >= 20,
    }


def _render_coverage_strip(cov: dict) -> html.Div:
    """One-line freshness strip: '新聞 12 · 籌碼 3/5 · 基本面 4/5 · 技術 ✓'."""
    news_n = cov.get("news", 0)
    chip = cov.get("chip", (0, 0))
    fund = cov.get("fund", (0, 0))
    tech_ok = cov.get("tech", False)

    def _cls_count(real: int, total: int) -> str:
        if total == 0:
            return "cov-missing"
        ratio = real / total
        if ratio >= 0.8:
            return "cov-ok"
        if ratio >= 0.4:
            return "cov-partial"
        return "cov-missing"

    return html.Div(
        className="ai-coverage-strip",
        title="advisor 4 個面向的資料完整度（齊全度高，分析品質越穩定）",
        children=[
            html.Span("資料", className="ai-coverage-label"),
            html.Span(
                f"新聞 {news_n}",
                className=f"ai-coverage-pill {('cov-ok' if news_n >= 5 else 'cov-partial' if news_n > 0 else 'cov-missing')}",
            ),
            html.Span(
                f"籌碼 {chip[0]}/{chip[1] or 5}",
                className=f"ai-coverage-pill {_cls_count(chip[0], chip[1] or 5)}",
            ),
            html.Span(
                f"基本面 {fund[0]}/{fund[1]}",
                className=f"ai-coverage-pill {_cls_count(fund[0], fund[1])}",
            ),
            html.Span(
                f"技術 {'✓' if tech_ok else '⚠'}",
                className=f"ai-coverage-pill {'cov-ok' if tech_ok else 'cov-missing'}",
            ),
        ],
    )


def _render_advisor_source_badge(advisor: Advisor) -> html.Span:
    """Phase 7.4/7.5 — pill showing source + freshness ("LLM · 12 分鐘前")."""
    if advisor.source == "llm":
        label = "LLM"
        cls = "llm"
    else:
        label = "規則式"
        cls = "heuristic"
    fresh_text = _humanize_age(advisor.generated_at)
    text = f"{label}{('  · ' + fresh_text) if fresh_text else ''}"
    full_ts = advisor.generated_at or "未知時間"
    return html.Span(
        text,
        className=f"ai-source-badge ai-source-{cls}",
        title=f"資料來源：{'LLM 分析' if advisor.source == 'llm' else '規則式'}（生成於 {full_ts}）",
    )


def _humanize_age(iso_ts: str) -> str:
    """Convert ISO timestamp to '剛剛 / N 分鐘前 / N 小時前 / HH:MM'."""
    if not iso_ts:
        return ""
    try:
        from datetime import datetime, timezone, timedelta
        ts = datetime.fromisoformat(iso_ts)
        now = datetime.now(ts.tzinfo or timezone(timedelta(hours=8)))
        delta = now - ts
        secs = int(delta.total_seconds())
    except (ValueError, TypeError):
        return iso_ts[11:16] if len(iso_ts) >= 16 else ""
    if secs < 60:
        return "剛剛"
    if secs < 3600:
        return f"{secs // 60} 分鐘前"
    if secs < 24 * 3600:
        return f"{secs // 3600} 小時前"
    return iso_ts[5:10] if len(iso_ts) >= 10 else ""


def _render_ai_panel(
    advisor: Advisor,
    stock_id: str,
    stock_name: str,
    coverage: Optional[dict] = None,
) -> List[Any]:
    """Render the Phase 5 AI advisor right-rail panel."""
    score = float(advisor.overall_score)
    stance_cls = _advisor_pill_class(advisor.stance)
    delta_cls = "up" if advisor.delta.startswith("+") else "down" if advisor.delta.startswith("-") else "flat"
    delta_arrow = "↑" if delta_cls == "up" else "↓" if delta_cls == "down" else "→"
    confidence_pct = max(0, min(100, int(round(advisor.confidence * 100))))

    return [
        html.Div(
            className="ai-advisor-header",
            children=[
                html.Div(
                    className="ai-advisor-title-row",
                    children=[
                        html.Span(className="signal-dot ai"),
                        html.Span("AI 顧問", className="ai-advisor-title"),
                        html.Span(f"{stock_id} {stock_name}", className="num ai-advisor-stock"),
                        _render_advisor_source_badge(advisor),
                    ],
                ),
                html.Div(
                    className="ai-advisor-score-row",
                    children=[
                        html.Span(f"{score:.1f}", className="num ai-advisor-score"),
                        html.Span("/10", className="ai-advisor-score-unit"),
                        html.Span(advisor.stance, className=f"pill {stance_cls} ai-advisor-stance"),
                        html.Span(
                            f"{delta_arrow} {advisor.delta}",
                            className=f"num ai-advisor-delta {delta_cls}",
                        ),
                    ],
                ),
                html.Div(
                    className="ai-confidence-row",
                    children=[
                        html.Span("信心度", className="ai-confidence-label"),
                        html.Div(
                            className="ai-confidence-track",
                            children=[
                                html.Div(
                                    className="ai-confidence-fill",
                                    style={"width": f"{confidence_pct}%"},
                                ),
                            ],
                        ),
                        html.Span(f"{confidence_pct}%", className="num ai-confidence-value"),
                    ],
                ),
                _render_coverage_strip(coverage) if coverage else html.Div(),
            ],
        ),
        html.Div(
            className="ai-dimension-list",
            children=[_render_ai_dimension_card(dim) for dim in advisor.dimensions],
        ),
        html.Div(
            className="ai-advisor-footer",
            children=[
                html.Div("策略觀點", className="ai-advisor-footer-label"),
                html.Div(advisor.recommendation, className="ai-advisor-footer-text"),
            ],
        ),
    ]


def _render_ai_dimension_card(dim: AdvisorDimension) -> html.Details:
    """Render one expandable dimension card."""
    dir_cls = _advisor_direction_class(dim.direction)
    score_width = max(0, min(100, int(round(float(dim.score) * 10))))
    return html.Details(
        className=f"ai-dim-card ai-dim-{dim.key}",
        children=[
            html.Summary(
                className="ai-dim-summary",
                children=[
                    html.Div(
                        className="ai-dim-head",
                        children=[
                            html.Span(dim.label, className="ai-dim-label"),
                            html.Span(_advisor_direction_arrow(dim.direction), className=f"ai-dim-arrow {dir_cls}"),
                            html.Span(f"{dim.score:.1f}", className=f"num ai-dim-score {dir_cls}"),
                        ],
                    ),
                    html.Div(
                        className="ai-dim-meter",
                        children=[
                            html.Div(
                                className=f"ai-dim-meter-fill {dir_cls}",
                                style={"width": f"{score_width}%"},
                            ),
                        ],
                    ),
                    html.Div(dim.summary, className="ai-dim-text"),
                ],
            ),
            html.Div(
                className="ai-dim-bullets",
                children=[_render_ai_bullet(b) for b in dim.bullets[:3]],
            ),
        ],
    )


def _render_ai_bullet(bullet: AdvisorBullet) -> html.Div:
    dot_cls = {"bull": "bull", "bear": "bear", "neu": "neu"}.get(bullet.tag, "neu")
    label = {"bull": "多", "bear": "空", "neu": "平"}.get(bullet.tag, "平")
    pill_cls = {
        "bull": "pill-up",
        "bear": "pill-down",
        "neu": "pill-neu",
    }.get(bullet.tag, "pill-neu")
    return html.Div(
        className="ai-dim-bullet",
        children=[
            html.Span(className=f"signal-dot {dot_cls} ai-bullet-dot"),
            html.Span(label, className=f"pill {pill_cls} ai-bullet-pill"),
            html.Span(bullet.text, className="ai-bullet-text"),
        ],
    )


def _advisor_pill_class(stance: str) -> str:
    if stance == "偏多":
        return "pill-up"
    if stance == "偏空":
        return "pill-down"
    return "pill-neu"


def _advisor_direction_class(direction: str) -> str:
    if direction == "up":
        return "up"
    if direction == "down":
        return "down"
    return "flat"


def _advisor_direction_arrow(direction: str) -> str:
    if direction == "up":
        return "↑"
    if direction == "down":
        return "↓"
    return "→"


# ─── Phase 6 — /advisor full-canvas renderer ──────────────────────────

_ADVISOR_QUADRANT_TAG = {
    "news": "NEWS",
    "chip": "CHIP",
    "fund": "FUND",
    "tech": "TECH",
}


def _render_advisor_canvas(
    advisor: Advisor,
    stock_id: str,
    stock_name: str,
    *,
    quote: Optional[RealtimeQuote],
    articles: List[dict],
    cards: List[ChipKpiCard],
    fundamentals: Optional[FundamentalsSnapshot],
    daily_closes: Optional[List[float]] = None,
    daily_ohlc: Optional[List[Tuple[float, float, float]]] = None,
    coverage: Optional[dict] = None,
) -> List[Any]:
    """Phase 6 — Variant AI-2 full-canvas renderer."""
    return [
        _render_advisor_hero(advisor, stock_id, stock_name, quote, coverage),
        html.Div(
            id="advisor-grid",
            className="advisor-grid",
            children=[
                _render_advisor_quadrant(
                    dim,
                    quote=quote,
                    articles=articles,
                    cards=cards,
                    fundamentals=fundamentals,
                    daily_closes=daily_closes or [],
                    daily_ohlc=daily_ohlc or [],
                )
                for dim in advisor.dimensions
            ],
        ),
    ]


def _render_advisor_hero(
    advisor: Advisor,
    stock_id: str,
    stock_name: str,
    quote: Optional[RealtimeQuote],
    coverage: Optional[dict] = None,
) -> html.Div:
    score = float(advisor.overall_score)
    stance_cls = _advisor_pill_class(advisor.stance)
    delta_cls = (
        "up" if advisor.delta.startswith("+")
        else "down" if advisor.delta.startswith("-")
        else "flat"
    )

    price_text = "--"
    pct_text = ""
    price_cls = "flat"
    if quote is not None:
        price_text = f"{quote.current_price:.2f}"
        if quote.change_amount > 0:
            price_cls = "up"
        elif quote.change_amount < 0:
            price_cls = "down"
        sign = "+" if quote.change_percent >= 0 else ""
        pct_text = f"{sign}{quote.change_amount:.2f} ({sign}{quote.change_percent:.2f}%)"

    # spec — single horizontal row aligned to flex-end:
    #   [id-block] [spacer] [score | radar | rec]
    return html.Div(
        className="advisor-hero",
        children=[
            html.Div(
                className="advisor-hero-id",
                children=[
                    html.Div(
                        className="advisor-hero-eyebrow-row",
                        children=[
                            html.Div("AI ADVISOR", className="advisor-hero-eyebrow"),
                            _render_advisor_source_badge(advisor),
                        ],
                    ),
                    html.Div(
                        className="advisor-hero-name-row",
                        children=[
                            html.Span(stock_name, className="advisor-hero-name"),
                            html.Span(stock_id, className="num advisor-hero-code"),
                            html.Span(price_text, className=f"num advisor-hero-price {price_cls}"),
                            html.Span(pct_text, className=f"num advisor-hero-change {price_cls}"),
                        ],
                    ),
                    _render_coverage_strip(coverage) if coverage else html.Div(),
                ],
            ),
            html.Div(className="advisor-hero-spacer"),
            html.Div(
                className="advisor-hero-summary",
                children=[
                    html.Div(
                        className="advisor-hero-score",
                        children=[
                            html.Div("綜合評分", className="advisor-hero-score-label"),
                            html.Div(f"{score:.1f}", className="num advisor-hero-score-value"),
                            html.Div(
                                html.Span(advisor.stance, className=f"pill {stance_cls} advisor-hero-stance"),
                            ),
                        ],
                    ),
                    dcc.Graph(
                        id="advisor-radar-chart",
                        className="advisor-radar",
                        figure=_build_advisor_radar(advisor),
                        config={"displayModeBar": False, "staticPlot": True},
                        style={"height": "180px", "width": "200px"},
                    ),
                    html.Div(
                        className="advisor-hero-rec",
                        children=[
                            html.Div("策略觀點", className="advisor-hero-rec-label"),
                            html.Div(advisor.recommendation, className="advisor-hero-rec-text"),
                            html.Div(
                                className="advisor-confidence-row",
                                children=[
                                    html.Span("信心度", className="advisor-confidence-label"),
                                    html.Div(
                                        className="advisor-confidence-track",
                                        children=[
                                            html.Div(
                                                className="advisor-confidence-fill",
                                                style={
                                                    "width": f"{int(round(advisor.confidence * 100))}%",
                                                },
                                            ),
                                        ],
                                    ),
                                    html.Span(
                                        f"{int(round(advisor.confidence * 100))}%",
                                        className="num advisor-confidence-value",
                                    ),
                                    html.Span(
                                        advisor.delta,
                                        className=f"num advisor-hero-delta {delta_cls}",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _build_advisor_radar(advisor: Advisor) -> go.Figure:
    """4-axis radar chart of dimension scores."""
    label_map = {
        "news": "新聞面",
        "chip": "籌碼面",
        "fund": "基本面",
        "tech": "技術面",
    }
    categories = [label_map.get(d.key, d.key) for d in advisor.dimensions]
    values = [float(d.score) for d in advisor.dimensions]
    if categories:
        categories = categories + [categories[0]]
        values = values + [values[0]]

    fig = go.Figure(
        data=[
            go.Scatterpolar(
                r=values,
                theta=categories,
                fill="toself",
                line={"color": "#9C27B0", "width": 2},
                fillcolor="rgba(156,39,176,0.28)",
                hoverinfo="skip",
            ),
        ]
    )
    fig.update_layout(
        polar={
            "bgcolor": "#1E1E1E",
            "radialaxis": {
                "visible": True,
                "range": [0, 10],
                "tickvals": [2, 4, 6, 8, 10],
                "tickfont": {"size": 8, "color": "#666666"},
                "gridcolor": "rgba(255,255,255,0.08)",
                "linecolor": "rgba(255,255,255,0.08)",
            },
            "angularaxis": {
                "tickfont": {"size": 10, "color": "#AAAAAA"},
                "gridcolor": "rgba(255,255,255,0.08)",
                "linecolor": "rgba(255,255,255,0.08)",
            },
        },
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        margin={"l": 28, "r": 28, "t": 18, "b": 18},
    )
    return fig


def _render_advisor_quadrant(
    dim: AdvisorDimension,
    *,
    quote: Optional[RealtimeQuote],
    articles: List[dict],
    cards: List[ChipKpiCard],
    fundamentals: Optional[FundamentalsSnapshot],
    daily_closes: Optional[List[float]] = None,
    daily_ohlc: Optional[List[Tuple[float, float, float]]] = None,
) -> html.Div:
    dir_cls = _advisor_direction_class(dim.direction)
    tag = _ADVISOR_QUADRANT_TAG.get(dim.key, dim.key.upper())
    return html.Div(
        className=f"advisor-quadrant advisor-quadrant-{dim.key}",
        children=[
            html.Div(
                className="advisor-quadrant-head",
                children=[
                    html.Span(className=f"advisor-quadrant-bar {dir_cls}"),
                    html.Span(dim.label, className="advisor-quadrant-label"),
                    html.Span(tag, className="advisor-quadrant-tag"),
                    html.Span(f"{dim.score:.1f}", className=f"num advisor-quadrant-score {dir_cls}"),
                    html.Span("/10", className="advisor-quadrant-score-unit"),
                ],
            ),
            html.Div(
                className="advisor-quadrant-body",
                children=[
                    html.Div(
                        className="advisor-quadrant-text",
                        children=[
                            html.Div(dim.summary, className="advisor-quadrant-summary"),
                            html.Div(
                                className="advisor-quadrant-bullets",
                                children=[
                                    _render_advisor_bullet_row(b) for b in dim.bullets[:3]
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        className="advisor-quadrant-side",
                        children=[
                            html.Div("關鍵指標", className="advisor-quadrant-side-label"),
                            _render_quadrant_indicators(
                                dim.key,
                                quote=quote,
                                articles=articles,
                                cards=cards,
                                fundamentals=fundamentals,
                                daily_closes=daily_closes or [],
                                daily_ohlc=daily_ohlc or [],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _render_advisor_bullet_row(bullet: AdvisorBullet) -> html.Div:
    label = {"bull": "多", "bear": "空", "neu": "平"}.get(bullet.tag, "平")
    pill_cls = {
        "bull": "pill-up",
        "bear": "pill-down",
        "neu": "pill-neu",
    }.get(bullet.tag, "pill-neu")
    bar_cls = {"bull": "up", "bear": "down", "neu": "flat"}.get(bullet.tag, "flat")
    return html.Div(
        className=f"advisor-quadrant-bullet bullet-{bar_cls}",
        children=[
            html.Span(label, className=f"pill {pill_cls} advisor-bullet-pill"),
            html.Span(bullet.text, className="advisor-bullet-text"),
        ],
    )


def _compute_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """Wilder's RSI on the trailing close series."""
    if len(closes) < period + 1:
        return None
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - 100.0 / (1.0 + rs)


def _compute_kd(
    ohlc: List[Tuple[float, float, float]],
    n: int = 9,
) -> Tuple[Optional[float], Optional[float]]:
    """KD (9, 3, 3) — returns (K, D) at the latest bar, or (None, None)."""
    if len(ohlc) < n:
        return None, None
    rsv_list: List[float] = []
    for i in range(n - 1, len(ohlc)):
        window = ohlc[i - n + 1: i + 1]
        h = max(x[0] for x in window)
        l = min(x[1] for x in window)
        c = ohlc[i][2]
        rsv = (c - l) / (h - l) * 100 if h != l else 50.0
        rsv_list.append(rsv)
    k = 50.0
    d = 50.0
    for rsv in rsv_list:
        k = (2 / 3) * k + (1 / 3) * rsv
        d = (2 / 3) * d + (1 / 3) * k
    return k, d


def _render_quadrant_indicators(
    key: str,
    *,
    quote: Optional[RealtimeQuote],
    articles: List[dict],
    cards: List[ChipKpiCard],
    fundamentals: Optional[FundamentalsSnapshot],
    daily_closes: Optional[List[float]] = None,
    daily_ohlc: Optional[List[Tuple[float, float, float]]] = None,
) -> html.Div:
    if key == "news":
        bull = sum(1 for a in articles if a.get("impact_direction") == "up")
        bear = sum(1 for a in articles if a.get("impact_direction") == "down")
        neu = sum(1 for a in articles if a.get("impact_direction") not in ("up", "down"))
        avg = (
            sum(float(a.get("impact_score", 0.0) or 0.0) for a in articles) / len(articles)
            if articles else 0.0
        )
        rows = [
            ("利多", f"{bull}", "up"),
            ("利空", f"{bear}", "down"),
            ("中性", f"{neu}", "flat"),
            ("平均影響", f"{avg:.1f}" if articles else "--", "flat"),
        ]
        return _render_indicator_table(rows)

    if key == "chip":
        # Map cards by key for stable ordering. Phase 7.1 wires 融券 to
        # the MI_MARGN ``short_balance`` parser so it picks up real data
        # the same way as 融資; missing rows fall through to "--".
        by_key = {c.key: c for c in (cards or [])}
        order = [
            ("foreign", "外資"),
            ("trust",   "投信"),
            ("dealer",  "自營"),
            ("margin",  "融資"),
            ("short",   "融券"),
        ]
        rows: List[tuple[str, str, str]] = []
        for k, label in order:
            c = by_key.get(k)
            if c:
                rows.append((label, c.value_text or "--", c.direction or "flat"))
            else:
                rows.append((label, "--", "flat"))
        return _render_indicator_table(rows)

    if key == "fund":
        f = fundamentals or FundamentalsSnapshot()
        rows: List[tuple[str, str, str]] = []

        # EPS
        if f.eps_q is not None:
            yoy = f.eps_yoy
            cls = "up" if (yoy or 0) > 0 else "down" if (yoy or 0) < 0 else "flat"
            txt = f"{f.eps_q:.2f}"
            if yoy is not None:
                txt += f" ({yoy:+.0f}%)"
            label = f"EPS {f.eps_period}".strip() if f.eps_period else "EPS"
            rows.append((label, txt, cls))
        else:
            rows.append(("EPS", "--", "flat"))

        # 毛利率
        if f.gross_margin is not None:
            d = f.gm_delta
            cls = "up" if (d or 0) > 0 else "down" if (d or 0) < 0 else "flat"
            txt = f"{f.gross_margin:.1f}%"
            if d is not None:
                txt += f" ({d:+.1f}pp)"
            rows.append(("毛利率", txt, cls))
        else:
            rows.append(("毛利率", "--", "flat"))

        # 本益比
        if f.pe is not None:
            cls = "flat"
            if f.pe_avg is not None and f.pe_avg > 0:
                gap = (f.pe - f.pe_avg) / f.pe_avg
                cls = "up" if gap < -0.12 else "down" if gap > 0.18 else "flat"
            txt = f"{f.pe:.1f}x"
            if f.pe_avg is not None and f.pe_avg > 0:
                txt += f" (均 {f.pe_avg:.1f}x)"
            rows.append(("本益比", txt, cls))
        else:
            rows.append(("本益比", "--", "flat"))

        return _render_indicator_table(rows)

    if key == "tech":
        rows: List[tuple[str, str, str]] = []

        # 漲跌幅 / 成交量 / 開盤 / 高 / 低 — from realtime quote
        if quote is not None:
            pct = float(getattr(quote, "change_percent", 0.0) or 0.0)
            cls = "up" if pct > 0 else "down" if pct < 0 else "flat"
            sign = "+" if pct >= 0 else ""
            rows.append(("漲跌幅", f"{sign}{pct:.2f}%", cls))
            vol = int(getattr(quote, "total_volume", 0) or 0)
            rows.append(("成交量", f"{vol:,} 張" if vol else "--", "flat"))
            rows.append(("開盤", f"{quote.open_price:.2f}" if quote.open_price else "--", "flat"))
            rows.append(("最高", f"{quote.high_price:.2f}" if quote.high_price else "--", "up"))
            rows.append(("最低", f"{quote.low_price:.2f}" if quote.low_price else "--", "down"))
        else:
            rows.extend([
                ("漲跌幅", "--", "flat"),
                ("成交量", "--", "flat"),
                ("開盤", "--", "flat"),
                ("最高", "--", "up"),
                ("最低", "--", "down"),
            ])

        # MA5 / MA20 / MA60 — derive from daily_closes (newest at end)
        closes = [float(c) for c in (daily_closes or []) if isinstance(c, (int, float))]
        last_price = None
        if quote is not None and quote.current_price:
            last_price = float(quote.current_price)
        elif closes:
            last_price = closes[-1]

        for window, label in [(5, "MA5"), (20, "MA20"), (60, "MA60")]:
            if len(closes) >= window:
                ma = sum(closes[-window:]) / window
                if last_price is not None:
                    cls = "up" if last_price >= ma else "down"
                    note = "站上" if last_price >= ma else "跌破"
                    rows.append((label, f"{ma:.2f} ({note})", cls))
                else:
                    rows.append((label, f"{ma:.2f}", "flat"))
            else:
                rows.append((label, "--", "flat"))

        # KD(9,3,3) — needs daily OHLC
        k, d = _compute_kd(daily_ohlc or [], n=9)
        if k is not None and d is not None:
            kd_cls = "up" if k > d else "down" if k < d else "flat"
            note = ""
            if k >= 80 and d >= 80:
                note = " 超買"
                kd_cls = "down"
            elif k <= 20 and d <= 20:
                note = " 超賣"
                kd_cls = "up"
            rows.append(("KD", f"K {k:.1f} / D {d:.1f}{note}", kd_cls))
        else:
            rows.append(("KD", "--", "flat"))

        # RSI(14) — closes only
        rsi = _compute_rsi(closes, period=14)
        if rsi is not None:
            if rsi >= 70:
                rsi_cls = "down"; note = " 超買"
            elif rsi <= 30:
                rsi_cls = "up"; note = " 超賣"
            else:
                rsi_cls = "flat"; note = ""
            rows.append(("RSI(14)", f"{rsi:.1f}{note}", rsi_cls))
        else:
            rows.append(("RSI(14)", "--", "flat"))

        return _render_indicator_table(rows)

    return html.Div("--", className="advisor-quadrant-no-data")


_EVENT_KIND_META = {
    "news":  ("新聞", "#FFEB3B"),
    "price": ("價格", "#2196F3"),
    "ai":    ("AI",   "#9C27B0"),
    "inst":  ("籌碼", "#FFB74D"),
    "fund":  ("基本面", "#81C784"),
    "macro": ("總經", "#90A4AE"),
    "tech":  ("技術", "#E91E63"),
}


def _render_stock_events_timeline(events: List[StockEvent]) -> List[Any]:
    """Phase 6.4 — Variant N1 vertical timeline (per-stock).

    Group events by date (newest first) and render each row as
    [date · kind dot · pill+title+impact] plus the cluster summary.
    """
    if not events:
        return [html.Div("近 7 日無相關事件", className="events-empty")]

    by_date: Dict[str, List[StockEvent]] = {}
    for ev in events:
        by_date.setdefault(ev.date, []).append(ev)
    sorted_dates = sorted(by_date.keys(), reverse=True)

    rows: List[Any] = []
    rows.append(html.Div(className="stock-events-rail"))
    for d in sorted_dates:
        rows.append(
            html.Div(
                className="stock-events-date-group",
                children=[
                    html.Div(d, className="stock-events-date-label"),
                    *[_render_stock_event_row(ev) for ev in by_date[d]],
                ],
            )
        )
    return rows


def _render_stock_event_row(ev: StockEvent) -> html.Div:
    label, color = _EVENT_KIND_META.get(ev.kind, ("事件", "#AAAAAA"))
    arrow = "▲" if ev.direction == "up" else "▼" if ev.direction == "down" else "■"
    return html.Div(
        className="stock-event-row",
        children=[
            html.Div(
                className="stock-event-marker",
                style={"borderColor": color, "color": color},
                children=html.Span(arrow, className="stock-event-arrow"),
            ),
            html.Div(
                className="stock-event-body",
                children=[
                    html.Div(
                        className="stock-event-head",
                        children=[
                            html.Span(label, className="stock-event-pill", style={
                                "color": color,
                                "borderColor": color,
                            }),
                            html.Span(ev.label, className="stock-event-title"),
                            html.Span("爆量", className="stock-event-anomaly") if ev.is_anomaly else None,
                            html.Span(
                                f"影響 {ev.weight:.1f}",
                                className="num stock-event-weight",
                            ),
                            html.Span(
                                f"{ev.news_count} 則",
                                className="num stock-event-count",
                            ),
                        ],
                    ),
                    html.Div(ev.summary, className="stock-event-summary") if ev.summary else None,
                    _render_stock_event_articles(ev.articles or []),
                ],
            ),
        ],
    )


def _render_stock_event_articles(articles: List[dict]) -> Optional[html.Div]:
    """Inline news list (matches news-variants.jsx::News_Timeline mock).

    Each row renders [time · title+source · impact pill] and the title
    is the link target so the whole headline is clickable.
    """
    if not articles:
        return None
    rows: List[Any] = []
    for a in articles:
        d = a.get("impact_direction") or "neutral"
        pill_cls = "pill-up" if d in ("up", "bull") else "pill-down" if d in ("down", "bear") else "pill-neu"
        impact_score = float(a.get("impact_score") or 0.0)
        impact_text = f"{impact_score:.1f}" if impact_score > 0 else "—"
        rows.append(html.Div(
            className="stock-event-news-row",
            children=[
                html.Span(a.get("time") or "—", className="num stock-event-news-time"),
                html.Div(
                    className="stock-event-news-main",
                    children=[
                        html.A(
                            a.get("title") or "(未取得標題)",
                            href=a.get("url") or "#",
                            target="_blank",
                            rel="noopener noreferrer",
                            className="stock-event-news-title",
                        ),
                        html.Span(a.get("source") or "", className="stock-event-news-source"),
                    ],
                ),
                html.Span(
                    impact_text,
                    className=f"pill {pill_cls} stock-event-news-impact num",
                ),
            ],
        ))
    return html.Div(rows, className="stock-event-news-list")


def _render_indicator_table(rows: List[tuple[str, str, str]]) -> html.Div:
    return html.Div(
        className="advisor-indicator-table",
        children=[
            html.Div(
                className="advisor-indicator-row",
                children=[
                    html.Span(label, className="advisor-indicator-label"),
                    html.Span(value, className=f"num advisor-indicator-value {direction}"),
                ],
            )
            for (label, value, direction) in rows
        ],
    )


def _lazy_score_article(art: dict) -> None:
    """Phase 4 — Q5(a): if article dict has no impact_score, compute on the fly.

    Mutates `art` in place. Old JSON files written before Phase 4 lack the
    impact_score / impact_direction fields, so they default to 0.0 / "neutral"
    and would all sink to the low-impact section. Compute lazily without
    writing back to disk.
    """
    score = art.get("impact_score")
    direction = art.get("impact_direction")
    if score not in (None, 0, 0.0) or direction not in (None, "", "neutral"):
        return
    try:
        from src.news.news_impact import _keyword_score, _recency_bonus, _category_bonus, _direction
        from src.news.news_models import NewsCategory
        from datetime import datetime, timezone

        title = art.get("title", "")
        summary = art.get("summary", "") or art.get("excerpt", "")
        excerpt = art.get("excerpt", "")
        text = f"{title} {summary} {excerpt}"

        # parse published_at
        pub_str = art.get("published_at", "")
        try:
            pub_dt = datetime.fromisoformat(pub_str)
        except Exception:
            pub_dt = datetime.now(timezone.utc)

        # parse category
        try:
            cat = NewsCategory(art.get("category", "INTERNATIONAL"))
        except Exception:
            cat = NewsCategory.INTERNATIONAL

        score_v = (
            _keyword_score(text)
            + _recency_bonus(pub_dt, datetime.now(timezone.utc))
            + (1.0 if art.get("related_stock_ids") else 0.0)
            + _category_bonus(cat)
        )
        score_v = max(0.0, min(10.0, score_v))
        art["impact_score"] = round(score_v, 1)
        art["impact_direction"] = _direction(text)
    except Exception as e:
        logger.warning(f"lazy score failed for article {art.get('url', '?')}: {e}")


def _extract_articles_from_run(
    run_dict: dict,
    category: str,
    stock_filter: Optional[str],
    stock_name_filter: Optional[str] = None,
) -> List[dict]:
    """
    Extract article dicts from a serialised NewsRunResult dict.

    Args:
        run_dict: to_dict() output of a NewsRunResult
        category: category value ("ALL", "INTERNATIONAL", …)
        stock_filter: stock_id to filter by (None = no filter)
        stock_name_filter: stock name used as fallback for legacy untagged data

    Returns:
        List of plain article dicts ordered newest-first.
    """
    categories = run_dict.get("categories", {})
    articles: List[dict] = []

    for cat_key, cat_data in categories.items():
        if category != "ALL" and cat_key != category:
            continue
        for art in cat_data.get("articles", []):
            if stock_filter:
                related = art.get("related_stock_ids", [])
                if stock_filter not in related and not _article_matches_stock(
                    art,
                    stock_filter,
                    stock_name_filter,
                ):
                    continue
            art_copy = dict(art)
            art_copy["_category_key"] = cat_key
            _lazy_score_article(art_copy)
            articles.append(art_copy)

    # Sort newest-first
    articles.sort(key=lambda a: a.get("published_at", ""), reverse=True)
    return articles


def _article_matches_stock(
    article: dict,
    stock_id: str,
    stock_name: Optional[str],
) -> bool:
    """Fallback matcher for legacy news data without related_stock_ids."""
    terms = [stock_id]
    if stock_name:
        terms.append(stock_name)

    searchable = " ".join(
        str(article.get(field, "") or "")
        for field in ("title", "excerpt", "summary", "full_text")
    )
    return any(term and term in searchable for term in terms)


def _render_article_list(articles: List[dict]) -> html.Div:
    """Render a list of article dicts as Dash html components."""
    items = []
    for art in articles:
        cat_key = art.get("_category_key", "")
        cat_label = _CATEGORY_DISPLAY.get(cat_key, cat_key)
        pub_str = _format_news_time(art.get("published_at", ""), "%m/%d %H:%M")

        title = art.get("title", "（無標題）")
        summary = art.get("summary") or art.get("excerpt", "")
        url = art.get("url", "#")
        source = art.get("source", "")

        items.append(
            html.Div(
                className="news-article-card",
                children=[
                    html.Div(
                        className="news-article-header",
                        children=[
                            html.Span(cat_label, className="news-cat-badge"),
                            html.Span(source, className="news-source"),
                            html.Span(pub_str, className="news-pub-time"),
                        ],
                    ),
                    html.A(
                        title,
                        href=url,
                        target="_blank",
                        rel="noopener noreferrer",
                        className="news-article-title",
                    ),
                    html.P(summary, className="news-article-summary") if summary else None,
                ],
            )
        )

    return html.Div(items, className="news-articles-list")


def _render_right_rail_news_list(
    articles: List[dict],
    stock_id: Optional[str] = None,
    limit: int = 10,
) -> List[Any]:
    """Render layout-B right-rail news rows sorted by impact, then time."""
    sorted_articles = sorted(
        articles,
        key=lambda a: (
            float(a.get("impact_score", 0.0) or 0.0),
            a.get("published_at", ""),
        ),
        reverse=True,
    )[:limit]

    rows: List[Any] = []
    for art in sorted_articles:
        score = float(art.get("impact_score", 0.0) or 0.0)
        direction = art.get("impact_direction", "neutral")
        if direction == "up":
            pill_cls = "pill pill-up right-rail-news-impact"
        elif direction == "down":
            pill_cls = "pill pill-down right-rail-news-impact"
        else:
            pill_cls = "pill pill-neu right-rail-news-impact"

        pub_str = _format_news_time(art.get("published_at", ""))

        source = art.get("source", "")
        related = art.get("related_stock_ids") or []
        stock_text = related[0] if related else (stock_id or "")
        title = art.get("title", "（無標題）")
        url = art.get("url", "#")

        rows.append(
            html.A(
                href=url,
                target="_blank",
                rel="noopener noreferrer",
                className="right-rail-news-row",
                children=[
                    html.Div(
                        className="right-rail-news-meta",
                        children=[
                            html.Span(pub_str, className="num right-rail-news-time"),
                            html.Span(source, className="right-rail-news-source"),
                            html.Span(stock_text, className="num right-rail-news-stock"),
                            html.Span(f"{score:.1f}", className=pill_cls),
                        ],
                    ),
                    html.Div(title, className="right-rail-news-title"),
                ],
            )
        )

    if not rows:
        return [html.Div("目前無相關新聞", className="no-news")]
    return rows


# ── Phase 4 (N2) — impact feed helpers ────────────────────────────────────────

_HIGH_IMPACT_THRESHOLD = 5.0  # spec: < 5 collapsed


def _apply_impact_filter(
    articles: List[dict],
    filter_value: str,
    favorite_ids: set,
) -> List[dict]:
    """Filter articles by chip selection."""
    if filter_value == "FAVORITES":
        return [
            a for a in articles
            if any(sid in favorite_ids for sid in a.get("related_stock_ids", []))
        ]
    if filter_value == "UP":
        return [a for a in articles if a.get("impact_direction") == "up"]
    if filter_value == "DOWN":
        return [a for a in articles if a.get("impact_direction") == "down"]
    if filter_value == "NEUTRAL":
        return [a for a in articles if a.get("impact_direction") == "neutral"]
    return articles  # ALL


def _impact_score_tier(score: float) -> str:
    """Spec color tiers: ≥8 up, ≥5 highlight, else txt-2."""
    if score >= 8.0:
        return "tier-high"
    if score >= 5.0:
        return "tier-mid"
    return "tier-low"


def _direction_class(direction: str) -> str:
    if direction == "up":
        return "dir-up"
    if direction == "down":
        return "dir-down"
    return "dir-neutral"


def _render_impact_row(
    art: dict,
    *,
    url_to_event_size: Optional[Dict[str, int]] = None,
    stock_meta: Optional[dict] = None,
) -> html.Div:
    """Render a high-impact news row (3-col grid: 56 / 1fr / 280)."""
    is_top = bool(art.get("_is_top"))
    score = float(art.get("impact_score", 0.0) or 0.0)
    direction = art.get("impact_direction", "neutral")
    tier_cls = _impact_score_tier(score)
    dir_cls = _direction_class(direction)

    pub_str = _format_news_time(art.get("published_at", ""))

    title = art.get("title", "（無標題）")
    url = art.get("url", "#")
    source = art.get("source", "")
    summary = art.get("summary") or art.get("excerpt", "")
    full_text = art.get("full_text") or ""

    if direction == "up":
        direction_pill = html.Span("利多", className="pill pill-up news-direction-pill")
    elif direction == "down":
        direction_pill = html.Span("利空", className="pill pill-down news-direction-pill")
    else:
        direction_pill = html.Span("中性", className="pill pill-neu news-direction-pill")
    top_pill = html.Span("頂部訊號", className="pill pill-ai news-top-pill") if is_top else None

    badge = html.Div(
        className=f"news-score-badge {tier_cls}",
        children=[
            html.Div(f"{score:.1f}", className="news-score-value num"),
            html.Div("影響", className="news-score-label"),
            html.Div(
                className="news-score-bar",
                children=[
                    html.Div(
                        className=f"news-score-bar-fill {dir_cls}",
                        style={"width": f"{min(100, score * 10):.0f}%"},
                    ),
                ],
            ),
        ],
    )

    actions: List[Any] = []
    actions.append(html.Details(
        className="news-action news-action-ai",
        children=[
            html.Summary("AI 解讀", className="news-action-label"),
            html.Div(summary or "（無摘要）", className="news-action-content"),
        ],
    ))
    event_n = (url_to_event_size or {}).get(url, 0)
    if event_n > 1:
        actions.append(html.Span(
            f"關聯事件 ×{event_n}",
            className="news-action news-action-event",
        ))

    # Whole-row click → article. Overlay <a> spans entire row at low z-index.
    # Action chips + stock-card sit at higher z-index with pointer-events:auto.
    # Text content has pointer-events:none so clicks pass through to overlay.
    row_overlay = html.A(
        href=url,
        target="_blank",
        rel="noopener noreferrer",
        className="news-row-overlay",
        **{"aria-label": title},
    )

    content = html.Div(
        className="news-row-content",
        children=[
            html.Div(
                className="news-row-header",
                children=[
                    html.Span(pub_str, className="news-row-time num"),
                    html.Span(source, className="news-row-source"),
                    direction_pill,
                    top_pill,
                ],
            ),
            html.Div(title, className="news-row-title"),
            html.Div(summary, className="news-row-summary") if summary else None,
        ],
    )

    body = html.Div(
        className="news-row-body",
        children=[
            content,
            html.Div(actions, className="news-row-actions"),
        ],
    )

    if stock_meta:
        stock_card_inner = _render_stock_card(stock_meta)
        sid = stock_meta.get("stock_id", "")
        stock_card = html.A(
            href=f"/?stock={sid}",
            className="news-row-stock-link",
            children=stock_card_inner,
        )
    else:
        stock_card = html.Div(className="news-row-stock-card news-row-stock-empty")

    cls = "news-row news-row-top" if is_top else "news-row"
    return html.Div(className=cls, children=[row_overlay, badge, body, stock_card])


def _render_compact_row(art: dict) -> html.Div:
    """Render a low-impact row (5-col compact grid: 40/60/1fr/80/60)."""
    score = float(art.get("impact_score", 0.0) or 0.0)
    direction = art.get("impact_direction", "neutral")
    tier_cls = _impact_score_tier(score)

    pub_str = _format_news_time(art.get("published_at", ""))

    title = art.get("title", "（無標題）")
    url = art.get("url", "#")
    related = art.get("related_stock_ids") or []
    sid = related[0] if related else ""

    if direction == "up":
        tag = html.Span("利多", className="pill pill-up news-direction-pill")
    elif direction == "down":
        tag = html.Span("利空", className="pill pill-down news-direction-pill")
    else:
        tag = html.Span("中性", className="pill pill-neu news-direction-pill")

    return html.A(
        href=url,
        target="_blank",
        rel="noopener noreferrer",
        className="news-row-compact",
        children=[
            html.Span(f"{score:.1f}", className=f"news-row-compact-score num {tier_cls}"),
            html.Span(pub_str, className="news-row-compact-time num"),
            html.Span(title, className="news-row-compact-title"),
            html.Span(sid, className="news-row-compact-stock num"),
            tag,
        ],
    )


def _render_stock_card(meta: dict) -> html.Div:
    """Right-side boxed stock card per spec (280px column)."""
    from src.data.spark import render_spark, seeded_values

    name = meta.get("stock_name") or meta.get("stock_id", "")
    sid = meta.get("stock_id", "")
    price = meta.get("price")
    change_pct = meta.get("change_pct")
    direction = meta.get("direction", "flat")
    history = meta.get("history") or seeded_values(int(sid) if sid.isdigit() else 1)

    price_str = f"{price:,.2f}" if isinstance(price, (int, float)) else "—"
    if isinstance(change_pct, (int, float)):
        change_str = f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%"
    else:
        change_str = ""
    dir_cls = _direction_class(direction)

    return html.Div(
        className="news-row-stock-card",
        children=[
            html.Div(
                className="news-row-stock-row1",
                children=[
                    html.Span(name, className="news-row-stock-name"),
                    html.Span(sid, className="news-row-stock-id num"),
                    html.Span(price_str, className=f"news-row-stock-price num {dir_cls}"),
                ],
            ),
            html.Div(change_str, className=f"news-row-stock-change num {dir_cls}"),
            html.Div(
                render_spark(history, direction=direction, w=258, h=32),
                className="news-row-stock-spark",
            ),
        ],
    )


def _build_url_to_event_size(events_data: Optional[dict]) -> Dict[str, int]:
    """Map article URL → number of articles in the same event cluster."""
    out: Dict[str, int] = {}
    for c in (events_data or {}).get("clusters") or []:
        urls = c.get("article_urls") or []
        n = len(urls)
        if n <= 1:
            continue
        for u in urls:
            if u and out.get(u, 0) < n:
                out[u] = n
    return out


def _build_stock_lookup(articles: List[dict], fetcher, storage) -> Dict[str, dict]:
    """Look up live price + recent history for stocks referenced by articles.

    Q3 fallback: take first related_stock_id since per-tag relevance score
    is not available in current data.

    Quote source: DataFetcher.get_cached_quote() (storage has no realtime
    table — quotes live in the fetcher's in-memory cache, populated by
    Shioaji ticks or TWSE polls).
    """
    lookup: Dict[str, dict] = {}
    seen: set = set()
    for art in articles:
        ids = art.get("related_stock_ids") or []
        if not ids:
            continue
        sid = ids[0]
        if sid in seen:
            continue
        seen.add(sid)

        meta: dict = {"stock_id": sid, "stock_name": sid}

        # Live quote via fetcher cache
        quote = None
        if fetcher is not None:
            try:
                quote = fetcher.get_cached_quote(sid)
            except Exception as e:
                logger.debug(f"get_cached_quote({sid}) failed: {e}")
        if quote is not None:
            meta["stock_name"] = getattr(quote, "stock_name", None) or sid
            meta["price"] = getattr(quote, "current_price", None)
            change_amt = getattr(quote, "change_amount", None)
            meta["change_pct"] = getattr(quote, "change_percent", None)
            if change_amt is None:
                meta["direction"] = "flat"
            elif change_amt > 0:
                meta["direction"] = "up"
            elif change_amt < 0:
                meta["direction"] = "down"
            else:
                meta["direction"] = "flat"

        # History for sparkline + name fallback via daily file
        if storage is not None:
            try:
                daily = storage.load_daily_data(sid)
            except Exception as e:
                logger.debug(f"load_daily_data({sid}) failed: {e}")
                daily = None
            if daily is not None:
                if meta.get("stock_name") in (sid, None):
                    meta["stock_name"] = getattr(daily, "stock_name", None) or sid
                closes: List[float] = []
                for row in (getattr(daily, "daily_data", None) or [])[-24:]:
                    c = getattr(row, "close", None)
                    if isinstance(c, (int, float)):
                        closes.append(float(c))
                if closes:
                    meta["history"] = closes
                    # If no quote, derive last price + change from daily
                    if meta.get("price") is None and len(closes) >= 1:
                        meta["price"] = closes[-1]
                        if len(closes) >= 2 and closes[-2] > 0:
                            ch_pct = (closes[-1] - closes[-2]) / closes[-2] * 100
                            meta["change_pct"] = ch_pct
                            meta["direction"] = (
                                "up" if ch_pct > 0
                                else "down" if ch_pct < 0
                                else "flat"
                            )

        lookup[sid] = meta
    return lookup


def _render_impact_feed(
    articles: List[dict],
    events_data: Optional[dict] = None,
    fetcher=None,
    storage=None,
    sort_state: Optional[dict] = None,
) -> html.Div:
    """Render N2 feed: high-impact rows + collapsed low-impact section."""
    sort_state = sort_state or {"field": "IMPACT", "direction": "desc"}
    sort_mode = sort_state.get("field", "IMPACT")
    descending = sort_state.get("direction", "desc") == "desc"
    url_event = _build_url_to_event_size(events_data)

    def _sort_key(a: dict):
        if sort_mode == "TIME":
            return a.get("published_at", "")
        if sort_mode == "HEAT":
            return url_event.get(a.get("url", ""), 0)
        return float(a.get("impact_score", 0.0) or 0.0)

    sorted_articles = sorted(articles, key=_sort_key, reverse=descending)
    stock_lookup = _build_stock_lookup(sorted_articles, fetcher, storage)

    def _row(a: dict, is_top: bool) -> html.Div:
        a = dict(a)
        a["_is_top"] = is_top
        ids = a.get("related_stock_ids") or []
        meta = stock_lookup.get(ids[0]) if ids else None
        return _render_impact_row(a, url_to_event_size=url_event, stock_meta=meta)

    sections: List[Any] = []

    if sort_mode == "IMPACT":
        # Default mode — split by impact threshold + collapse low-impact.
        high = [a for a in sorted_articles if float(a.get("impact_score", 0.0) or 0.0) >= _HIGH_IMPACT_THRESHOLD]
        low  = [a for a in sorted_articles if float(a.get("impact_score", 0.0) or 0.0) <  _HIGH_IMPACT_THRESHOLD]
        if high:
            sections.append(html.Div(
                className="news-feed-section news-feed-high",
                children=[_row(a, i == 0) for i, a in enumerate(high)],
            ))
        if low:
            sections.append(html.Details(
                className="news-feed-section news-feed-low",
                open=False,
                children=[
                    html.Summary(
                        f"折疊 {len(low)} 則低影響新聞（影響分 < {_HIGH_IMPACT_THRESHOLD:.0f}）— 點擊展開",
                        className="news-feed-low-header",
                    ),
                    html.Div(
                        [_render_compact_row(a) for a in low],
                        className="news-feed-low-list",
                    ),
                ],
            ))
    else:
        # TIME / HEAT — flat sorted list, no high/low split, no collapse.
        sections.append(html.Div(
            className="news-feed-section news-feed-flat",
            children=[_row(a, False) for a in sorted_articles],
        ))

    if not sections:
        return html.Div("無符合條件的新聞", className="no-news")
    return html.Div(sections, className="news-impact-feed-content")


def _render_right_rail(
    articles: List[dict],
    news_data: dict,
    events_data: Optional[dict],
) -> List[Any]:
    """Phase 4 — Build right rail: 今日整理 / 情緒分佈 / 熱門關鍵字."""
    cards: List[Any] = []

    # ── Card 1: 今日整理 ────────────────────────────────────────────────
    brief = (news_data or {}).get("global_brief") or {}
    summary_text = (brief.get("overall_summary") or "").strip()
    if not summary_text:
        summary_text = "今日重點尚未產生。"
    cards.append(html.Div(
        className="rail-card",
        children=[
            html.Div("今日重點 · AI 摘要", className="rail-card-title"),
            html.Div(summary_text, className="rail-summary-text"),
        ],
    ))

    # ── Card 2: 情緒分佈（基於本批 articles 的 impact_direction）────────
    bull = sum(1 for a in articles if a.get("impact_direction") == "up")
    bear = sum(1 for a in articles if a.get("impact_direction") == "down")
    neutral = max(0, len(articles) - bull - bear)
    total = max(1, bull + bear + neutral)
    bull_pct = round(100 * bull / total)
    bear_pct = round(100 * bear / total)
    neut_pct = max(0, 100 - bull_pct - bear_pct)

    sentiment_score = brief.get("market_sentiment", 50)
    sentiment_reason = (brief.get("sentiment_reason") or "").strip()

    cards.append(html.Div(
        className="rail-card",
        children=[
            html.Div("情緒分佈", className="rail-card-title"),
            html.Div(
                className="rail-sentiment-bar",
                children=[
                    html.Div(
                        className="rail-sentiment-seg seg-up",
                        style={"width": f"{bull_pct}%"},
                        title=f"利多 {bull}",
                    ),
                    html.Div(
                        className="rail-sentiment-seg seg-neutral",
                        style={"width": f"{neut_pct}%"},
                        title=f"中性 {neutral}",
                    ),
                    html.Div(
                        className="rail-sentiment-seg seg-down",
                        style={"width": f"{bear_pct}%"},
                        title=f"利空 {bear}",
                    ),
                ],
            ),
            html.Div(
                className="rail-sentiment-legend",
                children=[
                    html.Div([
                        html.Span(f"{bull_pct}%", className="num legend-up"),
                        html.Span(" 利多", style={"color": "var(--txt-2)", "fontSize": "10px"}),
                    ]),
                    html.Div([
                        html.Span(f"{bear_pct}%", className="num legend-down"),
                        html.Span(" 利空", style={"color": "var(--txt-2)", "fontSize": "10px"}),
                    ]),
                    html.Div([
                        html.Span(f"{neut_pct}%", className="num legend-neutral"),
                        html.Span(" 中性", style={"color": "var(--txt-2)", "fontSize": "10px"}),
                    ]),
                ],
            ),
            html.Div(
                f"市場情緒指數：{sentiment_score}",
                className="rail-sentiment-score num",
            ),
            html.Div(sentiment_reason, className="rail-sentiment-reason") if sentiment_reason else None,
        ],
    ))

    # ── Card 3: 熱門關鍵字（aggregate event cluster keywords）──────────
    keywords = _aggregate_keywords(events_data, articles, top_n=12)
    if keywords:
        from src.news.news_impact import _BULLISH_WORDS, _BEARISH_WORDS
        bull_set = set(_BULLISH_WORDS)
        bear_set = set(_BEARISH_WORDS)

        def _kw_dir(kw: str) -> str:
            if kw in bull_set:
                return "up"
            if kw in bear_set:
                return "down"
            return "neutral"

        pills = []
        for kw, cnt in keywords:
            d = _kw_dir(kw)
            border_color = (
                "var(--up-line)" if d == "up"
                else "var(--down-line)" if d == "down"
                else "var(--line-2)"
            )
            pills.append(html.Span(
                children=[
                    kw,
                    html.Span(
                        f" {cnt}",
                        className="num",
                        style={"marginLeft": "6px", "color": "var(--txt-3)", "fontSize": "10px"},
                    ),
                ],
                className="rail-keyword-pill",
                style={"border": f"1px solid {border_color}"},
            ))
        cards.append(html.Div(
            className="rail-card",
            children=[
                html.Div("熱門關鍵字", className="rail-card-title"),
                html.Div(pills, className="rail-keywords-list"),
            ],
        ))

    return cards


def _aggregate_keywords(
    events_data: Optional[dict],
    articles: List[dict],
    top_n: int = 12,
) -> List[tuple]:
    """Aggregate top keywords from event clusters; fallback to article titles."""
    counts: Dict[str, int] = {}

    clusters = (events_data or {}).get("clusters") or []
    for c in clusters:
        for kw in (c.get("keywords") or []):
            kw = str(kw).strip()
            if kw:
                counts[kw] = counts.get(kw, 0) + int(c.get("daily_count", {}).get(
                    sorted((c.get("daily_count") or {}).keys())[-1] if c.get("daily_count") else "",
                    1,
                ) or 1)

    if not counts:
        # Fallback: extract from impact-scoring keyword set hits
        from src.news.news_impact import _TIER1_KEYWORDS, _TIER2_KEYWORDS
        watched = set(_TIER1_KEYWORDS) | set(_TIER2_KEYWORDS)
        for art in articles:
            text = f"{art.get('title','')} {art.get('summary','')}"
            for kw in watched:
                if kw in text:
                    counts[kw] = counts.get(kw, 0) + 1

    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_n]


_SIGNAL_STYLES = {
    "bullish": {"emoji": "🟢", "label": "利多", "cls": "signal-bullish"},
    "bearish": {"emoji": "🔴", "label": "利空", "cls": "signal-bearish"},
    "neutral": {"emoji": "⚪", "label": "中性", "cls": "signal-neutral"},
}


def _render_global_brief_card(brief: dict) -> html.Div:
    """Render the 今日重點 summary card on /news page."""
    if brief.get("failed"):
        return html.Div(
            [
                html.H3("今日重點", className="global-brief-title"),
                html.P(
                    f"分析失敗：{brief.get('sentiment_reason', '未知錯誤')}",
                    className="global-brief-error",
                ),
            ],
            className="global-brief-card-inner failed",
        )

    sentiment = int(brief.get("market_sentiment", 50))
    if sentiment >= 65:
        mood_label, mood_cls = "樂觀", "mood-bullish"
    elif sentiment <= 35:
        mood_label, mood_cls = "恐慌", "mood-bearish"
    else:
        mood_label, mood_cls = "中性", "mood-neutral"

    highlights_children = []
    for h in brief.get("category_highlights", []):
        cat = _CATEGORY_DISPLAY.get(h.get("category", ""), h.get("category", ""))
        points = h.get("headline_points", [])
        if not points:
            continue
        highlights_children.append(
            html.Div(
                [
                    html.H4(cat, className="brief-highlight-cat"),
                    html.Ul([html.Li(p) for p in points]),
                ],
                className="brief-highlight-block",
            )
        )

    return html.Div(
        [
            html.Div(
                [
                    html.H3("今日重點", className="global-brief-title"),
                    html.Div(
                        [
                            html.Span(f"市場情緒 {sentiment}", className="brief-sentiment-score"),
                            html.Span(mood_label, className=f"brief-sentiment-label {mood_cls}"),
                        ],
                        className="brief-sentiment-box",
                    ),
                ],
                className="global-brief-header",
            ),
            html.P(brief.get("overall_summary", ""), className="global-brief-summary"),
            html.P(
                f"情緒理由：{brief.get('sentiment_reason', '')}",
                className="global-brief-sentiment-reason",
            ) if brief.get("sentiment_reason") else None,
            html.Div(highlights_children, className="global-brief-highlights"),
        ],
        className="global-brief-card-inner",
    )


_SECTOR_TREND_COLORS = {
    "up": "#EF5350",      # 紅漲
    "down": "#26A69A",    # 綠跌
    "flat": "#9E9E9E",    # 灰
}


def _sentiment_color(score: int) -> str:
    """Return color matching Fear/Greed-style sentiment buckets."""
    if score >= 75:
        return "#EF5350"   # 極度樂觀（紅）
    if score >= 55:
        return "#FF9800"   # 偏多（橘）
    if score >= 45:
        return "#FFC107"   # 中性（黃）
    if score >= 25:
        return "#42A5F5"   # 偏空（藍）
    return "#26A69A"       # 極度恐慌（綠）


def _render_sentiment_gauge(brief: dict) -> html.Div:
    """Render the Fear/Greed-style market sentiment gauge."""
    sentiment = int(brief.get("market_sentiment", 50))
    sentiment = max(0, min(100, sentiment))
    color = _sentiment_color(sentiment)
    reason = (brief.get("sentiment_reason") or "").strip()

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=sentiment,
        number={"font": {"color": "#FFFFFF", "size": 36}},
        gauge={
            "axis": {
                "range": [0, 100],
                "tickwidth": 1,
                "tickcolor": "#888888",
                "tickfont": {"color": "#CCCCCC", "size": 11},
            },
            "bar": {"color": color, "thickness": 0.25},
            "bgcolor": "#2A2A2A",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 25],   "color": "#26A69A"},
                {"range": [25, 45],  "color": "#42A5F5"},
                {"range": [45, 55],  "color": "#FFC107"},
                {"range": [55, 75],  "color": "#FF9800"},
                {"range": [75, 100], "color": "#EF5350"},
            ],
            "threshold": {
                "line": {"color": "#FFFFFF", "width": 3},
                "thickness": 0.85,
                "value": sentiment,
            },
        },
    ))
    fig.update_layout(
        paper_bgcolor="#1E1E1E",
        plot_bgcolor="#1E1E1E",
        font={"color": "#FFFFFF"},
        margin={"l": 16, "r": 16, "t": 8, "b": 8},
        height=220,
    )

    return html.Div(
        [
            html.H3("市場情緒", className="dashboard-title"),
            dcc.Graph(
                figure=fig,
                config={"displayModeBar": False, "responsive": True},
                className="sentiment-gauge-graph",
            ),
            html.P(
                reason if reason else "（暫無情緒理由）",
                className="sentiment-gauge-reason",
            ),
        ],
        className="market-sentiment-gauge-inner",
    )


def _render_sector_heatmap(sectors: List[dict]) -> html.Div:
    """Render a horizontal bar chart of sector heat scores."""
    # Sort by heat_score desc for ranking effect
    valid = [s for s in sectors if s.get("sector")]
    valid.sort(key=lambda s: int(s.get("heat_score", 0) or 0), reverse=True)
    if not valid:
        return html.Div("板塊熱度尚未產生", className="sector-heatmap-empty")

    names = [s.get("sector", "") for s in valid]
    scores = [max(0, min(100, int(s.get("heat_score", 0) or 0))) for s in valid]
    trends = [str(s.get("trend", "flat")).lower() for s in valid]
    summaries = [str(s.get("summary", "")).strip() for s in valid]
    colors = [_SECTOR_TREND_COLORS.get(t, _SECTOR_TREND_COLORS["flat"]) for t in trends]
    trend_glyph = {"up": "▲", "down": "▼", "flat": "—"}
    text_labels = [
        f"{score}  {trend_glyph.get(trend, '—')}"
        for score, trend in zip(scores, trends)
    ]
    hover_texts = [
        f"<b>{name}</b><br>熱度 {score}　趨勢 {trend}<br>{summary or '（無說明）'}"
        for name, score, trend, summary in zip(names, scores, trends, summaries)
    ]

    fig = go.Figure(go.Bar(
        x=scores,
        y=names,
        orientation="h",
        marker={"color": colors, "line": {"width": 0}},
        text=text_labels,
        textposition="outside",
        textfont={"color": "#FFFFFF", "size": 12},
        hovertext=hover_texts,
        hoverinfo="text",
        cliponaxis=False,
    ))
    fig.update_layout(
        paper_bgcolor="#1E1E1E",
        plot_bgcolor="#1E1E1E",
        font={"color": "#FFFFFF"},
        margin={"l": 80, "r": 60, "t": 8, "b": 24},
        height=max(220, 36 * len(valid) + 48),
        xaxis={
            "range": [0, 110],
            "showgrid": True,
            "gridcolor": "#333333",
            "tickfont": {"color": "#CCCCCC"},
            "title": {"text": "熱度", "font": {"color": "#CCCCCC"}},
        },
        yaxis={
            "autorange": "reversed",
            "tickfont": {"color": "#FFFFFF", "size": 13},
        },
    )

    return html.Div(
        [
            html.H3("板塊熱度", className="dashboard-title"),
            dcc.Graph(
                figure=fig,
                config={"displayModeBar": False, "responsive": True},
                className="sector-heatmap-graph",
            ),
            html.Div(
                [
                    html.Span("▲ 偏多", style={"color": _SECTOR_TREND_COLORS["up"]}),
                    html.Span("　▼ 偏空", style={"color": _SECTOR_TREND_COLORS["down"]}),
                    html.Span("　— 中性", style={"color": _SECTOR_TREND_COLORS["flat"]}),
                ],
                className="sector-heatmap-legend",
            ),
        ],
        className="sector-heatmap-inner",
    )


def _render_event_timeline(event_data: Optional[dict]) -> html.Div:
    """Render Phase 3b cross-day event timeline."""
    clusters = (event_data or {}).get("clusters") or []
    clusters = [c for c in clusters if c.get("title") and c.get("daily_count")]
    if not clusters:
        return html.Div("議題演進尚未產生", className="event-timeline-empty")

    clusters = clusters[:10]
    dates = sorted({
        day
        for cluster in clusters
        for day in (cluster.get("daily_count") or {}).keys()
    })
    if not dates:
        return html.Div("議題演進尚未產生", className="event-timeline-empty")

    fig = go.Figure()
    for cluster in clusters:
        counts = cluster.get("daily_count") or {}
        title = cluster.get("title", "")[:28]
        if cluster.get("is_anomaly"):
            title = f"{title} 爆量"
        fig.add_trace(go.Bar(
            name=title,
            x=dates,
            y=[int(counts.get(day, 0) or 0) for day in dates],
            hovertemplate="<b>%{fullData.name}</b><br>%{x}: %{y} 篇<extra></extra>",
        ))
    fig.update_layout(
        barmode="stack",
        paper_bgcolor="#1E1E1E",
        plot_bgcolor="#1E1E1E",
        font={"color": "#FFFFFF"},
        margin={"l": 40, "r": 20, "t": 8, "b": 48},
        height=260,
        xaxis={"tickfont": {"color": "#CCCCCC"}},
        yaxis={
            "title": {"text": "文章數", "font": {"color": "#CCCCCC"}},
            "gridcolor": "#333333",
            "tickfont": {"color": "#CCCCCC"},
        },
        legend={"orientation": "h", "y": -0.25, "font": {"size": 10}},
    )

    event_items = []
    for cluster in clusters[:6]:
        urls = cluster.get("article_urls") or []
        event_items.append(html.Div(
            [
                html.Div(
                    [
                        html.Span(cluster.get("title", ""), className="event-title"),
                        html.Span("爆量", className="event-anomaly-badge") if cluster.get("is_anomaly") else None,
                        html.Span(
                            f"{cluster.get('first_seen', '')}–{cluster.get('last_seen', '')}",
                            className="event-date-range",
                        ),
                    ],
                    className="event-header",
                ),
                html.P(cluster.get("summary", ""), className="event-summary"),
                html.Div(
                    [
                        html.A(
                            f"來源 {idx + 1}",
                            href=url,
                            target="_blank",
                            rel="noopener noreferrer",
                            className="event-source-link",
                        )
                        for idx, url in enumerate(urls[:3])
                    ],
                    className="event-source-links",
                ),
            ],
            className="event-item",
        ))

    return html.Div(
        [
            html.H3("議題演進", className="dashboard-title"),
            dcc.Graph(
                figure=fig,
                config={"displayModeBar": False, "responsive": True},
                className="event-timeline-graph",
            ),
            html.Div(event_items, className="event-list"),
        ],
        className="event-timeline-inner",
    )


def _render_favorite_signal_strip(
    signals: List[dict],
    event_data: Optional[dict] = None,
) -> html.Div:
    """Render the 自選股訊號列 (horizontal strip) on main page."""
    anomaly_stock_ids = _collect_anomaly_stock_ids(event_data)
    items = []
    for s in signals:
        style = _SIGNAL_STYLES.get(s.get("signal", "neutral"), _SIGNAL_STYLES["neutral"])
        stock_id = s.get("stock_id", "")
        items.append(
            html.Div(
                [
                    html.Span(style["emoji"], className="fav-signal-emoji"),
                    html.Span(
                        f"{stock_id} {s.get('stock_name', '')}",
                        className="fav-signal-stock",
                    ),
                    html.Span(style["label"], className=f"fav-signal-label {style['cls']}"),
                    html.Span("爆量", className="fav-signal-anomaly") if stock_id in anomaly_stock_ids else None,
                    html.Span(s.get("reason", ""), className="fav-signal-reason"),
                ],
                className=f"fav-signal-item {style['cls']}",
                title=s.get("reason", ""),
            )
        )
    return html.Div(items, className="fav-signal-items")


def _render_news_chat_messages(history: List[dict]) -> html.Div:
    """Render news RAG chat history."""
    if not history:
        return html.Div("尚無對話", className="news-chat-empty")

    items = []
    for message in history:
        role = message.get("role", "user")
        citations = message.get("citations", []) or []
        citation_links = [
            html.A(
                f"[{idx + 1}] {c.get('title', '來源')}",
                href=c.get("url", "#"),
                target="_blank",
                rel="noopener noreferrer",
                className="news-chat-citation",
            )
            for idx, c in enumerate(citations)
        ]
        items.append(html.Div(
            [
                html.Div(message.get("content", ""), className="news-chat-text"),
                html.Div(citation_links, className="news-chat-citations") if citation_links else None,
            ],
            className=f"news-chat-message {role}",
        ))
    return html.Div(items, className="news-chat-message-list")


def _collect_anomaly_stock_ids(event_data: Optional[dict]) -> set:
    """Collect stock IDs linked to anomalous event clusters."""
    stock_ids = set()
    for cluster in (event_data or {}).get("clusters", []) or []:
        if not cluster.get("is_anomaly"):
            continue
        stock_ids.update(str(s) for s in cluster.get("related_stock_ids", []) if str(s))
    return stock_ids


def _collect_ticker_headlines(
    run_dict: dict,
    stock_filter: Optional[str],
    stock_name_filter: Optional[str] = None,
) -> List[dict]:
    """
    Collect one headline per category for the ticker bar.

    If stock_filter is set, prefer related articles; fall back to
    the most-recent article across all categories if nothing matches.
    """
    categories = run_dict.get("categories", {})
    headlines: List[dict] = []

    for cat_key, cat_data in categories.items():
        cat_articles = cat_data.get("articles", [])
        if not cat_articles:
            continue

        # Prefer articles related to the current stock
        picked = None
        if stock_filter:
            for art in cat_articles:
                if stock_filter in art.get("related_stock_ids", []) or _article_matches_stock(
                    art,
                    stock_filter,
                    stock_name_filter,
                ):
                    picked = art
                    break

        if picked is None:
            picked = cat_articles[0]

        headlines.append({
            "category": _CATEGORY_DISPLAY.get(cat_key, cat_key),
            "title": picked.get("title", ""),
            "url": picked.get("url", "#"),
        })

    return headlines


# ── Phase 3.5 module-level renderers ──────────────────────────────────────

def _dir_class(direction: str) -> str:
    """Map 'up'/'down'/'flat' to the matching CSS color class."""
    if direction == "up":
        return "up"
    if direction == "down":
        return "down"
    return "flat"


def _fmt_index_value(v: float) -> str:
    """Format an index level for the MarketStrip ribbon."""
    if v >= 1000:
        return f"{v:,.2f}"
    return f"{v:,.2f}"


def _fmt_signed(n: float, digits: int = 2) -> str:
    """Format a signed number with explicit + prefix on positives."""
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:,.{digits}f}"


def _render_strip_cards(entries: List[MarketIndexEntry]) -> List[Any]:
    """Below-chart MarketStrip — one card per entry, three stacked rows:
    title / value / pct%. Cards live in a CSS grid (1fr each) with
    container queries so all three font sizes scale with column width.
    """
    cards: List[Any] = []
    for e in entries:
        # Sub line shows the **today** move (vs session open) so the
        # delta number and the % share the same baseline. The card-level
        # direction/color is also driven by this delta — for foreign
        # indices the entry-wide ``direction`` is computed against the
        # previous-day close, which can disagree in sign with the
        # intraday move and is meaningless once we display vs-open.
        if e.open_price > 0:
            delta_open = e.value - e.open_price
            pct_open = (delta_open / e.open_price * 100.0) if e.open_price else 0.0
            cls = _dir_class(_direction_for(delta_open))
            arrow = "▲" if cls == "up" else "▼" if cls == "down" else "─"
            delta_txt = f"{abs(delta_open):.2f}"
            pct_txt = f"{abs(pct_open):.2f}%"
        else:
            cls = _dir_class(e.direction)
            arrow = "▲" if cls == "up" else "▼" if cls == "down" else "─"
            delta_txt = "--"
            pct_txt = f"{abs(e.pct):.2f}%"
        cards.append(
            html.Div(
                className="strip-card",
                children=[
                    html.Div(e.label, className="strip-card-label"),
                    html.Div(
                        _fmt_index_value(e.value),
                        className=f"strip-card-value {cls}",
                    ),
                    html.Div(
                        className=f"strip-card-sub {cls}",
                        children=[
                            html.Span(f"{arrow} {delta_txt}"),
                            html.Span(
                                f" ({pct_txt})",
                                className="strip-card-pct",
                            ),
                        ],
                    ),
                ],
            )
        )
    return cards


def _render_industry_pulse(entries: List[IndustryPulseEntry]) -> List[Any]:
    """Render the BreadthCard sector matrix as a 2-row × 4-col grid.

    Row order is fixed (上市 then 上櫃), sectors are fixed
    (半導體 / 通信 / 電零). First cell of each row is a label cell so
    the CSS grid (`60px repeat(3, 1fr)`) lines up. Missing entries
    fall through as muted placeholders so the grid never collapses.
    """
    if not entries:
        return []

    market_order = [("TSE", "上市"), ("OTC", "上櫃")]
    sector_order = ["半導體", "通信", "電零"]
    lookup = {(e.market, e.label): e for e in entries}

    out: List[Any] = []
    for market_key, market_label in market_order:
        out.append(html.Div(market_label, className="industry-row-label"))
        for sector in sector_order:
            e = lookup.get((market_key, sector))
            if e is None:
                out.append(html.Div("—", className="industry-cell industry-cell-empty"))
                continue
            cls = _dir_class(e.direction)
            sign = "+" if e.pct > 0 else ""
            out.append(
                html.Div(
                    className=f"industry-cell {cls}",
                    children=[
                        html.Span(market_label, className="industry-cell-tag"),
                        html.Span(e.label, className="industry-cell-label"),
                        html.Span(f"{sign}{e.pct:.2f}%", className=f"industry-cell-pct num {cls}"),
                    ],
                )
            )
    return out


def _render_breadth_row(breadth: dict) -> List[Any]:
    """Breadth row — for each of TSE/OTC show 漲家數 / 跌家數 + 漲停 / 跌停."""
    if not breadth:
        return []
    out: List[Any] = []
    for market in ("TSE", "OTC"):
        b = breadth.get(market)
        if b is None:
            continue
        market_tag = "上市" if market == "TSE" else "上櫃"
        out.append(
            html.Div(
                className="breadth-cell",
                children=[
                    html.Span(market_tag, className="breadth-tag"),
                    html.Span("漲", className="breadth-k up"),
                    html.Span(f"{b.advancers}", className="breadth-v up"),
                    html.Span(f"(漲停{b.limit_up})", className="breadth-sub up"),
                    html.Span("跌", className="breadth-k down"),
                    html.Span(f"{b.decliners}", className="breadth-v down"),
                    html.Span(f"(跌停{b.limit_down})", className="breadth-sub down"),
                ],
            )
        )
    return out


def _direction_for(delta: float) -> str:
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


def _render_market_strip(
    entries: List[MarketIndexEntry],
    tail_text: str = "",
) -> List[Any]:
    """Build children for the global MarketStrip ribbon (28px)."""
    items: List[Any] = []
    for idx, e in enumerate(entries):
        cls = _dir_class(e.direction)
        items.append(
            html.Div(
                className=(
                    "market-strip-item market-strip-last"
                    if idx == len(entries) - 1
                    else "market-strip-item"
                ),
                children=[
                    html.Span(e.label, className="market-strip-label"),
                    html.Span(
                        _fmt_index_value(e.value),
                        className=f"num market-strip-value {cls}",
                    ),
                    html.Div(
                        className=f"market-strip-delta {cls}",
                        children=[
                            html.Span(
                                _fmt_signed(e.change),
                                className=f"num market-strip-chg {cls}",
                            ),
                            html.Span(
                                f"({_fmt_signed(e.pct)}%)",
                                className=f"num market-strip-pct {cls}",
                            ),
                        ],
                    ),
                ],
            )
        )
    items.append(html.Div(className="market-strip-spacer"))
    if tail_text:
        items.append(html.Span(tail_text, className="market-strip-tail"))
    return items


def _render_chip_kpi_card(card: ChipKpiCard) -> html.Div:
    """Single KPI card in the bottom data row."""
    cls = _dir_class(card.direction)
    return html.Div(
        id=f"data-card-{card.key}",
        className="data-card",
        children=[
            html.Div(card.label, className="data-card-label"),
            html.Div(
                card.value_text,
                className=f"data-card-value {cls}",
            ),
            html.Div(card.caption or "", className="data-card-sub"),
        ],
    )


def _render_fundamentals_strip(fund: FundamentalsSnapshot) -> html.Div:
    """Three-cell fundamentals strip below the chip KPI cards.

    Phase 7.5 — when ``fund.is_stale`` is True (network failed → fell
    back to old disk cache), prepend a small badge so the user knows
    the numbers may be out of date.
    """
    cells = [
        _fund_cell(
            _period_label("EPS", fund.eps_period),
            _fmt_optional(fund.eps_q, "{:.2f}"),
            _fmt_optional(fund.eps_yoy, "{:+.0f}% YoY"),
        ),
        _fund_cell(
            "毛利率",
            _fmt_optional(fund.gross_margin, "{:.1f}%"),
            _fmt_optional(fund.gm_delta, "{:+.1f} PP"),
        ),
        _fund_cell(
            "本益比",
            _fmt_optional(fund.pe, "{:.1f}x"),
            _fmt_optional(fund.pe_avg, "vs avg {:.1f}"),
        ),
    ]
    children: List[Any] = []
    if fund.is_stale and fund.fetched_at:
        from datetime import datetime, timezone, timedelta
        ts = datetime.fromtimestamp(fund.fetched_at, tz=timezone(timedelta(hours=8)))
        children.append(html.Div(
            f"⚠ 基本面資料離線（最後更新 {ts.strftime('%m-%d %H:%M')}）",
            className="fund-stale-badge",
            title="網路失敗，使用最近一次成功取得的資料",
        ))
    children.extend(cells)
    return html.Div(children, className="fund-strip" + (" fund-strip-stale" if fund.is_stale else ""))


def _fund_cell(label: str, value: str, note: str) -> html.Div:
    return html.Div(
        className="fund-cell",
        children=[
            html.Span(label, className="fund-label"),
            html.Span(value, className="fund-value num"),
            html.Span(note, className="fund-note"),
        ],
    )


def _fmt_optional(value: Optional[float], fmt: str) -> str:
    if value is None:
        return "--"
    return fmt.format(value)


def _period_label(prefix: str, period: str) -> str:
    return f"{prefix} {period}" if period else prefix


def _session_pill_children(label: str) -> List[Any]:
    return [html.Span("●", className="session-dot"), label]


def _fmt_duration(delta) -> str:
    seconds = max(0, int(delta.total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}"


# ── Volume Spike Panel helpers ─────────────────────────────────────────────

_VOLUME_SPIKE_TZ = ZoneInfo("Asia/Taipei")


def _format_lot_volume(volume: int) -> str:
    """Compact lot count: 2,341 → '2.3K', 234 → '234'."""
    if volume >= 1000:
        return f"{volume / 1000:.1f}K"
    return f"{volume}"


def _format_amount_twd(amount: float) -> str:
    """143_200_000 → '143.2M', 4_300_000 → '4.3M', 250_000 → '250K'."""
    if amount >= 100_000_000:
        return f"{amount / 100_000_000:.2f}億"
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"{amount / 1_000:.0f}K"
    return f"{amount:.0f}"


def _kbar_direction_class(bar: MinuteKBar) -> str:
    """Return direction class for the mini K-bar column."""
    if bar.close > bar.open:
        return "vs-kbar-up"
    if bar.close < bar.open:
        return "vs-kbar-down"
    return "vs-kbar-flat"


def _kbar_aria_label(bar: MinuteKBar) -> str:
    if bar.close > bar.open:
        direction = "紅 K"
    elif bar.close < bar.open:
        direction = "綠 K"
    else:
        direction = "平盤 K"
    return (
        f"{direction} 開 {bar.open:.2f} 高 {bar.high:.2f} "
        f"低 {bar.low:.2f} 收 {bar.close:.2f}"
    )


def _kbar_inline_style(bar: MinuteKBar) -> Dict[str, str]:
    """Position the mini candle body by OHLC proportions."""
    price_range = bar.high - bar.low
    if price_range <= 0:
        return {"--vs-body-top": "8px", "--vs-body-height": "2px"}

    body_high = max(bar.open, bar.close)
    body_low = min(bar.open, bar.close)
    body_top_pct = (bar.high - body_high) / price_range
    body_height_pct = (body_high - body_low) / price_range

    top_px = 2 + body_top_pct * 14
    height_px = max(2, body_height_pct * 14)
    return {
        "--vs-body-top": f"{top_px:.1f}px",
        "--vs-body-height": f"{height_px:.1f}px",
    }


def _build_spike_tooltip(bar: MinuteKBar) -> str:
    """Multi-line text for hover tooltip (CSS white-space: pre-line)."""
    open_close_pct = ((bar.close - bar.open) / bar.open * 100) if bar.open else 0.0
    end_minute = bar.timestamp.replace(second=59)

    severity_label = bar.spike_severity.display_name or "—"
    ratio_text = f"{bar.volume_ratio:.1f}×" if bar.volume_ratio else "—×"
    baseline_text = (
        f"{bar.baseline_volume:.0f} 張"
        if bar.baseline_volume is not None
        else "—"
    )
    confidence_note = "  *baseline 不足" if bar.baseline_low_confidence else ""

    sep = "─────────────────────"
    return "\n".join([
        f"{bar.timestamp.strftime('%H:%M:%S')} ~ {end_minute.strftime('%H:%M:%S')}",
        sep,
        f"開 {bar.open:.2f}  →  收 {bar.close:.2f}  ({open_close_pct:+.2f}%)",
        f"高 {bar.high:.2f}     低 {bar.low:.2f}",
        sep,
        f"成交量    {bar.volume:,} 張",
        f"成交額    {_format_amount_twd(bar.amount)}",
        f"VWAP      {bar.vwap:.2f}",
        f"筆數      {bar.tick_count} 筆" if bar.tick_count else "筆數      —",
        sep,
        f"基準量    {baseline_text}{confidence_note}",
        f"倍數      {ratio_text}  {severity_label}".rstrip(),
        sep,
    ])


def _build_spike_notification_payload(stock_id: str, bar: MinuteKBar) -> Dict[str, Any]:
    """Compose the dict consumed by the clientside Notification callback."""
    open_close_pct = (
        (bar.close - bar.open) / bar.open * 100 if bar.open else 0.0
    )
    ratio_text = f"{bar.volume_ratio:.1f}×" if bar.volume_ratio else "—×"
    title = f"⚡ {stock_id} 爆量 {ratio_text}"
    body = (
        f"{bar.timestamp.strftime('%H:%M')} "
        f"{bar.close:.2f} {open_close_pct:+.2f}% "
        f"{bar.volume:,}張"
    )
    tag = f"{stock_id}_{bar.timestamp.isoformat()}"
    return {"title": title, "body": body, "tag": tag}


_WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]


def _render_spike_date_divider(d) -> html.Div:
    """Day divider inserted between spike rows of different dates."""
    label = f"{d.month}/{d.day} ({_WEEKDAY_ZH[d.weekday()]})"
    return html.Div(label, className="volume-spike-date-divider")


def _render_volume_spike_row(bar: MinuteKBar) -> html.Div:
    """Build one .volume-spike-row Div with hover tooltip."""
    kbar_cls = _kbar_direction_class(bar)
    severity_cls = f"vs-severity-{bar.spike_severity.value}"
    ratio_text = f"{bar.volume_ratio:.1f}×" if bar.volume_ratio else "—×"
    vol_text = f"{_format_lot_volume(bar.volume)} ({ratio_text})"
    vol_class = severity_cls
    if bar.baseline_low_confidence:
        vol_class += " vs-low-confidence"

    return html.Div(
        className="volume-spike-row",
        children=[
            html.Span(bar.timestamp.strftime("%H:%M"), className="vs-col-time"),
            html.Span(
                className=f"vs-col-kbar vs-kbar-candle {kbar_cls}",
                style=_kbar_inline_style(bar),
                **{"aria-label": _kbar_aria_label(bar), "role": "img"},
                children=[
                    html.Span(className="vs-kbar-wick"),
                    html.Span(className="vs-kbar-body"),
                ],
            ),
            html.Span(f"{bar.close:.2f}", className=f"vs-col-price {kbar_cls}"),
            html.Span(vol_text, className=f"vs-col-vol {vol_class}"),
            html.Div(_build_spike_tooltip(bar), className="vs-tooltip"),
        ],
    )
