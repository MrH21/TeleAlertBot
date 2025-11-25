import pandas as pd
import pandas_ta as ta
import numpy as np
from ripple.xrp_functions import get_candles
from core.db import db, User_Query
from sklearn.cluster import MiniBatchKMeans

# --- Get key levels using ML clustering ---
def get_key_levels(symbol, interval="1h", clusters=6):
    candles = get_candles(symbol,interval)
    latest_close = candles[-1][2]  # last candle's close price
    
    prices = []
    weights = []
    VOLUME_SCALE = 50_000_000
    
    for _, _, h, l, _, v in candles:
        prices.extend([h, l])
        weight = np.log1p(v / VOLUME_SCALE)
        weights.extend([weight, weight]) # weighting for h and l by volume
        
    prices = np.array(prices).reshape(-1,1)
    weights = np.array(weights)
    
    # run MiniBatchKMeans
    kmeans = MiniBatchKMeans(n_clusters=clusters, random_state=0, n_init=10,batch_size=256)
    kmeans.fit(prices,sample_weight=weights)
    
    levels = sorted(kmeans.cluster_centers_.flatten())
    levels = [round(l, 4) for l in levels]
    
    # Split into support/resistance based on latest close
    support = [lvl for lvl in levels if lvl < latest_close]
    resistance = [lvl for lvl in levels if lvl > latest_close]

    return latest_close, support, resistance


