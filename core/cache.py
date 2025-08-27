# --- Whale transactions cache ---
recent_whales_cache: list[dict] = []
user_sent_whales: dict[int, set] = {} # key=user_id, value= set of hashes
MAX_WHALE_CACHE = 50
