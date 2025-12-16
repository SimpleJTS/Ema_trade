"""
Binance Futures Trading Bot - 主入口
"""
import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.config import settings, config_manager
from app.database import init_db, DatabaseManager
from app.models import TradingPair, SystemConfig
from app.api.routes import router as api_router
from app.services.binance_api import binance_api
from app.services.binance_ws import binance_ws, KlineData
from app.services.strategy import ema_strategy, ema_advanced_strategy, SignalType
from app.services.position_manager import position_manager
from app.services.trailing_stop import trailing_stop_manager
from app.services.stop_loss_guard import stop_loss_guard
from app.services.telegram import telegram_service
from app.services.tg_monitor import oi_monitor
from app.utils.helpers import setup_logging
from app.utils.encryption import decrypt, encryption_manager

# 配置日志
setup_logging("INFO")
logger = logging.getLogger(__name__)


class TradingEngine:
    """交易引擎 - 核心交易逻辑"""

    def __init__(self):
        self._running = False
        self._kline_cache: dict = {}  # {symbol: [klines]}
        self._preloading: set = set()  # 正在预加载K线的交易对集合
        self._amplitude_check_task = None
        self._analysis_count: dict = {}  # {symbol: count} 策略分析计数
        self._log_interval = 10  # 每10次分析输出一次汇总日志
    
    async def on_kline(self, kline: KlineData):
        """处理K线数据回调"""
        symbol = kline.symbol

        # 更新缓存 - 如果缓存为空，先预加载历史K线
        if symbol not in self._kline_cache or len(self._kline_cache[symbol]) == 0:
            # 避免重复预加载
            if symbol in self._preloading:
                return

            self._preloading.add(symbol)
            try:
                # 获取交易对配置以确定interval
                session = await DatabaseManager.get_session()
                try:
                    result = await session.execute(
                        select(TradingPair).where(TradingPair.symbol == symbol)
                    )
                    pair = result.scalar_one_or_none()
                    if pair:
                        try:
                            # 预加载历史K线数据
                            logger.info(f"[{symbol}] 检测到K线缓存为空，正在预加载历史数据...")
                            klines = await binance_api.get_klines(
                                symbol=symbol,
                                interval=pair.strategy_interval,
                                limit=300
                            )
                            self._kline_cache[symbol] = klines
                            logger.info(f"[{symbol}] 成功预加载 {len(klines)} 根K线数据")
                        except Exception as e:
                            logger.error(f"[{symbol}] 预加载K线数据失败: {e}")
                            self._kline_cache[symbol] = []
                    else:
                        self._kline_cache[symbol] = []
                finally:
                    await session.close()
            finally:
                self._preloading.discard(symbol)

        # 只有K线收盘时才处理
        if not kline.is_closed:
            return
        
        # 添加到缓存
        kline_data = [
            kline.open_time, 
            str(kline.open_price),
            str(kline.high_price),
            str(kline.low_price),
            str(kline.close_price),
            str(kline.volume),
            kline.close_time
        ]
        self._kline_cache[symbol].append(kline_data)
        
        # 保持最近300根K线
        if len(self._kline_cache[symbol]) > 300:
            self._kline_cache[symbol] = self._kline_cache[symbol][-300:]
        
        # 检查是否有足够的K线数据
        if len(self._kline_cache[symbol]) < 60:
            return
        
        # 获取交易对配置
        session = await DatabaseManager.get_session()
        try:
            result = await session.execute(
                select(TradingPair).where(
                    TradingPair.symbol == symbol,
                    TradingPair.is_active == True,
                    TradingPair.is_amplitude_disabled == False
                )
            )
            pair = result.scalar_one_or_none()
            if not pair:
                return
            
            # 检查是否已有仓位
            if await position_manager.has_position(symbol):
                return

            # 根据策略类型选择策略
            strategy_type = pair.strategy_type if hasattr(pair, 'strategy_type') else "EMA_BASIC"
            if strategy_type == "EMA_ADVANCED":
                strategy = ema_advanced_strategy
            else:
                strategy = ema_strategy

            # 运行策略
            signal = strategy.analyze(symbol, self._kline_cache[symbol])
            
            if signal.signal_type == SignalType.NONE:
                # 更新分析计数
                if symbol not in self._analysis_count:
                    self._analysis_count[symbol] = 0
                self._analysis_count[symbol] += 1

                # 每N次分析输出一次汇总日志，避免刷屏
                if self._analysis_count[symbol] % self._log_interval == 1:
                    logger.info(f"[{symbol}] 策略分析第{self._analysis_count[symbol]}次: {signal.message} | EMA快={signal.ema_fast:.6f}, EMA慢={signal.ema_slow:.6f}")
                return
            
            logger.info(f"[{symbol}] 检测到交易信号: {signal.signal_type.value}, {signal.message}")
            
            # 计算下单数量
            quantity = await binance_api.calculate_order_quantity(
                symbol=symbol,
                leverage=pair.leverage
            )
            
            if quantity <= 0:
                logger.warning(f"[{symbol}] 计算的下单数量为0，无法开仓")
                return
            
            # 开仓
            side = "LONG" if signal.signal_type == SignalType.LONG else "SHORT"
            await position_manager.open_position(
                symbol=symbol,
                side=side,
                entry_price=signal.price,
                quantity=quantity,
                leverage=pair.leverage,
                stop_loss_percent=pair.stop_loss_percent
            )
            
        except Exception as e:
            logger.error(f"[{symbol}] 交易引擎处理异常: {e}")
        finally:
            await session.close()
    
    async def check_amplitude(self):
        """检查振幅并禁用低振幅交易对"""
        while self._running:
            try:
                await asyncio.sleep(3600)  # 每小时检查一次
                
                session = await DatabaseManager.get_session()
                try:
                    result = await session.execute(
                        select(TradingPair).where(
                            TradingPair.is_active == True,
                            TradingPair.is_amplitude_disabled == False
                        )
                    )
                    pairs = result.scalars().all()
                    
                    for pair in pairs:
                        # 获取K线数据
                        klines = await binance_api.get_klines(
                            symbol=pair.symbol,
                            interval=pair.strategy_interval,
                            limit=settings.AMPLITUDE_CHECK_KLINES
                        )
                        
                        # 计算振幅
                        amplitude = ema_strategy.calculate_amplitude(klines)
                        
                        if amplitude < settings.MIN_AMPLITUDE_PERCENT:
                            # 禁用该交易对
                            pair.is_amplitude_disabled = True
                            await session.commit()
                            
                            # 取消订阅
                            await binance_ws.unsubscribe(pair.symbol)
                            
                            # TG通知
                            msg = (
                                f"⚠️ **振幅禁用**\n"
                                f"交易对: {pair.symbol}\n"
                                f"振幅: {amplitude:.2f}%\n"
                                f"阈值: {settings.MIN_AMPLITUDE_PERCENT}%\n"
                                f"已自动停止交易"
                            )
                            await telegram_service.send_message(msg)
                            logger.info(f"[{pair.symbol}] 因振幅过低({amplitude}%)已禁用")
                
                finally:
                    await session.close()
                    
            except Exception as e:
                logger.error(f"振幅检查异常: {e}")
    
    async def start(self):
        """启动交易引擎"""
        self._running = True
        
        # 注册K线回调
        binance_ws.add_callback(self.on_kline)
        
        # 启动振幅检查任务
        self._amplitude_check_task = asyncio.create_task(self.check_amplitude())
        
        logger.info("交易引擎已启动")
    
    async def stop(self):
        """停止交易引擎"""
        self._running = False
        
        binance_ws.remove_callback(self.on_kline)
        
        if self._amplitude_check_task:
            self._amplitude_check_task.cancel()
            try:
                await self._amplitude_check_task
            except asyncio.CancelledError:
                pass
        
        logger.info("交易引擎已停止")


