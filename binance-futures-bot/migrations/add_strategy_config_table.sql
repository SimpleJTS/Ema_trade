-- 添加策略配置表
-- 用于支持灵活的策略条件组合配置

CREATE TABLE IF NOT EXISTS strategy_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT 0,

    -- EMA参数
    ema_fast INTEGER DEFAULT 9,
    ema_medium INTEGER,
    ema_slow INTEGER,

    -- 入场条件配置（JSON格式）
    entry_conditions TEXT DEFAULT '[]',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_strategy_configs_is_active ON strategy_configs(is_active);
CREATE INDEX IF NOT EXISTS idx_strategy_configs_name ON strategy_configs(name);

-- 插入默认策略配置示例

-- 策略1: EMA基础策略 (EMA6/51)
INSERT INTO strategy_configs (name, description, ema_fast, ema_medium, ema_slow, entry_conditions, is_active)
VALUES (
    'EMA基础策略',
    'EMA6/51金叉死叉策略，震荡行情过滤',
    6,
    51,
    NULL,
    '[
        {"type": "ema_cross", "enabled": true, "price_confirm": true},
        {"type": "cross_count_limit", "enabled": true, "lookback": 20, "max_crosses": 2}
    ]',
    0
);

-- 策略2: EMA高级策略 (EMA9/72/200 + ADX + 成交量)
INSERT INTO strategy_configs (name, description, ema_fast, ema_medium, ema_slow, entry_conditions, is_active)
VALUES (
    'EMA高级策略',
    'EMA9/72/200三均线+ADX趋势+成交量确认',
    9,
    72,
    200,
    '[
        {"type": "ema_cross", "enabled": true, "price_confirm": true},
        {"type": "price_above_ema", "enabled": true, "ema_type": "slow"},
        {"type": "adx_threshold", "enabled": true, "period": 14, "threshold": 25},
        {"type": "volume_surge", "enabled": true, "period": 30, "multiplier": 1.8},
        {"type": "cross_count_limit", "enabled": true, "lookback": 25, "max_crosses": 1}
    ]',
    1
);

-- 策略3: 简化趋势策略 (EMA9/72 + ADX)
INSERT INTO strategy_configs (name, description, ema_fast, ema_medium, ema_slow, entry_conditions, is_active)
VALUES (
    '简化趋势策略',
    'EMA9/72交叉+ADX趋势确认',
    9,
    72,
    NULL,
    '[
        {"type": "ema_cross", "enabled": true, "price_confirm": true},
        {"type": "adx_threshold", "enabled": true, "period": 14, "threshold": 25},
        {"type": "cross_count_limit", "enabled": true, "lookback": 25, "max_crosses": 1}
    ]',
    0
);

-- 策略4: 保守策略 (EMA9/72/200 + 多重过滤)
INSERT INTO strategy_configs (name, description, ema_fast, ema_medium, ema_slow, entry_conditions, is_active)
VALUES (
    '保守策略',
    '多重条件过滤，降低假信号',
    9,
    72,
    200,
    '[
        {"type": "ema_cross", "enabled": true, "price_confirm": true},
        {"type": "price_above_ema", "enabled": true, "ema_type": "medium"},
        {"type": "price_above_ema", "enabled": true, "ema_type": "slow"},
        {"type": "adx_threshold", "enabled": true, "period": 14, "threshold": 30},
        {"type": "volume_surge", "enabled": true, "period": 30, "multiplier": 2.0},
        {"type": "cross_count_limit", "enabled": true, "lookback": 30, "max_crosses": 0}
    ]',
    0
);
