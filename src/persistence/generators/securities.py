from config.settings import get_settings
from persistence.models import AssetClass

ETF_TICKERS = {"SPY", "IEF", "TLT", "SHY"}
CRYPTO_TICKERS = {"BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"}

# Government-bond ETFs, weighted heavier for collateral generation since
# Treasuries are the realistic "eligible collateral" asset class.
TREASURY_ETF_TICKERS = {"IEF", "TLT", "SHY"}


def asset_class_for(ticker: str) -> AssetClass:
    if ticker in CRYPTO_TICKERS:
        return AssetClass.CRYPTO
    if ticker in ETF_TICKERS:
        return AssetClass.ETF
    return AssetClass.EQUITY


def securities_universe() -> list[str]:
    return get_settings().market_universe_list