# 创建交易引擎实例
trading_engine = TradingEngine()


async def load_config_from_db():
    """从数据库加载配置（自动解密加密的配置）"""
    session = await DatabaseManager.get_session()
    try:
        result = await session.execute(select(SystemConfig))
        configs = result.scalars().all()
        
        encrypted_count = 0
        loaded_count = 0
        
        for config in configs:
            value = config.value
            
            # 检查是否是加密的值，如果是则解密
            if value and value.startswith("ENC:"):
                value = decrypt(value)
                encrypted_count += 1
            
            if config.key == "BINANCE_API_KEY" and value:
                settings.BINANCE_API_KEY = value
                loaded_count += 1
            elif config.key == "BINANCE_API_SECRET" and value:
                settings.BINANCE_API_SECRET = value
                loaded_count += 1
            elif config.key == "BINANCE_TESTNET":
                settings.BINANCE_TESTNET = value.lower() == "true" if value else False
            elif config.key == "TG_BOT_TOKEN" and value:
                settings.TG_BOT_TOKEN = value
                loaded_count += 1
            elif config.key == "TG_CHAT_ID" and value:
                settings.TG_CHAT_ID = value
                loaded_count += 1
            elif config.key == "TG_API_ID":
                settings.TG_API_ID = int(value) if value else 0
            elif config.key == "TG_API_HASH" and value:
                settings.TG_API_HASH = value
            elif config.key == "MIN_PRICE_CHANGE_PERCENT" and value:
                try:
                    settings.MIN_PRICE_CHANGE_PERCENT = float(value)
                except ValueError:
                    pass
        
        if loaded_count > 0:
            logger.info(f"已从数据库加载 {loaded_count} 项配置（其中 {encrypted_count} 项已解密）")
        else:
            logger.info("数据库中未找到已保存的配置，请通过Web界面配置API密钥")
    finally:
        await session.close()


