# 交易策略升级说明

## 📅 更新日期：2025-12-02

## 🎯 升级概述

本次升级对交易机器人进行了全面改造，新增了**高级交易信号策略**、**动态杠杆管理**和**智能止损止盈**功能。

---

## ✨ 新增功能

### 1️⃣ 双策略系统

系统现在支持两种策略，可根据币种配置自动选择：

#### **策略A：EMA基础策略**（原有策略，保留）
- **参数**：EMA6/EMA51
- **规则**：
  - 检测 EMA6 和 EMA51 的交叉
  - 前20根K线交叉次数 ≤ 2次才开仓
- **适用场景**：稳定币种、低波动市场

#### **策略B：EMA高级策略**（新增，默认）
- **参数**：EMA9/EMA72/EMA200 + ADX(14) + 成交量
- **开仓条件（5个条件全满足）**：

  **做多信号：**
  1. ✅ EMA9 上穿 EMA72 且收盘价 > EMA72
  2. ✅ 收盘价 > EMA200
  3. ✅ ADX(14) ≥ 25（趋势强度）
  4. ✅ 当前成交量 ≥ 30周期均量 × 1.8
  5. ✅ 前25根K线内仅发生 ≤1 次交叉

  **做空信号**：与做多相反

- **适用场景**：高波动币种、趋势明确市场

---

### 2️⃣ 动态杠杆策略

根据币种**市值层级**和**市场指标**自动计算最优杠杆倍数。

#### 市值层级划分

| 层级 | 市值范围 | 基础杠杆 | 动态调整规则 |
|------|---------|---------|------------|
| **1. 超大市值** | >1万亿USD<br/>(如BTC、ETH) | 20-25x | • 波动率<50% → 25x<br/>• 波动率>100% → 15x |
| **2. 大/中市值** | 100亿-1万亿USD<br/>(如SOL、BNB、XRP) | 10-18x | • ADX>30 → 18x<br/>• 资金费率高 → 10x |
| **3. 小市值** | 10亿-100亿USD<br/>(如PEPE、TAO) | 5-8x | • 成交量>3x均量 → 8x<br/>• 1h振幅>12% → 3-5x |
| **4. 新兴/低流动** | <10亿USD | 3-5x | • 仅ADX>35且波动可控时使用<br/>• 否则保守3x |

#### 杠杆计算时机
- ✅ 监控到新币种时自动计算
- ✅ 基于实时ATR波动率调整
- ✅ 开仓时决定，持仓期间不变

---

### 3️⃣ 智能止损止盈（1分钟专属版）

#### 初始止损
- **固定 2%**（价格止损，不含杠杆）

#### 4级移动止盈

| 级别 | 触发条件 | 止损动作 | 说明 |
|------|---------|---------|-----|
| **Level 0** | 开仓时 | 止损 = 成本价 × (1 - 2%) | 初始止损 |
| **Level 1** | 盈利 ≥ 1.8% | 止损移至成本+0.1% | 保本 |
| **Level 2** | 盈利 ≥ 2.5% | 止损提至成本+1.9% | 锁定部分利润 |
| **Level 3** | 盈利 ≥ 4.0% | **部分平仓50%**<br/>剩余50%设置1.5%追踪止损 | 锁定大部分利润，剩余仓位追踪 |

#### Level 3 追踪止损
- 从**最高点回撤1.5%**触发平仓
- 仅对剩余50%仓位生效
- 止损价随价格上涨动态上移

---

### 4️⃣ 部分平仓功能

当仓位盈利达到4%时：
- ✅ 自动平仓50%仓位，锁定利润
- ✅ 剩余50%继续持有，追踪止损
- ✅ 自动更新止损单数量
- ✅ Telegram通知部分平仓详情

---

### 5️⃣ ATR波动率监控

- **计算方式**：14周期ATR年化波动率
- **公式**：`(ATR / Price) × √(365×24×60) × 100%`
- **用途**：
  - 动态调整杠杆
  - 评估市场风险
  - 每分钟刷新

---

### 6️⃣ CoinGecko市值集成

- **数据源**：CoinGecko API
- **缓存时间**：1小时
- **获取信息**：
  - 币种市值（USD）
  - 市值排名
  - 24小时交易量
  - 流通量

---

## 🔧 技术实现

### 新增文件

```
app/services/
├── coingecko_api.py          # CoinGecko API集成
├── leverage_manager.py        # 动态杠杆管理器

app/utils/
├── indicators.py              # 技术指标计算（ADX、ATR）

migrations/
├── add_leverage_strategy_fields.sql  # 数据库迁移脚本
```

### 修改文件

```
app/models.py                  # 数据库模型扩展
app/services/strategy.py       # 新增EMAAdvancedStrategy类
app/services/trailing_stop.py  # 4级止损+部分平仓
app/services/position_manager.py # 部分平仓方法
app/services/telegram.py       # 集成杠杆计算
app/main.py                    # 策略选择逻辑
```

---

## 🗄️ 数据库变更

### TradingPair 表新增字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `strategy_type` | VARCHAR(20) | 策略类型（EMA_BASIC/EMA_ADVANCED） |
| `market_cap_usd` | FLOAT | 币种市值（美元） |
| `market_cap_tier` | INTEGER | 市值层级（1-4） |
| `base_leverage` | INTEGER | 基础杠杆 |
| `current_leverage` | INTEGER | 当前杠杆 |
| `atr_volatility` | FLOAT | ATR年化波动率(%) |
| `last_volatility_check` | TIMESTAMP | 最后波动率检查时间 |

