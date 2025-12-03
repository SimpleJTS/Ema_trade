"""
动态杠杆管理器
基于市值、波动率、ADX等动态调整杠杆倍数
"""
import logging
from typing import Optional, Dict
from app.services.coingecko_api import coingecko_api
from app.utils.indicators import technical_indicators

logger = logging.getLogger(__name__)


class LeverageManager:
    """动态杠杆管理器

    根据币种市值层级和实时市场指标动态计算杠杆倍数

    市值层级划分：
    1. 超大市值（>1万亿USD）：基础杠杆 20-25x
    2. 大/中市值（100-1000亿USD）：基础杠杆 10-18x
    3. 小市值（<100亿USD）：基础杠杆 5-8x
    4. 新兴/低流动性（<10亿USD）：基础杠杆 3-5x
    """

    # 市值层级配置
    TIER_CONFIG = {
        1: {  # 超大市值
            "name": "超大市值",
            "min_cap": 1_000_000_000_000,  # 1万亿
            "base_leverage_min": 20,
            "base_leverage_max": 25,
            "default_leverage": 22,
        },
        2: {  # 大/中市值
            "name": "大/中市值",
            "min_cap": 10_000_000_000,  # 100亿
            "base_leverage_min": 10,
            "base_leverage_max": 18,
            "default_leverage": 15,
        },
        3: {  # 小市值
            "name": "小市值",
            "min_cap": 1_000_000_000,  # 10亿
            "base_leverage_min": 5,
            "base_leverage_max": 8,
            "default_leverage": 7,
        },
        4: {  # 新兴/低流动性
            "name": "新兴/低流动性",
            "min_cap": 0,
            "base_leverage_min": 3,
            "base_leverage_max": 5,
            "default_leverage": 3,
        }
    }

    async def calculate_leverage(
        self,
        symbol: str,
        klines: Optional[list] = None,
        volatility: Optional[float] = None,
        adx: Optional[float] = None
    ) -> Dict:
        """计算杠杆（当前禁用动态调整，固定返回10x）

        Args:
            symbol: 交易对
            klines: K线数据（可选）
            volatility: ATR年化波动率（可选）
            adx: ADX值（可选）

        Returns:
            {
                "leverage": int,  # 固定10x
                "base_leverage": int,
                "market_cap_usd": float,
                "market_cap_tier": int,
                "tier_name": str,
                "volatility": float,
                "adx": float,
                "adjustment_reason": str
            }
        """
        # 计算技术指标（用于记录和后续分析）
        if klines and len(klines) >= 200:
            if volatility is None:
                volatility = technical_indicators.calculate_atr_volatility(klines, period=14)
            if adx is None:
                adx_values, _, _ = technical_indicators.calculate_adx(klines, period=14)
                adx = adx_values[-1] if adx_values else 0
        else:
            volatility = volatility or 0
            adx = adx or 0

        # 固定杠杆10x（动态调整已禁用）
        fixed_leverage = 10

        logger.info(f"[{symbol}] 固定杠杆: {fixed_leverage}x (波动率={volatility:.1f}%, ADX={adx:.1f})")

        return {
            "leverage": fixed_leverage,
            "base_leverage": fixed_leverage,
            "market_cap_usd": 0,
            "market_cap_tier": 0,
            "tier_name": "固定杠杆模式",
            "volatility": volatility,
            "adx": adx,
            "adjustment_reason": f"固定杠杆{fixed_leverage}x (波动率={volatility:.1f}%, ADX={adx:.1f})"
        }


# 全局实例
leverage_manager = LeverageManager()
