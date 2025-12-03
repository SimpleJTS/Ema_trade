"""
Telegram服务模块
包含消息推送功能
"""
import logging
from app.config import settings, config_manager

logger = logging.getLogger(__name__)


class TelegramService:
    """Telegram服务 - 消息推送"""
    
    def __init__(self):
        self._bot = None
        self._initialized = False
    
    async def initialize(self):
        """初始化Telegram Bot"""
        if not settings.TG_BOT_TOKEN or not settings.TG_CHAT_ID:
            logger.warning("Telegram Bot Token 或 Chat ID 未配置")
            return False
        
        try:
            from telegram import Bot
            self._bot = Bot(token=settings.TG_BOT_TOKEN)
            self._initialized = True
            logger.info("Telegram Bot 已初始化")
            return True
        except Exception as e:
            logger.error(f"Telegram Bot 初始化失败: {e}")
            return False
    
    async def send_message(self, message: str, parse_mode: str = "Markdown"):
        """发送消息到Telegram"""
        if not self._initialized:
            await self.initialize()
        
        if not self._bot:
            logger.warning("Telegram Bot 未初始化，跳过消息发送")
            return False
        
        try:
            # 转义Markdown特殊字符
            # message = self._escape_markdown(message)
            await self._bot.send_message(
                chat_id=settings.TG_CHAT_ID,
                text=message,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.error(f"发送 Telegram 消息失败: {e}")
            # 尝试不使用parse_mode
            try:
                await self._bot.send_message(
                    chat_id=settings.TG_CHAT_ID,
                    text=message
                )
                return True
            except Exception as e2:
                logger.error(f"发送纯文本消息也失败: {e2}")
                return False
    
    def _escape_markdown(self, text: str) -> str:
        """转义Markdown特殊字符"""
        escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in escape_chars:
            text = text.replace(char, f'\\{char}')
        return text


# 全局实例
telegram_service = TelegramService()


async def on_new_symbol_detected(symbol: str, change_percent: float):
    """当检测到新的符合条件的交易对时的处理函数"""
    from app.database import DatabaseManager
    from app.models import TradingPair
    from sqlalchemy import select
    from app.services.leverage_manager import leverage_manager
    from app.services.binance_api import binance_api
    from app.utils.indicators import technical_indicators
    from datetime import datetime

    logger.info(f"[{symbol}] 回调函数被调用，变化: {change_percent}%")

    session = await DatabaseManager.get_session()
    try:
        # 检查是否已存在
        result = await session.execute(
            select(TradingPair).where(TradingPair.symbol == symbol)
        )
        existing = result.scalar_one_or_none()

        if existing:
            logger.info(f"[{symbol}] 交易对已存在（is_active={existing.is_active}），跳过添加")
            return

        logger.info(f"[{symbol}] 交易对不存在，准备添加...")

        # 获取K线数据用于计算波动率和杠杆
        klines = []
        volatility = None
        try:
            klines = await binance_api.get_klines(symbol, interval="1m", limit=250)
            if klines and len(klines) >= 200:
                # 计算ATR年化波动率
                volatility = technical_indicators.calculate_atr_volatility(klines, period=14)
                logger.info(f"[{symbol}] ATR年化波动率: {volatility}%")
        except Exception as e:
            logger.warning(f"[{symbol}] 获取K线数据失败: {e}")

        # 使用杠杆管理器计算动态杠杆
        leverage_data = await leverage_manager.calculate_leverage(
            symbol=symbol,
            klines=klines if klines else None,
            volatility=volatility
        )

        final_leverage = leverage_data["leverage"]
        market_cap_usd = leverage_data["market_cap_usd"]
        market_cap_tier = leverage_data["market_cap_tier"]
        tier_name = leverage_data["tier_name"]
        base_leverage = leverage_data["base_leverage"]

        logger.info(
            f"[{symbol}] 杠杆计算完成: 市值={tier_name}(${market_cap_usd:,.0f}), "
            f"基础杠杆={base_leverage}x, 最终杠杆={final_leverage}x, "
            f"波动率={volatility}%, 调整原因: {leverage_data['adjustment_reason']}"
        )

        # 添加新交易对（默认使用高级策略）
        new_pair = TradingPair(
            symbol=symbol,
            leverage=final_leverage,
            strategy_interval=settings.DEFAULT_STRATEGY_INTERVAL,
            strategy_type="EMA_ADVANCED",  # 默认使用高级策略（EMA9/72/200）
            stop_loss_percent=settings.DEFAULT_STOP_LOSS_PERCENT,
            is_active=True,
            market_cap_usd=market_cap_usd,
            market_cap_tier=market_cap_tier,
            base_leverage=base_leverage,
            current_leverage=final_leverage,
            atr_volatility=volatility,
            last_volatility_check=datetime.utcnow() if volatility else None
        )
        session.add(new_pair)
        await session.commit()

        logger.info(f"[{symbol}] 已成功添加新交易对到数据库")

        # 通知配置变更
        await config_manager.notify_observers("trading_pair_added", {
            "symbol": symbol,
            "interval": settings.DEFAULT_STRATEGY_INTERVAL
        })
        logger.info(f"[{symbol}] 已通知观察者配置变更")

        # TG通知
        direction = "📈 涨幅" if change_percent > 0 else "📉 跌幅"
        msg = (
            f"🆕 **自动添加交易对**\n"
            f"交易对: {symbol}\n"
            f"24H变化: {direction} {abs(change_percent):.2f}%\n"
            f"市值层级: {tier_name}\n"
            f"市值: ${market_cap_usd:,.0f}\n"
            f"杠杆: {final_leverage}x (基础{base_leverage}x)\n"
            f"波动率: {volatility:.2f}% (ATR年化)\n"
            f"策略: EMA高级策略\n"
            f"来源: 币安24H涨跌幅监控"
        )
        await telegram_service.send_message(msg)

    except Exception as e:
        logger.error(f"[{symbol}] 添加新交易对失败: {e}", exc_info=True)
        await session.rollback()
    finally:
        await session.close()