### Position 表新增字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `is_partial_closed` | BOOLEAN | 是否已部分平仓 |
| `partial_close_quantity` | FLOAT | 部分平仓数量 |
| `remaining_quantity` | FLOAT | 剩余数量 |

---

## 📊 工作流程

### 新币种监控流程

```
1. 检测到24H涨跌幅 ≥ 30%的币种
   ↓
2. 调用CoinGecko API获取市值
   ↓
3. 获取1分钟K线数据（250根）
   ↓
4. 计算ATR年化波动率
   ↓
5. 计算ADX趋势强度
   ↓
6. LeverageManager计算最优杠杆
   ↓
7. 添加到交易对列表（默认EMA_ADVANCED策略）
   ↓
8. Telegram通知新增详情
```

### 交易信号生成流程

```
1. WebSocket接收K线数据
   ↓
2. 根据strategy_type选择策略
   ↓
3. EMA_ADVANCED: 检查5个开仓条件
   ↓
4. 所有条件满足 → 生成交易信号
   ↓
5. 计算下单数量（基于账户余额10%）
   ↓
6. 使用动态杠杆开仓
   ↓
7. 设置初始止损（2%）
```

### 止损管理流程

```
1. 每5秒检查持仓
   ↓
2. 计算当前盈亏百分比
   ↓
3. 判断是否触发级别提升
   ↓
4. Level 3: 执行50%部分平仓 + 追踪止损
   ↓
5. 追踪止损：价格创新高 → 止损上移
   ↓
6. 回撤1.5% → 触发剩余仓位平仓
```

---

## 🚀 使用说明

### 运行数据库迁移

```bash
cd binance-futures-bot
sqlite3 data/bot.db < migrations/add_leverage_strategy_fields.sql
```

### 启动机器人

```bash
python -m app.main
```

### 配置策略类型

可在数据库中手动修改现有交易对的策略类型：

```sql
-- 切换为高级策略
UPDATE trading_pairs SET strategy_type = 'EMA_ADVANCED' WHERE symbol = 'BTCUSDT';

-- 切换为基础策略
UPDATE trading_pairs SET strategy_type = 'EMA_BASIC' WHERE symbol = 'ETHUSDT';
```

### 查看杠杆信息

```sql
SELECT
    symbol,
    market_cap_tier,
    market_cap_usd,
    base_leverage,
    current_leverage,
    atr_volatility
FROM trading_pairs
WHERE is_active = 1;
```

---

## ⚠️ 注意事项

1. **CoinGecko API限制**：
   - 免费版：50次/分钟
   - 已实现1小时缓存机制
   - 获取市值失败时使用保守杠杆5x

2. **部分平仓限制**：
   - 每个仓位仅执行一次50%部分平仓
   - 部分平仓后`is_partial_closed`标记为True

3. **策略切换**：
   - 仅对新开仓位生效
   - 现有持仓保持原策略不变

4. **振幅过滤**：
   - 原有的7%振幅过滤功能**保留**
   - 24H涨跌幅30%监控功能**保留**

---

## 📈 预期效果

### 风险控制提升
- ✅ 根据市值动态调整杠杆，降低高风险币种爆仓概率
- ✅ 4级止损保护，最大程度锁定利润
- ✅ 部分平仓策略，50%落袋为安

### 信号质量提升
- ✅ 5个条件过滤，减少震荡市场假信号
- ✅ ADX趋势强度验证，仅捕捉强趋势机会
- ✅ 成交量确认，避免流动性不足陷阱

### 盈利能力提升
- ✅ 超大市值币种使用20-25x杠杆，放大收益
- ✅ 追踪止损跟随价格上涨，最大化盈利空间
- ✅ 部分平仓+追踪止损组合，兼顾安全与收益

---

## 🐛 故障排查

### 问题1：CoinGecko API请求失败
**解决方案**：
```python
# 检查网络连接
# 查看日志：Unable to get market cap data
# 系统会自动使用保守杠杆5x
```

### 问题2：部分平仓失败
**解决方案**：
```python
# 检查仓位数量是否足够
# 查看Binance API错误信息
# 即使部分平仓失败，止损仍会正常设置
```

### 问题3：策略不生效
**解决方案**：
```sql
-- 检查策略类型配置
SELECT symbol, strategy_type FROM trading_pairs WHERE symbol = 'BTCUSDT';

-- 确认K线数据充足（高级策略需要 200+25+14+2 = 241根K线）
```

---

## 📞 技术支持

如有问题，请查看日志文件：
- 应用日志：`logs/app.log`
- 错误日志：查看控制台输出

关键日志关键词：
- `[LeverageManager]` - 杠杆计算相关
- `[TrailingStopManager]` - 止损调整相关
- `[CoinGecko]` - 市值获取相关
- `部分平仓` - 部分平仓操作

---

## 🎉 升级完成！

所有新功能已集成完毕，机器人将自动：
- ✅ 为新币种计算动态杠杆
- ✅ 使用高级策略筛选信号
- ✅ 在达到4%盈利时部分平仓
- ✅ 追踪止损保护剩余利润

祝交易顺利！🚀📈
