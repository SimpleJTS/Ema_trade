"""
策略配置Web API
提供策略配置的CRUD接口
"""
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import logging
import asyncio
from typing import List, Dict
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, StrategyConfig

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# 条件定义
class StrategyCondition:
    """策略条件定义"""
    CONDITION_DEFINITIONS = {
        "ema_cross": {
            "name": "EMA交叉",
            "description": "快线穿越中线",
            "params": {
                "price_confirm": {"type": "boolean", "default": True, "label": "价格确认"}
            }
        },
        "price_above_ema": {
            "name": "价格高于EMA",
            "description": "收盘价高于指定EMA",
            "params": {
                "ema_type": {"type": "select", "options": ["fast", "medium", "slow"], "default": "slow", "label": "EMA类型"}
            }
        },
        "price_below_ema": {
            "name": "价格低于EMA",
            "description": "收盘价低于指定EMA",
            "params": {
                "ema_type": {"type": "select", "options": ["fast", "medium", "slow"], "default": "slow", "label": "EMA类型"}
            }
        },
        "adx_threshold": {
            "name": "ADX趋势强度",
            "description": "ADX指标超过阈值",
            "params": {
                "period": {"type": "number", "default": 14, "min": 5, "max": 50, "label": "周期"},
                "threshold": {"type": "number", "default": 25, "min": 10, "max": 50, "label": "阈值"}
            }
        },
        "volume_surge": {
            "name": "成交量激增",
            "description": "成交量超过均量倍数",
            "params": {
                "period": {"type": "number", "default": 30, "min": 10, "max": 100, "label": "均量周期"},
                "multiplier": {"type": "number", "default": 1.8, "min": 1.0, "max": 5.0, "step": 0.1, "label": "倍数"}
            }
        },
        "cross_count_limit": {
            "name": "交叉次数限制",
            "description": "回看期内交叉次数不超过限制",
            "params": {
                "lookback": {"type": "number", "default": 25, "min": 10, "max": 100, "label": "回看周期"},
                "max_crosses": {"type": "number", "default": 1, "min": 0, "max": 5, "label": "最大交叉次数"}
            }
        }
    }

# 创建Flask应用
app = Flask(__name__, static_folder='../web', static_url_path='')
CORS(app)  # 允许跨域