async def subscribe_active_pairs():
    """订阅所有活跃的交易对"""
    session = await DatabaseManager.get_session()
    try:
        result = await session.execute(
            select(TradingPair).where(
                TradingPair.is_active == True,
                TradingPair.is_amplitude_disabled == False
            )
        )
        pairs = result.scalars().all()
        
        for pair in pairs:
            await binance_ws.subscribe(pair.symbol, pair.strategy_interval)
            # 预加载K线数据
            try:
                # 高级策略需要至少241根K线 (EMA200 + lookback25 + ADX14 + 2)
                klines = await binance_api.get_klines(
                    symbol=pair.symbol,
                    interval=pair.strategy_interval,
                    limit=300
                )
                trading_engine._kline_cache[pair.symbol] = klines
            except Exception as e:
                logger.error(f"[{pair.symbol}] 预加载K线数据失败: {e}")
        
        logger.info(f"已订阅 {len(pairs)} 个交易对")
    finally:
        await session.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("正在启动 Binance Futures Bot...")
    
    # 初始化数据库
    await init_db()
    
    # 从数据库加载配置
    await load_config_from_db()
    
    # 初始化Telegram
    await telegram_service.initialize()
    
    # 加载持仓
    await position_manager.load_positions()
    
    # 启动WebSocket
    await binance_ws.start()
    
    # 订阅交易对
    await subscribe_active_pairs()
    
    # 启动交易引擎
    await trading_engine.start()
    
    # 启动移动止损管理器
    await trailing_stop_manager.start()
    logger.info("移动止损管理器启动完成")

    # 启动止损订单守护
    try:
        await stop_loss_guard.start()
        logger.info("止损守护服务启动完成")
    except Exception as e:
        logger.error(f"止损守护服务启动失败: {e}")

    # 启动24小时涨跌幅监控（无需TG配置，直接调用币安API）
    await oi_monitor.start(check_interval=300)  # 每5分钟检查一次
    
    # 发送启动通知
    await telegram_service.send_message("🚀 **Binance Futures Bot 已启动**")
    
    logger.info("Bot 启动成功!")
    
    yield
    
    # 关闭服务
    logger.info("正在关闭服务...")

    await stop_loss_guard.stop()
    await trailing_stop_manager.stop()
    await trading_engine.stop()
    await binance_ws.stop()
    await oi_monitor.stop()  # 停止涨跌幅监控
    await binance_api.close()
    
    await telegram_service.send_message("🛑 **Binance Futures Bot 已停止**")
    
    logger.info("Bot 已停止")


# 创建FastAPI应用
app = FastAPI(
    title="Binance Futures Bot",
    description="币安合约交易机器人",
    version="1.0.0",
    lifespan=lifespan
)

# 挂载静态文件
# app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 模板
templates = Jinja2Templates(directory="app/templates")

# 注册API路由
app.include_router(api_router, prefix="/api", tags=["API"])


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """主页"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "websocket": binance_ws.get_status(),
        "positions": len(position_manager.get_all_positions())
    }


def main():
    """主函数"""
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )


if __name__ == "__main__":
    main()
