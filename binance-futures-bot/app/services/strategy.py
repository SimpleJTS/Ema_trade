"""
EMA交易策略模块
实现EMA6和EMA51的金叉死叉策略
"""
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """信号类型"""
    NONE = "NONE"
    LONG = "LONG"  # 做多
    SHORT = "SHORT"  # 做空


@dataclass
class StrategySignal:
    """策略信号"""
    signal_type: SignalType
    symbol: str
    price: float
    ema_fast: float
    ema_slow: float
    cross_count: int
    message: str
    conditions: dict = None  # 详细的条件检测结果 {"条件名": {"pass": bool, "value": str}}


class EMAStrategy:
    """EMA交叉策略
    
    规则:
    1. 检测当前K线的EMA6和EMA51是否相交
    2. 如果当前K线没有相交，不开仓
    3. 如果相交，判断是金叉还是死叉
    4. 检查前20根K线中EMA6和EMA51的交叉次数
    5. 如果交叉次数>2次，说明震荡行情，不开仓
    6. 如果金叉且交叉次数<=2，则做多
    7. 如果死叉且交叉次数<=2，则做空
    """
    
    def __init__(self, fast_period: int = 6, slow_period: int = 51, lookback: int = 20):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.lookback = lookback
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """计算EMA
        
        EMA = 价格 * k + 昨日EMA * (1 - k)
        k = 2 / (period + 1)
        """
        if len(prices) < period:
            return []
        
        prices = np.array(prices)
        ema = np.zeros(len(prices))
        
        # 使用SMA作为第一个EMA值
        ema[period - 1] = np.mean(prices[:period])
        
        # 计算乘数
        multiplier = 2 / (period + 1)
        
        # 计算后续EMA值
        for i in range(period, len(prices)):
            ema[i] = prices[i] * multiplier + ema[i - 1] * (1 - multiplier)
        
        return ema.tolist()
    
    def detect_cross(self, ema_fast: List[float], ema_slow: List[float], 
                     index: int) -> Optional[str]:
        """检测交叉
        
        Returns:
            "GOLDEN": 金叉 (快线上穿慢线)
            "DEATH": 死叉 (快线下穿慢线)
            None: 无交叉
        """
        if index < 1 or index >= len(ema_fast) or index >= len(ema_slow):
            return None
        
        # 当前状态
        fast_above_now = ema_fast[index] > ema_slow[index]
        # 前一状态
        fast_above_prev = ema_fast[index - 1] > ema_slow[index - 1]
        
        # 检测交叉
        if fast_above_now and not fast_above_prev:
            return "GOLDEN"  # 金叉
        elif not fast_above_now and fast_above_prev:
            return "DEATH"  # 死叉
        
        return None
    
    def count_crosses(self, ema_fast: List[float], ema_slow: List[float], 
                      end_index: int, lookback: int = None) -> int:
        """统计交叉次数
        
        Args:
            ema_fast: 快速EMA列表
            ema_slow: 慢速EMA列表
            end_index: 结束位置(不包含当前K线)
            lookback: 回看K线数量
        
        Returns:
            交叉次数
        """
        if lookback is None:
            lookback = self.lookback
        
        start_index = max(1, end_index - lookback)
        cross_count = 0
        
        for i in range(start_index, end_index):
            if self.detect_cross(ema_fast, ema_slow, i):
                cross_count += 1
        
        return cross_count
    
    def analyze(self, symbol: str, klines: List[dict]) -> StrategySignal:
        """分析K线数据生成信号

        Args:
            symbol: 交易对
            klines: K线数据列表，每个元素包含 open, high, low, close, volume
                   格式: [open_time, open, high, low, close, volume, close_time, ...]

        Returns:
            StrategySignal
        """
        # 至少需要slow_period + lookback + 2根K线
        min_klines = self.slow_period + self.lookback + 2
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

        # 提取收盘价
        close_prices = [float(k[4]) for k in klines]

        # 计算EMA
        ema_fast = self.calculate_ema(close_prices, self.fast_period)
        ema_slow = self.calculate_ema(close_prices, self.slow_period)

        # 当前K线索引(最后一根已收盘的K线)
        current_index = len(close_prices) - 1
        current_price = close_prices[current_index]
        current_ema_fast = ema_fast[current_index] if ema_fast else 0
        current_ema_slow = ema_slow[current_index] if ema_slow else 0

        # 初始化条件检测结果
        conditions = {}

        # 条件1: 检测当前K线是否有交叉
        cross_type = self.detect_cross(ema_fast, ema_slow, current_index)
        if cross_type == "GOLDEN":
            conditions["EMA交叉"] = {"pass": True, "value": f"金叉(EMA{self.fast_period}={current_ema_fast:.6f} > EMA{self.slow_period}={current_ema_slow:.6f})"}
        elif cross_type == "DEATH":
            conditions["EMA交叉"] = {"pass": True, "value": f"死叉(EMA{self.fast_period}={current_ema_fast:.6f} < EMA{self.slow_period}={current_ema_slow:.6f})"}
        else:
            conditions["EMA交叉"] = {"pass": False, "value": f"无交叉(EMA{self.fast_period}={current_ema_fast:.6f}, EMA{self.slow_period}={current_ema_slow:.6f})"}
            return StrategySignal(
                signal_type=SignalType.NONE,
                symbol=symbol,
                price=current_price,
                ema_fast=current_ema_fast,
                ema_slow=current_ema_slow,
                cross_count=0,
                message="无交叉信号",
                conditions=conditions
            )

        # 条件2: 统计前20根K线的交叉次数(不包含当前K线)
        cross_count = self.count_crosses(ema_fast, ema_slow, current_index)
        cross_count_ok = cross_count <= 2
        conditions["交叉频率"] = {
            "pass": cross_count_ok,
            "value": f"前{self.lookback}根交叉{cross_count}次 {'<=' if cross_count_ok else '>'} 2次"
        }

        # 判断信号
        # 当前K线有交叉，且前20根K线交叉次数<=2次，才开仓
        # 如果交叉次数>2次，说明是震荡行情，不适合开仓
        if cross_count_ok:
            if cross_type == "GOLDEN":
                return StrategySignal(
                    signal_type=SignalType.LONG,
                    symbol=symbol,
                    price=current_price,
                    ema_fast=current_ema_fast,
                    ema_slow=current_ema_slow,
                    cross_count=cross_count,
                    message=f"✅ 金叉信号! 所有条件满足",
                    conditions=conditions
                )
            else:  # DEATH
                return StrategySignal(
                    signal_type=SignalType.SHORT,
                    symbol=symbol,
                    price=current_price,
                    ema_fast=current_ema_fast,
                    ema_slow=current_ema_slow,
                    cross_count=cross_count,
                    message=f"✅ 死叉信号! 所有条件满足",
                    conditions=conditions
                )
        else:
            return StrategySignal(
                signal_type=SignalType.NONE,
                symbol=symbol,
                price=current_price,
                ema_fast=current_ema_fast,
                ema_slow=current_ema_slow,
                cross_count=cross_count,
                message=f"❌ 条件不满足: 交叉频率",
                conditions=conditions
            )
    
    def calculate_amplitude(self, klines: List[dict], lookback: int = 200) -> float:
        """计算振幅
        
        振幅 = (最高价 - 最低价) / 最低价 * 100%
        
        Args:
            klines: K线数据
            lookback: 回看K线数量
        
        Returns:
            振幅百分比
        """
        if len(klines) < lookback:
            lookback = len(klines)
        
        recent_klines = klines[-lookback:]
        
        if not recent_klines:
            return 0
        
        # 计算区间最高价和最低价
        high_prices = [float(k[2]) for k in recent_klines]
        low_prices = [float(k[3]) for k in recent_klines]
        
        highest = max(high_prices)
        lowest = min(low_prices)
        
        if lowest == 0:
            return 0
        
        amplitude = ((highest - lowest) / lowest) * 100
        return round(amplitude, 2)


