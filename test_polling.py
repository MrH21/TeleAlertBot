import asyncio
from bot import create_application
from core.alerts import start_scheduler
from core.scheduler import start_msg_scheduler

def main():
    app = create_application()
   
    asyncio.get_event_loop().run_until_complete(start_scheduler(app))
    
    app.run_polling()

if __name__ == "__main__":
    main()
    
 
   