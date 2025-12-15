"""
止损订单守护模块
定时检查止损挂单情况，确保每个持仓都有正确的止损订单
"""
import asyncio
import logging
from typing import Optional, Dict, List
from decimal import Decimal

from app.services.binance_api import binance_api
from app.services.position_manager import position_manager
from app.services.telegram import telegram_service

logger = logging.getLogger(__name__)


class StopLossGuard:
    """止损订单守护器

    定时检查所有持仓的止损订单状态：
    1. 如果持仓没有止损订单，则新增
    2. 如果止损订单数量与持仓不匹配，则重新下单
    3. 如果止损订单价格与预期不一致，则重新下单
    """

    def __init__(self):
        self._running = False
        self._check_task: Optional[asyncio.Task] = None
        self._check_interval = 30  # 检查间隔(秒)
        self._last_check_results: Dict[str, dict] = {}  # 记录上次检查结果，避免重复告警

    async def _get_stop_orders_for_symbol(self, symbol: str) -> List[dict]:
        """获取指定交易对的止损挂单"""
        try:
            open_orders = await binance_api.get_open_orders(symbol)
            # 筛选止损单 (STOP_MARKET 类型)
            stop_orders = [
                order for order in open_orders
                if order.get("type") == "STOP_MARKET"
            ]
            return stop_orders
        except Exception as e:
            logger.error(f"[{symbol}] 获取止损挂单失败: {e}")
            return []

    async def _check_and_fix_stop_loss(self, position) -> dict:
        """检查并修复止损订单

        Returns:
            dict: 检查结果 {
                'status': 'ok' | 'fixed' | 'error',
                'message': str,
                'action': str | None
            }
        """
        symbol = position.symbol
        result = {'status': 'ok', 'message': '', 'action': None}

        try:
            # 获取当前止损挂单
            stop_orders = await self._get_stop_orders_for_symbol(symbol)

            # 获取精度信息
            precision_info = await binance_api.get_symbol_precision(symbol)

            # 预期的止损方向和价格
            expected_side = "SELL" if position.side == "LONG" else "BUY"
            expected_stop_price = position.stop_loss_price
            expected_quantity = position.quantity

            # 格式化预期值用于比较
            formatted_expected_price = binance_api.format_price(expected_stop_price, precision_info)
            formatted_expected_qty = binance_api.format_quantity(expected_quantity, precision_info)

            # 没有止损单
            if not stop_orders:
                logger.warning(f"[{symbol}] 未找到止损订单，正在补挂...")
                result['action'] = 'create'

                # 新建止损单
                stop_order = await binance_api.place_stop_loss_order(
                    symbol=symbol,
                    side=expected_side,
                    quantity=float(formatted_expected_qty),
                    stop_price=float(formatted_expected_price)
                )

                # 更新数据库中的止损单ID
                new_order_id = str(stop_order.get("orderId", ""))
                await self._update_stop_order_id(position, new_order_id)

                result['status'] = 'fixed'
                result['message'] = f"已补挂止损单: 价格={formatted_expected_price}, 数量={formatted_expected_qty}"

                # TG通知
                await telegram_service.send_message(
                    f"⚠️ **止损守护告警**\n"
                    f"交易对: {symbol}\n"
                    f"问题: 未找到止损订单\n"
                    f"处理: 已补挂止损单\n"
                    f"止损价: {formatted_expected_price}\n"
                    f"数量: {formatted_expected_qty}"
                )

                logger.info(f"[{symbol}] 止损单已补挂: {result['message']}")
                return result

            # 检查止损单是否正确
            valid_stop_order = None
            for order in stop_orders:
                order_side = order.get("side")
                order_price = order.get("stopPrice", "0")
                order_qty = order.get("origQty", "0")

                # 格式化订单价格和数量用于比较
                formatted_order_price = binance_api.format_price(float(order_price), precision_info)
                formatted_order_qty = binance_api.format_quantity(float(order_qty), precision_info)

                # 检查方向
                if order_side != expected_side:
                    continue

                # 检查价格是否匹配（允许格式化后相等）
                price_match = formatted_order_price == formatted_expected_price

                # 检查数量是否匹配（允许一定误差）
                qty_diff_ratio = abs(float(formatted_order_qty) - float(formatted_expected_qty)) / float(formatted_expected_qty) if float(formatted_expected_qty) > 0 else 0
                qty_match = qty_diff_ratio < 0.01  # 1%误差范围内

                if price_match and qty_match:
                    valid_stop_order = order
                    break

            if valid_stop_order:
                # 止损单正确
                result['status'] = 'ok'
                result['message'] = f"止损单正常: 价格={formatted_expected_price}, 数量={formatted_expected_qty}"
                return result

            # 止损单存在但不正确，需要修复
            logger.warning(f"[{symbol}] 止损订单异常，正在修复...")

            # 记录问题详情
            issues = []
            for order in stop_orders:
                order_price = order.get("stopPrice", "0")
                order_qty = order.get("origQty", "0")
                order_side = order.get("side")
                order_id = order.get("orderId")

                if order_side != expected_side:
                    issues.append(f"订单{order_id}方向错误: {order_side} (应为{expected_side})")
                else:
                    formatted_order_price = binance_api.format_price(float(order_price), precision_info)
                    formatted_order_qty = binance_api.format_quantity(float(order_qty), precision_info)

                    if formatted_order_price != formatted_expected_price:
                        issues.append(f"订单{order_id}价格不匹配: {formatted_order_price} (应为{formatted_expected_price})")

                    qty_diff_ratio = abs(float(formatted_order_qty) - float(formatted_expected_qty)) / float(formatted_expected_qty) if float(formatted_expected_qty) > 0 else 0
                    if qty_diff_ratio >= 0.01:
                        issues.append(f"订单{order_id}数量不匹配: {formatted_order_qty} (应为{formatted_expected_qty})")

            result['action'] = 'fix'

            # 取消所有现有止损单
            for order in stop_orders:
                try:
                    await binance_api.cancel_order(symbol, str(order.get("orderId")))
                    logger.info(f"[{symbol}] 已取消异常止损单: {order.get('orderId')}")
                except Exception as e:
                    logger.error(f"[{symbol}] 取消止损单失败: {e}")

            # 重新下止损单
            stop_order = await binance_api.place_stop_loss_order(
                symbol=symbol,
                side=expected_side,
                quantity=float(formatted_expected_qty),
                stop_price=float(formatted_expected_price)
            )

            # 更新数据库中的止损单ID
            new_order_id = str(stop_order.get("orderId", ""))
            await self._update_stop_order_id(position, new_order_id)

            result['status'] = 'fixed'
            result['message'] = f"已修复止损单: {'; '.join(issues)}"

            # TG通知
            await telegram_service.send_message(
                f"⚠️ **止损守护告警**\n"
                f"交易对: {symbol}\n"
                f"问题: {'; '.join(issues)}\n"
                f"处理: 已重新下止损单\n"
                f"新止损价: {formatted_expected_price}\n"
                f"新数量: {formatted_expected_qty}"
            )

            logger.info(f"[{symbol}] 止损单已修复: {result['message']}")
            return result

        except Exception as e:
            result['status'] = 'error'
            result['message'] = str(e)
            logger.error(f"[{symbol}] 止损守护检查失败: {e}")

            # 只有首次出错才告警，避免重复
            last_result = self._last_check_results.get(symbol)
            if not last_result or last_result.get('status') != 'error':
                await telegram_service.send_message(
                    f"❌ **止损守护错误**\n"
                    f"交易对: {symbol}\n"
                    f"错误: {str(e)}"
                )

            return result

    async def _update_stop_order_id(self, position, new_order_id: str):
        """更新数据库中的止损单ID"""
        from sqlalchemy import update
        from app.database import DatabaseManager
        from app.models import Position

        session = await DatabaseManager.get_session()
        try:
            await session.execute(
                update(Position)
                .where(Position.id == position.id)
                .values(stop_loss_order_id=new_order_id)
            )
            await session.commit()

            # 更新缓存
            position.stop_loss_order_id = new_order_id

        except Exception as e:
            logger.error(f"[{position.symbol}] 更新止损单ID失败: {e}")
            await session.rollback()
        finally:
            await session.close()

    async def _check_loop(self):
        """止损守护检查循环"""
        while self._running:
            try:
                positions = position_manager.get_all_positions()

                for position in positions:
                    if position.status != "OPEN":
                        continue

                    result = await self._check_and_fix_stop_loss(position)
                    self._last_check_results[position.symbol] = result

                    if result['status'] == 'fixed':
                        logger.info(f"[{position.symbol}] 止损守护: {result['message']}")

                    # 每个检查间隔1秒，避免API限频
                    await asyncio.sleep(1)

                await asyncio.sleep(self._check_interval)

            except Exception as e:
                logger.error(f"止损守护检查循环错误: {e}")
                await asyncio.sleep(self._check_interval)

    async def check_all_positions(self) -> Dict[str, dict]:
        """手动检查所有持仓的止损状态

        Returns:
            dict: 每个交易对的检查结果
        """
        results = {}
        positions = position_manager.get_all_positions()

        for position in positions:
            if position.status != "OPEN":
                continue

            result = await self._check_and_fix_stop_loss(position)
            results[position.symbol] = result
            self._last_check_results[position.symbol] = result

        return results

    async def start(self):
        """启动止损守护"""
        if self._running:
            return

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
