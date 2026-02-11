"""
Инициализация базы данных и модели
"""
import asyncio
import enum
import os
import shutil
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Enum, Float, select, update, text

# ===========================================
# Определение Enum для типов медиа
# ===========================================
class MediaType(enum.Enum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    VOICE = "voice"
    DOCUMENT = "document"

Base = declarative_base()

# ===========================================
# МОДЕЛИ БАЗЫ ДАННЫХ
# ===========================================
class Category(Base):
    __tablename__ = 'categories'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Статистика чтения для категории
    total_reading_time = Column(Float, default=0.0, nullable=True)
    reading_sessions_count = Column(Integer, default=0, nullable=True)
    last_read_at = Column(DateTime, nullable=True)

class Note(Base):
    __tablename__ = 'notes'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)
    content = Column(Text)
    media_type = Column(Enum(MediaType), default=MediaType.TEXT)
    media_file_id = Column(String(500), nullable=True)
    media_caption = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    
    # Связь с сессией чтения
    reading_session_id = Column(Integer, ForeignKey('reading_sessions.id'), nullable=True)

class ReadingSession(Base):
    __tablename__ = 'reading_sessions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=True)
    
    # Основные данные сессии
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    
    # Дополнительная информация
    notes_count = Column(Integer, default=0)
    media_notes_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Флаги
    is_completed = Column(Boolean, default=False)
    was_interrupted = Column(Boolean, default=False)

class DailyReadingStats(Base):
    __tablename__ = 'daily_reading_stats'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    
    # Дата и время
    date = Column(DateTime, nullable=False)
    
    # Статистика за день
    total_seconds = Column(Float, default=0.0)
    sessions_count = Column(Integer, default=0)
    notes_count = Column(Integer, default=0)
    
    # Разбивка по времени дня (в секундах)
    morning_seconds = Column(Float, default=0.0)  # 6:00-12:00
    afternoon_seconds = Column(Float, default=0.0)  # 12:00-18:00
    evening_seconds = Column(Float, default=0.0)  # 18:00-24:00
    night_seconds = Column(Float, default=0.0)  # 0:00-6:00
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ===========================================
# НАСТРОЙКА БАЗЫ ДАННЫХ
# ===========================================
DATABASE_URL = "sqlite+aiosqlite:///./notes.db"

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# ===========================================
# ФУНКЦИИ ИНИЦИАЛИЗАЦИИ БАЗЫ ДАННЫХ
# ===========================================
async def backup_database():
    """Создание резервной копии базы данных"""
    if os.path.exists("notes.db"):
        if not os.path.exists("backups"):
            os.makedirs("backups")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backups/notes_backup_{timestamp}.db"
        
        try:
            shutil.copy2("notes.db", backup_file)
            print(f"✅ Создана резервная копия: {backup_file}")
            
            # Удаляем старые бэкапы (оставляем последние 3)
            backups = sorted([f for f in os.listdir("backups") if f.startswith("notes_backup_")])
            if len(backups) > 3:
                for old_backup in backups[:-3]:
                    try:
                        os.remove(f"backups/{old_backup}")
                        print(f"🗑️ Удален старый бэкап: {old_backup}")
                    except:
                        pass
        except Exception as e:
            print(f"⚠️ Не удалось создать резервную копию: {e}")
    else:
        print("ℹ️ База данных не существует, создаем новую")

async def add_columns_to_table(conn, table_name, columns):
    """Добавление колонок в таблицу"""
    try:
        # Получаем существующие колонки
        result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
        existing_columns = result.fetchall()  # Убрал await здесь
        existing_column_names = [col[1] for col in existing_columns]
        
        for column_name, column_type in columns:
            if column_name not in existing_column_names:
                print(f"➕ Добавляем колонку '{column_name}' в таблицу '{table_name}'...")
                try:
                    await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
                    print(f"✅ Колонка '{column_name}' добавлена")
                except Exception as e:
                    print(f"⚠️ Ошибка при добавлении колонки '{column_name}': {e}")
            else:
                print(f"ℹ️ Колонка '{column_name}' уже существует в таблице '{table_name}'")
    
    except Exception as e:
        print(f"❌ Ошибка при проверке таблицы '{table_name}': {e}")

async def init_db():
    """Инициализация базы данных БЕЗ удаления существующих данных"""
    print("=" * 50)
    print("🔄 НАЧАЛО ИНИЦИАЛИЗАЦИИ БАЗЫ ДАННЫХ")
    print("=" * 50)
    
    # Создаем резервную копию
    await backup_database()
    
    async with engine.begin() as conn:
        # Создаем все таблицы
        await conn.run_sync(Base.metadata.create_all)
    
    # Обновляем существующие таблицы (миграция)
    await update_existing_tables()
    
    # Проверяем целостность
    await check_data_consistency()
    
    print("=" * 50)
    print("✅ ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ЗАВЕРШЕНА")
    print("=" * 50)

