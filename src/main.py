"""
Application entry point for autoFetchStock.

Usage:
    python -m src.main
    python -m src.main --host 0.0.0.0 --port 8080 --debug

This module initializes the application and starts the web server.
"""

import argparse
import logging
import signal
import sys
from typing import Optional

from src.config import AppConfig
from src.app.app_controller import AppController

logger = logging.getLogger("autofetchstock")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="台股即時資料抓取與視覺化系統",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Server host address"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8050,
        help="Server port number"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )

    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Data directory path"
    )

    parser.add_argument(
        "--fetch-interval",
        type=int,
        default=5,
        help="Data fetch interval in seconds"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level"
    )

    return parser.parse_args()


def create_config(args: argparse.Namespace) -> AppConfig:
    """Create AppConfig from command line arguments."""
    return AppConfig(
        host=args.host,
        port=args.port,
        debug=args.debug,
        data_dir=args.data_dir,
        fetch_interval=args.fetch_interval,
        log_level=args.log_level,
    )


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Parse arguments
    args = parse_args()

    # Create configuration
    config = create_config(args)

    # Global controller reference for signal handlers
    controller: Optional[AppController] = None

    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        print("\n正在關閉系統...")
        if controller:
            controller.shutdown()
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Create and run application
        print("=" * 50)
        print("  台股即時資料抓取與視覺化系統")
        print("=" * 50)
        print(f"  伺服器位址: http://{config.host}:{config.port}")
        print(f"  資料目錄: {config.data_dir}")
        print(f"  除錯模式: {'開啟' if config.debug else '關閉'}")
        print("=" * 50)
        print("按 Ctrl+C 停止伺服器\n")

        controller = AppController(config)
        controller.run()

        return 0

    except KeyboardInterrupt:
        print("\n正在關閉系統...")
        if controller:
            controller.shutdown()
        return 0

    except Exception as e:
        logger.exception(f"Application error: {e}")
        print(f"\n錯誤: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
