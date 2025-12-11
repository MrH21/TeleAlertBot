import time
import io
from tinydb import TinyDB, Query


# --- Whale transactions cache ---
recent_whales_cache: list[dict] = []
user_sent_whales: dict[int, set] = {} # key=user_id, value= set of hashes
MAX_WHALE_CACHE = 50
# --- Symbol data cache ---
CACHE_TTL = 60 * 55       # seconds - 55 minutes

class CachedSymbolData:
    def __init__(self, path="symbol_cache.json"):
        self.db = TinyDB(path)
        self.table = self.db.table("cache")
        self.q = Query()

    # convert base64 to chart image
    def convert_to_image(self, symbol):
        row = self.retreive_last(symbol)
        if not row:
            return None
        return row["chart"]

    # saving the processed indicators data into the cache
    def save_data(self, symbol, process_indicators, create_price_chart_with_levels):
        '''
        saving the processed indicators data into the cache
        '''
        processed = process_indicators(symbol)

        timestamp = int(time.time() // 3600 * 3600)  # round down to nearest hour

        chart_str = create_price_chart_with_levels(symbol)
        
        entry = {
            "symbol": symbol,
            "timestamp": timestamp,
            # Store each component of processed dict
            "macd": processed["macd"],
            "signal": processed["signal"],
            "macd_trend": processed["macd_trend"],
            "macd_insight": processed["macd_insight"],
            "rsi": processed["rsi"],
            "rsi_insight": processed["rsi_insight"],
            "trend": processed["trend"],
            "ema_200": processed["ema_200"],
            "ema_insight": processed["ema_insight"],
            "sr_insight": processed["sr_insight"],
            "overall": processed["overall"],
            "confidence": processed["confidence"],
            "chart": chart_str
        }

        self.table.insert(entry)

    # retrieve the last processed indicators data from the cache
    def retreive_last(self, symbol):
        '''
        retreive the last processed indicators data from the cache
        '''
        rows = self.table.search(self.q.symbol == symbol)
        if not rows:
            return None
        # Get the most recent entry based on timestamp
        latest_entry = max(rows, key=lambda x: x["timestamp"])
        return latest_entry
    


