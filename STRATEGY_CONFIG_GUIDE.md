# 策略配置器使用指南

## 📋 功能概述

策略配置器是一个**可视化的Web界面**，让你无需修改代码就能灵活配置交易策略。

### 主要特性

✅ **模块化条件** - 每个入场条件独立配置
✅ **灵活组合** - 自由选择条件组合
✅ **实时保存** - 配置立即生效
✅ **预设策略** - 内置4种常用策略模板
✅ **可视化界面** - 无需编写代码

---

## 🚀 快速开始

### 1. 启动策略配置服务

```bash
cd binance-futures-bot
python app/web_api.py
```

服务将在 **http://localhost:5000** 启动

### 2. 访问配置界面

在浏览器中打开：
```
http://localhost:5000
```

### 3. 初始化数据库

首次使用需要运行数据库迁移：

```bash
sqlite3 trading_bot.db < migrations/add_strategy_config_table.sql
```

这将创建策略配置表并插入4个预设策略。

---

## 📐 可用条件类型

### 1️⃣ EMA交叉 (ema_cross)

**说明**：快线穿越中线

**参数**：
- `direction`: 方向 (`golden`=金叉, `death`=死叉)
- `price_confirm`: 价格确认 (布尔值)

**示例**：
```json
{
    "type": "ema_cross",
    "enabled": true,
    "price_confirm": true
}
```

---

### 2️⃣ 价格高于EMA (price_above_ema)

**说明**：收盘价高于指定EMA

**参数**：
- `ema_type`: EMA类型 (`fast`, `medium`, `slow`)

**示例**：
```json
{
    "type": "price_above_ema",
    "enabled": true,
    "ema_type": "slow"
}
```

---

### 3️⃣ 价格低于EMA (price_below_ema)

**说明**：收盘价低于指定EMA

**参数**：
- `ema_type`: EMA类型 (`fast`, `medium`, `slow`)

**示例**：
```json
{
    "type": "price_below_ema",
    "enabled": true,
    "ema_type": "slow"
}
```

---

### 4️⃣ ADX趋势强度 (adx_threshold)

**说明**：ADX指标超过阈值

**参数**：
- `period`: ADX周期 (默认14)
- `threshold`: 阈值 (默认25)

**示例**：
```json
{
    "type": "adx_threshold",
    "enabled": true,
    "period": 14,
    "threshold": 25
}
```

---

### 5️⃣ 成交量激增 (volume_surge)

**说明**：成交量超过均量倍数

**参数**：
- `period`: 均量周期 (默认30)
- `multiplier`: 倍数 (默认1.8)

**示例**：
```json
{
    "type": "volume_surge",
    "enabled": true,
    "period": 30,
    "multiplier": 1.8
}
```

---

### 6️⃣ 交叉次数限制 (cross_count_limit)

**说明**：回看期内交叉次数不超过限制

**参数**：
- `lookback`: 回看周期 (默认25)
- `max_crosses`: 最大交叉次数 (默认1)

**示例**：
```json
{
    "type": "cross_count_limit",
    "enabled": true,
    "lookback": 25,
    "max_crosses": 1
}
```

---

## 🎯 预设策略

### 策略1：EMA基础策略

**配置**：
- EMA：6/51
- 条件：
  - EMA交叉（价格确认）
  - 交叉次数限制（20根K线内≤2次）

**适用场景**：简单的趋势跟随

---

### 策略2：EMA高级策略 ⭐ (默认激活)

**配置**：
- EMA：9/72/200
- 条件：
  - EMA9上穿EMA72（价格确认）
  - 价格高于EMA200
  - ADX(14) ≥ 25
  - 成交量 ≥ 30期均量 × 1.8
  - 交叉次数限制（25根K线内≤1次）

**适用场景**：强趋势行情，过滤假信号

---

### 策略3：简化趋势策略

**配置**：
- EMA：9/72
- 条件：
  - EMA交叉（价格确认）
  - ADX(14) ≥ 25
  - 交叉次数限制（25根K线内≤1次）

**适用场景**：中等趋势行情

---

### 策略4：保守策略

**配置**：
- EMA：9/72/200
- 条件：
  - EMA9上穿EMA72（价格确认）
  - 价格高于EMA72
  - 价格高于EMA200
  - ADX(14) ≥ 30（更高阈值）
  - 成交量 ≥ 30期均量 × 2.0（更高倍数）
  - 交叉次数限制（30根K线内=0次）

**适用场景**：追求低假信号率，适合保守交易

---

## 🖼️ 界面操作指南

### 创建新策略

1. 点击左上角 **"➕ 新建策略"** 按钮
2. 输入策略名称
3. 配置EMA参数和条件
4. 点击 **"💾 保存策略"**

### 编辑策略

1. 从左侧列表点击策略
2. 修改EMA参数
3. 启用/禁用条件（点击右侧开关）
4. 调整条件参数
5. 点击 **"💾 保存策略"**

### 激活策略

1. 编辑策略后
2. 点击 **"🚀 激活策略"** 按钮
3. 确认激活（会停用其他策略）
4. 交易机器人将使用此策略

### 删除策略

1. 编辑策略
2. 点击 **"🗑️ 删除"** 按钮
3. 确认删除

