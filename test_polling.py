import asyncio
from bot import create_application
from core.alerts import start_scheduler
'''
def main():
    app = create_application()
   
    asyncio.run(start_scheduler(app))
    
    app.run_polling()

if __name__ == "__main__":
    main()
    
'''
async def main():
    # Create the application
    app = create_application()  

    # --- Initialize the bot for async usage ---
    await app.initialize()

    # --- Start the scheduler concurrently ---
    asyncio.create_task(start_scheduler(app))

    # --- Start the bot ---
    await app.start()                 # starts the bot connection
    await app.updater.start_polling() # polling for updates

    # Keep the program running
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
   