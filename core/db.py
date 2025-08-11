import os
from tinydb import TinyDB, Query, where

# set up tinydb in powershell to run either dev or prod.
ENV = os.environ.get("ENV", "prod")
db_path = "test_db.json" if ENV == "dev" else os.environ.get("TINYDB_PATH", "db.json")
db = TinyDB(db_path)
User = Query()
