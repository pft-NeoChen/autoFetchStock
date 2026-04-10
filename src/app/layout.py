"""
Dash layout module for autoFetchStock.

This module defines the web application layout structure:
- Multi-page routing via dcc.Location
- Stock search input field
- Stock info display area
- Three-tab interface (intraday / K-line / news)
- News page layout (/news)
- News ticker bar
- Control components (period selector, intervals)
"""

from dash import html, dcc

from src.models import KlinePeriod


def create_layout() -> html.Div:
    """
    Create the top-level application shell.

    Contains the URL router, shared hidden components, the navigation
    header, a ``page-content`` placeholder filled by the routing
    callback, and the persistent news ticker bar at the bottom.

    Returns:
        Dash html.Div containing the complete shell layout
    """
    return html.Div(
        id="main-container",
        className="main-container",
        children=[
            # URL router (no page refresh)
            dcc.Location(id="url", refresh=False),

            # Hidden stores and intervals (shared across all pages)
            _create_hidden_components(),

            # Top navigation bar
            _create_nav_bar(),

            # Dynamic page content (swapped by routing callback)
            html.Div(id="page-content"),

            # News ticker bar (visible on all pages)
            _create_news_ticker(),
        ]
    )


def create_main_page_layout() -> html.Div:
    """
    Create the stock-monitoring main page layout (pathname='/').

    Layout structure:
    - Header with stock search
    - Main content area with:
      - Left sidebar (favorites list)
      - Center content (stock info, three-tab panel)
      - Right sidebar (big orders / best five prices)
    - Error message display
    - System status bar

    Returns:
        html.Div for the main stock page
    """
    return html.Div(
        id="stock-page",
        children=[
            # Header with search
            _create_header(),

            # Main content area (sidebar + content)
            html.Div(
                className="content-wrapper",
                children=[
                    # Left sidebar - Favorites
                    _create_favorites_sidebar(),

                    # Center content area
                    html.Div(
                        className="main-content",
                        children=[
                            # Stock info display
                            _create_stock_info_section(),

                            # Main tabs (intraday / K-line / news)
                            _create_tabs_section(),
                        ]
                    ),

                    # Right sidebar - Big Orders
                    _create_big_orders_sidebar(),
                ]
            ),

            # Error message display
            _create_error_display(),

            # System status bar
            _create_status_bar(),
        ]
    )


def create_news_page_layout() -> html.Div:
    """
    Create the standalone news page layout (pathname='/news').

    Displays all five news categories in sub-tabs with a manual
    refresh button.

    Returns:
        html.Div for the /news page
    """
    category_tabs = [
        dcc.Tab(label="國際新聞",   value="INTERNATIONAL", className="tab", selected_className="tab-selected"),
        dcc.Tab(label="財經新聞",   value="FINANCIAL",     className="tab", selected_className="tab-selected"),
        dcc.Tab(label="科技新聞",   value="TECH",          className="tab", selected_className="tab-selected"),
        dcc.Tab(label="台股相關",   value="STOCK_TW",      className="tab", selected_className="tab-selected"),
        dcc.Tab(label="美股相關",   value="STOCK_US",      className="tab", selected_className="tab-selected"),
    ]

    return html.Div(
        id="news-page",
        className="news-page",
        children=[
            html.Div(
                className="news-page-header",
                children=[
                    html.H2("市場新聞總覽", className="news-page-title"),
                    html.Button(
                        "手動更新",
                        id="news-refresh-button",
                        className="news-refresh-button",
                    ),
                    html.Span(
                        id="news-last-updated",
                        className="news-last-updated",
                        children="最後更新：--",
                    ),
                ],
            ),
            dcc.Tabs(
                id="news-category-tabs",
                value="INTERNATIONAL",
                className="main-tabs",
                children=category_tabs,
            ),
            html.Div(id="news-category-content", className="news-category-content"),
        ],
    )


def _create_hidden_components() -> html.Div:
    """Create hidden components for state management."""
    return html.Div(
        style={"display": "none"},
        children=[
            # App state store
            dcc.Store(
                id="app-state-store",
                data={
                    "current_stock": None,
                    "current_tab": "intraday",
                    "current_period": "daily",
                    "favorites": [],  # List of {id, name}
                }
            ),

            # Latest news data cache (shared between ticker and news tab)
            dcc.Store(id="news-data-store", data=None),

            # Auto-update interval (1 second for real-time feel)
            dcc.Interval(
                id="auto-update-interval",
                interval=1 * 1000,  # 1 second
                n_intervals=0,
                disabled=False,  # Start enabled to update favorites list
            ),

            # Ticker rotation interval (5 seconds)
            dcc.Interval(
                id="news-ticker-interval",
                interval=5 * 1000,  # 5 seconds
                n_intervals=0,
                disabled=False,
            ),
        ]
    )