# 数据库配置
DATABASE_URL = "sqlite+aiosqlite:///trading_bot.db"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def run_async(coro):
    """运行异步函数"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ==================== 条件定义接口 ====================

@app.route('/api/conditions/definitions', methods=['GET'])
def get_condition_definitions():
    """获取所有可用的条件定义"""
    return jsonify({
        "success": True,
        "data": StrategyCondition.CONDITION_DEFINITIONS
    })


# ==================== 策略配置CRUD ====================

@app.route('/api/strategies', methods=['GET'])
def get_strategies():
    """获取所有策略配置"""
    async def _get_strategies():
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(StrategyConfig))
            strategies = result.scalars().all()
            return [{
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "is_active": s.is_active,
                "ema_fast": s.ema_fast,
                "ema_medium": s.ema_medium,
                "ema_slow": s.ema_slow,
                "entry_conditions": s.entry_conditions,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None
            } for s in strategies]

    try:
        strategies = run_async(_get_strategies())
        return jsonify({
            "success": True,
            "data": strategies
        })
    except Exception as e:
        logger.error(f"获取策略列表失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/strategies/<int:strategy_id>', methods=['GET'])
def get_strategy(strategy_id):
    """获取单个策略配置"""
    async def _get_strategy():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(StrategyConfig).where(StrategyConfig.id == strategy_id)
            )
            strategy = result.scalar_one_or_none()
            if not strategy:
                return None
            return {
                "id": strategy.id,
                "name": strategy.name,
                "description": strategy.description,
                "is_active": strategy.is_active,
                "ema_fast": strategy.ema_fast,
                "ema_medium": strategy.ema_medium,
                "ema_slow": strategy.ema_slow,
                "entry_conditions": strategy.entry_conditions,
                "created_at": strategy.created_at.isoformat() if strategy.created_at else None,
                "updated_at": strategy.updated_at.isoformat() if strategy.updated_at else None
            }

    try:
        strategy = run_async(_get_strategy())
        if strategy:
            return jsonify({
                "success": True,
                "data": strategy
            })
        else:
            return jsonify({
                "success": False,
                "error": "策略不存在"
            }), 404
    except Exception as e:
        logger.error(f"获取策略失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/strategies', methods=['POST'])
def create_strategy():
    """创建新策略"""
    data = request.json

    async def _create_strategy():
        async with AsyncSessionLocal() as session:
            strategy = StrategyConfig(
                name=data.get("name"),
                description=data.get("description", ""),
                is_active=data.get("is_active", False),
                ema_fast=data.get("ema_fast", 9),
                ema_medium=data.get("ema_medium"),
                ema_slow=data.get("ema_slow"),
                entry_conditions=data.get("entry_conditions", [])
            )
            session.add(strategy)
            await session.commit()
            await session.refresh(strategy)
            return strategy.id

    try:
        strategy_id = run_async(_create_strategy())
        return jsonify({
            "success": True,
            "data": {"id": strategy_id},
            "message": "策略创建成功"
        }), 201
    except Exception as e:
        logger.error(f"创建策略失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/strategies/<int:strategy_id>', methods=['PUT'])
def update_strategy(strategy_id):
    """更新策略配置"""
    data = request.json

    async def _update_strategy():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(StrategyConfig).where(StrategyConfig.id == strategy_id)
            )
            strategy = result.scalar_one_or_none()
            if not strategy:
                return False

            # 更新字段
            if "name" in data:
                strategy.name = data["name"]
            if "description" in data:
                strategy.description = data["description"]
            if "is_active" in data:
                strategy.is_active = data["is_active"]
            if "ema_fast" in data:
                strategy.ema_fast = data["ema_fast"]
            if "ema_medium" in data:
                strategy.ema_medium = data["ema_medium"]
            if "ema_slow" in data:
                strategy.ema_slow = data["ema_slow"]
            if "entry_conditions" in data:
                strategy.entry_conditions = data["entry_conditions"]

            await session.commit()
            return True

    try:
        success = run_async(_update_strategy())
        if success:
            return jsonify({
                "success": True,
                "message": "策略更新成功"
            })
        else:
            return jsonify({
                "success": False,
                "error": "策略不存在"
            }), 404
    except Exception as e:
        logger.error(f"更新策略失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/strategies/<int:strategy_id>', methods=['DELETE'])
def delete_strategy(strategy_id):
    """删除策略配置"""
    async def _delete_strategy():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(StrategyConfig).where(StrategyConfig.id == strategy_id)
            )
            strategy = result.scalar_one_or_none()
            if not strategy:
                return False

            await session.delete(strategy)
            await session.commit()
            return True

    try:
        success = run_async(_delete_strategy())
        if success:
            return jsonify({
                "success": True,
                "message": "策略删除成功"
            })
        else:
            return jsonify({
                "success": False,
                "error": "策略不存在"
            }), 404
    except Exception as e:
        logger.error(f"删除策略失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/strategies/<int:strategy_id>/activate', methods=['POST'])
def activate_strategy(strategy_id):
    """激活策略（停用其他策略）"""
    async def _activate_strategy():
        async with AsyncSessionLocal() as session:
            # 停用所有策略
            await session.execute(
                update(StrategyConfig).values(is_active=False)
            )

            # 激活指定策略
            result = await session.execute(
                select(StrategyConfig).where(StrategyConfig.id == strategy_id)
            )
            strategy = result.scalar_one_or_none()
            if not strategy:
                return False

            strategy.is_active = True
            await session.commit()
            return True

    try:
        success = run_async(_activate_strategy())
        if success:
            return jsonify({
                "success": True,
                "message": "策略已激活"
            })
        else:
            return jsonify({
                "success": False,
                "error": "策略不存在"
            }), 404
    except Exception as e:
        logger.error(f"激活策略失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/strategies/active', methods=['GET'])
def get_active_strategy():
    """获取当前激活的策略"""
    async def _get_active_strategy():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(StrategyConfig).where(StrategyConfig.is_active == True)
            )
            strategy = result.scalar_one_or_none()
            if not strategy:
                return None
            return {
                "id": strategy.id,
                "name": strategy.name,
                "description": strategy.description,
                "ema_fast": strategy.ema_fast,
                "ema_medium": strategy.ema_medium,
                "ema_slow": strategy.ema_slow,
                "entry_conditions": strategy.entry_conditions
            }

    try:
        strategy = run_async(_get_active_strategy())
        if strategy:
            return jsonify({
                "success": True,
                "data": strategy
            })
        else:
            return jsonify({
                "success": False,
                "error": "没有激活的策略"
            }), 404
    except Exception as e:
        logger.error(f"获取激活策略失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ==================== 前端页面 ====================

@app.route('/')
def index():
    """策略配置主页"""
    return send_from_directory('../web', 'strategy_config.html')


@app.route('/health')
def health():
    """健康检查"""
    return jsonify({"status": "ok"})


# ==================== 初始化数据库 ====================

async def init_db():
    """初始化数据库表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据库表初始化完成")


if __name__ == '__main__':
    # 初始化数据库
    run_async(init_db())

    # 启动Flask服务
    logger.info("策略配置Web API启动在 http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
