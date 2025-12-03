"""
技术指标计算工具
包含 ADX, ATR, 成交量均线等指标
"""
import logging
import numpy as np
from typing import List, Tuple, Optional
import math

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """技术指标计算器"""

    @staticmethod
    def calculate_atr(klines: List[dict], period: int = 14) -> List[float]:
        """计算ATR (Average True Range)

        Args:
            klines: K线数据 [open_time, open, high, low, close, volume, ...]
            period: ATR周期

        Returns:
            ATR值列表
        """
        if len(klines) < period + 1:
            return []

        high_prices = np.array([float(k[2]) for k in klines])
        low_prices = np.array([float(k[3]) for k in klines])
        close_prices = np.array([float(k[4]) for k in klines])

        # 计算True Range
        tr_list = []
        for i in range(1, len(klines)):
            high_low = high_prices[i] - low_prices[i]
            high_close = abs(high_prices[i] - close_prices[i - 1])
            low_close = abs(low_prices[i] - close_prices[i - 1])
            tr = max(high_low, high_close, low_close)
            tr_list.append(tr)

        tr_array = np.array(tr_list)

        # 计算ATR（使用EMA平滑）
        atr = np.zeros(len(tr_array))
        atr[period - 1] = np.mean(tr_array[:period])

        multiplier = 1 / period
        for i in range(period, len(tr_array)):
            atr[i] = atr[i - 1] * (1 - multiplier) + tr_array[i] * multiplier

        return atr.tolist()

    @staticmethod
    def calculate_atr_volatility(klines: List[dict], period: int = 14) -> Optional[float]:
        """计算ATR年化波动率（针对1分钟K线）

        Args:
            klines: K线数据
            period: ATR周期

        Returns:
            年化波动率百分比，如 150.5 表示 150.5%
        """
        if len(klines) < period + 1:
            return None

        atr_values = TechnicalIndicators.calculate_atr(klines, period)
        if not atr_values:
            return None

        current_atr = atr_values[-1]
        current_price = float(klines[-1][4])

        if current_price == 0:
            return None

        # 1分钟K线的年化因子: sqrt(365 * 24 * 60) = sqrt(525600) ≈ 725.07
        annualization_factor = math.sqrt(365 * 24 * 60)

        # ATR年化波动率 = (ATR / Price) * 年化因子 * 100%
        volatility_percent = (current_atr / current_price) * annualization_factor * 100

        return round(volatility_percent, 2)

    @staticmethod
    def calculate_adx(klines: List[dict], period: int = 14) -> Tuple[List[float], List[float], List[float]]:
        """计算ADX (Average Directional Index)

        Args:
            klines: K线数据
            period: ADX周期

        Returns:
            (ADX值列表, +DI列表, -DI列表)
        """
        if len(klines) < period * 2:
            return [], [], []

        high_prices = np.array([float(k[2]) for k in klines])
        low_prices = np.array([float(k[3]) for k in klines])
        close_prices = np.array([float(k[4]) for k in klines])

        # 计算+DM和-DM
        plus_dm = []
        minus_dm = []
        for i in range(1, len(klines)):
            high_diff = high_prices[i] - high_prices[i - 1]
            low_diff = low_prices[i - 1] - low_prices[i]

            if high_diff > low_diff and high_diff > 0:
                plus_dm.append(high_diff)
            else:
                plus_dm.append(0)

            if low_diff > high_diff and low_diff > 0:
                minus_dm.append(low_diff)
            else:
                minus_dm.append(0)

        plus_dm = np.array(plus_dm)
        minus_dm = np.array(minus_dm)

        # 计算ATR
        atr_values = TechnicalIndicators.calculate_atr(klines, period)
        atr_array = np.array(atr_values)

        # 平滑+DM和-DM
        smoothed_plus_dm = np.zeros(len(plus_dm))
        smoothed_minus_dm = np.zeros(len(minus_dm))

        smoothed_plus_dm[period - 1] = np.sum(plus_dm[:period])
        smoothed_minus_dm[period - 1] = np.sum(minus_dm[:period])

        for i in range(period, len(plus_dm)):
            smoothed_plus_dm[i] = smoothed_plus_dm[i - 1] - (smoothed_plus_dm[i - 1] / period) + plus_dm[i]
            smoothed_minus_dm[i] = smoothed_minus_dm[i - 1] - (smoothed_minus_dm[i - 1] / period) + minus_dm[i]

        # 计算+DI和-DI
        plus_di = np.zeros(len(atr_array))
        minus_di = np.zeros(len(atr_array))

        for i in range(period - 1, len(atr_array)):
            if atr_array[i] != 0:
                plus_di[i] = (smoothed_plus_dm[i] / atr_array[i]) * 100
                minus_di[i] = (smoothed_minus_dm[i] / atr_array[i]) * 100

        # 计算DX
        dx = np.zeros(len(plus_di))
        for i in range(period - 1, len(plus_di)):
            di_sum = plus_di[i] + minus_di[i]
            if di_sum != 0:
                dx[i] = abs(plus_di[i] - minus_di[i]) / di_sum * 100

        # 计算ADX（DX的平滑移动平均）
        adx = np.zeros(len(dx))
        adx[period * 2 - 2] = np.mean(dx[period - 1:period * 2 - 1])

        for i in range(period * 2 - 1, len(dx)):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

        return adx.tolist(), plus_di.tolist(), minus_di.tolist()

    @staticmethod
    def calculate_volume_average(klines: List[dict], period: int = 30) -> List[float]:
        """计算成交量均线

        Args:
            klines: K线数据
            period: 均线周期

        Returns:
            成交量均线列表
        """
        if len(klines) < period:
            return []

        volumes = np.array([float(k[5]) for k in klines])
        volume_ma = []

        for i in range(period - 1, len(volumes)):
            ma = np.mean(volumes[i - period + 1:i + 1])
            volume_ma.append(ma)

        return volume_ma

    @staticmethod
    def check_volume_surge(klines: List[dict], period: int = 30, multiplier: float = 1.8) -> bool:
        """检查成交量是否突破均量

        Args:
            klines: K线数据
            period: 均量周期
            multiplier: 倍数，如1.8表示当前成交量需要≥均量的1.8倍

        Returns:
            True表示成交量符合条件
        """
        if len(klines) < period + 1:
            return False

        volume_ma = TechnicalIndicators.calculate_volume_average(klines, period)
        if not volume_ma:
            return False

        current_volume = float(klines[-1][5])
        avg_volume = volume_ma[-1]

        return current_volume >= avg_volume * multiplier


# 全局实例
technical_indicators = TechnicalIndicators()
