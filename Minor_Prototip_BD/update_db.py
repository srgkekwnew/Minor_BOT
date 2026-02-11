# update_db.py
import asyncio
from init_db import init_db

async def main():
    await init_db()
    print("✅ База данных обновлена!")

if __name__ == "__main__":
    asyncio.run(main())