def _create_nav_bar() -> html.Div:
    """Create top navigation bar with links to main page and news page."""
    return html.Div(
        id="nav-bar",
        className="nav-bar",
        children=[
            html.A("台股即時資料", href="/", className="nav-link nav-home"),
            html.A("市場新聞", href="/news", className="nav-link nav-news"),
        ],
    )


def _create_news_ticker() -> html.Div:
    """Create the news ticker bar displayed at the bottom of every page."""
    return html.Div(
        id="news-ticker-bar",
        className="news-ticker-bar",
        style={"display": "none"},  # hidden until news data is available
        children=[
            html.Span("新聞：", className="ticker-label"),
            html.Div(
                id="news-ticker-content",
                className="ticker-content",
                children="--",
            ),
        ],
    )


def _create_header() -> html.Div:
    """Create header with stock search input."""
    return html.Div(
        id="header-section",
        className="header-section",
        children=[
            html.H1(
                "台股即時資料系統",
                className="app-title"
            ),
            html.Div(
                style={"position": "relative", "flex": "1", "max-width": "400px"},
                children=[
                    html.Div(
                        className="search-container",
                        children=[
                            dcc.Input(
                                id="stock-search-input",
                                type="text",
                                placeholder="輸入股票代號或名稱...",
                                className="search-input",
                            ),
                            html.Button(
                                "搜尋",
                                id="stock-search-button",
                                className="search-button",
                            ),
                        ]
                    ),
                    # Search results dropdown
                    html.Div(
                        id="stock-match-list",
                        className="match-list",
                        children=[],
                    ),
                ]
            ),
        ]
    )


def _create_favorites_sidebar() -> html.Div:
    """Create favorites sidebar section."""
    return html.Div(
        id="favorites-sidebar",
        className="favorites-sidebar",
        children=[
            html.H3("我的最愛", className="sidebar-title"),
            html.Div(
                id="favorites-list",
                className="favorites-list",
                children=[
                    html.Div("尚未加入最愛", className="no-favorites")
                ]
            ),
        ]
    )


def _create_big_orders_sidebar() -> html.Div:
    """Create big orders monitoring sidebar with best five prices."""
    return html.Div(
        id="big-orders-sidebar",
        className="big-orders-sidebar",
        children=[
            html.H3("大戶即時監控", className="sidebar-title"),
            html.Div(
                className="big-orders-header",
                children=[
                    html.Span("時間", className="header-time"),
                    html.Span("張數", className="header-volume"),
                ]
            ),
            html.Div(
                id="big-orders-list",
                className="big-orders-list",
                children=[
                    html.Div("尚無大戶資料", className="no-data")
                ]
            ),

            # Best Five Prices section
            _create_best_five_prices(),
        ]
    )


def _create_best_five_prices() -> html.Div:
    """Create best five prices (最佳五檔) section."""
    return html.Div(
        id="best-five-prices-section",
        className="best-five-section",
        children=[
            html.H3("最佳五檔", className="sidebar-title"),

            # Bid/Ask ratio bar
            html.Div(
                className="bidask-ratio-container",
                children=[
                    html.Div(
                        className="bidask-ratio-bar",
                        children=[
                            html.Div(
                                id="bidask-ratio-inner",
                                className="bidask-ratio-inner",
                                style={"width": "50%"},
                            ),
                            html.Span("內外盤比", className="bidask-ratio-label"),
                        ]
                    ),
                    html.Div(
                        className="bidask-ratio-values",
                        children=[
                            html.Span(id="ask-total-vol", className="ask-total-val", children="--"),
                            html.Span(id="bid-total-vol", className="bid-total-val", children="--"),
                        ]
                    ),
                ]
            ),

            # Table header
            html.Div(
                className="five-prices-header",
                children=[
                    html.Span("買進", className="five-header-buy"),
                    html.Span("賣出", className="five-header-sell"),
                ]
            ),

            # Five-level rows
            html.Div(
                id="best-five-prices-body",
                className="five-prices-body",
                children=[
                    html.Div("等待五檔資料...", className="no-data")
                ]
            ),
        ]
    )


