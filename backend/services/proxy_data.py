"""Proxy data manager — downloads and caches S&P 500 OHLCV via yfinance."""
from __future__ import annotations

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.correlation import ProxyPrice


SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


class ProxyDataManager:
    DEFAULT_PERIOD = "2y"

    def update(self, db: Session, max_tickers: int | None = None) -> int:
        """Fetch S&P 500 constituent list, download OHLCV via yfinance, upsert into DB.
        Returns total rows upserted."""
        if max_tickers is None:
            max_tickers = get_settings().PROXY_DATA_TICKERS

        # 1. Fetch S&P 500 tickers from Wikipedia
        tables = pd.read_html(SP500_URL)
        tickers: list[str] = tables[0]["Symbol"].tolist()
        # yfinance uses '-' not '.' in tickers (e.g. BRK-B not BRK.B)
        tickers = [t.replace(".", "-") for t in tickers]
        tickers = sorted(tickers)[:max_tickers]

        # 2. Download OHLCV
        raw = yf.download(
            tickers,
            period=self.DEFAULT_PERIOD,
            auto_adjust=True,
            progress=False,
        )

        # 3. Flatten and upsert
        # raw has MultiIndex columns: (field, ticker)
        count = 0
        for ticker in tickers:
            try:
                ticker_df = raw.xs(ticker, axis=1, level=1) if len(tickers) > 1 else raw
            except KeyError:
                continue  # ticker had no data
            for date_idx, row in ticker_df.iterrows():
                date_str = str(date_idx.date()) if hasattr(date_idx, "date") else str(date_idx)
                existing = db.get(ProxyPrice, (ticker, date_str))
                if existing is None:
                    pp = ProxyPrice(
                        ticker=ticker,
                        date=date_str,
                        open=_safe_float(row.get("Open")),
                        high=_safe_float(row.get("High")),
                        low=_safe_float(row.get("Low")),
                        close=_safe_float(row.get("Close")),
                        volume=_safe_int(row.get("Volume")),
                    )
                    db.add(pp)
                else:
                    existing.open = _safe_float(row.get("Open"))
                    existing.high = _safe_float(row.get("High"))
                    existing.low = _safe_float(row.get("Low"))
                    existing.close = _safe_float(row.get("Close"))
                    existing.volume = _safe_int(row.get("Volume"))
                count += 1
        db.commit()
        return count

    def get_panel(self, db: Session) -> pd.DataFrame:
        """Read all proxy_prices rows. Returns MultiIndex (date, ticker) DataFrame."""
        rows = db.query(ProxyPrice).all()
        if not rows:
            idx = pd.MultiIndex.from_tuples([], names=["date", "ticker"])
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"], index=idx
            )
        records = [
            {
                "date": r.date,
                "ticker": r.ticker,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]
        df = pd.DataFrame.from_records(records)
        df = df.set_index(["date", "ticker"]).sort_index()
        return df


def _safe_float(val) -> float | None:
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> int | None:
    try:
        f = float(val)
        return None if pd.isna(f) else int(f)
    except (TypeError, ValueError):
        return None