async def update_existing_tables():
    """Обновление существующих таблиц (миграция)"""
    print("🔄 Обновление существующих таблиц...")
    
    # Список колонок для добавления в таблицу categories
    category_columns = [
        ('total_reading_time', 'FLOAT DEFAULT 0.0'),
        ('reading_sessions_count', 'INTEGER DEFAULT 0'),
        ('last_read_at', 'DATETIME')
    ]
    
    # Список колонок для добавления в таблицу notes
    note_columns = [
        ('reading_session_id', 'INTEGER')
    ]
    
    # Список колонок для добавления в таблицу reading_sessions
    session_columns = [
        ('notes_count', 'INTEGER DEFAULT 0'),
        ('media_notes_count', 'INTEGER DEFAULT 0'),
        ('is_completed', 'BOOLEAN DEFAULT FALSE'),
        ('was_interrupted', 'BOOLEAN DEFAULT FALSE')
    ]
    
    async with engine.begin() as conn:
        # Обновляем таблицу categories
        await add_columns_to_table(conn, 'categories', category_columns)
        
        # Обновляем таблицу notes
        await add_columns_to_table(conn, 'notes', note_columns)
        
        # Обновляем таблицу reading_sessions
        await add_columns_to_table(conn, 'reading_sessions', session_columns)

async def check_data_consistency():
    """Проверка целостности данных"""
    print("🔍 Проверка целостности данных...")
    
    async with engine.connect() as conn:
        try:
            # Проверяем все таблицы
            result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = result.fetchall()
            
            print(f"📊 Найдено таблиц: {len(tables)}")
            for table in tables:
                table_name = table[0]
                result = await conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.scalar()
                print(f"  • {table_name}: {count} записей")
            
            # Проверяем пользователей
            result = await conn.execute(text("SELECT COUNT(DISTINCT user_id) FROM categories"))
            user_count = result.scalar()
            print(f"👥 Уникальных пользователей: {user_count}")
            
            print("✅ Проверка целостности данных завершена")
            
        except Exception as e:
            print(f"⚠️ Ошибка при проверке целостности данных: {e}")

# ===========================================
# ОСНОВНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ
# ===========================================
async def create_reading_session(user_id: int, category_id: int = None) -> ReadingSession:
    """Создание новой сессии чтения"""
    async with AsyncSessionLocal() as session:
        reading_session = ReadingSession(
            user_id=user_id,
            category_id=category_id,
            start_time=datetime.utcnow(),
            is_completed=False
        )
        session.add(reading_session)
        await session.commit()
        await session.refresh(reading_session)
        
        # Обновляем статистику категории если она указана
        if category_id:
            await update_category_stats_after_session_start(category_id, user_id)
        
        return reading_session

async def update_category_stats_after_session_start(category_id: int, user_id: int):
    """Обновление статистики категории после начала сессии"""
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                text("""
                UPDATE categories 
                SET reading_sessions_count = COALESCE(reading_sessions_count, 0) + 1,
                    last_read_at = :last_read_at
                WHERE id = :category_id AND user_id = :user_id
                """),
                {
                    "last_read_at": datetime.utcnow(),
                    "category_id": category_id,
                    "user_id": user_id
                }
            )
            await session.commit()
        except Exception as e:
            print(f"⚠️ Ошибка при обновлении статистики категории: {e}")

async def complete_reading_session(session_id: int, duration_seconds: float, 
                                  notes_count: int = 0, media_notes_count: int = 0):
    """Завершение сессии чтения"""
    async with AsyncSessionLocal() as session:
        try:
            # Получаем сессию
            result = await session.execute(
                select(ReadingSession).where(ReadingSession.id == session_id)
            )
            reading_session = result.scalar_one_or_none()
            
            if reading_session:
                # Обновляем сессию
                reading_session.end_time = datetime.utcnow()
                reading_session.duration_seconds = duration_seconds
                reading_session.notes_count = notes_count
                reading_session.media_notes_count = media_notes_count
                reading_session.is_completed = True
                reading_session.was_interrupted = False
                
                # Обновляем статистику категории если она указана
                if reading_session.category_id:
                    await update_category_stats_after_session_complete(
                        reading_session.category_id, 
                        duration_seconds,
                        reading_session.user_id
                    )
                
                # Обновляем дневную статистику
                await update_daily_stats(
                    reading_session.user_id,
                    datetime.utcnow(),
                    duration_seconds
                )
                
                await session.commit()
                return True
            else:
                print(f"⚠️ Сессия с ID {session_id} не найдена")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка при завершении сессии: {e}")
            return False