def _create_stock_info_section() -> html.Div:
    """Create stock information display section."""
    return html.Div(
        id="stock-info-section",
        className="stock-info-section",
        children=[
            # Stock name and ID with Star toggle
            html.Div(
                className="stock-header",
                children=[
                    html.Button(
                        "★",
                        id="stock-star-toggle",
                        className="star-button",
                        title="加入/移除最愛",
                    ),
                    html.Span(
                        id="stock-name-display",
                        className="stock-name",
                        children="--",
                    ),
                    html.Span(
                        id="stock-id-display",
                        className="stock-id",
                        children="",
                    ),
                ]
            ),
            # Price info
            html.Div(
                className="price-container",
                children=[
                    html.Span(
                        id="stock-price-display",
                        className="stock-price",
                        children="--",
                    ),
                    html.Span(
                        id="stock-change-display",
                        className="stock-change",
                        children="",
                    ),
                ]
            ),
            # Volume info
            html.Div(
                className="volume-container",
                children=[
                    html.Span("成交量：", className="label"),
                    html.Span(
                        id="stock-volume-display",
                        className="stock-volume",
                        children="--",
                    ),
                ]
            ),
            # Last update time
            html.Div(
                className="update-time-container",
                children=[
                    html.Span("更新時間：", className="label"),
                    html.Span(
                        id="last-update-display",
                        className="last-update",
                        children="--",
                    ),
                ]
            ),
        ]
    )


def _create_tabs_section() -> html.Div:
    """Create main tabs section (Intraday / K-line / News)."""
    return html.Div(
        id="tabs-section",
        className="tabs-section",
        children=[
            dcc.Tabs(
                id="main-tabs",
                value="intraday",
                className="main-tabs",
                children=[
                    # Intraday tab
                    dcc.Tab(
                        label="分時資料",
                        value="intraday",
                        className="tab",
                        selected_className="tab-selected",
                        children=_create_intraday_tab_content(),
                    ),
                    # K-line tab
                    dcc.Tab(
                        label="K 線圖",
                        value="kline",
                        className="tab",
                        selected_className="tab-selected",
                        children=_create_kline_tab_content(),
                    ),
                    # News tab (stock-filtered)
                    dcc.Tab(
                        label="新聞",
                        value="news",
                        className="tab",
                        selected_className="tab-selected",
                        children=_create_news_tab_content(),
                    ),
                ]
            ),
        ]
    )


def _create_news_tab_content() -> html.Div:
    """Create the stock-filtered news tab inside the main page."""
    category_tabs = [
        dcc.Tab(label="全部",     value="ALL",           className="tab", selected_className="tab-selected"),
        dcc.Tab(label="國際",     value="INTERNATIONAL", className="tab", selected_className="tab-selected"),
        dcc.Tab(label="財經",     value="FINANCIAL",     className="tab", selected_className="tab-selected"),
        dcc.Tab(label="科技",     value="TECH",          className="tab", selected_className="tab-selected"),
        dcc.Tab(label="台股",     value="STOCK_TW",      className="tab", selected_className="tab-selected"),
        dcc.Tab(label="美股",     value="STOCK_US",      className="tab", selected_className="tab-selected"),
    ]
    return html.Div(
        id="news-tab-content",
        className="tab-content",
        children=[
            dcc.Tabs(
                id="stock-news-category-tabs",
                value="ALL",
                className="main-tabs",
                children=category_tabs,
            ),
            html.Div(
                id="stock-news-articles",
                className="news-articles-container",
                children=[html.Div("請先選擇股票", className="no-news")],
            ),
        ],
    )


def _create_intraday_tab_content() -> html.Div:
    """Create intraday tab content."""
    return html.Div(
        id="intraday-tab-content",
        className="tab-content",
        children=[
            # Intraday chart
            dcc.Graph(
                id="intraday-chart",
                className="chart",
                config={
                    "displayModeBar": True,
                    "scrollZoom": True,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                },
            ),
        ]
    )


