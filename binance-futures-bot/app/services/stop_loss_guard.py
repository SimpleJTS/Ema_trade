"""
止损订单守护模块
基于实时持仓数据，计算并调整止盈止损订单
"""
import asyncio
import json
import logging
from typing import Optional, Dict, List
from decimal import Decimal

from app.services.binance_api import binance_api
from app.services.position_manager import position_manager
from app.services.telegram import telegram_service
from app.database import DatabaseManager
from app.models import SystemConfig
from sqlalchemy import select

logger = logging.getLogger(__name__)


# 默认止损配置
DEFAULT_TRAILING_CONFIG = {
    "level_1": {"profit_min": 1.8, "profit_max": 2.5, "lock_profit": 0.1, "trailing_enabled": False, "trailing_percent": 0},
    "level_2": {"profit_min": 2.5, "profit_max": 4.0, "lock_profit": 1.9, "trailing_enabled": False, "trailing_percent": 0},
    "level_3": {"profit_min": 4.0, "profit_max": None, "lock_profit": 1.9, "trailing_enabled": True, "trailing_percent": 1.5, "partial_close_percent": 50.0}
}


class StopLossGuard:
    """止损订单守护器
    
    简化逻辑：
    1. 调用API获取实时持仓
    2. 解析持仓数据
    3. 执行止盈止损策略计算点位
    4. 下单调整止盈止损
    """

    def __init__(self):
        self._running = False
        self._check_task: Optional[asyncio.Task] = None
        self._check_interval = 30  # 检查间隔(秒)
        self._config: Dict = DEFAULT_TRAILING_CONFIG.copy()
        self._highest_prices: Dict[str, float] = {}  # 记录最高价(做多)或最低价(做空)

    async def load_config(self):
        """从数据库加载止损配置"""
        session = await DatabaseManager.get_session()
        try:
            result = await session.execute(
                select(SystemConfig).where(SystemConfig.key == "TRAILING_STOP_CONFIG")
            )
            config = result.scalar_one_or_none()
            
            if config and config.value:
                try:
                    self._config = json.loads(config.value)
                    logger.info(f"已加载移动止损配置: {self._config}")
                except json.JSONDecodeError:
                    logger.warning("移动止损配置解析失败，使用默认配置")
                    self._config = DEFAULT_TRAILING_CONFIG.copy()
            else:
                logger.info("未找到移动止损配置，使用默认配置")
                self._config = DEFAULT_TRAILING_CONFIG.copy()
        except Exception as e:
            logger.error(f"加载移动止损配置失败: {e}")
            self._config = DEFAULT_TRAILING_CONFIG.copy()
        finally:
            await session.close()

    def _parse_position_data(self, position_data: dict) -> dict:
        """解析持仓数据
        
        Args:
            position_data: 币安API返回的持仓数据
            
        Returns:
            dict: {
                'symbol': str,
                'side': 'LONG' | 'SHORT',
                'entry_price': float,
                'quantity': float,
                'leverage': int,
                'unrealized_pnl': float,
                'mark_price': float
            }
        """
        symbol = position_data.get("symbol", "")
        position_amt = float(position_data.get("positionAmt", 0))
        entry_price = float(position_data.get("entryPrice", 0))
        leverage = int(float(position_data.get("leverage", 1)))
        unrealized_pnl = float(position_data.get("unRealizedProfit", 0))
        mark_price = float(position_data.get("markPrice", 0))
        
        # 判断方向
        side = "LONG" if position_amt > 0 else "SHORT"
        quantity = abs(position_amt)
        
        return {
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'quantity': quantity,
            'leverage': leverage,
            'unrealized_pnl': unrealized_pnl,
            'mark_price': mark_price
        }

    def _calculate_profit_percent(self, entry_price: float, current_price: float, side: str) -> float:
        """计算盈利百分比(基于价格变动，不含杠杆)"""
        if side == "LONG":
            profit = ((current_price - entry_price) / entry_price) * 100
        else:
            profit = ((entry_price - current_price) / entry_price) * 100
        return profit

    def _calculate_initial_stop_loss_price(self, parsed_pos: dict) -> float:
        """计算初始止损价格（基于入场价的一定百分比，默认-2%）
        
        Args:
            parsed_pos: 解析后的持仓数据
            
        Returns:
            初始止损价格
        """
        symbol = parsed_pos['symbol']
        side = parsed_pos['side']
        entry_price = parsed_pos['entry_price']
        
        # 默认初始止损为入场价的-2%（做多时止损低于入场价，做空时止损高于入场价）
        initial_stop_percent = -2.0
        
        if side == "LONG":
            # 做多：止损价 = 入场价 * (1 - 2%)
            initial_stop_price = entry_price * (1 + initial_stop_percent / 100)
        else:
            # 做空：止损价 = 入场价 * (1 + 2%)
            initial_stop_price = entry_price * (1 - initial_stop_percent / 100)
        
        logger.info(f"[{symbol}] 计算初始止损价: 入场价={entry_price}, 止损价={initial_stop_price} (基于{abs(initial_stop_percent)}%止损)")
        return initial_stop_price

    def _calculate_stop_loss_price(self, parsed_pos: dict, current_price: float, current_stop_price: Optional[float] = None) -> Optional[float]:
        """计算止损价格
        
        Args:
            parsed_pos: 解析后的持仓数据
            current_price: 当前价格
            current_stop_price: 当前止损价格（可选，用于追踪止损比较）
            
        Returns:
            止损价格，如果不需要调整则返回None
        """
        symbol = parsed_pos['symbol']
        side = parsed_pos['side']
        entry_price = parsed_pos['entry_price']
        profit_percent = self._calculate_profit_percent(entry_price, current_price, side)
        
        # 更新最高/最低价格
        if side == "LONG":
            if symbol not in self._highest_prices or current_price > self._highest_prices[symbol]:
                self._highest_prices[symbol] = current_price
            highest = self._highest_prices[symbol]
        else:
            if symbol not in self._highest_prices or current_price < self._highest_prices[symbol]:
                self._highest_prices[symbol] = current_price
            highest = self._highest_prices[symbol]
        
        # 从配置中读取各级别参数
        level_1_cfg = self._config.get("level_1", DEFAULT_TRAILING_CONFIG["level_1"])
        level_2_cfg = self._config.get("level_2", DEFAULT_TRAILING_CONFIG["level_2"])
        level_3_cfg = self._config.get("level_3", DEFAULT_TRAILING_CONFIG["level_3"])
        
        l1_min = level_1_cfg.get("profit_min", 1.8)
        l1_max = level_1_cfg.get("profit_max", 2.5)
        l1_lock = level_1_cfg.get("lock_profit", 0.1)
        
        l2_min = level_2_cfg.get("profit_min", 2.5)
        l2_max = level_2_cfg.get("profit_max", 4.0)
        l2_lock = level_2_cfg.get("lock_profit", 1.9)
        
        l3_min = level_3_cfg.get("profit_min", 4.0)
        l3_lock = level_3_cfg.get("lock_profit", 1.9)
        l3_trailing = level_3_cfg.get("trailing_enabled", True)
        l3_trailing_pct = level_3_cfg.get("trailing_percent", 1.5)
        
        new_stop_price = None
        
        # 级别1: 保本止损
        if l1_min <= profit_percent < (l1_max or float('inf')):
            if l1_lock == 0:
                new_stop_price = entry_price
            else:
                if side == "LONG":
                    new_stop_price = entry_price * (1 + l1_lock / 100)
                else:
                    new_stop_price = entry_price * (1 - l1_lock / 100)
            logger.info(f"[{symbol}] 触发级别1: 价格变动{profit_percent:.2f}%，止损设为 {new_stop_price}")
        
        # 级别2: 锁定利润
        elif l2_min <= profit_percent < (l2_max or float('inf')):
            if side == "LONG":
                new_stop_price = entry_price * (1 + l2_lock / 100)
            else:
                new_stop_price = entry_price * (1 - l2_lock / 100)
            logger.info(f"[{symbol}] 触发级别2: 价格变动{profit_percent:.2f}%，锁定{l2_lock}%利润，止损价 {new_stop_price}")
        
        # 级别3: 追踪止损
        elif profit_percent >= l3_min:
            if l3_trailing:
                # 追踪止损逻辑
                if side == "LONG":
                    # 做多：从最高价回撤trailing_percent
                    trailing_stop = highest * (1 - l3_trailing_pct / 100)
                    # 基础止损价格
                    base_stop = entry_price * (1 + l3_lock / 100)
                    # 取两者中的较高者
                    calculated_stop = max(trailing_stop, base_stop)
                    # 如果当前有止损价格，新止损必须更高才更新
                    if current_stop_price is None or calculated_stop > current_stop_price:
                        new_stop_price = calculated_stop
                        logger.info(f"[{symbol}] 触发级别3追踪止损: 价格变动{profit_percent:.2f}%，止损价 {new_stop_price}")
                else:
                    # 做空：从最低价反弹trailing_percent
                    trailing_stop = highest * (1 + l3_trailing_pct / 100)
                    # 基础止损价格
                    base_stop = entry_price * (1 - l3_lock / 100)
                    # 取两者中的较低者
                    calculated_stop = min(trailing_stop, base_stop)
                    # 如果当前有止损价格，新止损必须更低才更新
                    if current_stop_price is None or calculated_stop < current_stop_price:
                        new_stop_price = calculated_stop
                        logger.info(f"[{symbol}] 触发级别3追踪止损: 价格变动{profit_percent:.2f}%，止损价 {new_stop_price}")
            else:
                # 不追踪，只锁定利润
                if side == "LONG":
                    new_stop_price = entry_price * (1 + l3_lock / 100)
                else:
                    new_stop_price = entry_price * (1 - l3_lock / 100)
                logger.info(f"[{symbol}] 触发级别3: 价格变动{profit_percent:.2f}%，锁定{l3_lock}%利润，止损价 {new_stop_price}")
        
        return new_stop_price

    async def _adjust_stop_loss(self, symbol: str, side: str, quantity: float, stop_price: float):
        """调整止损订单
        
        Args:
            symbol: 交易对
            side: LONG/SHORT
            quantity: 数量
            stop_price: 止损价格
        """
        try:
            # 获取精度信息
            precision_info = await binance_api.get_symbol_precision(symbol)
            formatted_price = binance_api.format_price(stop_price, precision_info)
            formatted_qty = binance_api.format_quantity(quantity, precision_info)
            
            # 取消所有现有止损单（算法订单使用algoId，普通订单使用orderId）
            try:
                open_orders = await binance_api.get_open_orders(symbol)
                for order in open_orders:
                    try:
                        # 算法订单使用algoId，普通订单使用orderId
                        order_id = order.get("algoId") or order.get("orderId")
                        if order.get("algoId"):
                            await binance_api.cancel_algo_order(symbol, str(order_id))
                        else:
                            await binance_api.cancel_order(symbol, str(order_id))
                        logger.info(f"[{symbol}] 已取消原止损单: {order_id}")
                    except Exception as e:
                        logger.warning(f"[{symbol}] 取消止损单失败: {e}")
            except Exception as e:
                logger.warning(f"[{symbol}] 获取挂单失败: {e}")
            
            # 下新的止损单
            stop_side = "SELL" if side == "LONG" else "BUY"
            stop_order = await binance_api.place_stop_loss_order(
                symbol=symbol,
                side=stop_side,
                quantity=float(formatted_qty),
                stop_price=float(formatted_price)
            )
            
            # 算法订单返回algoId，普通订单返回orderId
            order_id = str(stop_order.get("algoId") or stop_order.get("orderId", ""))
            logger.info(f"[{symbol}] 已设置止损单: 价格={formatted_price}, 数量={formatted_qty}, 订单ID={order_id}")
            
            # TG通知
            await telegram_service.send_message(
                f"🔔 **止损调整**\n"
                f"交易对: {symbol}\n"
                f"方向: {'做多' if side == 'LONG' else '做空'}\n"
                f"止损价: {formatted_price}\n"
                f"数量: {formatted_qty}"
            )
            
            return order_id
            
        except Exception as e:
            logger.error(f"[{symbol}] 调整止损失败: {e}")
            raise

    async def _process_position(self, position_data: dict):
        """处理单个持仓
        
        Args:
            position_data: 币安API返回的持仓数据
        """
        try:
            # 解析持仓数据
            parsed_pos = self._parse_position_data(position_data)
            symbol = parsed_pos['symbol']
            current_price = parsed_pos['mark_price']

            # 获取当前止损单价格（如果有）
            current_stop_price = None
            existing_stop_orders_count = 0
            try:
                open_orders = await binance_api.get_open_orders(symbol)
                logger.info(f"[{symbol}] 查询到{len(open_orders) if open_orders else 0}个挂单")
                if open_orders:
                    for o in open_orders:
                        order_id = o.get('algoId') or o.get('orderId', 'N/A')
                        stop_price = o.get('stopPrice') or o.get('triggerPrice', 'N/A')
                        order_type = o.get('orderType') or o.get('type', 'N/A')
                        logger.info(f"[{symbol}] 挂单详情: type={order_type}, ID={order_id}, stopPrice={stop_price}")
                # 检查所有类型的止损单（算法订单和普通订单）
                # 算法订单使用orderType，普通订单使用type
                stop_orders = [o for o in open_orders if (o.get("type") or o.get("orderType")) in ("STOP_MARKET", "STOP", "STOP_LOSS", "STOP_LOSS_LIMIT")]
                existing_stop_orders_count = len(stop_orders)
                if stop_orders:
                    # 算法订单使用triggerPrice，普通订单使用stopPrice
                    current_stop_price = float(stop_orders[0].get("stopPrice") or stop_orders[0].get("triggerPrice", 0))
                    logger.info(f"[{symbol}] 检测到{len(stop_orders)}个止损单, 当前止损价={current_stop_price}")
            except Exception as e:
                logger.warning(f"[{symbol}] 检查当前止损单失败: {e}")

            # 如果已经有止损单，根据动态策略调整
            if existing_stop_orders_count > 0 and current_stop_price is not None:
                # 计算止损价格
                new_stop_price = self._calculate_stop_loss_price(parsed_pos, current_price, current_stop_price)

                if new_stop_price is None:
                    logger.debug(f"[{symbol}] 当前盈利未达到调整止损的条件，保持现有止损单")
                    return

                # 获取精度信息用于比较
                precision_info = await binance_api.get_symbol_precision(symbol)
                formatted_current = binance_api.format_price(current_stop_price, precision_info)
                formatted_new = binance_api.format_price(new_stop_price, precision_info)

                # 如果新止损价格与当前相同，不需要调整
                if formatted_current == formatted_new:
                    logger.debug(f"[{symbol}] 止损价格未变化({formatted_current})，跳过调整")
                    return

                # 检查是否需要调整（做多时新止损应该更高，做空时新止损应该更低）
                if parsed_pos['side'] == "LONG":
                    if new_stop_price <= current_stop_price:
                        logger.debug(f"[{symbol}] 新止损价格({new_stop_price})不高于当前止损({current_stop_price})，跳过调整")
                        return
                else:
                    if new_stop_price >= current_stop_price:
                        logger.debug(f"[{symbol}] 新止损价格({new_stop_price})不低于当前止损({current_stop_price})，跳过调整")
                        return

                # 需要调整止损
                logger.info(f"[{symbol}] 需要调整止损: {current_stop_price} -> {new_stop_price}")
                await self._adjust_stop_loss(
                    symbol=symbol,
                    side=parsed_pos['side'],
                    quantity=parsed_pos['quantity'],
                    stop_price=new_stop_price
                )
            else:
                # 没有止损单，必须创建一个初始止损单
                # 优先使用动态策略计算的止损价格，如果未达到条件则使用初始止损价格
                new_stop_price = self._calculate_stop_loss_price(parsed_pos, current_price, None)
                if new_stop_price is None:
                    # 如果动态策略未触发，使用初始止损价格（基于入场价的-2%）
                    new_stop_price = self._calculate_initial_stop_loss_price(parsed_pos)
                    logger.info(f"[{symbol}] 未检测到止损单，创建初始止损: {new_stop_price}")
                else:
                    logger.info(f"[{symbol}] 未检测到止损单，创建动态止损: {new_stop_price}")
                
                await self._adjust_stop_loss(
                    symbol=symbol,
                    side=parsed_pos['side'],
                    quantity=parsed_pos['quantity'],
                    stop_price=new_stop_price
                )
            
        except Exception as e:
            logger.error(f"处理持仓失败: {e}")

    async def _cleanup_orphan_orders(self, positions: List[dict]):
        """清理无对应仓位的挂单
        
        Args:
            positions: 当前持仓列表
        """
        try:
            # 获取所有持仓的交易对
            position_symbols = {p.get("symbol") for p in positions}
            
            # 获取所有挂单
            all_orders = await binance_api.get_open_orders()
            if not all_orders:
                return
            
            # 找出止损单（算法订单使用orderType，普通订单使用type）
            stop_orders = [o for o in all_orders if (o.get("type") or o.get("orderType")) in ("STOP_MARKET", "STOP", "STOP_LOSS", "STOP_LOSS_LIMIT")]
            
            for order in stop_orders:
                order_symbol = order.get("symbol")
                # 如果挂单对应的币种没有持仓，则取消该挂单
                if order_symbol not in position_symbols:
                    order_id = order.get("algoId") or order.get("orderId")
                    try:
                        if order.get("algoId"):
                            await binance_api.cancel_algo_order(order_symbol, str(order_id))
                        else:
                            await binance_api.cancel_order(order_symbol, str(order_id))
                        logger.info(f"[{order_symbol}] 已清理无对应仓位的止损挂单: {order_id}")
                    except Exception as e:
                        logger.warning(f"[{order_symbol}] 清理挂单失败: {e}")
        except Exception as e:
            logger.error(f"清理无对应仓位的挂单失败: {e}")

    async def _check_loop(self):
        """止损守护检查循环"""
        logger.info("止损守护检查循环已启动")
        check_count = 0

        while self._running:
            try:
                # 1. 调用API获取实时持仓
                positions = await binance_api.get_position()
                check_count += 1

                if positions:
                    logger.info(f"[止损守护] 第{check_count}次检查，共{len(positions)}个持仓")

                    # 2. 清理无对应仓位的挂单
                    await self._cleanup_orphan_orders(positions)

                    # 3. 处理每个持仓
                    for position_data in positions:
                        await self._process_position(position_data)
                        # 每个持仓间隔1秒，避免API限频
                        await asyncio.sleep(1)
                else:
                    # 每10次检查输出一次"无持仓"日志，避免刷屏
                    if check_count % 10 == 1:
                        logger.info(f"[止损守护] 第{check_count}次检查，当前无持仓")
                    # 清空最高价记录
                    self._highest_prices.clear()
                    # 清理所有挂单（因为没有持仓了）
                    try:
                        all_orders = await binance_api.get_open_orders()
                        stop_orders = [o for o in all_orders if (o.get("type") or o.get("orderType")) in ("STOP_MARKET", "STOP", "STOP_LOSS", "STOP_LOSS_LIMIT")]
                        for order in stop_orders:
                            order_symbol = order.get("symbol")
                            order_id = order.get("algoId") or order.get("orderId")
                            try:
                                if order.get("algoId"):
                                    await binance_api.cancel_algo_order(order_symbol, str(order_id))
                                else:
                                    await binance_api.cancel_order(order_symbol, str(order_id))
                                logger.info(f"[{order_symbol}] 已清理无对应仓位的止损挂单: {order_id}")
                            except Exception as e:
                                logger.warning(f"[{order_symbol}] 清理挂单失败: {e}")
                    except Exception as e:
                        logger.warning(f"清理挂单失败: {e}")

                await asyncio.sleep(self._check_interval)

            except Exception as e:
                logger.error(f"止损守护检查循环错误: {e}")
                await asyncio.sleep(self._check_interval)

    async def start(self):
        """启动止损守护"""
        if self._running:
            return

        # 加载配置
        await self.load_config()

        self._running = True
        self._check_task = asyncio.create_task(self._check_loop())
        logger.info(f"止损守护已启动，检查间隔: {self._check_interval}秒")

    async def stop(self):
        """停止止损守护"""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("止损守护已停止")

    def set_check_interval(self, interval: int):
        """设置检查间隔"""
        self._check_interval = max(10, interval)  # 最小10秒
        logger.info(f"止损守护检查间隔已设置为: {self._check_interval}秒")


# 全局实例
stop_loss_guard = StopLossGuard()
