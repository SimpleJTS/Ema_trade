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
        """计算动态杠杆

        Args:
            symbol: 交易对
            klines: K线数据（用于计算波动率和ADX，可选）
            volatility: ATR年化波动率（可选，不提供则计算）
            adx: ADX值（可选，不提供则计算）

        Returns:
            {
                "leverage": int,  # 最终杠杆
                "base_leverage": int,  # 基础杠杆
                "market_cap_usd": float,  # 市值
                "market_cap_tier": int,  # 市值层级
                "tier_name": str,  # 层级名称
                "volatility": float,  # 波动率
                "adx": float,  # ADX值
                "adjustment_reason": str  # 调整原因
            }
        """
        # 1. 获取市值信息
        market_data = await coingecko_api.get_coin_market_data(symbol)
        if not market_data:
            logger.warning(f"[{symbol}] 无法获取市值数据，使用默认杠杆10x")
            return {
                "leverage": 10,
                "base_leverage": 10,
                "market_cap_usd": 0,
                "market_cap_tier": 4,
                "tier_name": "未知",
                "volatility": 0,
                "adx": 0,
                "adjustment_reason": "市值数据不可用，使用默认杠杆10x"
            }

        market_cap_usd = market_data["market_cap_usd"]

        # 2. 确定市值层级
        tier = coingecko_api.get_market_cap_tier(market_cap_usd)
        tier_config = self.TIER_CONFIG[tier]

        # 3. 获取基础杠杆
        base_leverage = tier_config["default_leverage"]
        logger.info(f"[{symbol}] 市值层级: {tier_config['name']}, 市值: ${market_cap_usd:,.0f}, 基础杠杆: {base_leverage}x")

        # 4. 计算波动率和ADX（如果提供了K线数据）
        if klines and len(klines) >= 200:
            if volatility is None:
                volatility = technical_indicators.calculate_atr_volatility(klines, period=14)
            if adx is None:
                adx_values, _, _ = technical_indicators.calculate_adx(klines, period=14)
                adx = adx_values[-1] if adx_values else 0
        else:
            volatility = volatility or 0
            adx = adx or 0

        # 5. 动态调整杠杆
        adjusted_leverage = base_leverage
        adjustment_reasons = []

        # 层级1：超大市值动态调整
        if tier == 1:
            if volatility > 0:
                if volatility < 50:
                    adjusted_leverage = min(tier_config["base_leverage_max"], adjusted_leverage + 3)
                    adjustment_reasons.append(f"低波动率({volatility:.1f}%<50%)→提升至{adjusted_leverage}x")
                elif volatility > 100:
                    adjusted_leverage = max(tier_config["base_leverage_min"] - 5, 15)
                    adjustment_reasons.append(f"高波动率({volatility:.1f}%>100%)→降至{adjusted_leverage}x")

        # 层级2：大/中市值动态调整
        elif tier == 2:
            if adx > 30:
                adjusted_leverage = min(tier_config["base_leverage_max"], adjusted_leverage + 3)
                adjustment_reasons.append(f"强趋势(ADX={adx:.1f}>30)→提升至{adjusted_leverage}x")
            # 资金费率检查已省略（需要实时API调用）

        # 层级3：小市值动态调整
        elif tier == 3:
            if klines and len(klines) >= 30:
                # 检查成交量突破
                volume_surge = technical_indicators.check_volume_surge(klines, period=30, multiplier=3.0)
                if volume_surge:
                    adjusted_leverage = tier_config["base_leverage_max"]
                    adjustment_reasons.append(f"成交量突破(>3x均量)→提升至{adjusted_leverage}x")

            # 检查1小时振幅（需要1h K线，这里简化处理）
            # 如果振幅过大，强制降低杠杆
            if volatility > 180:  # 极高波动
                adjusted_leverage = max(3, tier_config["base_leverage_min"] - 2)
                adjustment_reasons.append(f"极高波动率({volatility:.1f}%)→降至{adjusted_leverage}x")

        # 层级4：新兴/低流动性
        elif tier == 4:
            # 仅在强趋势且适度波动时使用
            if adx > 35 and volatility < 200:
                adjusted_leverage = tier_config["base_leverage_max"]
                adjustment_reasons.append(f"强趋势(ADX={adx:.1f}>35)且波动可控→使用{adjusted_leverage}x")
            else:
                adjusted_leverage = tier_config["base_leverage_min"]
                adjustment_reasons.append(f"风险过高→保守杠杆{adjusted_leverage}x")

        # 6. 安全上下限
        adjusted_leverage = max(3, min(25, adjusted_leverage))

        adjustment_reason = "; ".join(adjustment_reasons) if adjustment_reasons else "无调整"

        result = {
            "leverage": adjusted_leverage,
            "base_leverage": base_leverage,
            "market_cap_usd": market_cap_usd,
            "market_cap_tier": tier,
            "tier_name": tier_config["name"],
            "volatility": volatility or 0,
            "adx": adx or 0,
            "adjustment_reason": adjustment_reason
        }

        logger.info(f"[{symbol}] 杠杆计算完成: {adjusted_leverage}x (基础{base_leverage}x, {adjustment_reason})")
        return result


# 全局实例
leverage_manager = LeverageManager()
