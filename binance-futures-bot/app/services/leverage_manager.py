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
        """计算动态杠杆（策略3：波动率+趋势强度综合策略）

        基础杠杆: 10x
        最低杠杆: 10x
        最高杠杆: 25x

        波动率调整系数:
        - ATR < 70%  → 系数 1.5 (低波动，提升杠杆)
        - ATR 70-120% → 系数 1.0 (正常波动)
        - ATR > 120% → 系数 1.0 (高波动，保持最低杠杆)

        趋势强度调整系数:
        - ADX > 35  → 系数 1.3 (超强趋势)
        - ADX 25-35 → 系数 1.15 (强趋势)
        - ADX < 25  → 系数 1.0 (弱趋势，保持最低杠杆)

        最终杠杆 = 基础杠杆 × 波动率系数 × 趋势系数 (限制在10-25x)

        Args:
            symbol: 交易对
            klines: K线数据（可选）
            volatility: ATR年化波动率（可选）
            adx: ADX值（可选）

        Returns:
            {
                "leverage": int,  # 最终杠杆
                "base_leverage": int,  # 基础杠杆
                "volatility": float,  # 波动率
                "adx": float,  # ADX值
                "vol_factor": float,  # 波动率系数
                "trend_factor": float,  # 趋势系数
                "adjustment_reason": str  # 调整原因
            }
        """
        # 基础杠杆
        base_leverage = 10

        # 计算技术指标
        if klines and len(klines) >= 200:
            if volatility is None:
                volatility = technical_indicators.calculate_atr_volatility(klines, period=14)
            if adx is None:
                adx_values, _, _ = technical_indicators.calculate_adx(klines, period=14)
                adx = adx_values[-1] if adx_values else 0
        else:
            volatility = volatility or 0
            adx = adx or 0

        # 1. 计算波动率系数
        if volatility > 0:
            if volatility < 70:
                vol_factor = 1.5  # 低波动，提升杠杆
                vol_desc = f"低波动({volatility:.1f}%<70%)"
            elif volatility <= 120:
                vol_factor = 1.0  # 正常波动
                vol_desc = f"正常波动({volatility:.1f}%)"
            else:
                vol_factor = 1.0  # 高波动，保持最低杠杆
                vol_desc = f"高波动({volatility:.1f}%>120%)"
        else:
            vol_factor = 1.0
            vol_desc = "波动率未知"

        # 2. 计算趋势强度系数
        if adx > 35:
            trend_factor = 1.3  # 超强趋势
            trend_desc = f"超强趋势(ADX={adx:.1f}>35)"
        elif adx >= 25:
            trend_factor = 1.15  # 强趋势
            trend_desc = f"强趋势(ADX={adx:.1f}≥25)"
        else:
            trend_factor = 1.0  # 弱趋势，保持最低杠杆
            trend_desc = f"弱趋势(ADX={adx:.1f}<25)"

        # 3. 计算最终杠杆
        final_leverage = base_leverage * vol_factor * trend_factor

        # 4. 限制在10-25x范围内
        final_leverage = max(10, min(25, int(final_leverage)))

        # 5. 生成调整原因
        adjustment_reason = f"{vol_desc}, {trend_desc} → 系数{vol_factor}×{trend_factor}={vol_factor*trend_factor:.2f}"

        logger.info(f"[{symbol}] 动态杠杆: {final_leverage}x (基础{base_leverage}x, {adjustment_reason})")

        return {
            "leverage": final_leverage,
            "base_leverage": base_leverage,
            "market_cap_usd": 0,
            "market_cap_tier": 0,
            "tier_name": "综合策略",
            "volatility": volatility,
            "adx": adx,
            "vol_factor": vol_factor,
            "trend_factor": trend_factor,
            "adjustment_reason": adjustment_reason
        }


# 全局实例
leverage_manager = LeverageManager()
