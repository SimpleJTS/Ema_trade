"""
CoinGecko API集成
用于获取加密货币市值信息
"""
import logging
import aiohttp
from typing import Optional, Dict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CoinGeckoAPI:
    """CoinGecko API客户端"""

    def __init__(self):
        self.base_url = "https://api.coingecko.com/api/v3"
        self._cache: Dict[str, Dict] = {}  # 市值缓存
        self._cache_ttl = timedelta(hours=1)  # 缓存1小时

    def _binance_symbol_to_coingecko_id(self, binance_symbol: str) -> str:
        """转换币安交易对到CoinGecko ID

        Args:
            binance_symbol: 币安交易对，如 "BTCUSDT"

        Returns:
            CoinGecko ID，如 "bitcoin"
        """
        # 移除USDT后缀
        base_symbol = binance_symbol.replace("USDT", "").lower()

        # 常见币种映射
        symbol_mapping = {
            "btc": "bitcoin",
            "eth": "ethereum",
            "bnb": "binancecoin",
            "sol": "solana",
            "xrp": "ripple",
            "ada": "cardano",
            "avax": "avalanche-2",
            "doge": "dogecoin",
            "dot": "polkadot",
            "matic": "matic-network",
            "shib": "shiba-inu",
            "link": "chainlink",
            "atom": "cosmos",
            "ltc": "litecoin",
            "uni": "uniswap",
            "etc": "ethereum-classic",
            "xlm": "stellar",
            "near": "near",
            "algo": "algorand",
            "ape": "apecoin",
            "axs": "axie-infinity",
            "sand": "the-sandbox",
            "mana": "decentraland",
            "ftm": "fantom",
            "egld": "elrond-erd-2",
            "xtz": "tezos",
            "aave": "aave",
            "theta": "theta-token",
            "fil": "filecoin",
            "hbar": "hedera-hashgraph",
            "eos": "eos",
            "mkr": "maker",
            "grt": "the-graph",
            "bch": "bitcoin-cash",
            "qnt": "quant-network",
            "ar": "arweave",
            "icp": "internet-computer",
            "stx": "blockstack",
            "inj": "injective-protocol",
            "rune": "thorchain",
            "ldo": "lido-dao",
            "op": "optimism",
            "arb": "arbitrum",
            "sui": "sui",
            "pepe": "pepe",
            "tao": "bittensor",
            "ondo": "ondo-finance",
            "wld": "worldcoin-wld",
        }

        return symbol_mapping.get(base_symbol, base_symbol)

    async def get_coin_market_data(self, binance_symbol: str) -> Optional[Dict]:
        """获取币种市值数据

        Args:
            binance_symbol: 币安交易对，如 "BTCUSDT"

        Returns:
            {
                "market_cap_usd": float,  # 市值（美元）
                "market_cap_rank": int,   # 市值排名
                "price": float,           # 当前价格
                "volume_24h": float,      # 24小时交易量
                "circulating_supply": float,  # 流通量
            }
        """
        # 检查缓存
        if binance_symbol in self._cache:
            cached_data = self._cache[binance_symbol]
            if datetime.now() - cached_data["cached_at"] < self._cache_ttl:
                logger.debug(f"[{binance_symbol}] 使用缓存的市值数据")
                return cached_data["data"]

        coingecko_id = self._binance_symbol_to_coingecko_id(binance_symbol)

        try:
            url = f"{self.base_url}/coins/{coingecko_id}"
            params = {
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        market_data = data.get("market_data", {})

                        result = {
                            "market_cap_usd": market_data.get("market_cap", {}).get("usd", 0),
                            "market_cap_rank": data.get("market_cap_rank", 999),
                            "price": market_data.get("current_price", {}).get("usd", 0),
                            "volume_24h": market_data.get("total_volume", {}).get("usd", 0),
                            "circulating_supply": market_data.get("circulating_supply", 0),
                        }

                        # 缓存结果
                        self._cache[binance_symbol] = {
                            "data": result,
                            "cached_at": datetime.now()
                        }

                        logger.info(f"[{binance_symbol}] 获取市值: ${result['market_cap_usd']:,.0f} (排名#{result['market_cap_rank']})")
                        return result
                    elif response.status == 404:
                        logger.warning(f"[{binance_symbol}] CoinGecko未找到币种ID: {coingecko_id}")
                        return None
                    else:
                        logger.error(f"[{binance_symbol}] CoinGecko API错误: {response.status}")
                        return None

        except aiohttp.ClientError as e:
            logger.error(f"[{binance_symbol}] CoinGecko API请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"[{binance_symbol}] 获取市值数据异常: {e}")
            return None

    def get_market_cap_tier(self, market_cap_usd: float) -> int:
        """根据市值判断层级

        Args:
            market_cap_usd: 市值（美元）

        Returns:
            1: 超大市值 (>1万亿)
            2: 大/中市值 (100亿-1万亿)
            3: 小市值 (<100亿)
            4: 新兴/低流动性 (<10亿)
        """
        if market_cap_usd >= 1_000_000_000_000:  # >= 1万亿
            return 1
        elif market_cap_usd >= 10_000_000_000:  # >= 100亿
            return 2
        elif market_cap_usd >= 1_000_000_000:   # >= 10亿
            return 3
        else:
            return 4

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
        logger.info("CoinGecko缓存已清空")


# 全局实例
coingecko_api = CoinGeckoAPI()