---

## 🔗 集成到交易机器人

### 方法1：手动集成（推荐）

在 `app/main.py` 中添加可配置策略支持：

```python
from sqlalchemy import select
from app.models import StrategyConfig
from app.services.configurable_strategy import ConfigurableStrategy

# 在启动时加载激活的策略
async def load_active_strategy():
    async with AsyncSession() as session:
        result = await session.execute(
            select(StrategyConfig).where(StrategyConfig.is_active == True)
        )
        config = result.scalar_one_or_none()

        if config:
            return ConfigurableStrategy(config.to_dict())
        else:
            # 使用默认策略
            from app.services.strategy import ema_advanced_strategy
            return ema_advanced_strategy

# 在K线处理中使用
configurable_strategy = await load_active_strategy()
signal = configurable_strategy.analyze(symbol, klines, direction="both")
```

### 方法2：策略选择逻辑

```python
# 根据TradingPair的strategy_type选择策略
if pair.strategy_type == "CONFIGURABLE":
    # 使用可配置策略
    signal = configurable_strategy.analyze(symbol, klines)
elif pair.strategy_type == "EMA_ADVANCED":
    # 使用固定的高级策略
    signal = ema_advanced_strategy.analyze(symbol, klines)
else:
    # 使用基础策略
    signal = ema_strategy.analyze(symbol, klines)
```

---

## 📊 策略配置JSON格式

完整的策略配置示例：

```json
{
    "name": "我的自定义策略",
    "description": "适合震荡行情的策略",
    "ema_fast": 9,
    "ema_medium": 72,
    "ema_slow": 200,
    "entry_conditions": [
        {
            "type": "ema_cross",
            "enabled": true,
            "price_confirm": true
        },
        {
            "type": "price_above_ema",
            "enabled": true,
            "ema_type": "slow"
        },
        {
            "type": "adx_threshold",
            "enabled": true,
            "period": 14,
            "threshold": 25
        },
        {
            "type": "volume_surge",
            "enabled": true,
            "period": 30,
            "multiplier": 1.8
        },
        {
            "type": "cross_count_limit",
            "enabled": true,
            "lookback": 25,
            "max_crosses": 1
        }
    ]
}
```

---

## 🔧 API接口

策略配置器提供REST API接口：

### 获取所有策略
```http
GET /api/strategies
```

### 获取单个策略
```http
GET /api/strategies/:id
```

### 创建策略
```http
POST /api/strategies
Content-Type: application/json

{
    "name": "策略名称",
    "ema_fast": 9,
    "ema_medium": 72,
    "ema_slow": 200,
    "entry_conditions": []
}
```

### 更新策略
```http
PUT /api/strategies/:id
Content-Type: application/json

{
    "name": "新名称",
    "entry_conditions": [...]
}
```

### 激活策略
```http
POST /api/strategies/:id/activate
```

### 删除策略
```http
DELETE /api/strategies/:id
```

### 获取激活的策略
```http
GET /api/strategies/active
```

### 获取条件定义
```http
GET /api/conditions/definitions
```

---

## 🚨 注意事项

1. **只能有一个激活策略**
   激活新策略会自动停用其他策略

2. **所有条件必须满足**
   只有启用的所有条件都通过时才会开仓

3. **参数范围**
   - EMA周期：1-500
   - ADX阈值：10-50
   - 成交量倍数：1.0-5.0
   - 回看周期：10-100

4. **实时生效**
   保存后需要重启交易机器人才能生效

5. **数据备份**
   策略配置保存在 `trading_bot.db` 中，建议定期备份

---

## 💡 策略设计建议

### 做多策略

推荐条件组合：
```
✅ EMA快线上穿中线
✅ 价格高于EMA慢线
✅ ADX ≥ 25
✅ 成交量激增
✅ 交叉次数限制
```

### 做空策略

推荐条件组合：
```
✅ EMA快线下穿中线
✅ 价格低于EMA慢线
✅ ADX ≥ 25
✅ 成交量激增
✅ 交叉次数限制
```

### 保守策略

建议配置：
- 更高的ADX阈值（30+）
- 更高的成交量倍数（2.0+）
- 更严格的交叉限制（0次）
- 多重EMA过滤

### 激进策略

建议配置：
- 较低的ADX阈值（20）
- 较低的成交量倍数（1.5）
- 较松的交叉限制（2-3次）
- 较少的过滤条件

---

## 🐛 故障排除

### 问题1：无法访问配置界面

**解决**：
```bash
# 检查服务是否启动
ps aux | grep web_api

# 重新启动服务
python app/web_api.py
```

### 问题2：保存失败

**解决**：
- 检查策略名称是否重复
- 检查EMA参数是否合法
- 查看浏览器控制台错误信息

### 问题3：策略未生效

**解决**：
1. 确认策略已激活（绿色标记）
2. 重启交易机器人
3. 检查日志中的策略加载信息

---

## 📞 技术支持

遇到问题？
- 查看日志：`docker logs binance-futures-bot`
- 检查数据库：`sqlite3 trading_bot.db "SELECT * FROM strategy_configs;"`
- 提交Issue：https://github.com/your-repo/issues

---

祝交易顺利！🚀📈
