import os
from tinydb import TinyDB, Query

# set up tinydb in powershell to run either dev or prod.
ENV = os.environ.get("ENV", "prod")
db_path = "test_db.json" if ENV == "dev" else os.environ.get("TINYDB_PATH", "db.json")
db = TinyDB(db_path)
# define a query
User_Query = Query()

# --- Symbol data cache (use single root-level cache file)
symbol_db = TinyDB('symbol_cache.json')
Symbol_Query = Query()