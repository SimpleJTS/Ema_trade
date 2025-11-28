#!/usr/bin/env python3
"""
获取24小时涨跌幅绝对值超过30%的币种
无需API Key，因为这是公开接口
"""
import asyncio
import httpx


async def get_high_change_symbols(min_change_percent: float = 30.0):
    """获取24小时涨跌幅绝对值大于指定百分比的币种"""
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 获取所有交易对的24小时行情
        response = await client.get("https://fapi.binance.com/fapi/v1/ticker/24hr")
        response.raise_for_status()
        all_tickers = response.json()
    
    # 筛选USDT永续合约且涨跌幅绝对值 >= min_change_percent 的币种
    high_change = []
    for ticker in all_tickers:
        symbol = ticker.get("symbol", "")
        # 只看USDT永续合约
        if not symbol.endswith("USDT"):
            continue
        
        try:
            change_percent = float(ticker.get("priceChangePercent", 0))
            if abs(change_percent) >= min_change_percent:
                high_change.append({
                    "symbol": symbol,
                    "priceChangePercent": change_percent,
                    "lastPrice": float(ticker.get("lastPrice", 0)),
                    "highPrice": float(ticker.get("highPrice", 0)),
                    "lowPrice": float(ticker.get("lowPrice", 0)),
                    "volume": float(ticker.get("volume", 0)),
                    "quoteVolume": float(ticker.get("quoteVolume", 0)),
                })
        except (ValueError, TypeError):
            continue
    
    # 按涨跌幅绝对值降序排列
    high_change.sort(key=lambda x: abs(x["priceChangePercent"]), reverse=True)
    
    return high_change


async def main():
    min_change = 30.0  # 可以修改这个值
    
    print(f"\n🔍 正在获取24小时涨跌幅绝对值 >= {min_change}% 的币种...\n")
    
    symbols = await get_high_change_symbols(min_change)
    
    if not symbols:
        print(f"❌ 没有找到涨跌幅绝对值 >= {min_change}% 的币种")
        return
    
    print(f"✅ 找到 {len(symbols)} 个符合条件的币种:\n")
    print(f"{'交易对':<15} {'涨跌幅':>10} {'最新价':>15} {'24H成交额(USDT)':>20}")
    print("-" * 65)
    
    for s in symbols:
        change = s['priceChangePercent']
        change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
        volume_str = f"{s['quoteVolume']:,.0f}"
        print(f"{s['symbol']:<15} {change_str:>10} {s['lastPrice']:>15.8g} {volume_str:>20}")
    
    print("\n" + "=" * 65)
    
    # 分别显示涨幅和跌幅
    gainers = [s for s in symbols if s['priceChangePercent'] > 0]
    losers = [s for s in symbols if s['priceChangePercent'] < 0]
    
    if gainers:
        print(f"\n📈 涨幅超过 {min_change}% 的币种 ({len(gainers)} 个):")
        for s in gainers:
            print(f"   {s['symbol']}: +{s['priceChangePercent']:.2f}%")
    
    if losers:
        print(f"\n📉 跌幅超过 {min_change}% 的币种 ({len(losers)} 个):")
        for s in losers:
            print(f"   {s['symbol']}: {s['priceChangePercent']:.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
