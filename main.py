"""
Entry point for AI Trading Signal Bot
"""
from core.main import main

if __name__ == "__main__":
    import asyncio
    import sys
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user")
    except Exception as e:
        print(f"Bot crashed: {e}")
        sys.exit(1)
