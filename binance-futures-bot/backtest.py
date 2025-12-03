"""
交易策略回测脚本
用于回测EMA高级策略的表现
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
from app.services.strategy import ema_advanced_strategy, SignalType
from app.services.binance_api import binance_api
from app.utils.indicators import technical_indicators

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Backtest:
    """回测引擎"""

    def __init__(self,
                 initial_balance: float = 1000.0,
                 position_size_percent: float = 10.0,
                 leverage: int = 10,
                 stop_loss_percent: float = 2.0):
        """
        Args:
            initial_balance: 初始资金（USDT）
            position_size_percent: 单次开仓占总资金的百分比
            leverage: 杠杆倍数
            stop_loss_percent: 初始止损百分比
        """
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.position_size_percent = position_size_percent
        self.leverage = leverage
        self.stop_loss_percent = stop_loss_percent

        # 交易记录
        self.trades: List[Dict] = []
        self.positions: Dict[str, Dict] = {}  # 当前持仓

        # 统计数据
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_profit = 0.0
        self.max_drawdown = 0.0
        self.peak_balance = initial_balance

    def open_position(self, symbol: str, signal_type: SignalType, entry_price: float,
                     timestamp: datetime, reason: str = ""):
        """开仓"""
        if symbol in self.positions:
            return False

        # 计算开仓金额
        position_value = self.current_balance * (self.position_size_percent / 100)
        quantity = position_value / entry_price

        # 计算止损价
        if signal_type == SignalType.LONG:
            stop_loss_price = entry_price * (1 - self.stop_loss_percent / 100)
        else:
            stop_loss_price = entry_price * (1 + self.stop_loss_percent / 100)

        self.positions[symbol] = {
            "side": "LONG" if signal_type == SignalType.LONG else "SHORT",
            "entry_price": entry_price,
            "quantity": quantity,
            "position_value": position_value,
            "stop_loss_price": stop_loss_price,
            "stop_level": 0,
            "is_partial_closed": False,
            "opened_at": timestamp,
            "reason": reason
        }

        logger.info(f"[{timestamp}] 开仓 {symbol} {self.positions[symbol]['side']} @{entry_price:.6f}, 数量={quantity:.4f}, 止损={stop_loss_price:.6f}")
        return True

    def check_stop_loss(self, symbol: str, current_price: float, timestamp: datetime) -> bool:
        """检查止损和移动止盈"""
        if symbol not in self.positions:
            return False

        position = self.positions[symbol]
        side = position["side"]
        entry_price = position["entry_price"]
        stop_loss_price = position["stop_loss_price"]

        # 计算当前盈亏百分比（基于价格，不含杠杆）
        if side == "LONG":
            profit_percent = ((current_price - entry_price) / entry_price) * 100
        else:
            profit_percent = ((entry_price - current_price) / entry_price) * 100

        # 检查是否触发止损
        if side == "LONG" and current_price <= stop_loss_price:
            self.close_position(symbol, current_price, timestamp, "STOP_LOSS")
            return True
        elif side == "SHORT" and current_price >= stop_loss_price:
            self.close_position(symbol, current_price, timestamp, "STOP_LOSS")
            return True

        # 4级止损逻辑
        current_level = position["stop_level"]

        # Level 1: 盈利≥1.8% → 止损移至成本+0.1%
        if profit_percent >= 1.8 and current_level < 1:
            if side == "LONG":
                position["stop_loss_price"] = entry_price * 1.001
            else:
                position["stop_loss_price"] = entry_price * 0.999
            position["stop_level"] = 1
            logger.info(f"[{timestamp}] {symbol} 触发Level 1: 盈利{profit_percent:.2f}%, 止损移至保本")

        # Level 2: 盈利≥2.5% → 止损提至成本+1.9%
        elif profit_percent >= 2.5 and current_level < 2:
            if side == "LONG":
                position["stop_loss_price"] = entry_price * 1.019
            else:
                position["stop_loss_price"] = entry_price * 0.981
            position["stop_level"] = 2
            logger.info(f"[{timestamp}] {symbol} 触发Level 2: 盈利{profit_percent:.2f}%, 锁定1.9%利润")

        # Level 3: 盈利≥4.0% → 部分平仓50%
        elif profit_percent >= 4.0 and current_level < 3:
            if not position["is_partial_closed"]:
                # 部分平仓50%
                close_quantity = position["quantity"] * 0.5
                if side == "LONG":
                    partial_pnl = (current_price - entry_price) * close_quantity
                else:
                    partial_pnl = (entry_price - current_price) * close_quantity

                # 计算杠杆盈亏
                partial_pnl_with_leverage = partial_pnl * self.leverage
                self.current_balance += partial_pnl_with_leverage

                # 更新仓位
                position["quantity"] *= 0.5
                position["is_partial_closed"] = True
                position["stop_level"] = 3

                # 设置追踪止损（1.5%）
                if side == "LONG":
                    position["stop_loss_price"] = entry_price * 1.019
                    position["trailing_stop_percent"] = 1.5
                    position["highest_price"] = current_price
                else:
                    position["stop_loss_price"] = entry_price * 0.981
                    position["trailing_stop_percent"] = 1.5
                    position["lowest_price"] = current_price

                logger.info(f"[{timestamp}] {symbol} 触发Level 3: 盈利{profit_percent:.2f}%, 部分平仓50%, 盈利{partial_pnl_with_leverage:.2f} USDT")

        # 追踪止损（Level 3之后）
        if position["stop_level"] >= 3 and "trailing_stop_percent" in position:
            trailing_percent = position["trailing_stop_percent"]

            if side == "LONG":
                if current_price > position.get("highest_price", entry_price):
                    position["highest_price"] = current_price
                    # 更新追踪止损
                    new_stop = current_price * (1 - trailing_percent / 100)
                    if new_stop > position["stop_loss_price"]:
                        position["stop_loss_price"] = new_stop
                        logger.debug(f"[{timestamp}] {symbol} 追踪止损上移至 {new_stop:.6f}")
            else:  # SHORT
                if current_price < position.get("lowest_price", entry_price):
                    position["lowest_price"] = current_price
                    # 更新追踪止损
                    new_stop = current_price * (1 + trailing_percent / 100)
                    if new_stop < position["stop_loss_price"]:
                        position["stop_loss_price"] = new_stop
                        logger.debug(f"[{timestamp}] {symbol} 追踪止损下移至 {new_stop:.6f}")

        return False

    def close_position(self, symbol: str, exit_price: float, timestamp: datetime,
                      reason: str = "SIGNAL"):
        """平仓"""
        if symbol not in self.positions:
            return

        position = self.positions[symbol]
        side = position["side"]
        entry_price = position["entry_price"]
        quantity = position["quantity"]

        # 计算盈亏（价格盈亏）
        if side == "LONG":
            pnl = (exit_price - entry_price) * quantity
        else:
            pnl = (entry_price - exit_price) * quantity

        # 计算杠杆盈亏
        pnl_with_leverage = pnl * self.leverage
        pnl_percent = (pnl / entry_price / quantity) * 100 * self.leverage

        # 更新余额
        self.current_balance += pnl_with_leverage

        # 记录交易
        trade_record = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "pnl": pnl_with_leverage,
            "pnl_percent": pnl_percent,
            "opened_at": position["opened_at"],
            "closed_at": timestamp,
            "reason": reason,
            "stop_level": position["stop_level"],
            "is_partial_closed": position["is_partial_closed"]
        }
        self.trades.append(trade_record)

        # 更新统计
        self.total_trades += 1
        if pnl_with_leverage > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        self.total_profit += pnl_with_leverage

        # 更新最大回撤
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
        drawdown = (self.peak_balance - self.current_balance) / self.peak_balance * 100
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

        logger.info(f"[{timestamp}] 平仓 {symbol} {side} @{exit_price:.6f}, "
                   f"盈亏={pnl_with_leverage:.2f} USDT ({pnl_percent:.2f}%), "
                   f"原因={reason}, 余额={self.current_balance:.2f}")

        # 删除仓位
        del self.positions[symbol]

    def get_statistics(self) -> Dict:
        """获取回测统计"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0

        # 计算平均盈利和亏损
        winning_pnls = [t["pnl"] for t in self.trades if t["pnl"] > 0]
        losing_pnls = [t["pnl"] for t in self.trades if t["pnl"] < 0]

        avg_win = sum(winning_pnls) / len(winning_pnls) if winning_pnls else 0
        avg_loss = sum(losing_pnls) / len(losing_pnls) if losing_pnls else 0

        profit_factor = abs(sum(winning_pnls) / sum(losing_pnls)) if losing_pnls else float('inf')

        return {
            "initial_balance": self.initial_balance,
            "final_balance": self.current_balance,
            "total_profit": self.total_profit,
            "return_percent": (self.current_balance - self.initial_balance) / self.initial_balance * 100,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown": self.max_drawdown
        }


