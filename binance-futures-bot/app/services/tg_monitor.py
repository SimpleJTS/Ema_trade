"""
24小时涨跌幅监控模块
定时从币安API获取24小时涨跌幅超过阈值的币种并自动添加交易对
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Set

logger = logging.getLogger(__name__)


class PriceChangeMonitor:
    """24小时涨跌幅监控器
    
    定时调用币安API获取24小时价格变化统计，
    当价格变化绝对值超过阈值时自动添加交易对
    """
    
    def __init__(self):
        self._running = False
        self._task = None
        self._checked_symbols: Set[str] = set()  # 已处理过的symbol，避免重复通知
        self._check_interval = 300  # 默认5分钟检查一次
    
    def _get_settings(self):
        """延迟导入配置，避免循环导入"""
        from app.config import settings
        return settings
    
    def _get_binance_api(self):
        """延迟导入币安API，避免循环导入"""
        from app.services.binance_api import binance_api
        return binance_api
    
    async def _process_high_change_symbols(self, symbols: List[Dict]):
        """处理涨跌幅超阈值的币种"""
        from app.services.telegram import on_new_symbol_detected
        
        settings = self._get_settings()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for symbol_data in symbols:
            symbol = symbol_data["symbol"]
            change_percent = symbol_data["priceChangePercent"]
            
            # 检查是否已处理过（本次运行周期内）
            if symbol in self._checked_symbols:
                continue
            
            direction = "涨幅" if change_percent > 0 else "跌幅"
            logger.info(f"[{now}] [{symbol}] 检测到{direction} {abs(change_percent):.2f}% >= 阈值 {settings.MIN_PRICE_CHANGE_PERCENT}%")
            
            try:
                # 调用回调函数添加交易对
                await on_new_symbol_detected(symbol, change_percent)
                self._checked_symbols.add(symbol)
            except Exception as e:
                logger.error(f"[{symbol}] 添加交易对失败: {e}")
    
    async def _check_loop(self):
        """定时检查循环"""
        settings = self._get_settings()
        binance_api = self._get_binance_api()
        
        logger.info(f"【涨跌幅监控】已启动，检查间隔: {self._check_interval}秒")
        logger.info(f"规则: 24小时涨跌幅绝对值 >= {settings.MIN_PRICE_CHANGE_PERCENT}% 自动添加交易对")
        
        # 首次启动立即检查一次
        await self._do_check()
        
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)
                
                if not self._running:
                    break
                
                await self._do_check()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"涨跌幅监控检查异常: {e}", exc_info=True)
                await asyncio.sleep(60)  # 出错后等待1分钟再重试
    
    async def _do_check(self):
        """执行一次检查"""
        settings = self._get_settings()
        binance_api = self._get_binance_api()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[{now}] 正在检查24小时涨跌幅...")
        
        try:
            # 获取涨跌幅超阈值的币种
            high_change_symbols = await binance_api.get_high_change_symbols(
                min_change_percent=settings.MIN_PRICE_CHANGE_PERCENT
            )
            
            if high_change_symbols:
                # 分离涨幅和跌幅
                gainers = [s for s in high_change_symbols if s["priceChangePercent"] > 0]
                losers = [s for s in high_change_symbols if s["priceChangePercent"] < 0]
                
                logger.info(f"[{now}] 发现 {len(gainers)} 个涨幅 >= {settings.MIN_PRICE_CHANGE_PERCENT}%，"
                           f"{len(losers)} 个跌幅 >= {settings.MIN_PRICE_CHANGE_PERCENT}%")
                
                # 处理这些币种
                await self._process_high_change_symbols(high_change_symbols)
            else:
                logger.info(f"[{now}] 当前没有涨跌幅绝对值 >= {settings.MIN_PRICE_CHANGE_PERCENT}% 的币种")
                
        except Exception as e:
            logger.error(f"获取24小时涨跌幅失败: {e}")
    
    def clear_checked_cache(self):
        """清除已检查缓存（每日清理或手动触发）"""
        self._checked_symbols.clear()
        logger.info("已清除涨跌幅监控缓存")
    
    # ================= 对外接口 =================
    
    async def start(self, check_interval: int = 300):
        """启动监控
        
        Args:
            check_interval: 检查间隔（秒），默认300秒（5分钟）
        """
        if self._running:
            logger.warning("涨跌幅监控已在运行中")
            return
        
        self._check_interval = check_interval
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("涨跌幅监控任务已启动")
    
    async def stop(self):
        """停止监控"""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("【涨跌幅监控】已停止")
    
    def is_running(self) -> bool:
        """检查监控是否运行中"""
        return self._running and (self._task is not None and not self._task.done())
    
    async def check_now(self):
        """立即执行一次检查（手动触发）"""
        await self._do_check()


# 全局实例（保持原名以减少其他文件改动）
oi_monitor = PriceChangeMonitor()
