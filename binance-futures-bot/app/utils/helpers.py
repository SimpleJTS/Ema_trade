"""
工具函数
"""
import logging
from datetime import datetime
from typing import List


def setup_logging(level: str = "INFO"):
    """配置日志"""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def format_price(price: float, decimals: int = 4) -> str:
    """格式化价格"""
    return f"{price:.{decimals}f}"


def format_percent(value: float, decimals: int = 2) -> str:
    """格式化百分比"""
    return f"{value:.{decimals}f}%"


def timestamp_to_datetime(timestamp: int) -> datetime:
    """时间戳转datetime"""
    return datetime.fromtimestamp(timestamp / 1000)


def datetime_to_timestamp(dt: datetime) -> int:
    """datetime转时间戳"""
    return int(dt.timestamp() * 1000)
