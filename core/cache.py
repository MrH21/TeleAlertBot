import time
import io
from tinydb import TinyDB, Query
from indicators.data_processing import get_key_levels, create_price_chart_with_levels
from core.utilities import get_candles
from indicators.data_processing import process_indicators


# --- Whale transactions cache ---
recent_whales_cache: list[dict] = []
user_sent_whales: dict[int, set] = {} # key=user_id, value= set of hashes
MAX_WHALE_CACHE = 50

# --- Symbol data cache ---
symbol_db = TinyDB('core/symbol_cache.json')
Symbol = Query()

CACHE_TTL = 60 * 55       # seconds - 55 minutes

class CachedSymbolData:
    def __init__(self, symbol, candles, support, resistance, insights, chart_bytes, last_updated):

        self.symbol = symbol
        self.candles = candles
        self.support = support
        self.resistance = resistance  
        self.insights = insights  
        self.chart_bytes = chart_bytes
        self.last_updated = last_updated

    @property
    def chart(self):
        return io.BytesIO(self.chart_bytes)
    
    @property
    def caption(self):
        return f"📈 {self.symbol} — Last updated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(self.last_updated))}"
    
async def generate_and_store(symbol):
    candles = get_candles(symbol)                   
    support, resistance = get_key_levels(symbol)  
    insights = process_indicators(symbol)    
    chart = create_price_chart_with_levels(symbol, candles, support, resistance)

    # Convert chart to bytes if it's a Matplotlib fig
    if hasattr(chart, "savefig"):
        bio = io.BytesIO()
        chart.savefig(bio, format="png", dpi=200)
        bio.seek(0)
        chart_bytes = bio.read()
    else:
        chart_bytes = chart  # already bytes

    payload = {
        "symbol": symbol.upper(),
        "last_updated": int(time.time()),
        "candles": candles,
        "support": support,
        "resistance": resistance,
        "insights": insights,
        "chart": chart_bytes
    }

    symbol_db.upsert(payload, Symbol.symbol == symbol.upper())

    return CachedSymbolData(
        symbol,
        candles,
        support,
        resistance,
        insights,
        chart_bytes,
        payload["last_updated"]
    )


async def get_cahed_symbol(symbol):
    symbol = symbol.upper()
    record = symbol_db.get(Symbol.symbol == symbol)

    if record:
        age = time.time() - record["last_updated"]
        if age < CACHE_TTL:
            return CachedSymbolData(
                symbol,
                record["candles"],
                record["support"],
                record["resistance"],
                record["insights"],
                record["chart"],
                record["last_updated"]
            )

    # Cache miss or stale → regenerate
    return await generate_and_store(symbol)