async def update_category_stats_after_session_complete(category_id: int, duration_seconds: float, user_id: int):
    """Обновление статистики категории после завершения сессии"""
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                text("""
                UPDATE categories 
                SET total_reading_time = COALESCE(total_reading_time, 0) + :duration_seconds,
                    last_read_at = :last_read_at
                WHERE id = :category_id AND user_id = :user_id
                """),
                {
                    "duration_seconds": duration_seconds,
                    "last_read_at": datetime.utcnow(),
                    "category_id": category_id,
                    "user_id": user_id
                }
            )
            await session.commit()
        except Exception as e:
            print(f"⚠️ Ошибка при обновлении статистики категории: {e}")

async def update_daily_stats(user_id: int, date_time: datetime, duration_seconds: float):
    """Обновление дневной статистики"""
    async with AsyncSessionLocal() as session:
        try:
            # Получаем дату без времени
            date_only = date_time.date()
            date_only_dt = datetime.combine(date_only, datetime.min.time())
            
            # Определяем время дня
            hour = date_time.hour
            if 6 <= hour < 12:
                time_column = "morning_seconds"
            elif 12 <= hour < 18:
                time_column = "afternoon_seconds"
            elif 18 <= hour < 24:
                time_column = "evening_seconds"
            else:
                time_column = "night_seconds"
            
            # Проверяем существование записи за этот день
            result = await session.execute(
                select(DailyReadingStats).where(
                    DailyReadingStats.user_id == user_id,
                    DailyReadingStats.date == date_only_dt
                )
            )
            existing_record = result.scalar_one_or_none()
            
            if existing_record:
                # Обновляем существующую запись
                setattr(existing_record, 'total_seconds', existing_record.total_seconds + duration_seconds)
                setattr(existing_record, 'sessions_count', existing_record.sessions_count + 1)
                setattr(existing_record, time_column, getattr(existing_record, time_column) + duration_seconds)
                existing_record.updated_at = datetime.utcnow()
            else:
                # Создаем новую запись
                daily_stats = DailyReadingStats(
                    user_id=user_id,
                    date=date_only_dt,
                    total_seconds=duration_seconds,
                    sessions_count=1
                )
                
                # Устанавливаем время дня
                setattr(daily_stats, time_column, duration_seconds)
                
                session.add(daily_stats)
            
            await session.commit()
            
        except Exception as e:
            print(f"⚠️ Ошибка при обновлении дневной статистики: {e}")

async def get_user_reading_stats(user_id: int, days: int = 30):
    """Получение статистики чтения пользователя"""
    from sqlalchemy import func
    
    async with AsyncSessionLocal() as session:
        try:
            # Общая статистика
            result = await session.execute(
                select(
                    func.count(ReadingSession.id).label('total_sessions'),
                    func.sum(ReadingSession.duration_seconds).label('total_seconds'),
                    func.avg(ReadingSession.duration_seconds).label('avg_session_seconds'),
                    func.max(ReadingSession.duration_seconds).label('max_session_seconds')
                ).where(
                    ReadingSession.user_id == user_id,
                    ReadingSession.is_completed == True
                )
            )
            overall_stats = result.fetchone()
            
            # Статистика по категориям
            result = await session.execute(
                select(
                    Category.name,
                    func.count(ReadingSession.id).label('sessions_count'),
                    func.sum(ReadingSession.duration_seconds).label('total_seconds'),
                    func.avg(ReadingSession.duration_seconds).label('avg_seconds')
                )
                .join(ReadingSession, ReadingSession.category_id == Category.id)
                .where(
                    ReadingSession.user_id == user_id,
                    ReadingSession.is_completed == True
                )
                .group_by(Category.id, Category.name)
                .order_by(func.sum(ReadingSession.duration_seconds).desc())
            )
            category_stats = result.fetchall()
            
            # Дневная статистика (последние N дней)
            result = await session.execute(
                select(
                    DailyReadingStats.date,
                    DailyReadingStats.total_seconds,
                    DailyReadingStats.sessions_count,
                    DailyReadingStats.morning_seconds,
                    DailyReadingStats.afternoon_seconds,
                    DailyReadingStats.evening_seconds,
                    DailyReadingStats.night_seconds
                )
                .where(DailyReadingStats.user_id == user_id)
                .order_by(DailyReadingStats.date.desc())
                .limit(days)
            )
            daily_stats = result.fetchall()
            
            return {
                "overall": overall_stats,
                "by_category": category_stats,
                "daily": daily_stats
            }
            
        except Exception as e:
            print(f"⚠️ Ошибка при получении статистики: {e}")
            return {
                "overall": (0, 0, 0, 0),
                "by_category": [],
                "daily": []
            }

# ===========================================
# ЗАПУСК МИГРАЦИИ ПРИ НЕОБХОДИМОСТИ
# ===========================================
if __name__ == "__main__":
    async def main():
        await init_db()
        print("🎉 Все готово! База данных обновлена.")
    
    asyncio.run(main())