"""
Entry point for AI Trading Signal Bot
"""
import sys
import os

# Add current directory to Python path to enable package imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
