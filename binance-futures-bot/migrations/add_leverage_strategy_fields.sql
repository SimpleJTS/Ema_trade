-- 数据库迁移脚本：添加杠杆策略和部分平仓字段
-- 创建时间：2025-12-02
-- 描述：为 trading_pairs 和 positions 表添加新字段以支持动态杠杆和部分平仓

-- ==========================================
-- 1. TradingPair 表更新
-- ==========================================

-- 添加策略类型字段
ALTER TABLE trading_pairs ADD COLUMN strategy_type VARCHAR(20) DEFAULT 'EMA_BASIC';

-- 添加市值相关字段
ALTER TABLE trading_pairs ADD COLUMN market_cap_usd FLOAT NULL;
ALTER TABLE trading_pairs ADD COLUMN market_cap_tier INTEGER NULL;
ALTER TABLE trading_pairs ADD COLUMN base_leverage INTEGER NULL;
ALTER TABLE trading_pairs ADD COLUMN current_leverage INTEGER NULL;

-- 添加波动率相关字段
ALTER TABLE trading_pairs ADD COLUMN atr_volatility FLOAT NULL;
ALTER TABLE trading_pairs ADD COLUMN last_volatility_check TIMESTAMP NULL;

-- ==========================================
-- 2. Position 表更新
-- ==========================================

-- 添加部分平仓相关字段
ALTER TABLE positions ADD COLUMN is_partial_closed BOOLEAN DEFAULT FALSE;
ALTER TABLE positions ADD COLUMN partial_close_quantity FLOAT NULL;
ALTER TABLE positions ADD COLUMN remaining_quantity FLOAT NULL;

-- ==========================================
-- 3. 数据迁移（可选）
-- ==========================================

-- 为现有交易对设置默认策略类型
UPDATE trading_pairs SET strategy_type = 'EMA_BASIC' WHERE strategy_type IS NULL;

-- 为现有持仓设置部分平仓状态
UPDATE positions SET is_partial_closed = FALSE WHERE is_partial_closed IS NULL;

-- ==========================================
-- 完成
-- ==========================================
-- 迁移完成！
