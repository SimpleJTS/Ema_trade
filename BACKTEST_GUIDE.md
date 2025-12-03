# 📈 策略回测指南

## 🎯 回测脚本说明

我已经为你创建了一个完整的回测脚本 `backtest.py`，可以回测**EMA高级策略**在历史数据上的表现。

---

## 🚀 快速开始

### 在本地运行（推荐）

```bash
cd ~/Ema_trade/binance-futures-bot

# 安装pandas（回测需要）
pip install pandas

# 运行回测（示例：回测BTCUSDT最近7天）
python backtest.py
```

### 在Docker容器中运行

```bash
# 进入容器
docker exec -it binance-futures-bot bash

# 安装pandas
pip install pandas

# 运行回测
python /app/backtest.py
```

---

## 📝 回测参数配置

### 方法1：修改脚本底部（推荐新手）

编辑 `backtest.py` 最后几行：

```python
if __name__ == "__main__":
    asyncio.run(run_backtest(
        symbol="BTCUSDT",      # 交易对
        days=7,                # 回测天数
        initial_balance=1000.0, # 初始资金（USDT）
        leverage=10            # 杠杆倍数
    ))
```

### 方法2：创建自定义回测脚本

```python
# my_backtest.py
import asyncio
from backtest import run_backtest

async def main():
    # 回测多个币种
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    for symbol in symbols:
        print(f"\n{'='*80}")
        print(f"回测 {symbol}")
        print(f"{'='*80}\n")

        await run_backtest(
            symbol=symbol,
            days=30,              # 回测30天
            initial_balance=1000, # 初始1000U
            leverage=10           # 10倍杠杆
        )

asyncio.run(main())
```

---

## 📊 回测结果解读

### 输出示例

```
==============================================================
回测结果
==============================================================
初始资金: 1000.00 USDT
最终资金: 1250.50 USDT
总盈亏: 250.50 USDT (25.05%)
--------------------------------------------------------------
总交易次数: 45
盈利次数: 28
亏损次数: 17
胜率: 62.22%
--------------------------------------------------------------
平均盈利: 15.30 USDT
平均亏损: -8.50 USDT
盈亏比: 1.80
最大回撤: 8.50%
==============================================================
```

### 关键指标说明

| 指标 | 说明 | 理想值 |
|------|------|--------|
| **总盈亏** | 回测期间的总盈亏金额和百分比 | > 0 |
| **胜率** | 盈利交易占总交易的比例 | > 50% |
| **盈亏比** | 平均盈利/平均亏损 | > 1.5 |
| **最大回撤** | 从最高点到最低点的最大跌幅 | < 20% |

### 评估标准

✅ **优秀策略**：
- 胜率 > 55%
- 盈亏比 > 2.0
- 最大回撤 < 15%

⚠️ **需要优化**：
- 胜率 < 45%
- 盈亏比 < 1.2
- 最大回撤 > 25%

---

## 🔍 回测功能特性

### 1. 完整的交易模拟

- ✅ **开仓信号识别**：使用EMA高级策略（9/72/200 + ADX + 成交量）
- ✅ **初始止损**：固定2%
- ✅ **4级止损止盈**：
  - Level 1: 盈利≥1.8% → 保本
  - Level 2: 盈利≥2.5% → 锁定1.9%
  - Level 3: 盈利≥4.0% → 50%部分平仓 + 1.5%追踪止损
- ✅ **追踪止损**：Level 3后，止损价随价格上涨动态调整
- ✅ **杠杆计算**：真实模拟10x杠杆的盈亏

### 2. 自动导出交易明细

回测完成后会自动生成CSV文件：

```
backtest_BTCUSDT_7days_20231203_123456.csv
```

CSV包含每笔交易的详细信息：
- 开仓/平仓时间
- 开仓/平仓价格
- 盈亏金额和百分比
- 止损级别
- 是否部分平仓

### 3. 实时日志输出

回测过程中会输出详细日志：

```
[2023-12-03 09:30:00] 开仓 BTCUSDT LONG @42150.50, 数量=0.0237, 止损=41267.49
[2023-12-03 10:15:00] BTCUSDT 触发Level 1: 盈利1.85%, 止损移至保本
[2023-12-03 11:30:00] BTCUSDT 触发Level 3: 盈利4.2%, 部分平仓50%, 盈利10.50 USDT
[2023-12-03 12:00:00] 平仓 BTCUSDT LONG @43800.00, 盈亏=16.80 USDT (1.68%), 原因=STOP_LOSS
```

---

## 🎛️ 高级配置

### 修改回测参数

编辑 `backtest.py` 中的 `Backtest` 类初始化参数：

```python
backtest = Backtest(
    initial_balance=1000.0,      # 初始资金
    position_size_percent=10.0,   # 单次开仓占总资金比例（10%）
    leverage=10,                  # 杠杆倍数
    stop_loss_percent=2.0         # 初始止损百分比
)
```

### 回测不同周期

```python
# 回测最近1天（1440根1分钟K线）
await run_backtest(symbol="BTCUSDT", days=1)

# 回测最近1周
await run_backtest(symbol="BTCUSDT", days=7)

# 回测最近1个月
await run_backtest(symbol="BTCUSDT", days=30)

# 回测最近3个月
await run_backtest(symbol="BTCUSDT", days=90)
```

### 回测多个币种

