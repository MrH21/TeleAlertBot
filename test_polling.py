from bot import create_application

if __name__ == "__main__":
    app = create_application()
    print("Running bot locally via polling...")
    app.run_polling()