class EMAAdvancedStrategy:
    """EMA高级交叉策略（EMA9/EMA72/EMA200 + ADX + 成交量）

    规则:
    做多信号（5个条件全满足才开仓）：
    1. EMA9 上穿 EMA72 且收盘价 > EMA72
    2. 收盘价 > EMA200
    3. ADX(14) ≥ 25
    4. 当前成交量 ≥ 30周期均量 × 1.8
    5. 前25根K线内仅发生 ≤1 次EMA9/EMA72交叉（最好0次）

    做空信号（5个条件全满足才开仓）：
    1. EMA9 下穿 EMA72 且收盘价 < EMA72
    2. 收盘价 < EMA200
    3. ADX(14) ≥ 25
    4. 当前成交量 ≥ 30周期均量 × 1.8
    5. 前25根K线内仅发生 ≤1 次EMA9/EMA72交叉（最好0次）
    """

    def __init__(self, ema_fast: int = 9, ema_medium: int = 72, ema_slow: int = 200,
                 adx_period: int = 14, adx_threshold: float = 25,
                 volume_period: int = 30, volume_multiplier: float = 1.8,
                 lookback: int = 25, max_crosses: int = 1):
        self.ema_fast = ema_fast
        self.ema_medium = ema_medium
        self.ema_slow = ema_slow
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.volume_period = volume_period
        self.volume_multiplier = volume_multiplier
        self.lookback = lookback
        self.max_crosses = max_crosses

    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """计算EMA（复用基础策略的方法）"""
        return EMAStrategy.calculate_ema(prices, period)

    def detect_cross(self, ema_fast: List[float], ema_medium: List[float],
                     index: int) -> Optional[str]:
        """检测EMA9和EMA72的交叉"""
        if index < 1 or index >= len(ema_fast) or index >= len(ema_medium):
            return None

        # 当前状态
        fast_above_now = ema_fast[index] > ema_medium[index]
        # 前一状态
        fast_above_prev = ema_fast[index - 1] > ema_medium[index - 1]

        # 检测交叉
        if fast_above_now and not fast_above_prev:
            return "GOLDEN"  # 金叉
        elif not fast_above_now and fast_above_prev:
            return "DEATH"  # 死叉

        return None

    def count_crosses(self, ema_fast: List[float], ema_medium: List[float],
                      end_index: int, lookback: int = None) -> int:
        """统计EMA9和EMA72交叉次数"""
        if lookback is None:
            lookback = self.lookback

        start_index = max(1, end_index - lookback)
        cross_count = 0

        for i in range(start_index, end_index):
            if self.detect_cross(ema_fast, ema_medium, i):
                cross_count += 1

        return cross_count

    def analyze(self, symbol: str, klines: List[dict]) -> StrategySignal:
        """分析K线数据生成信号

        Args:
            symbol: 交易对
            klines: K线数据列表

        Returns:
            StrategySignal
        """
        # 导入技术指标
        from app.utils.indicators import technical_indicators

        # 至少需要 ema_slow + lookback + adx_period + 2 根K线
        min_klines = self.ema_slow + self.lookback + self.adx_period + 2
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

        # 提取收盘价
        close_prices = [float(k[4]) for k in klines]

        # 计算EMA9, EMA72, EMA200
        ema9 = self.calculate_ema(close_prices, self.ema_fast)
        ema72 = self.calculate_ema(close_prices, self.ema_medium)
        ema200 = self.calculate_ema(close_prices, self.ema_slow)

        # 当前K线索引
        current_index = len(close_prices) - 1
        current_price = close_prices[current_index]
        current_ema9 = ema9[current_index] if ema9 else 0
        current_ema72 = ema72[current_index] if ema72 else 0
        current_ema200 = ema200[current_index] if ema200 else 0

        # 初始化条件检测结果
        conditions = {}

        # 条件1: 检测当前K线是否有EMA9/EMA72交叉
        cross_type = self.detect_cross(ema9, ema72, current_index)
        if cross_type == "GOLDEN":
            conditions["EMA交叉"] = {"pass": True, "value": f"金叉(EMA{self.ema_fast}={current_ema9:.6f} > EMA{self.ema_medium}={current_ema72:.6f})"}
        elif cross_type == "DEATH":
            conditions["EMA交叉"] = {"pass": True, "value": f"死叉(EMA{self.ema_fast}={current_ema9:.6f} < EMA{self.ema_medium}={current_ema72:.6f})"}
        else:
            conditions["EMA交叉"] = {"pass": False, "value": f"无交叉(EMA{self.ema_fast}={current_ema9:.6f}, EMA{self.ema_medium}={current_ema72:.6f})"}
            return StrategySignal(
                signal_type=SignalType.NONE,
                symbol=symbol,
                price=current_price,
                ema_fast=current_ema9,
                ema_slow=current_ema72,
                cross_count=0,
                message="无EMA交叉信号",
                conditions=conditions
            )

        # 条件2: 检查收盘价与EMA200的关系
        if cross_type == "GOLDEN":
            price_vs_ema200_ok = current_price > current_ema200
            conditions["价格vs EMA200"] = {
                "pass": price_vs_ema200_ok,
                "value": f"价格({current_price:.6f}) {'>' if price_vs_ema200_ok else '<='} EMA200({current_ema200:.6f})"
            }
        else:  # DEATH
            price_vs_ema200_ok = current_price < current_ema200
            conditions["价格vs EMA200"] = {
                "pass": price_vs_ema200_ok,
                "value": f"价格({current_price:.6f}) {'<' if price_vs_ema200_ok else '>='} EMA200({current_ema200:.6f})"
            }

        # 条件3: 计算ADX并检查是否≥25
        adx_values, plus_di, minus_di = technical_indicators.calculate_adx(klines, self.adx_period)
        current_adx = 0
        adx_ok = False
        if adx_values and len(adx_values) > 0:
            current_adx = adx_values[-1]
            adx_ok = current_adx >= self.adx_threshold
        conditions["ADX强度"] = {
            "pass": adx_ok,
            "value": f"ADX({current_adx:.2f}) {'>=' if adx_ok else '<'} {self.adx_threshold}"
        }

        # 条件4: 检查成交量是否突破
        volume_ok = technical_indicators.check_volume_surge(
            klines, self.volume_period, self.volume_multiplier
        )
        current_volume = float(klines[-1][5])
        volume_ma_list = technical_indicators.calculate_volume_average(klines, self.volume_period)
        avg_volume = volume_ma_list[-1] if volume_ma_list else 0
        volume_threshold = avg_volume * self.volume_multiplier
        conditions["成交量突破"] = {
            "pass": volume_ok,
            "value": f"当前({current_volume:.0f}) {'>=' if volume_ok else '<'} 阈值({volume_threshold:.0f}, {self.volume_multiplier}x均量)"
        }

        # 条件5: 统计前N根K线的交叉次数
        cross_count = self.count_crosses(ema9, ema72, current_index)
        cross_count_ok = cross_count <= self.max_crosses
        conditions["交叉频率"] = {
            "pass": cross_count_ok,
            "value": f"前{self.lookback}根交叉{cross_count}次 {'<=' if cross_count_ok else '>'} {self.max_crosses}次"
        }

        # 判断所有条件是否都满足
        all_conditions_met = all(cond["pass"] for cond in conditions.values())

        if all_conditions_met:
            # 所有条件满足，生成信号
            if cross_type == "GOLDEN":
                return StrategySignal(
                    signal_type=SignalType.LONG,
                    symbol=symbol,
                    price=current_price,
                    ema_fast=current_ema9,
                    ema_slow=current_ema72,
                    cross_count=cross_count,
                    message=f"✅ 做多信号! 所有条件满足",
                    conditions=conditions
                )
            else:  # DEATH
                return StrategySignal(
                    signal_type=SignalType.SHORT,
                    symbol=symbol,
                    price=current_price,
                    ema_fast=current_ema9,
                    ema_slow=current_ema72,
                    cross_count=cross_count,
                    message=f"✅ 做空信号! 所有条件满足",
                    conditions=conditions
                )
        else:
            # 有条件不满足
            failed_conditions = [name for name, cond in conditions.items() if not cond["pass"]]
            return StrategySignal(
                signal_type=SignalType.NONE,
                symbol=symbol,
                price=current_price,
                ema_fast=current_ema9,
                ema_slow=current_ema72,
                cross_count=cross_count,
                message=f"❌ 条件不满足: {', '.join(failed_conditions)}",
                conditions=conditions
            )


# 全局策略实例
ema_strategy = EMAStrategy()  # 基础策略（EMA6/EMA51）
ema_advanced_strategy = EMAAdvancedStrategy()  # 高级策略（EMA9/EMA72/EMA200）