def _create_kline_tab_content() -> html.Div:
    """Create K-line tab content."""
    return html.Div(
        id="kline-tab-content",
        className="tab-content",
        children=[
            # Period selector
            html.Div(
                className="period-selector-container",
                children=[
                    html.Span("時間週期：", className="label"),
                    dcc.RadioItems(
                        id="period-selector",
                        className="period-selector",
                        options=[
                            {"label": "日K", "value": "daily"},
                            {"label": "週K", "value": "weekly"},
                            {"label": "月K", "value": "monthly"},
                            {"label": "1分", "value": "min_1"},
                            {"label": "5分", "value": "min_5"},
                            {"label": "15分", "value": "min_15"},
                            {"label": "30分", "value": "min_30"},
                            {"label": "60分", "value": "min_60"},
                        ],
                        value="daily",
                        inline=True,
                    ),
                ]
            ),
            # OHLC info display (for hover)
            html.Div(
                id="ohlc-display",
                className="ohlc-display",
                children=[
                    html.Span("開：", className="label"),
                    html.Span(id="ohlc-open", className="ohlc-value", children="--"),
                    html.Span("高：", className="label"),
                    html.Span(id="ohlc-high", className="ohlc-value", children="--"),
                    html.Span("低：", className="label"),
                    html.Span(id="ohlc-low", className="ohlc-value", children="--"),
                    html.Span("收：", className="label"),
                    html.Span(id="ohlc-close", className="ohlc-value", children="--"),
                    html.Span("量：", className="label"),
                    html.Span(id="ohlc-volume", className="ohlc-value", children="--"),
                ]
            ),
            # K-line chart
            dcc.Graph(
                id="kline-chart",
                className="chart",
                config={
                    "displayModeBar": True,
                    "scrollZoom": True,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                },
            ),
        ]
    )


def _create_error_display() -> html.Div:
    """Create error message display area."""
    return html.Div(
        id="error-message-display",
        className="error-message-display",
        style={"display": "none"},  # Hidden by default
        children=[
            html.Span(
                id="error-icon",
                className="error-icon",
                children="⚠️"
            ),
            html.Span(
                id="error-text",
                className="error-text",
                children=""
            ),
            html.Button(
                "×",
                id="error-close-button",
                className="error-close-button"
            ),
        ]
    )


def _create_status_bar() -> html.Div:
    """Create system status bar."""
    return html.Div(
        id="system-status-bar",
        className="status-bar",
        children=[
            html.Span(
                id="connection-status",
                className="status-item",
                children="● 連線狀態：正常"
            ),
            html.Span(
                id="market-status",
                className="status-item",
                children="● 市場狀態：--"
            ),
            html.Span(
                id="scheduler-status",
                className="status-item",
                children="● 排程狀態：--"
            ),
        ]
    )


# Component IDs for reference in callbacks
COMPONENT_IDS = {
    # Search components
    "search_input": "stock-search-input",
    "search_button": "stock-search-button",
    "match_list": "stock-match-list",

    # Stock info displays
    "stock_star": "stock-star-toggle",
    "stock_name": "stock-name-display",
    "stock_id": "stock-id-display",
    "stock_price": "stock-price-display",
    "stock_change": "stock-change-display",
    "stock_volume": "stock-volume-display",
    "last_update": "last-update-display",

    # Sidebar
    "favorites_sidebar": "favorites-sidebar",
    "favorites_list": "favorites-list",

    # Tab components
    "main_tabs": "main-tabs",
    "intraday_tab": "intraday-tab-content",
    "kline_tab": "kline-tab-content",
    "news_tab": "news-tab-content",

    # Charts
    "intraday_chart": "intraday-chart",
    "kline_chart": "kline-chart",

    # K-line controls
    "period_selector": "period-selector",
    "ohlc_display": "ohlc-display",
    "ohlc_open": "ohlc-open",
    "ohlc_high": "ohlc-high",
    "ohlc_low": "ohlc-low",
    "ohlc_close": "ohlc-close",
    "ohlc_volume": "ohlc-volume",

    # Hidden components
    "app_state": "app-state-store",
    "auto_update": "auto-update-interval",
    "news_data_store": "news-data-store",
    "news_ticker_interval": "news-ticker-interval",

    # News main page tab
    "stock_news_category_tabs": "stock-news-category-tabs",
    "stock_news_articles": "stock-news-articles",

    # News page (/news)
    "news_category_tabs": "news-category-tabs",
    "news_category_content": "news-category-content",
    "news_refresh_button": "news-refresh-button",
    "news_last_updated": "news-last-updated",

    # Ticker
    "news_ticker_bar": "news-ticker-bar",
    "news_ticker_content": "news-ticker-content",

    # Error and status
    "error_display": "error-message-display",
    "error_text": "error-text",
    "error_close": "error-close-button",
    "connection_status": "connection-status",
    "market_status": "market-status",
    "scheduler_status": "scheduler-status",
}