```python
import asyncio
from backtest import run_backtest

async def multi_symbol_backtest():
    symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "ADAUSDT"
    ]

    results = {}

    for symbol in symbols:
        stats = await run_backtest(
            symbol=symbol,
            days=30,
            initial_balance=1000,
            leverage=10
        )
        results[symbol] = stats

    # 打印汇总
    print("\n" + "="*80)
    print("回测汇总")
    print("="*80)
    for symbol, stats in results.items():
        print(f"{symbol:12} | 收益率: {stats['return_percent']:>7.2f}% | "
              f"胜率: {stats['win_rate']:>6.2f}% | "
              f"盈亏比: {stats['profit_factor']:>5.2f}")

asyncio.run(multi_symbol_backtest())
```

---

## 📉 回测注意事项

### 1. 历史数据限制

- 币安API限制：每次最多获取1000根K线
- 脚本会自动分批获取，但很久以前的数据可能无法获取
- 建议回测周期：**7-90天**

### 2. 回测与实盘差异

**回测不包括：**
- ❌ 滑点（实盘下单价格与预期价格的偏差）
- ❌ 手续费（币安合约手续费约0.04%）
- ❌ 资金费率（持仓过夜需要支付或收取资金费）
- ❌ 网络延迟（信号产生到下单完成的时间差）
- ❌ 部分成交（市场流动性不足导致无法完全成交）

**因此：**
- ✅ 回测收益 > 实盘收益（通常高10-30%）
- ✅ 回测胜率 > 实盘胜率
- ✅ 回测是**乐观估计**，实盘需谨慎

### 3. 过拟合风险

如果你根据回测结果不断调整参数：
- ⚠️ 可能导致策略过度拟合历史数据
- ⚠️ 未来表现可能与回测差异巨大
- ✅ 建议：在不同时间段、不同币种上测试策略稳定性

### 4. 市场环境变化

- 📈 牛市：趋势策略表现好
- 📉 熊市：震荡市假信号多
- 🔄 震荡市：胜率降低，需要调整参数

---

## 🔧 故障排查

### 问题1：获取历史数据失败

**错误信息**：
```
获取K线数据失败: Connection error
```

**解决方案**：
```bash
# 检查网络连接
ping api.binance.com

# 如果在Docker内，检查DNS
docker exec binance-futures-bot ping -c 3 api.binance.com

# 可能需要重试几次
```

### 问题2：pandas未安装

**错误信息**：
```
ModuleNotFoundError: No module named 'pandas'
```

**解决方案**：
```bash
pip install pandas
```

### 问题3：K线数据不足

**错误信息**：
```
K线数据不足，无法进行回测
```

**解决方案**：
- 减少回测天数
- 检查币种是否在币安存在
- 某些新上线的币种历史数据较少

### 问题4：回测运行很慢

**原因**：
- 回测天数过长（如90天 = 129,600根K线）
- 逐根K线分析计算量大

**解决方案**：
- 减少回测天数
- 或在本地运行（比Docker快）

---

## 📊 回测结果分析建议

### 1. 多周期验证

```python
# 测试不同周期的稳定性
for days in [7, 14, 30, 60]:
    stats = await run_backtest("BTCUSDT", days=days)
    print(f"{days}天收益率: {stats['return_percent']:.2f}%")
```

### 2. 多币种验证

```python
# 测试策略在不同币种的表现
for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    stats = await run_backtest(symbol, days=30)
    print(f"{symbol} 胜率: {stats['win_rate']:.2f}%")
```

### 3. 不同杠杆对比

```python
# 测试不同杠杆的影响
for leverage in [5, 10, 15, 20]:
    stats = await run_backtest("BTCUSDT", days=30, leverage=leverage)
    print(f"{leverage}x杠杆 收益/回撤: {stats['return_percent']:.2f}% / {stats['max_drawdown']:.2f}%")
```

---

## 💡 使用建议

### 新手用户

1. **先回测主流币种**（BTC、ETH）7-14天
2. **观察胜率和盈亏比**
3. **如果胜率>50%，盈亏比>1.5，可以考虑小资金实盘测试**

### 进阶用户

1. **回测多个币种，找出表现最好的**
2. **分析亏损交易，找出策略弱点**
3. **调整止损止盈参数，对比回测结果**
4. **用不同时间段验证策略稳定性**

### 专业用户

1. **编写自动化回测脚本，批量测试**
2. **导出CSV分析交易明细**
3. **计算夏普比率、索提诺比率等高级指标**
4. **考虑加入手续费、滑点等真实成本**

---

## 📝 示例：完整回测流程

```bash
# 1. 进入项目目录
cd ~/Ema_trade/binance-futures-bot

# 2. 确保依赖已安装
pip install pandas

# 3. 运行回测
python backtest.py

# 4. 查看生成的CSV文件
ls -lh backtest_*.csv

# 5. 用Excel或Numbers打开CSV分析
# 或者在Linux上用cat查看
cat backtest_BTCUSDT_7days_*.csv
```

---

## 🎉 完成！

现在你可以：
- ✅ 回测任意币种、任意周期的策略表现
- ✅ 导出详细的交易记录进行分析
- ✅ 对比不同参数下的策略效果
- ✅ 验证策略的稳定性和可靠性

**重要提醒**：
- 📊 回测结果仅供参考，不代表未来表现
- 💰 实盘交易请小资金测试
- ⚠️ 加密货币市场高风险，注意风控

祝回测顺利！📈🚀
