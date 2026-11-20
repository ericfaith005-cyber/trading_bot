"""
Technical Indicators calculation module for AI Trading Bot.
Calculates RSI, MACD, Bollinger Bands, EMA, and ATR using pandas and numpy.
"""
import pandas as pd
import numpy as np

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / (loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calculate_bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0):
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = sma + (std * num_std)
    lower = sma - (std * num_std)
    return upper, sma, lower

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enriches candle DataFrame (columns: open, high, low, close, volume) with technical indicators.
    """
    res = df.copy()
    res['ema_9'] = calculate_ema(res['close'], 9)
    res['ema_21'] = calculate_ema(res['close'], 21)
    res['ema_50'] = calculate_ema(res['close'], 50)
    res['rsi_14'] = calculate_rsi(res['close'], 14)
    
    macd, macd_sig, macd_hist = calculate_macd(res['close'])
    res['macd'] = macd
    res['macd_signal'] = macd_sig
    res['macd_hist'] = macd_hist
    
    bb_up, bb_mid, bb_low = calculate_bollinger_bands(res['close'])
    res['bb_upper'] = bb_up
    res['bb_middle'] = bb_mid
    res['bb_lower'] = bb_low
    
    res['atr_14'] = calculate_atr(res)
    return res