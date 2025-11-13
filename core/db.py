import os
from tinydb import TinyDB, Query

# set up tinydb in powershell to run either dev or prod.
ENV = os.environ.get("ENV", "prod")
db_path = "test_db.json" if ENV == "dev" else os.environ.get("TINYDB_PATH", "db.json")
db = TinyDB(db_path)
# define a query
User_Query = Query()


'''
# update my record
myID = os.environ.get("ADMIN_ID")

if myID is not None:
    try:
        myID = int(myID)
    except ValueError:
        pass  # fallback to string if conversion fails

db.update({'plan': 'premium',
           'trial_expiry': '2030-09-22T13:36:34.561237+00:00',
           'subscriber': True}, User_Query.user_id == myID)
'''