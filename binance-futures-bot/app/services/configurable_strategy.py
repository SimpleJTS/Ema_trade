"""
可配置策略引擎
根据用户配置的条件组合动态生成交易信号
"""
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from app.services.strategy import SignalType, StrategySignal, EMAStrategy
from app.utils.indicators import technical_indicators

logger = logging.getLogger(__name__)


@dataclass
class ConditionResult:
    """条件检查结果"""
    passed: bool
    condition_type: str
    message: str
    value: Optional[float] = None


class ConfigurableStrategy:
    """可配置策略引擎

    根据StrategyConfig动态检查条件并生成信号
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 策略配置字典
                {
                    "name": "策略名称",
                    "ema_fast": 9,
                    "ema_medium": 72,
                    "ema_slow": 200,
                    "entry_conditions": [
                        {"type": "ema_cross", "enabled": true, "direction": "golden", "price_confirm": true},
                        {"type": "price_above_ema", "enabled": true, "ema_type": "slow"},
                        {"type": "adx_threshold", "enabled": true, "period": 14, "threshold": 25},
                        {"type": "volume_surge", "enabled": true, "period": 30, "multiplier": 1.8},
                        {"type": "cross_count_limit", "enabled": true, "lookback": 25, "max_crosses": 1}
                    ]
                }
        """
        self.config = config
        self.ema_fast = config.get("ema_fast", 9)
        self.ema_medium = config.get("ema_medium", 72)
        self.ema_slow = config.get("ema_slow", 200)
        self.entry_conditions = config.get("entry_conditions", [])

    def analyze(self, symbol: str, klines: List[dict],
                direction: str = "both") -> StrategySignal:
        """分析K线数据生成信号

        Args:
            symbol: 交易对
            klines: K线数据列表
            direction: "long", "short", "both"

        Returns:
            StrategySignal
        """
        # 检查K线数据充足性
        min_klines = max(self.ema_slow, 200) + 50  # 预留足够数据
        if len(klines) < min_klines:
            return StrategySignal(
                signal_type=SignalType.NONE,
                symbol=symbol,
                price=0,
                ema_fast=0,
                ema_slow=0,
                cross_count=0,
                message=f"K线数据不足: {len(klines)} < {min_klines}"
            )

        # 提取价格数据
        close_prices = [float(k[4]) for k in klines]
        current_price = close_prices[-1]

        # 计算EMA
        ema_fast_values = EMAStrategy.calculate_ema(close_prices, self.ema_fast)
        ema_medium_values = EMAStrategy.calculate_ema(close_prices, self.ema_medium) if self.ema_medium else None
        ema_slow_values = EMAStrategy.calculate_ema(close_prices, self.ema_slow) if self.ema_slow else None

        current_ema_fast = ema_fast_values[-1] if ema_fast_values else 0
        current_ema_medium = ema_medium_values[-1] if ema_medium_values else 0

        # 检测交叉方向
        cross_type = self._detect_cross(ema_fast_values, ema_medium_values, -1) if ema_medium_values else None

        # 判断做多还是做空
        if cross_type == "GOLDEN" and direction in ["long", "both"]:
            signal_direction = "long"
        elif cross_type == "DEATH" and direction in ["short", "both"]:
            signal_direction = "short"
        else:
            return StrategySignal(
                signal_type=SignalType.NONE,
                symbol=symbol,
                price=current_price,
                ema_fast=current_ema_fast,
                ema_slow=current_ema_medium,
                cross_count=0,
                message="当前无交叉或不符合方向要求"
            )

        # 检查所有启用的条件
        condition_results = []
        for condition_config in self.entry_conditions:
            if not condition_config.get("enabled", False):
                continue

            result = self._check_condition(
                condition_config,
                klines,
                close_prices,
                ema_fast_values,
                ema_medium_values,
                ema_slow_values,
                signal_direction
            )
            condition_results.append(result)

        # 判断是否所有条件都通过
        failed_conditions = [r for r in condition_results if not r.passed]

        if not failed_conditions:
            # 所有条件通过，生成信号
            signal_type = SignalType.LONG if signal_direction == "long" else SignalType.SHORT
            messages = [r.message for r in condition_results]

            return StrategySignal(
                signal_type=signal_type,
                symbol=symbol,
                price=current_price,
                ema_fast=current_ema_fast,
                ema_slow=current_ema_medium,
                cross_count=0,
                message=f"✅ 所有条件满足: {' | '.join(messages)}"
            )
        else:
            # 有条件未通过
            failed_messages = [r.message for r in failed_conditions]
            return StrategySignal(
                signal_type=SignalType.NONE,
                symbol=symbol,
                price=current_price,
                ema_fast=current_ema_fast,
                ema_slow=current_ema_medium,
                cross_count=0,
                message=f"❌ 条件未满足: {' | '.join(failed_messages)}"
            )

    def _check_condition(self, condition_config: Dict, klines: List[dict],
                        close_prices: List[float],
                        ema_fast: List[float], ema_medium: List[float],
                        ema_slow: List[float], direction: str) -> ConditionResult:
        """检查单个条件"""
        condition_type = condition_config["type"]

        # EMA交叉
        if condition_type == "ema_cross":
            return self._check_ema_cross(condition_config, ema_fast, ema_medium,
                                        close_prices, direction)

        # 价格高于/低于EMA
        elif condition_type in ["price_above_ema", "price_below_ema"]:
            return self._check_price_position(condition_config, close_prices,
                                             ema_fast, ema_medium, ema_slow, direction)

        # ADX阈值
        elif condition_type == "adx_threshold":
            return self._check_adx(condition_config, klines)

        # 成交量激增
        elif condition_type == "volume_surge":
            return self._check_volume(condition_config, klines)

        # 交叉次数限制
        elif condition_type == "cross_count_limit":
            return self._check_cross_count(condition_config, ema_fast, ema_medium)

        else:
            return ConditionResult(
                passed=False,
                condition_type=condition_type,
                message=f"未知条件类型: {condition_type}"
            )

    def _detect_cross(self, ema_fast: List[float], ema_medium: List[float],
                     index: int) -> Optional[str]:
        """检测交叉"""
        if not ema_fast or not ema_medium or index < -len(ema_fast) or abs(index) > len(ema_fast):
            return None

        if index < 0:
            index = len(ema_fast) + index

        if index < 1:
            return None

        fast_above_now = ema_fast[index] > ema_medium[index]
        fast_above_prev = ema_fast[index - 1] > ema_medium[index - 1]

        if fast_above_now and not fast_above_prev:
            return "GOLDEN"
        elif not fast_above_now and fast_above_prev:
            return "DEATH"

        return None

    def _check_ema_cross(self, config: Dict, ema_fast: List[float],
                        ema_medium: List[float], close_prices: List[float],
                        direction: str) -> ConditionResult:
        """检查EMA交叉"""
        expected_direction = "GOLDEN" if direction == "long" else "DEATH"
        cross_type = self._detect_cross(ema_fast, ema_medium, -1)

        if cross_type != expected_direction:
            return ConditionResult(
                passed=False,
                condition_type="ema_cross",
                message=f"无{expected_direction}交叉"
            )

        # 价格确认
        price_confirm = config.get("price_confirm", True)
        if price_confirm:
            current_price = close_prices[-1]
            current_ema_medium = ema_medium[-1]

            if direction == "long" and current_price <= current_ema_medium:
                return ConditionResult(
                    passed=False,
                    condition_type="ema_cross",
                    message=f"价格{current_price:.2f}未高于EMA{self.ema_medium}({current_ema_medium:.2f})"
                )
            elif direction == "short" and current_price >= current_ema_medium:
                return ConditionResult(
                    passed=False,
                    condition_type="ema_cross",
                    message=f"价格{current_price:.2f}未低于EMA{self.ema_medium}({current_ema_medium:.2f})"
                )

        return ConditionResult(
            passed=True,
            condition_type="ema_cross",
            message=f"EMA{self.ema_fast}{'上穿' if direction == 'long' else '下穿'}EMA{self.ema_medium}"
        )

    def _check_price_position(self, config: Dict, close_prices: List[float],
                             ema_fast: List[float], ema_medium: List[float],
                             ema_slow: List[float], direction: str) -> ConditionResult:
        """检查价格位置"""
        ema_type = config.get("ema_type", "slow")
        current_price = close_prices[-1]

        if ema_type == "fast":
            ema_value = ema_fast[-1]
            ema_name = f"EMA{self.ema_fast}"
        elif ema_type == "medium":
            ema_value = ema_medium[-1] if ema_medium else None
            ema_name = f"EMA{self.ema_medium}"
        else:  # slow
            ema_value = ema_slow[-1] if ema_slow else None
            ema_name = f"EMA{self.ema_slow}"

        if ema_value is None:
            return ConditionResult(
                passed=False,
                condition_type=config["type"],
                message=f"{ema_name}未配置"
            )

        condition_type = config["type"]
        if condition_type == "price_above_ema":
            if direction == "long" and current_price > ema_value:
                return ConditionResult(
                    passed=True,
                    condition_type=condition_type,
                    message=f"价格{current_price:.2f} > {ema_name}({ema_value:.2f})",
                    value=current_price
                )
            else:
                return ConditionResult(
                    passed=False,
                    condition_type=condition_type,
                    message=f"价格{current_price:.2f}未高于{ema_name}({ema_value:.2f})"
                )
        else:  # price_below_ema
            if direction == "short" and current_price < ema_value:
                return ConditionResult(
                    passed=True,
                    condition_type=condition_type,
                    message=f"价格{current_price:.2f} < {ema_name}({ema_value:.2f})",
                    value=current_price
                )
            else:
                return ConditionResult(
                    passed=False,
                    condition_type=condition_type,
                    message=f"价格{current_price:.2f}未低于{ema_name}({ema_value:.2f})"
                )

    def _check_adx(self, config: Dict, klines: List[dict]) -> ConditionResult:
        """检查ADX"""
        period = config.get("period", 14)
        threshold = config.get("threshold", 25)

        adx_values, _, _ = technical_indicators.calculate_adx(klines, period=period)
        if not adx_values:
            return ConditionResult(
                passed=False,
                condition_type="adx_threshold",
                message="ADX计算失败"
            )

        current_adx = adx_values[-1]
        if current_adx >= threshold:
            return ConditionResult(
                passed=True,
                condition_type="adx_threshold",
                message=f"ADX({period})={current_adx:.1f} ≥ {threshold}",
                value=current_adx
            )
        else:
            return ConditionResult(
                passed=False,
                condition_type="adx_threshold",
                message=f"ADX({period})={current_adx:.1f} < {threshold}"
            )

    def _check_volume(self, config: Dict, klines: List[dict]) -> ConditionResult:
        """检查成交量"""
        period = config.get("period", 30)
        multiplier = config.get("multiplier", 1.8)

        volumes = [float(k[5]) for k in klines]
        if len(volumes) < period + 1:
            return ConditionResult(
                passed=False,
                condition_type="volume_surge",
                message="成交量数据不足"
            )

        current_volume = volumes[-1]
        avg_volume = sum(volumes[-period-1:-1]) / period

        if current_volume >= avg_volume * multiplier:
            return ConditionResult(
                passed=True,
                condition_type="volume_surge",
                message=f"成交量{current_volume:.0f} ≥ {period}期均量({avg_volume:.0f}) × {multiplier}",
                value=current_volume
            )
        else:
            return ConditionResult(
                passed=False,
                condition_type="volume_surge",
                message=f"成交量{current_volume:.0f} < {period}期均量({avg_volume:.0f}) × {multiplier}"
            )

    def _check_cross_count(self, config: Dict, ema_fast: List[float],
                          ema_medium: List[float]) -> ConditionResult:
        """检查交叉次数"""
        lookback = config.get("lookback", 25)
        max_crosses = config.get("max_crosses", 1)

        if not ema_fast or not ema_medium or len(ema_fast) < lookback:
            return ConditionResult(
                passed=False,
                condition_type="cross_count_limit",
                message="数据不足以检查交叉次数"
            )

        cross_count = 0
        end_index = len(ema_fast) - 1
        start_index = max(1, end_index - lookback)

        for i in range(start_index, end_index):
            if self._detect_cross(ema_fast, ema_medium, i):
                cross_count += 1

        if cross_count <= max_crosses:
            return ConditionResult(
                passed=True,
                condition_type="cross_count_limit",
                message=f"前{lookback}根K线交叉{cross_count}次 ≤ {max_crosses}",
                value=cross_count
            )
        else:
            return ConditionResult(
                passed=False,
                condition_type="cross_count_limit",
                message=f"前{lookback}根K线交叉{cross_count}次 > {max_crosses}（震荡市场）"
            )


# 全局实例（根据活跃配置创建）
configurable_strategy = None