# --- Process the rsi data ---
def process_indicators(ticker):
    try:
        symbol = ticker.upper()
        # Extract the candle data from exchange
        candles = get_candles(symbol=symbol, interval="1h", limit=1000)
        
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["close"] = df["close"].astype(float)
        
        # Calculate RSI
        df["rsi"] = ta.rsi(df["close"], length=14)
        
        # Calculate MACD
        macd_data = ta.macd(df["close"], fast=12, slow=26, signal=9)
        df["macd"] = macd_data["MACD_12_26_9"]
        df["macd_signal"] = macd_data["MACDs_12_26_9"]
        
        # Calculate EMA
        df["ema_200"] = ta.ema(df["close"], length=200)
        
        # extract last values
        last_rsi = df["rsi"].iloc[-1]
        last_macd = df["macd"].iloc[-1]     
        last_macd_signal = df["macd_signal"].iloc[-1]
        last_ema_200 = df["ema_200"].iloc[-1]
        last_close = df["close"].iloc[-1]
        
        # --- MACD Insight ---
        if last_macd > last_macd_signal:
            macd_trend = "Bullish"
            if last_macd < 0 and last_macd_signal < 0:
                macd_insight = "Momentum improving, though the market remains weak — early bullish shift."
            elif last_macd > 0 and last_macd_signal > 0:
                macd_insight = "Momentum strong and sustained in bullish territory — trend confirmation."
            else:
                macd_insight = "Momentum turning upward — potential start of a new uptrend."
        else:
            macd_trend = "Bearish"
            if last_macd > 0 and last_macd_signal > 0:
                macd_insight = "Momentum fading within the positive zone — early bearish reversal risk."
            elif last_macd < 0 and last_macd_signal < 0:
                macd_insight = "Bearish momentum persisting — sellers currently dominant."
            else:
                macd_insight = "Momentum turning downward — possible short-term correction."

        # --- RSI Insight ---
        if last_rsi > 70:
            rsi_insight = "RSI above 70 — overbought zone, suggesting potential exhaustion."
        elif last_rsi < 30:
            rsi_insight = "RSI below 30 — oversold zone, suggesting potential rebound conditions."
        else:
            rsi_insight = "RSI in neutral territory — no strong momentum extremes."

        # --- EMA-200 Trend ---
        if last_close > last_ema_200:
            trend = "Uptrend"
            ema_insight = (
                f"Price (${last_close:.4f}) is above moving average (${last_ema_200:.4f}) — long-term trend remains upward."
            )
        else:
            trend = "Downtrend"
            ema_insight = (
                f"Price (${last_close:.4f}) is below moving average (${last_ema_200:.4f}) — long-term trend remains downward."
            )
            
        # get ML timeframe and key levels
        close, support, resistance = get_key_levels(symbol=ticker)
        support_str = [f"${lvl:.4f}" for lvl in support]
        resistance_str = [f"${lvl:.4f}" for lvl in resistance]
        # Join them for display
        support_text = ", ".join(support_str)
        resistance_text = ", ".join(resistance_str)
        sr_insight = f"Key support levels: {support_text}\nKey resistance levels: {resistance_text}"
        
        # Find nearest key levels to current price  
        if support:
            nearest_support = min(support, key=lambda x: abs(x - last_close))
        else:
            nearest_support = last_close

        if resistance:
            nearest_resistance = min(resistance, key=lambda x: abs(x - last_close))
        else:
            nearest_resistance = last_close

        dist_to_support = abs(last_close - nearest_support) / last_close
        dist_to_resistance = abs(nearest_resistance - last_close) / last_close
        
        near_threshold = 0.005   # 0.5%
        moderate_threshold = 0.015  # 1.5%

        if nearest_resistance > last_close and dist_to_resistance < near_threshold:
            if macd_trend == "Bullish" and last_rsi < 70:
                sr_insight = (
                    f"Price (${last_close:.4f}) is nearing resistance at ${nearest_resistance:.4f}. "
                    "Momentum remains positive — potential breakout zone."
                )
            else:
                sr_insight = (
                    f"Price (${last_close:.4f}) is approaching resistance at ${nearest_resistance:.4f}. "
                    "Momentum appears to be cooling — watch for possible rejection."
                )

        elif nearest_support < last_close and dist_to_support < near_threshold:
            if macd_trend == "Bearish" and last_rsi > 30:
                sr_insight = (
                    f"Price (${last_close:.4f}) is nearing support at ${nearest_support:.4f}. "
                    "Selling pressure remains, but a rebound could form if buyers return."
                )
            else:
                sr_insight = (
                    f"Price (${last_close:.4f}) is approaching support at ${nearest_support:.4f}. "
                    "Momentum stabilizing — potential bounce zone."
                )

        elif nearest_resistance > last_close and dist_to_resistance < moderate_threshold:
            sr_insight = (
                f"Price (${last_close:.4f}) is within range of resistance at ${nearest_resistance:.4f}. "
                "Monitor for breakout confirmation or pullback."
            )

        elif nearest_support < last_close and dist_to_support < moderate_threshold:
            sr_insight = (
                f"Price (${last_close:.4f}) is within range of support at ${nearest_support:.4f}. "
                "Market may test this level again soon."
            )

        else:
            sr_insight = (
                f"Price (${last_close:.4f}) is trading comfortably between key support "
                f"(${nearest_support:.4f}) and resistance (${nearest_resistance:.4f}) levels — "
                "trend structure intact."
            )

            
        # --- Confidence Scoring ---
        score = 0

        # RSI
        if 40 <= last_rsi <= 60:
            score += 2
        elif 60 < last_rsi < 70:
            score += 3
        elif 30 < last_rsi < 40:
            score += 1
        else:
            score -= 2

        # MACD alignment
        if macd_trend == "Bullish" and last_macd > 0:
            score += 3
        elif macd_trend == "Bullish":
            score += 2
        elif macd_trend == "Bearish" and last_macd < 0:
            score -= 2
        elif abs(last_macd - last_macd_signal) < 0.0005:
            score += 0  # Neutral — trend undecided

        # EMA trend bias
        ema_diff = abs((last_close - last_ema_200) / last_ema_200)
        if trend == "Uptrend":
            # If price is above EMA, stronger confidence the further it is above
            if ema_diff > 0.02:
                score += 2  # clear uptrend, strong distance from EMA
            else:
                score += 1  # mild uptrend, price close to EMA line
        else:
            # If price below EMA, stronger negative bias the further it is below
            if ema_diff > 0.02:
                score -= 2  # clear downtrend, strong distance below EMA
            else:
                score -= 1  # mild downtrend, price near EMA — could flip soon
            
        # ML key levels
        if "breakout" in sr_insight.lower():
            score += 1
        elif "rejection" in sr_insight.lower() or "selling pressure" in sr_insight.lower():
            score -= 1

        # Normalize score 0–10
        confidence = (max(0, min(10, score + 5)))

        # --- Overall Signal ---
        if trend == "Uptrend" and macd_trend == "Bullish" and last_rsi < 70:
            overall = "BUY"
        elif trend == "Downtrend" and macd_trend == "Bearish" and last_rsi > 30:
            overall = "SELL"
        else:
            overall = "NEUTRAL"

        return {
            "macd": last_macd,
            "signal": last_macd_signal,
            "macd_trend": macd_trend,
            "macd_insight": macd_insight,
            "rsi": last_rsi,
            "rsi_insight": rsi_insight,
            "trend": trend,
            "ema_200": last_ema_200,
            "ema_insight": ema_insight,
            "sr_insight": sr_insight,
            "overall": overall,
            "confidence": confidence
        }

        
    except Exception as e:
        print(f"Error processing indicators: {e}")
        return {}