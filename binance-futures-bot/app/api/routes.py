"""
Web API路由
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, DatabaseManager
from app.models import TradingPair, Position, TradeLog, SystemConfig, StopLossLog
from app.api.schemas import (
    TradingPairCreate, TradingPairUpdate, TradingPairResponse,
    BinanceConfigUpdate, TelegramConfigUpdate, SystemConfigResponse,
    PositionResponse, WebSocketStatus, TradeLogResponse, StopLossLogResponse,
    MessageResponse, ErrorResponse,
    TrailingStopConfig, TrailingStopConfigUpdate, TrailingStopLevel,
    TGMonitorConfig, TGMonitorConfigUpdate,
    PnLAnalysisResponse, PnLSummary, PnLCurvePoint, PnLIncomeRecord, PnLBySymbol
)
from app.config import settings, config_manager
from app.services.binance_api import binance_api
from app.services.binance_ws import binance_ws
from app.services.position_manager import position_manager
from app.services.stop_loss_guard import stop_loss_guard
from app.services.telegram import telegram_service
from app.utils.encryption import encrypt, encryption_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ========== Trading Pairs ==========

@router.get("/trading-pairs", response_model=List[TradingPairResponse])
async def get_trading_pairs():
    """获取所有交易对配置"""
    session = await DatabaseManager.get_session()
    try:
        result = await session.execute(select(TradingPair).order_by(TradingPair.created_at.desc()))
        pairs = result.scalars().all()
        return pairs
    finally:
        await session.close()


@router.post("/trading-pairs", response_model=TradingPairResponse)
async def create_trading_pair(data: TradingPairCreate):
    """创建交易对配置"""
    session = await DatabaseManager.get_session()
    try:
        # 检查是否已存在
        result = await session.execute(
            select(TradingPair).where(TradingPair.symbol == data.symbol.upper())
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"交易对 {data.symbol} 已存在")
        
        # 创建
        pair = TradingPair(
            symbol=data.symbol.upper(),
            leverage=data.leverage,
            strategy_interval=data.strategy_interval,
            stop_loss_percent=data.stop_loss_percent,
            is_active=data.is_active
        )
        session.add(pair)
        await session.commit()
        await session.refresh(pair)
        
        # 通知配置变更
        if pair.is_active:
            await config_manager.notify_observers("trading_pair_added", {
                "symbol": pair.symbol,
                "interval": pair.strategy_interval
            })
        
        return pair
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.put("/trading-pairs/{symbol}", response_model=TradingPairResponse)
async def update_trading_pair(symbol: str, data: TradingPairUpdate):
    """更新交易对配置"""
    session = await DatabaseManager.get_session()
    try:
        result = await session.execute(
            select(TradingPair).where(TradingPair.symbol == symbol.upper())
        )
        pair = result.scalar_one_or_none()
        if not pair:
            raise HTTPException(status_code=404, detail=f"交易对 {symbol} 不存在")
        
        # 记录旧状态
        old_active = pair.is_active
        old_interval = pair.strategy_interval
        
        # 更新字段
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(pair, key, value)
        
        await session.commit()
        await session.refresh(pair)
        
        # 通知配置变更
        if old_active != pair.is_active or old_interval != pair.strategy_interval:
            await config_manager.notify_observers("trading_pair_updated", {
                "symbol": pair.symbol,
                "interval": pair.strategy_interval,
                "is_active": pair.is_active
            })
        
        return pair
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.delete("/trading-pairs/{symbol}", response_model=MessageResponse)
async def delete_trading_pair(symbol: str):
    """删除交易对配置"""
    session = await DatabaseManager.get_session()
    try:
        result = await session.execute(
            select(TradingPair).where(TradingPair.symbol == symbol.upper())
        )
        pair = result.scalar_one_or_none()
        if not pair:
            raise HTTPException(status_code=404, detail=f"交易对 {symbol} 不存在")
        
        await session.delete(pair)
        await session.commit()
        
        # 通知配置变更
        await config_manager.notify_observers("trading_pair_removed", {
            "symbol": symbol.upper()
        })
        
        return MessageResponse(success=True, message=f"已删除交易对 {symbol}")
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


# ========== System Config ==========

@router.get("/config/status", response_model=SystemConfigResponse)
async def get_config_status():
    """获取系统配置状态"""
    return SystemConfigResponse(
        binance_configured=bool(settings.BINANCE_API_KEY and settings.BINANCE_API_SECRET),
        binance_testnet=settings.BINANCE_TESTNET,
        telegram_configured=bool(settings.TG_BOT_TOKEN and settings.TG_CHAT_ID),
        channel_listener_configured=bool(settings.TG_API_ID and settings.TG_API_HASH),
        encryption_enabled=encryption_manager.is_available
    )


@router.post("/config/binance", response_model=MessageResponse)
async def update_binance_config(data: BinanceConfigUpdate):
    """更新币安API配置（加密存储）"""
    session = await DatabaseManager.get_session()
    try:
        # 加密敏感数据后保存到数据库
        configs = [
            ("BINANCE_API_KEY", encrypt(data.api_key), "币安API Key (加密)"),
            ("BINANCE_API_SECRET", encrypt(data.api_secret), "币安API Secret (加密)"),
            ("BINANCE_TESTNET", str(data.testnet), "是否使用测试网")
        ]
        
        for key, value, desc in configs:
            result = await session.execute(
                select(SystemConfig).where(SystemConfig.key == key)
            )
            config = result.scalar_one_or_none()
            if config:
                config.value = value
                config.description = desc
            else:
                config = SystemConfig(key=key, value=value, description=desc)
                session.add(config)
        
        await session.commit()
        
        # 更新运行时配置（使用明文）
        config_manager.update_binance_config(data.api_key, data.api_secret, data.testnet)
        
        encrypted_status = "已加密" if encryption_manager.is_available else "未加密（加密器不可用）"
        return MessageResponse(success=True, message=f"币安API配置已更新（{encrypted_status}）")
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.post("/config/telegram", response_model=MessageResponse)
async def update_telegram_config(data: TelegramConfigUpdate):
    """更新Telegram配置（加密存储）"""
    session = await DatabaseManager.get_session()
    try:
        # 加密敏感数据后保存
        configs = [
            ("TG_BOT_TOKEN", encrypt(data.bot_token), "Telegram Bot Token (加密)"),
            ("TG_CHAT_ID", data.chat_id, "Telegram Chat ID"),  # Chat ID 不需要加密
        ]
        
        if data.api_id:
            configs.append(("TG_API_ID", str(data.api_id), "Telegram API ID"))
        if data.api_hash:
            configs.append(("TG_API_HASH", encrypt(data.api_hash), "Telegram API Hash (加密)"))
        
        for key, value, desc in configs:
            result = await session.execute(
                select(SystemConfig).where(SystemConfig.key == key)
            )
            config = result.scalar_one_or_none()
            if config:
                config.value = value
                config.description = desc
            else:
                config = SystemConfig(key=key, value=value, description=desc)
                session.add(config)
        
        await session.commit()
        
        # 更新运行时配置（使用明文）
        config_manager.update_telegram_config(
            data.bot_token, data.chat_id,
            data.api_id or 0, data.api_hash or ""
        )
        
        # 重新初始化Telegram服务
        await telegram_service.initialize()
        
        encrypted_status = "已加密" if encryption_manager.is_available else "未加密（加密器不可用）"
        return MessageResponse(success=True, message=f"Telegram配置已更新（{encrypted_status}）")
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


# ========== Positions ==========

@router.get("/positions", response_model=List[PositionResponse])
async def get_positions(status: Optional[str] = Query(None, description="OPEN/CLOSED")):
    """获取仓位列表"""
    session = await DatabaseManager.get_session()
    try:
        query = select(Position).order_by(Position.opened_at.desc())
        if status:
            query = query.where(Position.status == status.upper())
        
        result = await session.execute(query)
        positions = result.scalars().all()
        return positions
    finally:
        await session.close()


@router.post("/positions/{symbol}/close", response_model=MessageResponse)
async def close_position(symbol: str):
    """手动平仓"""
    try:
        success = await position_manager.close_position(symbol.upper(), reason="MANUAL")
        if success:
            return MessageResponse(success=True, message=f"已平仓 {symbol}")
        else:
            raise HTTPException(status_code=404, detail=f"未找到 {symbol} 的持仓")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== WebSocket Status ==========

@router.get("/websocket/status", response_model=WebSocketStatus)
async def get_websocket_status():
    """获取WebSocket状态"""
    status = binance_ws.get_status()
    return WebSocketStatus(**status)


@router.post("/websocket/restart", response_model=MessageResponse)
async def restart_websocket():
    """重启WebSocket连接"""
    try:
        await binance_ws.stop()
        await binance_ws.start()
        return MessageResponse(success=True, message="WebSocket已重启")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== Trade Logs ==========

@router.get("/trade-logs", response_model=List[TradeLogResponse])
async def get_trade_logs(
    symbol: Optional[str] = None,
    limit: int = Query(default=100, le=1000)
):
    """获取交易日志"""
    session = await DatabaseManager.get_session()
    try:
        query = select(TradeLog).order_by(TradeLog.created_at.desc()).limit(limit)
        if symbol:
            query = query.where(TradeLog.symbol == symbol.upper())
        
        result = await session.execute(query)
        logs = result.scalars().all()
        return logs
    finally:
        await session.close()


# ========== Stop Loss Logs ==========

@router.get("/stop-loss-logs", response_model=List[StopLossLogResponse])
async def get_stop_loss_logs(
    symbol: Optional[str] = None,
    limit: int = Query(default=100, le=500)
):
    """获取止损调整记录"""
    session = await DatabaseManager.get_session()
    try:
        query = select(StopLossLog).order_by(StopLossLog.created_at.desc()).limit(limit)
        if symbol:
            query = query.where(StopLossLog.symbol == symbol.upper())
        
        result = await session.execute(query)
        logs = result.scalars().all()
        return logs
    finally:
        await session.close()


@router.get("/stop-loss-logs/stats")
async def get_stop_loss_stats():
    """获取止损调整统计"""
    session = await DatabaseManager.get_session()
    try:
        # 获取最近的调整记录数
        result = await session.execute(
            select(StopLossLog).order_by(StopLossLog.created_at.desc()).limit(100)
        )
        logs = result.scalars().all()
        
        # 统计各级别调整次数
        level_counts = {0: 0, 1: 0, 2: 0, 3: 0}
        trailing_count = 0
        symbols = set()
        
        for log in logs:
            level_counts[log.new_level] = level_counts.get(log.new_level, 0) + 1
            if log.is_trailing:
                trailing_count += 1
            symbols.add(log.symbol)
        
        return {
            "total_adjustments": len(logs),
            "level_counts": level_counts,
            "trailing_adjustments": trailing_count,
            "symbols_affected": list(symbols)
        }
    finally:
        await session.close()


# ========== Account ==========

@router.get("/account/balance")
async def get_account_balance():
    """获取账户余额"""
    try:
        balances = await binance_api.get_account_balance()
        usdt = balances.get("USDT", {})
        return {
            "usdt_balance": usdt.get("balance", 0),
            "usdt_available": usdt.get("available", 0),
            "unrealized_pnl": usdt.get("unrealized_pnl", 0)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== Test ==========

@router.post("/test/telegram", response_model=MessageResponse)
async def test_telegram():
    """测试Telegram通知"""
    try:
        success = await telegram_service.send_message("🔔 测试消息 - Binance Futures Bot 运行正常!")
        if success:
            return MessageResponse(success=True, message="测试消息已发送")
        else:
            raise HTTPException(status_code=500, detail="发送失败，请检查Telegram配置")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== Trailing Stop Config ==========

def get_default_trailing_config() -> dict:
    """获取默认移动止损配置"""
    return {
        "level_1": {"profit_min": 2.5, "profit_max": 5.0, "lock_profit": 0, "trailing_enabled": False, "trailing_percent": 3.0},
        "level_2": {"profit_min": 5.0, "profit_max": 10.0, "lock_profit": 3.0, "trailing_enabled": False, "trailing_percent": 3.0},
        "level_3": {"profit_min": 10.0, "profit_max": None, "lock_profit": 5.0, "trailing_enabled": True, "trailing_percent": 3.0}
    }


@router.get("/config/trailing-stop", response_model=TrailingStopConfig)
async def get_trailing_stop_config():
    """获取移动止损配置"""
    import json
    session = await DatabaseManager.get_session()
    try:
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == "TRAILING_STOP_CONFIG")
        )
        config = result.scalar_one_or_none()
        
        if config and config.value:
            try:
                config_data = json.loads(config.value)
                return TrailingStopConfig(
                    level_1=TrailingStopLevel(**config_data.get("level_1", get_default_trailing_config()["level_1"])),
                    level_2=TrailingStopLevel(**config_data.get("level_2", get_default_trailing_config()["level_2"])),
                    level_3=TrailingStopLevel(**config_data.get("level_3", get_default_trailing_config()["level_3"]))
                )
            except (json.JSONDecodeError, TypeError):
                pass
        
        # 返回默认配置
        default = get_default_trailing_config()
        return TrailingStopConfig(
            level_1=TrailingStopLevel(**default["level_1"]),
            level_2=TrailingStopLevel(**default["level_2"]),
            level_3=TrailingStopLevel(**default["level_3"])
        )
    finally:
        await session.close()


@router.post("/config/trailing-stop", response_model=MessageResponse)
async def update_trailing_stop_config(data: TrailingStopConfigUpdate):
    """更新移动止损配置"""
    import json
    session = await DatabaseManager.get_session()
    try:
        # 先获取现有配置
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == "TRAILING_STOP_CONFIG")
        )
        config = result.scalar_one_or_none()
        
        # 合并配置
        existing_config = get_default_trailing_config()
        if config and config.value:
            try:
                existing_config = json.loads(config.value)
            except json.JSONDecodeError:
                pass
        
        # 更新提供的级别
        if data.level_1:
            existing_config["level_1"] = data.level_1.model_dump()
        if data.level_2:
            existing_config["level_2"] = data.level_2.model_dump()
        if data.level_3:
            existing_config["level_3"] = data.level_3.model_dump()
        
        # 保存到数据库
        config_value = json.dumps(existing_config)
        if config:
            config.value = config_value
            config.description = "移动止损级别配置"
        else:
            config = SystemConfig(
                key="TRAILING_STOP_CONFIG",
                value=config_value,
                description="移动止损级别配置"
            )
            session.add(config)
        
        await session.commit()
        
        # 通知配置变更
        await config_manager.notify_observers("trailing_stop_config_updated", existing_config)
        
        return MessageResponse(success=True, message="移动止损配置已更新")
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


# ========== TG Monitor Config ==========

@router.get("/config/tg-monitor", response_model=TGMonitorConfig)
async def get_tg_monitor_config():
    """获取TG频道监控配置"""
    from app.services.tg_monitor import oi_monitor
    
    session = await DatabaseManager.get_session()
    try:
        # 从数据库获取配置
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == "MIN_PRICE_CHANGE_PERCENT")
        )
        config = result.scalar_one_or_none()
        
        min_change = settings.MIN_PRICE_CHANGE_PERCENT
        if config and config.value:
            try:
                min_change = float(config.value)
            except ValueError:
                pass
        
        return TGMonitorConfig(
            min_price_change_percent=min_change,
            is_running=oi_monitor.is_running()
        )
    finally:
        await session.close()


@router.post("/config/tg-monitor", response_model=MessageResponse)
async def update_tg_monitor_config(data: TGMonitorConfigUpdate):
    """更新TG频道监控配置"""
    session = await DatabaseManager.get_session()
    try:
        # 保存到数据库
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == "MIN_PRICE_CHANGE_PERCENT")
        )
        config = result.scalar_one_or_none()
        
        if config:
            config.value = str(data.min_price_change_percent)
            config.description = "TG频道监控 - 24H价格变化阈值%"
        else:
            config = SystemConfig(
                key="MIN_PRICE_CHANGE_PERCENT",
                value=str(data.min_price_change_percent),
                description="TG频道监控 - 24H价格变化阈值%"
            )
            session.add(config)
        
        await session.commit()
        
        # 更新运行时配置
        settings.MIN_PRICE_CHANGE_PERCENT = data.min_price_change_percent
        
        logger.info(f"TG监控价格变化阈值已更新为: {data.min_price_change_percent}%")
        
        return MessageResponse(
            success=True,
            message=f"TG监控配置已更新，价格变化阈值: {data.min_price_change_percent}%"
        )
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


# ========== PnL Analysis ==========

@router.get("/pnl/analysis", response_model=PnLAnalysisResponse)
async def get_pnl_analysis(
    start_date: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
    symbol: Optional[str] = Query(None, description="交易对筛选")
):
    """获取PnL分析数据（从币安API获取真实交易数据）"""
    from datetime import datetime, timedelta
    from collections import defaultdict

    try:
        # 解析日期范围
        if start_date:
            period_start = datetime.strptime(start_date, "%Y-%m-%d")
        else:
            period_start = datetime.utcnow() - timedelta(days=30)

        if end_date:
            period_end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        else:
            period_end = datetime.utcnow()

        # 转换为毫秒时间戳
        start_ts = int(period_start.timestamp() * 1000)
        end_ts = int(period_end.timestamp() * 1000)

        # 从币安API获取收益历史
        income_data = await binance_api.get_all_income_history(
            symbol=symbol.upper() if symbol else None,
            start_time=start_ts,
            end_time=end_ts
        )

        # 分类统计
        realized_pnl_records = []  # 已实现盈亏
        commission_total = 0.0
        funding_fee_total = 0.0
        symbol_stats = defaultdict(lambda: {
            "realized_pnl": 0.0,
            "commission": 0.0,
            "funding_fee": 0.0,
            "trade_count": 0
        })

        # 处理每条收益记录
        all_records = []
        for record in income_data:
            income = float(record.get("income", 0))
            income_type = record.get("incomeType", "")
            sym = record.get("symbol", "")
            timestamp = datetime.fromtimestamp(record.get("time", 0) / 1000)

            all_records.append(PnLIncomeRecord(
                symbol=sym,
                income_type=income_type,
                income=income,
                asset=record.get("asset", "USDT"),
                timestamp=timestamp,
                info=record.get("info"),
                tran_id=record.get("tranId"),
                trade_id=record.get("tradeId")
            ))

            if income_type == "REALIZED_PNL":
                realized_pnl_records.append(income)
                symbol_stats[sym]["realized_pnl"] += income
                symbol_stats[sym]["trade_count"] += 1
            elif income_type == "COMMISSION":
                commission_total += abs(income)
                symbol_stats[sym]["commission"] += abs(income)
            elif income_type == "FUNDING_FEE":
                funding_fee_total += income
                symbol_stats[sym]["funding_fee"] += income

        # 计算统计数据
        total_trades = len(realized_pnl_records)
        winning_trades = sum(1 for p in realized_pnl_records if p > 0)
        losing_trades = sum(1 for p in realized_pnl_records if p < 0)

        total_realized_pnl = sum(realized_pnl_records)
        net_pnl = total_realized_pnl - commission_total + funding_fee_total

        wins = [p for p in realized_pnl_records if p > 0]
        losses = [p for p in realized_pnl_records if p < 0]

        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0

        total_win_amount = sum(wins) if wins else 0
        total_loss_amount = abs(sum(losses)) if losses else 0
        profit_factor = total_win_amount / total_loss_amount if total_loss_amount > 0 else (999.99 if total_win_amount > 0 else 0)

        max_win = max(wins) if wins else 0
        max_loss = min(losses) if losses else 0

        # 计算连胜/连亏
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_wins = 0
        current_losses = 0

        for pnl in realized_pnl_records:
            if pnl > 0:
                current_wins += 1
                current_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, current_wins)
            elif pnl < 0:
                current_losses += 1
                current_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, current_losses)
            else:
                current_wins = 0
                current_losses = 0

        # 构建PnL曲线数据（按时间顺序累计净盈亏）
        curve_data = []
        cumulative_pnl = 0
        pnl_count = 0
        for record in all_records:
            if record.income_type == "REALIZED_PNL":
                cumulative_pnl += record.income
                pnl_count += 1
            elif record.income_type == "COMMISSION":
                cumulative_pnl -= abs(record.income)
            elif record.income_type == "FUNDING_FEE":
                cumulative_pnl += record.income

            curve_data.append(PnLCurvePoint(
                timestamp=record.timestamp,
                cumulative_pnl=round(cumulative_pnl, 2),
                trade_count=pnl_count
            ))

        # 按交易对统计
        by_symbol = [
            PnLBySymbol(
                symbol=sym,
                realized_pnl=round(stats["realized_pnl"], 2),
                commission=round(stats["commission"], 2),
                funding_fee=round(stats["funding_fee"], 2),
                net_pnl=round(stats["realized_pnl"] - stats["commission"] + stats["funding_fee"], 2),
                trade_count=stats["trade_count"]
            )
            for sym, stats in sorted(symbol_stats.items(), key=lambda x: x[1]["realized_pnl"], reverse=True)
            if sym  # 过滤空symbol
        ]

        # 构建摘要
        summary = PnLSummary(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=round((winning_trades / total_trades * 100) if total_trades > 0 else 0, 2),
            realized_pnl=round(total_realized_pnl, 2),
            commission=round(commission_total, 2),
            funding_fee=round(funding_fee_total, 2),
            net_pnl=round(net_pnl, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            profit_factor=round(min(profit_factor, 999.99), 2),
            max_win=round(max_win, 2),
            max_loss=round(max_loss, 2),
            max_consecutive_wins=max_consecutive_wins,
            max_consecutive_losses=max_consecutive_losses
        )

        return PnLAnalysisResponse(
            summary=summary,
            curve_data=curve_data,
            by_symbol=by_symbol,
            records=all_records[-500:],  # 只返回最近500条记录
            period_start=period_start,
            period_end=period_end
        )
    except Exception as e:
        logger.error(f"获取PnL分析数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pnl/symbols")
async def get_pnl_symbols():
    """获取有交易记录的交易对列表（从币安API获取）"""
    from datetime import datetime, timedelta

    try:
        # 获取最近90天的数据
        end_ts = int(datetime.utcnow().timestamp() * 1000)
        start_ts = int((datetime.utcnow() - timedelta(days=90)).timestamp() * 1000)

        income_data = await binance_api.get_all_income_history(
            income_type="REALIZED_PNL",
            start_time=start_ts,
            end_time=end_ts
        )

        # 提取唯一的交易对
        symbols = set()
        for record in income_data:
            sym = record.get("symbol", "")
            if sym:
                symbols.add(sym)

        return {"symbols": sorted(list(symbols))}
    except Exception as e:
        logger.error(f"获取交易对列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== Stop Loss Guard ==========

@router.get("/stop-loss-guard/check")
async def check_stop_loss_orders():
    """手动检查所有持仓的止损订单状态"""
    try:
        results = await stop_loss_guard.check_all_positions()
        return {
            "success": True,
            "message": f"已检查 {len(results)} 个持仓",
            "results": results
        }
    except Exception as e:
        logger.error(f"止损守护检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop-loss-guard/interval")
async def set_stop_loss_guard_interval(interval: int = Query(..., ge=10, le=300, description="检查间隔(秒)")):
    """设置止损守护检查间隔"""
    try:
        stop_loss_guard.set_check_interval(interval)
        return MessageResponse(
            success=True,
            message=f"止损守护检查间隔已设置为 {interval} 秒"
        )
    except Exception as e:
        logger.error(f"设置止损守护间隔失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