async def run_backtest(symbol: str,
                      days: int = 30,
                      initial_balance: float = 1000.0,
                      leverage: int = 10):
    """运行回测

    Args:
        symbol: 交易对，如 "BTCUSDT"
        days: 回测天数
        initial_balance: 初始资金
        leverage: 杠杆倍数
    """
    logger.info(f"=" * 60)
    logger.info(f"开始回测: {symbol}")
    logger.info(f"回测周期: {days}天")
    logger.info(f"初始资金: {initial_balance} USDT")
    logger.info(f"杠杆: {leverage}x")
    logger.info(f"=" * 60)

    # 创建回测引擎
    backtest = Backtest(
        initial_balance=initial_balance,
        position_size_percent=10.0,
        leverage=leverage,
        stop_loss_percent=2.0
    )

    # 获取历史K线数据
    logger.info(f"正在获取历史数据...")
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)

    # 每次获取最多1000根K线
    all_klines = []
    current_time = start_time

    while current_time < end_time:
        try:
            klines = await binance_api.get_klines(
                symbol=symbol,
                interval="1m",
                limit=1000,
                start_time=int(current_time.timestamp() * 1000)
            )

            if not klines:
                break

            all_klines.extend(klines)

            # 更新时间
            last_kline_time = int(klines[-1][0])
            current_time = datetime.fromtimestamp(last_kline_time / 1000) + timedelta(minutes=1)

            logger.info(f"已获取 {len(all_klines)} 根K线...")

        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            break

    logger.info(f"共获取 {len(all_klines)} 根K线数据")

    if len(all_klines) < 300:
        logger.error("K线数据不足，无法进行回测")
        return

    # 开始回测
    logger.info(f"\n开始回测交易...")

    for i in range(250, len(all_klines)):
        # 获取最近250根K线用于策略分析
        recent_klines = all_klines[max(0, i-250):i+1]
        current_kline = all_klines[i]

        current_price = float(current_kline[4])  # 收盘价
        timestamp = datetime.fromtimestamp(int(current_kline[0]) / 1000)

        # 检查现有持仓的止损
        for sym in list(backtest.positions.keys()):
            backtest.check_stop_loss(sym, current_price, timestamp)

        # 如果没有持仓，检查是否有开仓信号
        if symbol not in backtest.positions:
            signal = ema_advanced_strategy.analyze(symbol, recent_klines)

            if signal.signal_type != SignalType.NONE:
                backtest.open_position(
                    symbol=symbol,
                    signal_type=signal.signal_type,
                    entry_price=current_price,
                    timestamp=timestamp,
                    reason=signal.message
                )

    # 平掉所有剩余仓位
    for sym in list(backtest.positions.keys()):
        last_price = float(all_klines[-1][4])
        last_time = datetime.fromtimestamp(int(all_klines[-1][0]) / 1000)
        backtest.close_position(sym, last_price, last_time, "BACKTEST_END")

    # 生成报告
    stats = backtest.get_statistics()

    logger.info(f"\n" + "=" * 60)
    logger.info(f"回测结果")
    logger.info(f"=" * 60)
    logger.info(f"初始资金: {stats['initial_balance']:.2f} USDT")
    logger.info(f"最终资金: {stats['final_balance']:.2f} USDT")
    logger.info(f"总盈亏: {stats['total_profit']:.2f} USDT ({stats['return_percent']:.2f}%)")
    logger.info(f"-" * 60)
    logger.info(f"总交易次数: {stats['total_trades']}")
    logger.info(f"盈利次数: {stats['winning_trades']}")
    logger.info(f"亏损次数: {stats['losing_trades']}")
    logger.info(f"胜率: {stats['win_rate']:.2f}%")
    logger.info(f"-" * 60)
    logger.info(f"平均盈利: {stats['avg_win']:.2f} USDT")
    logger.info(f"平均亏损: {stats['avg_loss']:.2f} USDT")
    logger.info(f"盈亏比: {stats['profit_factor']:.2f}")
    logger.info(f"最大回撤: {stats['max_drawdown']:.2f}%")
    logger.info(f"=" * 60)

    # 导出交易明细
    if backtest.trades:
        df = pd.DataFrame(backtest.trades)
        filename = f"backtest_{symbol}_{days}days_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(filename, index=False)
        logger.info(f"\n交易明细已导出到: {filename}")

    return stats


if __name__ == "__main__":
    # 示例：回测BTCUSDT最近7天的数据
    asyncio.run(run_backtest(
        symbol="BTCUSDT",
        days=7,
        initial_balance=1000.0,
        leverage=10
    ))
