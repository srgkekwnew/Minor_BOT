"""
HSEBookNotes Bot - основной файл бота с таймером чтения
Версия 3.0.0
"""

import asyncio
import io
import time
from datetime import datetime, timedelta
from typing import Dict, Any

import matplotlib
import matplotlib.pyplot as plt
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ContentType, ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Message, ReplyKeyboardMarkup
)
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import func, select

# Импортируем обновленные модели и функции
from init_db import (
    Category, Note, MediaType, ReadingSession, DailyReadingStats,
    AsyncSessionLocal, create_reading_session, complete_reading_session,
    get_user_reading_stats, update_daily_stats
)

# ===========================================
# НАСТРОЙКИ
# ===========================================
plt.style.use('seaborn-v0_8-darkgrid')
matplotlib.use('Agg')

# ===========================================
# ОПРЕДЕЛЕНИЕ СОСТОЯНИЙ FSM
# ===========================================
class CategoryState(StatesGroup):
    waiting_for_category_name = State()

class EditNoteState(StatesGroup):
    waiting_for_new_text = State()

class RenameCategoryState(StatesGroup):
    waiting_for_new_category_name = State()

class DeleteCategoryState(StatesGroup):
    waiting_for_delete_confirmation = State()

class AddMediaNoteState(StatesGroup):
    waiting_for_media = State()
    waiting_for_caption = State()

class TimerState(StatesGroup):
    waiting_for_timer_category = State()
    timer_running = State()

# ===========================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# ===========================================
bot = Bot(
    token="8350095060:AAE3FRQkj3QbtDXiC6ffi6wnDwh_PLzeBv0",
    default=DefaultBotProperties(parse_mode='HTML')
)

dp = Dispatcher(storage=MemoryStorage())

# ===========================================
# ГЛОБАЛЬНОЕ ХРАНИЛИЩЕ АКТИВНЫХ ТАЙМЕРОВ
# ===========================================
active_timers: Dict[int, Dict[str, Any]] = {}

# ===========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ===========================================
def format_time(seconds: int) -> str:
    """Форматирует секунды в читаемый вид"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def format_time_short(seconds: int) -> str:
    """Короткий формат времени"""
    if seconds < 3600:  # Менее часа
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02d}:{seconds:02d}"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}ч {minutes:02d}м"

def get_main_keyboard():
    """Основная клавиатура"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Категории"), KeyboardButton(text="📝 Заметки")],
            [KeyboardButton(text="➕ Новая категория"), KeyboardButton(text="📸 Медиа")],
            [KeyboardButton(text="⏱️ Таймер чтения"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="ℹ️ О нас")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие..."
    )
# ===========================================
# ФУНКЦИЯ СОЗДАНИЯ ГРАФИКОВ (3 ГРАФИКА)
# ===========================================
def create_reading_stats_chart(notes_by_category: dict, notes_by_date: dict, time_by_date: dict):
    """Создать 3 графика: 
       1. Круговая - заметки по категориям
       2. Столбчатая - заметки по дням
       3. Столбчатая - время чтения по дням
    """
    
    # Создаем фигуру с 3 подграфиками
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 6), facecolor='white')
    fig.suptitle('Статистика чтения', fontsize=18, fontweight='bold', y=1.05)
    
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD']
    
    # === ГРАФИК 1: КРУГОВАЯ ДИАГРАММА (КАТЕГОРИИ) ===
    ax1.set_facecolor('white')
    
    if notes_by_category and sum(notes_by_category.values()) > 0:
        category_names = list(notes_by_category.keys())
        category_counts = list(notes_by_category.values())
        
        # Обрезаем длинные названия
        short_names = []
        for name in category_names:
            if len(name) > 15:
                short_names.append(name[:12] + '...')
            else:
                short_names.append(name)
        
        wedges, texts, autotexts = ax1.pie(
            category_counts, 
            labels=short_names,
            colors=colors[:len(category_names)],
            autopct='%1.0f%%',
            startangle=90,
            wedgeprops={'edgecolor': 'white', 'linewidth': 2, 'antialiased': True}
        )
        
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
            autotext.set_fontsize(9)
        
        for text in texts:
            text.set_fontsize(9)
            text.set_fontweight('bold')
        
        ax1.set_title('Заметки по категориям', fontsize=13, pad=15, fontweight='bold')
        ax1.axis('equal')
    else:
        ax1.text(0.5, 0.5, 'Нет данных', ha='center', va='center', 
                fontsize=12, transform=ax1.transAxes)
        ax1.set_title('Заметки по категориям', fontsize=13, pad=15, fontweight='bold')
        ax1.axis('off')
    
    # === ГРАФИК 2: СТОЛБЧАТАЯ ДИАГРАММА (ЗАМЕТКИ ПО ДНЯМ) ===
    ax2.set_facecolor('white')
    
    if notes_by_date and len(notes_by_date) > 0:
        # Берем последние 10 дней
        dates = sorted(notes_by_date.keys())[-10:]
        date_labels = [d[-5:] if len(d) > 5 else d for d in dates]
        note_counts = [notes_by_date.get(d, 0) for d in dates]
        
        x = range(len(dates))
        
        bars = ax2.bar(x, note_counts, color=colors[0], edgecolor='white', linewidth=2, width=0.7)
        
        # Добавляем значения
        for bar, count in zip(bars, note_counts):
            height = bar.get_height()
            if height > 0:
                ax2.text(bar.get_x() + bar.get_width()/2, height + 0.1,
                        f'{int(height)}', ha='center', va='bottom', fontweight='bold', fontsize=9)
        
        ax2.set_title('Заметки по дням', fontsize=13, pad=15, fontweight='bold')
        ax2.set_xlabel('Дата', fontsize=10)
        ax2.set_ylabel('Количество заметок', fontsize=10)
        ax2.set_xticks(x)
        ax2.set_xticklabels(date_labels, rotation=45, ha='right')
        ax2.grid(True, alpha=0.3, axis='y', linestyle='--')
    else:
        ax2.text(0.5, 0.5, 'Нет данных за 30 дней', ha='center', va='center', 
                fontsize=12, transform=ax2.transAxes)
        ax2.set_title('Заметки по дням', fontsize=13, pad=15, fontweight='bold')
        ax2.axis('off')
    
    # === ГРАФИК 3: СТОЛБЧАТАЯ ДИАГРАММА (ВРЕМЯ ПО ДНЯМ) ===
    ax3.set_facecolor('white')
    
    if time_by_date and len(time_by_date) > 0:
        # Берем последние 10 дней
        dates = sorted(time_by_date.keys())[-10:]
        date_labels = [d[-5:] if len(d) > 5 else d for d in dates]
        time_minutes = [time_by_date.get(d, 0) / 60 for d in dates]  # в минутах
        
        x = range(len(dates))
        
        bars = ax3.bar(x, time_minutes, color=colors[1], edgecolor='white', linewidth=2, width=0.7)
        
        # Добавляем значения
        for bar, minutes in zip(bars, time_minutes):
            height = bar.get_height()
            if height > 0:
                ax3.text(bar.get_x() + bar.get_width()/2, height + 0.5,
                        f'{int(minutes)}м', ha='center', va='bottom', fontweight='bold', fontsize=9)
        
        ax3.set_title('Время чтения по дням', fontsize=13, pad=15, fontweight='bold')
        ax3.set_xlabel('Дата', fontsize=10)
        ax3.set_ylabel('Минуты', fontsize=10)
        ax3.set_xticks(x)
        ax3.set_xticklabels(date_labels, rotation=45, ha='right')
        ax3.grid(True, alpha=0.3, axis='y', linestyle='--')
    else:
        ax3.text(0.5, 0.5, 'Нет данных о времени', ha='center', va='center', 
                fontsize=12, transform=ax3.transAxes)
        ax3.set_title('Время чтения по дням', fontsize=13, pad=15, fontweight='bold')
        ax3.axis('off')
    
    plt.tight_layout()
    
    # Сохраняем
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    plt.close(fig)
    
    return buf


# ===========================================
# СТАТИСТИКА (3 ГРАФИКА + ПОЛНЫЙ ТЕКСТ)
# ===========================================
@dp.message(Command("stats"))
@dp.message(F.text == "📊 Статистика")
async def show_statistics(message: Message):
    """Показать статистику чтения (3 графика + полная текстовая статистика)"""
    user_id = message.from_user.id
    
    loading_msg = await message.answer("📊 Собираю статистику...")
    
    async with AsyncSessionLocal() as session:
        try:
            # === ОСНОВНЫЕ ПОКАЗАТЕЛИ ===
            cat_result = await session.execute(
                select(func.count(Category.id)).where(Category.user_id == user_id)
            )
            categories_count = cat_result.scalar() or 0
            
            notes_result = await session.execute(
                select(func.count(Note.id)).where(
                    Note.user_id == user_id, 
                    Note.is_deleted == False
                )
            )
            notes_count = notes_result.scalar() or 0
            
            sessions_result = await session.execute(
                select(ReadingSession).where(ReadingSession.user_id == user_id)
            )
            all_sessions = sessions_result.scalars().all()
            
            total_time = 0
            completed_sessions = [s for s in all_sessions if s.duration_seconds]
            sessions_count = len(completed_sessions)
            
            for s in completed_sessions:
                total_time += s.duration_seconds
            
            avg_session_time = total_time / sessions_count if sessions_count > 0 else 0
            hours = total_time / 3600
            
            # === ЗАМЕТКИ ПО КАТЕГОРИЯМ ===
            cat_stats = await session.execute(
                select(Category.name, func.count(Note.id))
                .join(Note, Category.id == Note.category_id)
                .where(
                    Category.user_id == user_id,
                    Note.is_deleted == False
                )
                .group_by(Category.id, Category.name)
                .order_by(func.count(Note.id).desc())
            )
            notes_by_category = dict(cat_stats.all())
            
            # === АКТИВНОСТЬ ПО ДНЯМ ===
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            
            # Заметки по дням
            daily_notes = await session.execute(
                select(func.date(Note.created_at), func.count(Note.id))
                .where(
                    Note.user_id == user_id,
                    Note.created_at >= thirty_days_ago,
                    Note.is_deleted == False
                )
                .group_by(func.date(Note.created_at))
                .order_by(func.date(Note.created_at))
            )
            
            notes_by_date = {}
            total_days_with_notes = 0
            max_notes_in_day = 0
            most_active_day = "—"
            
            for date_str, count in daily_notes.all():
                if date_str:
                    try:
                        date_obj = datetime.strptime(str(date_str), '%Y-%m-%d')
                        formatted_date = date_obj.strftime('%d.%m.%Y')
                        notes_by_date[formatted_date] = count
                        total_days_with_notes += 1
                        
                        if count > max_notes_in_day:
                            max_notes_in_day = count
                            most_active_day = formatted_date
                    except:
                        continue
            
            # Время по дням
            daily_time = await session.execute(
                select(func.date(ReadingSession.start_time), func.sum(ReadingSession.duration_seconds))
                .where(
                    ReadingSession.user_id == user_id,
                    ReadingSession.start_time >= thirty_days_ago,
                    ReadingSession.is_completed == True
                )
                .group_by(func.date(ReadingSession.start_time))
            )
            
            time_by_date = {}
            total_reading_days = 0
            max_time_in_day = 0
            most_reading_day = "—"
            
            for date_str, seconds in daily_time.all():
                if date_str and seconds:
                    try:
                        date_obj = datetime.strptime(str(date_str), '%Y-%m-%d')
                        formatted_date = date_obj.strftime('%d.%m.%Y')
                        time_by_date[formatted_date] = seconds
                        total_reading_days += 1
                        
                        if seconds > max_time_in_day:
                            max_time_in_day = seconds
                            most_reading_day = formatted_date
                    except:
                        continue
            
            # === СРЕДНИЕ ПОКАЗАТЕЛИ ===
            avg_notes_per_day = notes_count / 30 if notes_count > 0 else 0
            avg_notes_per_active_day = notes_count / total_days_with_notes if total_days_with_notes > 0 else 0
            avg_time_per_day = total_time / 30 if total_time > 0 else 0
            avg_time_per_reading_day = total_time / total_reading_days if total_reading_days > 0 else 0
            
            # === СТРЕЙК ===
            today = datetime.utcnow().date()
            streak = 0
            check_date = today
            
            while True:
                day_activity = await session.execute(
                    select(Note.id)
                    .where(
                        Note.user_id == user_id,
                        func.date(Note.created_at) == check_date.strftime('%Y-%m-%d'),
                        Note.is_deleted == False
                    )
                    .limit(1)
                )
                
                if day_activity.first():
                    streak += 1
                    check_date -= timedelta(days=1)
                else:
                    break
            
            # === ПОСЛЕДНИЕ ЗАМЕТКИ ===
            recent_notes_result = await session.execute(
                select(Note.content, Note.created_at)
                .where(
                    Note.user_id == user_id,
                    Note.is_deleted == False
                )
                .order_by(Note.created_at.desc())
                .limit(3)
            )
            recent_notes = recent_notes_result.all()
            
        except Exception as e:
            await loading_msg.delete()
            await message.answer(f"❌ Ошибка загрузки статистики: {e}")
            return
    
    # === ОТПРАВКА ГРАФИКОВ ===
    try:
        chart_buf = create_reading_stats_chart(notes_by_category, notes_by_date, time_by_date)
        await loading_msg.delete()
        await message.answer_photo(
            BufferedInputFile(chart_buf.getvalue(), filename="stats.png"),
            caption="📈 Статистика чтения (графики)"
        )
    except Exception as e:
        print(f"Ошибка создания графиков: {e}")
        await loading_msg.delete()
        await message.answer("📊 Загружаю текстовую статистику...")
    
    # ========== ТЕКСТОВАЯ СТАТИСТИКА ==========
    
    # --- ОГОНЕК ---
    if streak == 0:
        fire = "🕯️"
        streak_text = "Нет серии"
    elif streak == 1:
        fire = "🔥"
        streak_text = "1 день"
    elif streak == 2:
        fire = "🔥🔥"
        streak_text = "2 дня"
    elif streak == 3:
        fire = "🔥🔥🔥"
        streak_text = "3 дня"
    elif streak == 4:
        fire = "🔥🔥🔥🔥"
        streak_text = "4 дня"
    elif streak == 5:
        fire = "🔥🔥🔥🔥🔥"
        streak_text = "5 дней"
    elif streak == 6:
        fire = "🔥🔥🔥🔥🔥🔥"
        streak_text = "6 дней"
    elif streak >= 7:
        fire = "🔥" * 7
        streak_text = f"{streak} дней"
    
    # --- УРОВЕНЬ ---
    level = min(50, notes_count // 5 + 1)
    exp_current = notes_count % 5
    
    if level <= 5:
        level_title = "🌱 НОВИЧОК"
        next_level = 6
        next_level_title = "📖 ЧИТАТЕЛЬ"
    elif level <= 10:
        level_title = "📖 ЧИТАТЕЛЬ"
        next_level = 11
        next_level_title = "📚 КНИГОЛЮБ"
    elif level <= 15:
        level_title = "📚 КНИГОЛЮБ"
        next_level = 16
        next_level_title = "🔍 ИССЛЕДОВАТЕЛЬ"
    elif level <= 20:
        level_title = "🔍 ИССЛЕДОВАТЕЛЬ"
        next_level = 21
        next_level_title = "🧠 МЫСЛИТЕЛЬ"
    elif level <= 25:
        level_title = "🧠 МЫСЛИТЕЛЬ"
        next_level = 26
        next_level_title = "⚡ ЭРУДИТ"
    elif level <= 30:
        level_title = "⚡ ЭРУДИТ"
        next_level = 31
        next_level_title = "💫 МАСТЕР"
    elif level <= 35:
        level_title = "💫 МАСТЕР"
        next_level = 36
        next_level_title = "🏆 ПРОФЕССОР"
    elif level <= 40:
        level_title = "🏆 ПРОФЕССОР"
        next_level = 41
        next_level_title = "👑 МАГИСТР"
    elif level <= 45:
        level_title = "👑 МАГИСТР"
        next_level = 46
        next_level_title = "✨ ЛЕГЕНДА"
    else:
        level_title = "✨ ЛЕГЕНДА"
        next_level = 51
        next_level_title = "МАКСИМУМ"
    
    level_bar = '█' * exp_current + '░' * (5 - exp_current)
    level_progress = (notes_count / (next_level * 5)) * 100 if next_level <= 50 else 100
    level_progress_bar = '█' * int(level_progress / 5) + '░' * (20 - int(level_progress / 5))
    
    # --- ДОСТИЖЕНИЯ ---
    achievements = []
    
    if categories_count >= 1:
        achievements.append("📁 Первая категория")
    if categories_count >= 3:
        achievements.append("📚 Три книги")
    if categories_count >= 5:
        achievements.append("🏛️ Библиотека")
    
    if notes_count >= 1:
        achievements.append("📝 Первая заметка")
    if notes_count >= 10:
        achievements.append("📄 10 заметок")
    if notes_count >= 25:
        achievements.append("📑 25 заметок")
    if notes_count >= 50:
        achievements.append("📚 50 заметок")
    if notes_count >= 100:
        achievements.append("📖 100 заметок")
    
    if total_time >= 3600:
        achievements.append("⏱️ 1 час чтения")
    if total_time >= 7200:
        achievements.append("🕐 2 часа чтения")
    if total_time >= 10800:
        achievements.append("⌛ 3 часа чтения")
    if total_time >= 36000:
        achievements.append("⏳ 10 часов чтения")
    
    if streak >= 3:
        achievements.append("🔥 3 дня подряд")
    if streak >= 7:
        achievements.append("🔥🔥 Неделя")
    if streak >= 14:
        achievements.append("⚡ 2 недели")
    if streak >= 30:
        achievements.append("🌋 Месяц")
    
    # --- ЦЕЛИ ---
    if notes_count < 10:
        next_goal = "📄 10 заметок"
        next_goal_current = notes_count
        next_goal_target = 10
    elif notes_count < 25:
        next_goal = "📑 25 заметок"
        next_goal_current = notes_count
        next_goal_target = 25
    elif notes_count < 50:
        next_goal = "📚 50 заметок"
        next_goal_current = notes_count
        next_goal_target = 50
    elif notes_count < 100:
        next_goal = "📖 100 заметок"
        next_goal_current = notes_count
        next_goal_target = 100
    else:
        next_goal = "📕 250 заметок"
        next_goal_current = notes_count
        next_goal_target = 250
    
    goal_progress = (next_goal_current / next_goal_target * 100)
    goal_bar = '█' * int(goal_progress / 5) + '░' * (20 - int(goal_progress / 5))
    
    # --- ФОРМИРУЕМ ТЕКСТ ---
    text = f"📊 <b>СТАТИСТИКА ЧТЕНИЯ</b>\n"
    text += f"{'═' * 35}\n\n"
    
    # Серия и уровень
    text += f"{fire} <b>Серия:</b> {streak_text}\n"
    text += f"{level_title} • <b>Уровень {level}</b>\n"
    text += f"<code>{level_bar}</code> {exp_current}/5 XP\n"
    text += f"✨ <b>Всего опыта:</b> {notes_count} XP\n\n"
    
    # Основные показатели
    text += f"📂 <b>Категории:</b> {categories_count}\n"
    text += f"📝 <b>Заметки:</b> {notes_count}\n"
    text += f"⏱️ <b>Сессии:</b> {sessions_count}\n"
    text += f"🕐 <b>Время:</b> {format_time_short(int(total_time))} ({hours:.1f}ч)\n"
    text += f"📊 <b>Среднее/сессия:</b> {format_time_short(int(avg_session_time))}\n\n"
    
    # Средние показатели
    text += f"📈 <b>СРЕДНИЕ ПОКАЗАТЕЛИ (30 дней):</b>\n"
    text += f"  • Заметок в день: {avg_notes_per_day:.1f}\n"
    text += f"  • Заметок в активный день: {avg_notes_per_active_day:.1f}\n"
    text += f"  • Времени в день: {format_time_short(int(avg_time_per_day))}\n"
    text += f"  • Времени в день чтения: {format_time_short(int(avg_time_per_reading_day))}\n\n"
    
    # Самые активные дни
    if most_active_day != "—":
        text += f"🔥 <b>Самый активный день (заметки):</b> {most_active_day} • {max_notes_in_day} заметок\n"
    if most_reading_day != "—":
        text += f"⏱️ <b>Самый активный день (время):</b> {most_reading_day} • {format_time_short(int(max_time_in_day))}\n\n"
    
    # Топ категории
    if notes_by_category:
        text += f"📚 <b>ТОП КАТЕГОРИЙ:</b>\n"
        for i, (cat, cnt) in enumerate(list(notes_by_category.items())[:3], 1):
            percent = (cnt / notes_count * 100) if notes_count > 0 else 0
            bar_len = int(percent / 5)
            cat_bar = '█' * bar_len + '░' * (20 - bar_len)
            
            if len(cat) > 25:
                cat = cat[:22] + "..."
            
            if i == 1:
                medal = "🥇"
            elif i == 2:
                medal = "🥈"
            else:
                medal = "🥉"
            
            text += f"{medal} <b>{cat}</b>\n"
            text += f"   <code>{cat_bar}</code> {cnt} ({percent:.0f}%)\n"
        text += f"\n"
    
    # Последние заметки
    if recent_notes:
        text += f"🕐 <b>ПОСЛЕДНИЕ ЗАМЕТКИ:</b>\n"
        for content, date in recent_notes[:3]:
            date_str = date.strftime('%d.%m.%Y')
            short_content = content[:25] + "..." if len(content) > 25 else content
            text += f"  • {date_str}: {short_content}\n"
        text += f"\n"
    
    # Достижения
    if achievements:
        text += f"🏆 <b>ДОСТИЖЕНИЯ ({len(achievements)}):</b>\n"
        
        # Показываем последние 6 достижений в 2 колонки
        recent_achievements = achievements[-6:]
        half = len(recent_achievements) // 2 + len(recent_achievements) % 2
        col1 = recent_achievements[:half]
        col2 = recent_achievements[half:]
        
        for i in range(max(len(col1), len(col2))):
            ach1 = col1[i] if i < len(col1) else ""
            ach2 = col2[i] if i < len(col2) else ""
            text += f"  {ach1:<25} {ach2}\n"
        text += f"\n"
    
    # Прогресс уровня
    if level < 50:
        text += f"🎯 <b>ПРОГРЕСС УРОВНЯ:</b>\n"
        text += f"  {level_title} → {next_level_title}\n"
        text += f"  <code>{level_progress_bar}</code> {notes_count}/{next_level * 5} XP ({level_progress:.0f}%)\n\n"
    else:
        text += f"👑 <b>МАКСИМАЛЬНЫЙ УРОВЕНЬ!</b>\n\n"
    
    # Следующая цель
    text += f"🎯 <b>СЛЕДУЮЩАЯ ЦЕЛЬ:</b>\n"
    text += f"  {next_goal}\n"
    text += f"  <code>{goal_bar}</code> {next_goal_current}/{next_goal_target} ({goal_progress:.0f}%)\n\n"
    
    # Совет дня
    import random
    
    if streak == 0:
        tip = "🔥 Сделайте первую заметку сегодня, чтобы начать серию!"
    elif streak == 6:
        tip = "🔥 Завтра будет НЕДЕЛЯ! Продолжайте в том же духе!"
    elif streak == 13:
        tip = "⚡ Завтра 2 НЕДЕЛИ! Вы делаете потрясающий прогресс!"
    elif notes_count < 10:
        tip = f"📝 Осталось {10-notes_count} заметок до достижения «10 заметок»!"
    elif hours < 1:
        tip = f"⏱️ Ещё {60-int(total_time/60)} минут до 1 часа чтения!"
    elif not notes_by_category:
        tip = "📚 Создайте первую категорию, чтобы упорядочить заметки!"
    else:
        tips = [
            "📚 Читайте каждый день хотя бы 20 минут — это формирует привычку",
            "🎯 Поставьте цель: 5 заметок в неделю",
            "⏱️ Используйте таймер чтения для отслеживания прогресса",
            "📸 Фотографируйте интересные страницы — это удобно",
            f"🔥 {streak} дней подряд! Отличный результат!",
            "📊 Проверяйте статистику каждую неделю",
            "💭 Делайте заметки сразу после чтения",
            "🎯 Следующая цель — 100 заметок!"
        ]
        tip = random.choice(tips)
    
    text += f"💡 <b>СОВЕТ ДНЯ:</b>\n{tip}"
    
    await message.answer(text, parse_mode='HTML')        
        
        
        # ФУНКЦИИ ДЛЯ РАБОТЫ С ЗАМЕТКАМИ
# ===========================================
async def create_text_note(user_id: int, category_id: int, text: str, session_id: int = None) -> Note:
    """Создание текстовой заметки"""
    async with AsyncSessionLocal() as session:
        new_note = Note(
            category_id=category_id,
            user_id=user_id,
            content=text,
            media_type=MediaType.TEXT,
            reading_session_id=session_id
        )
        session.add(new_note)
        await session.commit()
        await session.refresh(new_note)
        return new_note

async def create_media_note(user_id: int, category_id: int, media_type: MediaType, 
                           file_id: str, caption: str = "", content: str = "", session_id: int = None) -> Note:
    """Создание медиа-заметки"""
    async with AsyncSessionLocal() as session:
        new_note = Note(
            category_id=category_id,
            user_id=user_id,
            content=content or caption or f"{media_type.value.capitalize()} заметка",
            media_type=media_type,
            media_file_id=file_id,
            media_caption=caption,
            reading_session_id=session_id
        )
        session.add(new_note)
        await session.commit()
        await session.refresh(new_note)
        return new_note

async def save_media_note(data: dict, user_id: int, category_id: int):
    """Сохранение медиа-заметки с данными из состояния"""
    async with AsyncSessionLocal() as session:
        media_type = data.get("media_type")
        file_id = data.get("media_file_id")
        caption = data.get("media_caption", "")
        
        note = await create_media_note(
            user_id=user_id,
            category_id=category_id,
            media_type=media_type,
            file_id=file_id,
            caption=caption,
            content=caption or f"{media_type.value.capitalize()} заметка"
        )
        
        return note

async def update_timer(user_id: int, stop_event: asyncio.Event):
    """Задача обновления таймера каждую секунду"""
    timer_data = active_timers.get(user_id)
    if not timer_data:
        return
    
    message_id = timer_data["message_id"]
    start_time = timer_data["start_time"]
    
    while not stop_event.is_set() and user_id in active_timers:
        try:
            # Вычисляем прошедшее время
            elapsed = int(time.time() - start_time)
            time_str = f"⏱️ {format_time(elapsed)}"
            
            # Обновляем сообщение
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=time_str
            )
            
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                print(f"Ошибка обновления таймера: {e}")
                break
        except Exception as e:
            print(f"Ошибка таймера: {e}")
            break
        
        await asyncio.sleep(1)

async def stop_and_report(user_id: int) -> int:
    """Останавливает таймер и возвращает прошедшее время"""
    if user_id not in active_timers:
        return 0
    
    timer_data = active_timers[user_id]
    
    # Сигнализируем задаче об остановке
    if "stop_event" in timer_data:
        timer_data["stop_event"].set()
    
    # Ждём завершения задачи обновления
    if "update_task" in timer_data:
        try:
            await asyncio.wait_for(timer_data["update_task"], timeout=2)
        except:
            timer_data["update_task"].cancel()
    
    # Вычисляем итоговое время
    elapsed_time = int(time.time() - timer_data["start_time"])
    
    # Обновляем сессию в БД
    session_id = timer_data.get("session_id")
    if session_id:
        notes_count = timer_data.get("notes_count", 0)
        media_notes_count = timer_data.get("media_notes_count", 0)
        await complete_reading_session(session_id, elapsed_time, notes_count, media_notes_count)
    
    # Удаляем сообщение с таймером
    try:
        await bot.delete_message(
            chat_id=user_id,
            message_id=timer_data["message_id"]
        )
    except:
        pass
    
    # Удаляем данные таймера
    del active_timers[user_id]
    
    return elapsed_time

# ===========================================
# ГЛАВНОЕ МЕНЮ И КОМАНДЫ
# ===========================================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "Привет! 🎉\n\n"
        "Это приложение-заметки по прочитанным книгам.\n\n"
        "<b>Новая функция:</b> ⏱️ Таймер чтения\n"
        "• Засекайте время, проведенное за чтением\n"
        "• Отслеживайте прогресс в статистике\n"
        "• Улучшайте свои привычки к чтению\n\n"
        "<b>Поддерживаются медиа:</b>\n"
        "📸 Фото\n🎥 Видео\n🎤 Голосовые\n📄 Документы\n\n"
        "Используй кнопки ниже или команды:\n"
        "/timer – запустить таймер чтения\n"
        "/category – выбрать категорию\n"
        "/notes – посмотреть заметки\n"
        "/addmedia – добавить медиа\n"
        "/stats – статистика чтения\n"
        "/about – информация о проекте\n\n"
        "ℹ️ Нажми «О нас» чтобы узнать больше!"
    )
    await message.answer(text, reply_markup=get_main_keyboard())

# ===========================================
# ТАЙМЕР ЧТЕНИЯ
# ===========================================
@dp.message(F.text == "⏱️ Таймер чтения")
@dp.message(Command("timer"))
async def start_timer_command(message: Message, state: FSMContext):
    """Начало работы с таймером"""
    user_id = message.from_user.id
    
    # Проверяем, есть ли активный таймер
    if user_id in active_timers:
        await message.answer(
            "⏱️ <b>У вас уже запущен таймер!</b>\n\n"
            "Время отслеживается в отдельном сообщении.\n"
            "Нажмите '⏹️ Остановить таймер' чтобы завершить сессию.",
            parse_mode='HTML'
        )
        return
    
    # Получаем категории пользователя
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Category).where(Category.user_id == user_id)
        )
        categories = result.scalars().all()
    
    if not categories:
        await message.answer(
            "📚 <b>Сначала создайте категорию!</b>\n\n"
            "Таймер будет привязан к конкретной книге/категории.\n"
            "Нажмите '➕ Новая категория' чтобы создать.",
            parse_mode='HTML'
        )
        return
    
    # Предлагаем выбрать категорию для таймера
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📖 {cat.name}", callback_data=f"timer_cat_{cat.id}")]
        for cat in categories
    ] + [
        [InlineKeyboardButton(text="⏱️ Без категории", callback_data="timer_no_category")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="timer_cancel")]
    ])
    
    await message.answer(
        "⏱️ <b>Запуск таймера чтения</b>\n\n"
        "Выберите категорию (книгу) для таймера:\n"
        "<i>Время чтения будет учитываться в статистике</i>",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    await state.set_state(TimerState.waiting_for_timer_category)

@dp.callback_query(TimerState.waiting_for_timer_category)
async def select_timer_category(query: CallbackQuery, state: FSMContext):
    """Выбор категории для таймера"""
    try:
        if query.data == "timer_no_category":
            category_id = None
            category_name = "Без категории"
        elif query.data == "timer_cancel":
            await state.clear()
            await query.message.edit_text("❌ Запуск таймера отменен")
            await query.answer()
            return
        else:
            category_id = int(query.data.split("_")[2])
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Category).where(Category.id == category_id)
                )
                category = result.scalar_one_or_none()
                category_name = category.name if category else "Неизвестно"
        
        # Создаем сессию чтения в БД
        reading_session = await create_reading_session(query.from_user.id, category_id)
        
        # Запускаем таймер
        await start_timer_function(query, category_id, category_name, reading_session.id)
        await state.set_state(TimerState.timer_running)
        
    except Exception as e:
        await query.answer(f"❌ Ошибка: {str(e)}")
        await state.clear()

async def start_timer_function(query: CallbackQuery, category_id: int, category_name: str, session_id: int):
    """Функция запуска таймера"""
    user_id = query.from_user.id
    
    # Создаем сообщение с таймером
    timer_msg = await query.message.answer("🕐 00:00:00")
    
    # Запускаем задачу обновления
    start_time = time.time()
    stop_event = asyncio.Event()
    
    active_timers[user_id] = {
        "message_id": timer_msg.message_id,
        "start_time": start_time,
        "stop_event": stop_event,
        "category_id": category_id,
        "category_name": category_name,
        "session_id": session_id,
        "notes_count": 0,
        "media_notes_count": 0,
        "db_start_time": datetime.utcnow()
    }
    
    # Создаем и запускаем задачу обновления
    update_task = asyncio.create_task(update_timer(user_id, stop_event))
    active_timers[user_id]["update_task"] = update_task
    
    # Клавиатура для управления таймером
    timer_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏹️ Остановить таймер", callback_data="stop_timer_reading")],
        [
            InlineKeyboardButton(text="📝 Сделать заметку", callback_data="timer_add_note"),
            InlineKeyboardButton(text="📸 Добавить медиа", callback_data="timer_add_media")
        ],
        [InlineKeyboardButton(text="📊 Статистика чтения", callback_data="timer_show_stats")]
    ])
    
    await query.message.edit_text(
        f"✅ <b>Таймер запущен!</b>\n\n"
        f"📖 <b>Книга:</b> {category_name}\n"
        f"⏱️ <b>Таймер:</b> Отслеживается в сообщении выше ⬆️\n"
        f"🕐 <b>Старт:</b> {datetime.now().strftime('%H:%M')}\n\n"
        f"<i>Читайте с удовольствием! 📚</i>\n"
        f"<i>Для удобства советуем запинить данное сообщение!</i>\n"
        f"<i>Во время чтения можно делать заметки</i>",
        reply_markup=timer_keyboard,
        parse_mode='HTML'
    )
    
    await query.answer()

@dp.callback_query(F.data == "stop_timer_reading")
async def stop_timer_callback(query: CallbackQuery, state: FSMContext):
    """Остановка таймера чтения"""
    user_id = query.from_user.id
    
    if user_id in active_timers:
        # Получаем итоговое время
        elapsed_time = await stop_and_report(user_id)
        
        # Показываем результат
        result_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Посмотреть статистику", callback_data="show_stats_after_timer")],
            [InlineKeyboardButton(text="🔄 Новый таймер", callback_data="start_timer")]
        ])
        
        category_name = active_timers.get(user_id, {}).get("category_name", "Неизвестно")
        
        await query.message.edit_text(
            f"⏹️ <b>Таймер остановлен!</b>\n\n"
            f"📖 <b>Книга:</b> {category_name}\n"
            f"⏱️ <b>Время чтения:</b> {format_time(elapsed_time)}\n"
            f"🕐 <b>Потрачено:</b> {elapsed_time // 60} минут\n\n"
            f"<i>Отличная работа! Продолжайте в том же духе! 📚</i>",
            reply_markup=result_keyboard,
            parse_mode='HTML'
        )
        await state.clear()
    else:
        await query.answer("❌ Таймер не был запущен", show_alert=True)
    
    await query.answer()

@dp.callback_query(F.data == "timer_add_note")
async def timer_add_note_callback(query: CallbackQuery, state: FSMContext):
    """Добавление заметки во время чтения"""
    user_id = query.from_user.id
    
    if user_id in active_timers:
        timer_data = active_timers[user_id]
        category_id = timer_data["category_id"]
        
        if category_id:
            # Сохраняем категорию для заметки в состоянии FSM
            await state.update_data(
                current_category=category_id,
                from_timer=True,
                timer_message_id=query.message.message_id
            )
            
            await query.message.answer(
                f"📝 <b>Добавление заметки во время чтения</b>\n\n"
                f"📖 <b>Книга:</b> {timer_data['category_name']}\n"
                f"⏱️ <b>Таймер:</b> Продолжает работать\n\n"
                f"Отправьте текст заметки:\n"
                f"<i>Заметка будет сохранена в текущую книгу</i>",
                parse_mode='HTML'
            )
            await query.answer("Теперь отправьте заметку")
        else:
            await query.answer("❌ Для добавления заметки выберите категорию", show_alert=True)
    else:
        await query.answer("❌ Таймер не запущен", show_alert=True)

@dp.callback_query(F.data == "timer_add_media")
async def timer_add_media_callback(query: CallbackQuery, state: FSMContext):
    """Добавление медиа во время чтения"""
    user_id = query.from_user.id
    
    if user_id in active_timers:
        timer_data = active_timers[user_id]
        category_id = timer_data["category_id"]
        
        if category_id:
            # Сохраняем категорию для медиа в состоянии FSM
            await state.update_data(
                current_category=category_id,
                from_timer=True,
                timer_message_id=query.message.message_id
            )
            
            # Устанавливаем состояние для медиа
            await state.set_state(AddMediaNoteState.waiting_for_media)
            
            await query.message.answer(
                f"📸 <b>Добавление медиа во время чтения</b>\n\n"
                f"📖 <b>Книга:</b> {timer_data['category_name']}\n"
                f"⏱️ <b>Таймер:</b> Продолжает работать\n\n"
                f"Отправьте фото, видео, голосовое сообщение или документ:\n"
                f"<i>Медиа будет сохранено в текущую книгу</i>",
                parse_mode='HTML'
            )
            await query.answer("Теперь отправьте медиа")
        else:
            await query.answer("❌ Для добавления медиа выберите категорию", show_alert=True)
    else:
        await query.answer("❌ Таймер не запущен", show_alert=True)

@dp.callback_query(F.data == "timer_show_stats")
async def timer_show_stats_callback(query: CallbackQuery):
    """Показ статистики во время таймера"""
    user_id = query.from_user.id
    
    if user_id in active_timers:
        timer_data = active_timers[user_id]
        elapsed = int(time.time() - timer_data["start_time"])
        
        await query.answer(
            f"⏱️ Текущее время: {format_time(elapsed)}\n"
            f"📖 Книга: {timer_data['category_name']}",
            show_alert=True
        )
    else:
        await query.answer("❌ Таймер не запущен", show_alert=True)

@dp.callback_query(F.data == "show_stats_after_timer")
async def show_stats_after_timer(query: CallbackQuery):
    """Показ статистики после таймера"""
    await show_statistics(query.message)
    await query.answer()

@dp.callback_query(F.data == "start_timer")
async def start_timer_callback(query: CallbackQuery, state: FSMContext):
    """Запуск таймера из callback"""
    await start_timer_command(query.message, state)
    await query.answer()

@dp.message(Command("stop_timer"))
async def stop_timer_command(message: Message):
    """Команда остановки таймера"""
    user_id = message.from_user.id
    
    if user_id in active_timers:
        elapsed_time = await stop_and_report(user_id)
        category_name = active_timers.get(user_id, {}).get("category_name", "Неизвестно")
        
        await message.answer(
            f"⏹️ <b>Таймер остановлен по команде!</b>\n\n"
            f"📖 Книга: {category_name}\n"
            f"⏱️ Проработал: {format_time(elapsed_time)}",
            parse_mode='HTML'
        )
    else:
        await message.answer("❌ Нет активного таймера для остановки.")

@dp.message(Command("timer_status"))
async def timer_status_command(message: Message):
    """Проверка текущего времени таймера"""
    user_id = message.from_user.id
    
    if user_id in active_timers:
        timer_data = active_timers[user_id]
        elapsed = int(time.time() - timer_data["start_time"])
        category_name = timer_data.get("category_name", "Неизвестно")
        
        await message.answer(
            f"✅ <b>Таймер активен!</b>\n\n"
            f"📖 Книга: {category_name}\n"
            f"⏱️ Текущее время: {format_time(elapsed)}",
            parse_mode='HTML'
        )
    else:
        await message.answer("⏱️ Таймер не активен. Используйте /timer для запуска.")

# ===========================================
# ОБРАБОТКА МЕДИА (ОБЩАЯ И ДЛЯ ТАЙМЕРА)
# ===========================================
async def handle_media_from_timer(message: Message, state: FSMContext):
    """Обработка медиа из таймера"""
    user_id = message.from_user.id
    
    if user_id not in active_timers:
        await message.answer("❌ Таймер больше не активен")
        await state.clear()
        return
    
    timer_data = active_timers[user_id]
    category_id = timer_data["category_id"]
    category_name = timer_data["category_name"]
    caption = message.caption or ""
    
    # Обновляем счетчики в таймере
    timer_data["media_notes_count"] = timer_data.get("media_notes_count", 0) + 1
    
    # Обработка фото
    if message.photo:
        file_id = message.photo[-1].file_id
        await create_media_note(
            user_id=user_id,
            category_id=category_id,
            media_type=MediaType.PHOTO,
            file_id=file_id,
            caption=caption,
            content=caption or "Фото заметка из чтения",
            session_id=timer_data.get("session_id")
        )
        await message.answer(
            f"📸 <b>Фото-заметка сохранена во время чтения!</b>\n\n"
            f"📖 Книга: <b>{category_name}</b>\n"
            f"⏱️ Таймер: <b>Продолжает работать</b>",
            parse_mode='HTML'
        )
    
    # Обработка видео
    elif message.video:
        file_id = message.video.file_id
        await create_media_note(
            user_id=user_id,
            category_id=category_id,
            media_type=MediaType.VIDEO,
            file_id=file_id,
            caption=caption,
            content=caption or "Видео заметка из чтения",
            session_id=timer_data.get("session_id")
        )
        await message.answer(
            f"🎥 <b>Видео-заметка сохранена во время чтения!</b>\n\n"
            f"📖 Книга: <b>{category_name}</b>\n"
            f"⏱️ Таймер: <b>Продолжает работать</b>",
            parse_mode='HTML'
        )
    
    # Обработка голосовых
    elif message.voice:
        file_id = message.voice.file_id
        await create_media_note(
            user_id=user_id,
            category_id=category_id,
            media_type=MediaType.VOICE,
            file_id=file_id,
            caption=caption,
            content=caption or "Голосовая заметка из чтения",
            session_id=timer_data.get("session_id")
        )
        await message.answer(
            f"🎤 <b>Голосовая заметка сохранена во время чтения!</b>\n\n"
            f"📖 Книга: <b>{category_name}</b>\n"
            f"⏱️ Таймер: <b>Продолжает работать</b>",
            parse_mode='HTML'
        )
    
    # Обработка документов
    elif message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "Документ"
        await create_media_note(
            user_id=user_id,
            category_id=category_id,
            media_type=MediaType.DOCUMENT,
            file_id=file_id,
            caption=caption,
            content=caption or f"Документ из чтения: {file_name}",
            session_id=timer_data.get("session_id")
        )
        await message.answer(
            f"📄 <b>Документ-заметка сохранена во время чтения!</b>\n\n"
            f"📖 Книга: <b>{category_name}</b>\n"
            f"⏱️ Таймер: <b>Продолжает работать</b>",
            parse_mode='HTML'
        )
    
    # Очищаем состояние, но таймер продолжает работать
    await state.clear()

@dp.message(AddMediaNoteState.waiting_for_media)
async def handle_media_input(message: Message, state: FSMContext):
    """Обработка входящего медиа или текста"""
    data = await state.get_data()
    from_timer = data.get("from_timer", False)
    
    if from_timer:
        # Если медиа из таймера
        await handle_media_from_timer(message, state)
        return
    
    user_id = message.from_user.id
    data = await state.get_data()
    category_id = data.get("current_category")
    
    if not category_id:
        await message.answer(
            "❌ Сначала выберите категорию!\n\n"
            "Нажмите «📚 Категории» или используйте /category"
        )
        return
    
    # Получаем подпись из сообщения (если есть)
    caption = message.caption or ""
    
    # Обработка фото
    if message.photo:
        file_id = message.photo[-1].file_id
        
        # Сохраняем данные в состоянии
        await state.update_data(
            media_type=MediaType.PHOTO,
            media_file_id=file_id,
            media_caption=caption
        )
        
        # Всегда запрашиваем подпись
        await state.set_state(AddMediaNoteState.waiting_for_caption)
        
        if caption:
            await message.answer(
                "📸 <b>Фото получено!</b>\n\n"
                f"Текущая подпись: <i>{caption}</i>\n\n"
                "Хотите изменить подпись?\n"
                "Отправьте новый текст или напишите 'пропустить' чтобы оставить как есть.",
                parse_mode='HTML'
            )
        else:
            await message.answer(
                "📸 <b>Фото получено!</b>\n\n"
                "Хотите добавить подпись к фото?\n"
                "Отправьте текст подписи или напишите 'пропустить' для сохранения без подписи.",
                parse_mode='HTML'
            )
    
    # Обработка видео
    elif message.video:
        file_id = message.video.file_id
        
        await state.update_data(
            media_type=MediaType.VIDEO,
            media_file_id=file_id,
            media_caption=caption
        )
        
        await state.set_state(AddMediaNoteState.waiting_for_caption)
        
        if caption:
            await message.answer(
                "🎥 <b>Видео получено!</b>\n\n"
                f"Текущая подпись: <i>{caption}</i>\n\n"
                "Хотите изменить подпись?\n"
                "Отправьте новый текст или напишите 'пропустить' чтобы оставить как есть.",
                parse_mode='HTML'
            )
        else:
            await message.answer(
                "🎥 <b>Видео получено!</b>\n\n"
                "Хотите добавить описание к видео?\n"
                "Отправьте текст или напишите 'пропустить' для сохранения без подписи.",
                parse_mode='HTML'
            )
    
    # Обработка голосовых сообщений
    elif message.voice:
        file_id = message.voice.file_id
        
        await state.update_data(
            media_type=MediaType.VOICE,
            media_file_id=file_id,
            media_caption=caption
        )
        
        await state.set_state(AddMediaNoteState.waiting_for_caption)
        
        if caption:
            await message.answer(
                "🎤 <b>Голосовое сообщение получено!</b>\n\n"
                f"Текущая подпись: <i>{caption}</i>\n\n"
                "Хотите изменить описание?\n"
                "Отправьте новый текст или напишите 'пропустить' чтобы оставить как есть.",
                parse_mode='HTML'
            )
        else:
            await message.answer(
                "🎤 <b>Голосовое сообщение получено!</b>\n\n"
                "Хотите добавить текстовое описание?\n"
                "Отправьте текст или напишите 'пропустить' для сохранения без описания.",
                parse_mode='HTML'
            )
    
    # Обработка документов
    elif message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "Документ"
        
        await state.update_data(
            media_type=MediaType.DOCUMENT,
            media_file_id=file_id,
            media_caption=caption,
            document_name=file_name
        )
        
        await state.set_state(AddMediaNoteState.waiting_for_caption)
        
        if caption:
            await message.answer(
                f"📄 <b>Документ получен: {file_name}</b>\n\n"
                f"Текущая подпись: <i>{caption}</i>\n\n"
                "Хотите изменить описание?\n"
                "Отправьте новый текст или напишите 'пропустить' чтобы оставить как есть.",
                parse_mode='HTML'
            )
        else:
            await message.answer(
                f"📄 <b>Документ получен: {file_name}</b>\n\n"
                "Хотите добавить описание к документу?\n"
                "Отправьте текст или напишите 'пропустить' для сохранения без описания.",
                parse_mode='HTML'
            )
    
    # Обработка текста
    elif message.text and not message.text.startswith('/'):
        if message.text.lower() in ['пропустить', 'skip', 'нет']:
            # Если пользователь пропускает добавление медиа
            await state.clear()
            await message.answer("❌ Добавление медиа отменено")
            return
        
        # Если в режиме медиа, но пришел текст - делаем обычную заметку
        await create_text_note(user_id, category_id, message.text)
        await message.answer("✅ Текстовая заметка сохранена!")
        await state.clear()

@dp.message(AddMediaNoteState.waiting_for_caption)
async def handle_media_caption(message: Message, state: FSMContext):
    """Обработка подписи к медиа"""
    if message.text and message.text.lower() in ['/skip', 'пропустить', 'skip', 'нет']:
        # Если пользователь не хочет добавлять подпись
        data = await state.get_data()
        user_id = message.from_user.id
        category_id = data.get("current_category")
        
        if category_id:
            note = await save_media_note(data, user_id, category_id)
            
            # Получаем название категории
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Category).where(Category.id == category_id)
                )
                category = result.scalar_one_or_none()
            
            media_emoji = {
                MediaType.PHOTO: "📸",
                MediaType.VIDEO: "🎥",
                MediaType.VOICE: "🎤",
                MediaType.DOCUMENT: "📄"
            }.get(data.get("media_type"), "📎")
            
            await message.answer(
                f"{media_emoji} <b>Медиа-заметка сохранена!</b>\n\n"
                f"📁 Категория: <b>{category.name if category else 'Неизвестно'}</b>\n"
                f"📌 Тип: <b>{data.get('media_type').value.capitalize()}</b>",
                parse_mode='HTML'
            )
        
        await state.clear()
        return
    
    # Обновляем подпись в состоянии
    await state.update_data(media_caption=message.text)
    
    data = await state.get_data()
    user_id = message.from_user.id
    category_id = data.get("current_category")
    
    if category_id:
        note = await save_media_note(data, user_id, category_id)
        
        # Получаем название категории
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Category).where(Category.id == category_id)
            )
            category = result.scalar_one_or_none()
        
        media_emoji = {
            MediaType.PHOTO: "📸",
            MediaType.VIDEO: "🎥",
            MediaType.VOICE: "🎤",
            MediaType.DOCUMENT: "📄"
        }.get(data.get("media_type"), "📎")
        
        await message.answer(
            f"{media_emoji} <b>Медиа-заметка сохранена!</b>\n\n"
            f"📁 Категория: <b>{category.name if category else 'Неизвестно'}</b>\n"
            f"📌 Тип: <b>{data.get('media_type').value.capitalize()}</b>\n"
            f"📝 Подпись: {message.text}",
            parse_mode='HTML'
        )
    
    await state.clear()

# ===========================================
# КАТЕГОРИИ
# ===========================================
@dp.message(Command("category"))
async def choose_category(message: Message, state: FSMContext):
    """Показать список категорий"""
    user_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Category).where(Category.user_id == user_id)
        )
        categories = result.scalars().all()

    if not categories:
        await message.answer("Категорий ещё нет. Введите название новой категории:")
        await state.set_state(CategoryState.waiting_for_category_name)
        return

    # Показываем кнопки с категориями
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=cat.name, callback_data=f"cat_{cat.id}"),
            InlineKeyboardButton(text="✏️", callback_data=f"renamecat_{cat.id}"),
            InlineKeyboardButton(text="🗑️", callback_data=f"deletecat_{cat.id}")
        ]
        for cat in categories
    ] + [
        [InlineKeyboardButton(text="+ Создать новую категорию", callback_data="cat_new")]
    ])
    
    await message.answer("Выбери категорию (✏️-переименовать, 🗑️-удалить):", reply_markup=keyboard)

@dp.message(F.text == "📚 Категории")
async def handle_categories_button(message: Message, state: FSMContext):
    await choose_category(message, state)

@dp.callback_query(F.data == "cat_new")
async def new_category(query: CallbackQuery, state: FSMContext):
    """Обработка кнопки создания новой категории"""
    await query.message.answer("Введите название новой категории (обычно название книги):")
    await state.set_state(CategoryState.waiting_for_category_name)
    await query.answer()

@dp.message(F.text == "➕ Новая категория")
async def handle_new_category_button(message: Message, state: FSMContext):
    """Обработка кнопки создания новой категории из главного меню"""
    await message.answer("Введите название новой категории (обычно название книги):")
    await state.set_state(CategoryState.waiting_for_category_name)

@dp.message(CategoryState.waiting_for_category_name)
async def save_new_category(message: Message, state: FSMContext):
    user_id = message.from_user.id
    name = message.text.strip()

    # Проверяем, не является ли текст кнопкой меню
    if message.text in ["📚 Категории", "📝 Заметки", "➕ Новая категория", "📊 Статистика"]:
        await state.clear()
        
        if message.text == "📚 Категории":
            await choose_category(message, state)
        elif message.text == "📝 Заметки":
            await cmd_notes(message)
        elif message.text == "➕ Новая категория":
            await message.answer("Введите название новой категории:")
            await state.set_state(CategoryState.waiting_for_category_name)
        elif message.text == "📊 Статистика":
            await show_statistics(message)
        return

    if not name:
        await message.answer("Название не может быть пустым. Попробуй ещё раз:")
        return

    # Создаём новую категорию
    new_cat = Category(user_id=user_id, name=name)

    async with AsyncSessionLocal() as session:
        session.add(new_cat)
        await session.commit()
        await session.refresh(new_cat)

    # Сохраняем выбранную категорию
    await state.update_data(current_category=new_cat.id)
    await state.set_state(None)

    await message.answer(
        f"✅ Категория <b>{name}</b> создана и выбрана!\n\n"
        f"Теперь пиши сообщения — они будут сохраняться в эту категорию."
    )

@dp.callback_query(F.data.startswith("cat_"))
async def select_category(query: CallbackQuery, state: FSMContext):
    """Выбор существующей категории"""
    if query.data == "cat_new":
        return
    
    try:
        cat_id = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer("❌ Ошибка")
        return
    
    await state.update_data(current_category=cat_id)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Category).where(Category.id == cat_id)
        )
        category = result.scalar_one_or_none()

    if category:
        await query.message.answer(f"✅ Выбрана категория: <b>{category.name}</b>\nТеперь можно писать заметки!")
    
    await query.answer()

# ===========================================
# ЗАМЕТКИ
# ===========================================
@dp.message(Command("notes"))
async def cmd_notes(message: Message):
    user_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Category).where(Category.user_id == user_id)
        )
        categories = result.scalars().all()

    if not categories:
        await message.answer("Категорий пока нет. Создай → /category")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cat.name, callback_data=f"showcat_{cat.id}")]
        for cat in categories
    ] + [
        [InlineKeyboardButton(text="Сменить категорию", callback_data="change_category")]
    ])
    
    await message.answer("Выбери категорию для просмотра заметок:", reply_markup=kb)

@dp.message(F.text == "📝 Заметки")
async def show_notes(message: Message):
    await cmd_notes(message)

@dp.callback_query(F.data.startswith("showcat_"))
async def show_category_notes(query: CallbackQuery):
    """Просмотр заметок в категории"""
    try:
        category_id = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer("❌ Ошибка")
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Note).where(
                (Note.category_id == category_id) &
                (Note.is_deleted == False)
            ).order_by(Note.created_at.asc())
        )
        notes = result.scalars().all()

        cat_result = await session.execute(
            select(Category).where(Category.id == category_id)
        )
        category = cat_result.scalar_one_or_none()
    
    if not category:
        await query.message.answer("❌ Категория не найдена")
        await query.answer()
        return

    # Навигация
    nav_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← Вернуться к категориям", callback_data="back_cats")],
        [
            InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"renamecat_{category_id}"),
            InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"deletecat_{category_id}"),
            InlineKeyboardButton(text="📸 Добавить медиа", callback_data=f"add_media_{category_id}")
        ]
    ])

    # Считаем статистику по типам заметок
    text_count = sum(1 for n in notes if n.media_type == MediaType.TEXT)
    photo_count = sum(1 for n in notes if n.media_type == MediaType.PHOTO)
    video_count = sum(1 for n in notes if n.media_type == MediaType.VIDEO)
    voice_count = sum(1 for n in notes if n.media_type == MediaType.VOICE)
    doc_count = sum(1 for n in notes if n.media_type == MediaType.DOCUMENT)

    await query.message.answer(
        f"📖 <b>{category.name}</b>\n"
        f"📝 Всего заметок: {len(notes)}\n"
        f"📄 Текстовых: {text_count}\n"
        f"📸 Фото: {photo_count}\n"
        f"🎥 Видео: {video_count}\n"
        f"🎤 Голосовых: {voice_count}\n"
        f"📎 Документов: {doc_count}",
        reply_markup=nav_keyboard,
        parse_mode='HTML'
    )

    if not notes:
        await query.message.answer(
            f"В категории <b>{category.name}</b> нет заметок.",
            reply_markup=nav_keyboard,
            parse_mode='HTML'
        )
        await query.answer()
        return

    # Выводим каждую заметку
    for i, note in enumerate(notes, 1):
        media_emoji = {
            MediaType.TEXT: "📝",
            MediaType.PHOTO: "📸",
            MediaType.VIDEO: "🎥",
            MediaType.VOICE: "🎤",
            MediaType.DOCUMENT: "📄"
        }.get(note.media_type, "📎")
        
        created_time = note.created_at.strftime('%d.%m.%Y %H:%M') if note.created_at else "без даты"
        
        # Клавиатура для заметки
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{note.id}"),
                InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_{note.id}")
            ]
        ])
        
        if note.media_type != MediaType.TEXT:
            # Добавляем кнопку просмотра для медиа
            kb.inline_keyboard[0].append(
                InlineKeyboardButton(text="👁️ Просмотреть", callback_data=f"view_{note.id}")
            )
        
        if note.media_type == MediaType.TEXT:
            # Текстовая заметка
            note_content = note.content or ""
            if len(note_content) > 3000:
                note_content = note_content[:3000] + "...\n\n[Текст обрезан]"
            
            formatted_note = (
                f"{media_emoji} <b>Заметка #{i}</b>\n\n"
                f"<blockquote>{note_content}</blockquote>\n\n"
                f"🕒 <i>{created_time}</i>"
            )
            
            try:
                await query.message.answer(formatted_note, reply_markup=kb, parse_mode='HTML')
            except Exception:
                await query.message.answer(
                    f"Заметка #{i}\n\n{note_content}\n\n🕒 {created_time}",
                    reply_markup=kb
                )
        else:
            # Медиа-заметка
            media_info = f"{media_emoji} <b>Медиа-заметка #{i}</b>\n"
            
            if note.media_caption:
                media_info += f"📝 <i>{note.media_caption}</i>\n\n"
            elif note.content:
                media_info += f"📝 <i>{note.content}</i>\n\n"
            
            media_info += f"🕒 <i>{created_time}</i>"
            
            await query.message.answer(media_info, reply_markup=kb, parse_mode='HTML')
    
    await query.answer()

@dp.callback_query(F.data.startswith("add_media_"))
async def add_media_to_category(query: CallbackQuery, state: FSMContext):
    """Добавить медиа в конкретную категорию"""
    try:
        category_id = int(query.data.split("_")[2])
    except (IndexError, ValueError):
        await query.answer("❌ Ошибка")
        return
    
    # Сохраняем выбранную категорию
    await state.update_data(current_category=category_id)
    
    # Получаем название категории
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Category).where(Category.id == category_id)
        )
        category = result.scalar_one_or_none()
    
    await query.message.answer(
        f"📸 <b>Добавление медиа в категорию: {category.name if category else 'Неизвестно'}</b>\n\n"
        f"Отправьте фото, видео, голосовое сообщение или документ.",
        parse_mode='HTML'
    )
    
    # Устанавливаем состояние ожидания медиа
    await state.set_state(AddMediaNoteState.waiting_for_media)
    await query.answer()

@dp.message(F.text == "📸 Медиа")
@dp.message(Command("addmedia"))
async def start_media_note(message: Message, state: FSMContext):
    """Начало создания медиа-заметки"""
    data = await state.get_data()
    category_id = data.get("current_category")
    
    if not category_id:
        # Если категория не выбрана, показываем список категорий
        await message.answer("📁 Сначала выберите категорию для медиа-заметки:")
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Category).where(Category.user_id == message.from_user.id)
            )
            categories = result.scalars().all()
        
        if not categories:
            await message.answer("❌ У вас нет категорий. Создайте сначала категорию.")
            return
        
        # Показываем категории для выбора
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=cat.name, callback_data=f"media_cat_{cat.id}")]
            for cat in categories
        ] + [
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_media")]
        ])
        
        await message.answer("Выберите категорию для медиа-заметки:", reply_markup=keyboard)
        return
    
    # Если категория уже выбрана, запрашиваем медиа
    await state.set_state(AddMediaNoteState.waiting_for_media)
    
    await message.answer(
        "📸 <b>Добавление медиа-заметки</b>\n\n"
        "Отправьте фото, видео, голосовое сообщение или документ.\n"
        "Можно добавить подпись после отправки медиа.\n\n"
        "<i>Или отправьте текст для обычной заметки.</i>",
        parse_mode='HTML'
    )

@dp.callback_query(F.data.startswith("media_cat_"))
async def select_category_for_media(query: CallbackQuery, state: FSMContext):
    """Выбор категории для медиа-заметки"""
    try:
        category_id = int(query.data.split("_")[2])
    except (IndexError, ValueError):
        await query.answer("❌ Ошибка")
        return
    
    # Сохраняем выбранную категорию
    await state.update_data(current_category=category_id)
    
    # Получаем название категории
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Category).where(Category.id == category_id)
        )
        category = result.scalar_one_or_none()
    
    await query.message.edit_text(
        f"✅ Выбрана категория: <b>{category.name if category else 'Неизвестно'}</b>\n\n"
        f"Теперь отправьте фото, видео, голосовое сообщение или документ.",
        parse_mode='HTML'
    )
    
    # Устанавливаем состояние ожидания медиа
    await state.set_state(AddMediaNoteState.waiting_for_media)
    await query.answer()

@dp.callback_query(F.data == "cancel_media")
async def cancel_media_note(query: CallbackQuery, state: FSMContext):
    """Отмена создания медиа-заметки"""
    await state.clear()
    await query.message.edit_text("❌ Создание медиа-заметки отменено.")
    await query.answer()

@dp.callback_query(F.data.startswith("view_"))
async def view_media_note(query: CallbackQuery):
    """Просмотр медиа-заметки"""
    try:
        note_id = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer("❌ Ошибка")
        return
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Note).where(Note.id == note_id)
        )
        note = result.scalar_one_or_none()
        
        if not note or not note.media_file_id:
            await query.answer("❌ Заметка не найдена или не содержит медиа")
            return
        
        cat_result = await session.execute(
            select(Category).where(Category.id == note.category_id)
        )
        category = cat_result.scalar_one_or_none()
    
    # Создаем подпись
    caption = f"📁 {category.name if category else 'Категория'}\n"
    if note.media_caption:
        caption += f"📝 {note.media_caption}\n"
    caption += f"🕒 {note.created_at.strftime('%d.%m.%Y %H:%M')}"
    
    # Отправляем медиа в зависимости от типа
    try:
        if note.media_type == MediaType.PHOTO:
            await bot.send_photo(
                chat_id=query.from_user.id,
                photo=note.media_file_id,
                caption=caption,
                parse_mode='HTML'
            )
        elif note.media_type == MediaType.VIDEO:
            await bot.send_video(
                chat_id=query.from_user.id,
                video=note.media_file_id,
                caption=caption,
                parse_mode='HTML'
            )
        elif note.media_type == MediaType.VOICE:
            await bot.send_voice(
                chat_id=query.from_user.id,
                voice=note.media_file_id,
                caption=caption,
                parse_mode='HTML'
            )
        elif note.media_type == MediaType.DOCUMENT:
            await bot.send_document(
                chat_id=query.from_user.id,
                document=note.media_file_id,
                caption=caption,
                parse_mode='HTML'
            )
    except Exception as e:
        await query.message.answer(f"❌ Ошибка при отправке медиа: {e}")
    
    await query.answer()

@dp.callback_query(F.data == "back_cats")
async def back_to_categories(query: CallbackQuery):
    """Вернуться к списку категорий"""
    user_id = query.from_user.id

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Category).where(Category.user_id == user_id)
        )
        categories = result.scalars().all()

    if not categories:
        await query.message.answer("Категорий пока нет. Создай → /category")
        await query.answer()
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cat.name, callback_data=f"showcat_{cat.id}")]
        for cat in categories
    ] + [
        [InlineKeyboardButton(text="+ Создать новую категорию", callback_data="cat_new")]
    ])

    await query.message.answer("Выбери категорию:", reply_markup=keyboard)
    await query.answer()

@dp.callback_query(F.data == "change_category")
async def change_category(query: CallbackQuery, state: FSMContext):
    """Сменить категорию"""
    await query.message.answer("Выбираем новую категорию...")
    await choose_category(query.message, state)
    await query.answer()

@dp.callback_query(F.data.startswith("delete_"))
async def delete_note(query: CallbackQuery):
    """Удаление заметки"""
    try:
        note_id = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer("❌ Ошибка")
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Note).where(Note.id == note_id)
        )
        note = result.scalar_one_or_none()
        
        if note:
            note.is_deleted = True
            await session.commit()
            await query.message.edit_text("✅ Заметка удалена.")
    
    await query.answer()

@dp.callback_query(F.data.startswith("edit_"))
async def start_edit(query: CallbackQuery, state: FSMContext):
    """Начать редактирование заметки"""
    try:
        note_id = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer("❌ Ошибка")
        return
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Note).where(Note.id == note_id)
        )
        note = result.scalar_one_or_none()
        
        if not note:
            await query.answer("❌ Заметка не найдена")
            return
        
        current_text = note.content or ""
    
    await state.update_data(
        edit_note_id=note_id,
        original_text=current_text
    )
    
    await state.set_state(EditNoteState.waiting_for_new_text)
    
    await query.message.answer(
        f"✏️ <b>Редактирование заметка</b>\n\n"
        f"Текущий текст:\n"
        f"<i>{current_text[:200]}...</i>\n\n"
        f"Введите новый текст или напишите <code>/cancel</code> для отмены:",
        parse_mode='HTML'
    )
    await query.answer()

@dp.message(EditNoteState.waiting_for_new_text)
async def apply_edit(message: Message, state: FSMContext):
    """Применить редактирование заметки"""
    new_text = message.text.strip()
    
    if not new_text:
        await message.answer("❌ Текст не может быть пустым. Попробуйте снова:")
        return
    
    # Получаем ID заметки из состояния
    data = await state.get_data()
    note_id = data.get("edit_note_id")
    
    if not note_id:
        await message.answer("❌ Ошибка: ID заметки не найден")
        await state.clear()
        return
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Note).where(Note.id == note_id)
        )
        note = result.scalar_one_or_none()
        
        if note:
            note.content = new_text
            await session.commit()
            
            await message.answer(
                f"✅ <b>Заметка обновлена!</b>\n\n"
                f"📝 <b>Новый текст:</b>\n"
                f"<blockquote>{new_text[:300]}...</blockquote>",
                parse_mode='HTML'
            )
        else:
            await message.answer("❌ Заметка не найдена")
    
    await state.clear()

# ===========================================
# ПЕРЕИМЕНОВАНИЕ КАТЕГОРИИ
# ===========================================
@dp.callback_query(F.data.startswith("renamecat_"))
async def start_rename_category(query: CallbackQuery, state: FSMContext):
    """Начать переименование категории"""
    try:
        category_id = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer("❌ Ошибка")
        return
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Category).where(Category.id == category_id)
        )
        category = result.scalar_one_or_none()
        
        if not category:
            await query.answer("❌ Категория не найдена")
            return
        
        current_name = category.name
    
    await state.update_data(
        rename_category_id=category_id,
        rename_old_name=current_name
    )
    
    await state.set_state(RenameCategoryState.waiting_for_new_category_name)
    
    await query.message.answer(
        f"✏️ <b>Переименование категории</b>\n\n"
        f"Текущее название: <b>{current_name}</b>\n"
        f"Введите новое название или напишите <code>/cancel</code> для отмены:",
        parse_mode='HTML'
    )
    await query.answer()

@dp.message(RenameCategoryState.waiting_for_new_category_name)
async def apply_rename_category(message: Message, state: FSMContext):
    """Применить новое название категории"""
    if message.text.lower() in ["/cancel", "отмена", "cancel"]:
        await state.clear()
        await message.answer("❌ Переименование отменено")
        return
    
    new_name = message.text.strip()
    
    if not new_name:
        await message.answer("❌ Название не может быть пустым. Попробуйте снова:")
        return
    
    if len(new_name) > 100:
        await message.answer("❌ Название слишком длинное (макс. 100 символов). Попробуйте снова:")
        return
    
    data = await state.get_data()
    category_id = data.get("rename_category_id")
    old_name = data.get("rename_old_name", "")
    
    if not category_id:
        await message.answer("❌ Ошибка: ID категории не найден")
        await state.clear()
        return
    
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        duplicate_result = await session.execute(
            select(Category).where(
                (Category.user_id == user_id) &
                (Category.name == new_name) &
                (Category.id != category_id)
            )
        )
        duplicate = duplicate_result.scalar_one_or_none()
        
        if duplicate:
            await message.answer(f"❌ У вас уже есть категория с названием <b>{new_name}</b>")
            await state.clear()
            return
        
        result = await session.execute(
            select(Category).where(Category.id == category_id)
        )
        category = result.scalar_one_or_none()
        
        if category:
            category.name = new_name
            await session.commit()
            
            await message.answer(
                f"✅ <b>Категория переименована!</b>\n\n"
                f"📝 <b>Было:</b> {old_name}\n"
                f"📝 <b>Стало:</b> {new_name}"
            )
            
            current_data = await state.get_data()
            current_category_id = current_data.get("current_category")
            if current_category_id == category_id:
                await state.update_data(current_category_name=new_name)
        else:
            await message.answer("❌ Категория не найдена")
    
    await state.clear()

# ===========================================
# УДАЛЕНИЕ КАТЕГОРИИ
# ===========================================
@dp.callback_query(F.data.startswith("deletecat_"))
async def start_delete_category(query: CallbackQuery, state: FSMContext):
    """Начать удаление категории"""
    try:
        category_id = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer("❌ Ошибка")
        return
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Category).where(Category.id == category_id)
        )
        category = result.scalar_one_or_none()
        
        if not category:
            await query.answer("❌ Категория не найдена")
            return
        
        notes_result = await session.execute(
            select(Note).where(Note.category_id == category_id)
        )
        notes_count = len(notes_result.scalars().all())
        category_name = category.name
    
    await state.update_data(
        delete_category_id=category_id,
        delete_category_name=category_name,
        delete_notes_count=notes_count
    )
    
    await state.set_state(DeleteCategoryState.waiting_for_delete_confirmation)
    
    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete"),
            InlineKeyboardButton(text="❌ Нет, отмена", callback_data="cancel_delete")
        ]
    ])
    
    await query.message.answer(
        f"⚠️ <b>Подтвердите удаление категории</b>\n\n"
        f"📂 Категория: <b>{category_name}</b>\n"
        f"📝 Заметок в категории: <b>{notes_count}</b>\n\n"
        f"<i>Все заметки в этой категории также будут удалены!</i>\n"
        f"Вы уверены, что хотите удалить эту категорию?",
        reply_markup=confirm_keyboard
    )
    await query.answer()

@dp.callback_query(F.data == "confirm_delete")
async def confirm_delete_category(query: CallbackQuery, state: FSMContext):
    """Подтверждение удаления категории"""
    data = await state.get_data()
    category_id = data.get("delete_category_id")
    category_name = data.get("delete_category_name", "")
    notes_count = data.get("delete_notes_count", 0)
    
    if not category_id:
        await query.message.answer("❌ Ошибка: ID категории не найден")
        await state.clear()
        await query.answer()
        return
    
    user_id = query.from_user.id
    
    async with AsyncSessionLocal() as session:
        try:
            # Удаляем все заметки категории
            if notes_count > 0:
                await session.execute(
                    Note.__table__.delete().where(Note.category_id == category_id)
                )
            
            # Удаляем саму категорию
            await session.execute(
                Category.__table__.delete().where(
                    (Category.id == category_id) &
                    (Category.user_id == user_id)
                )
            )
            
            await session.commit()
            
            await query.message.edit_text(
                f"✅ <b>Категория удалена!</b>\n\n"
                f"📂 Категория: <b>{category_name}</b>\n"
                f"🗑️ Удалено заметок: <b>{notes_count}</b>"
            )
            
            current_data = await state.get_data()
            current_category_id = current_data.get("current_category")
            if current_category_id == category_id:
                await state.update_data(current_category=None)
                
        except Exception as e:
            await query.message.edit_text(f"❌ Ошибка при удалении: {e}")
    
    await state.clear()
    await query.answer()

@dp.callback_query(F.data == "cancel_delete")
async def cancel_delete_category(query: CallbackQuery, state: FSMContext):
    """Отмена удаления категории"""
    await query.message.edit_text("❌ Удаление категории отменено")
    await state.clear()
    await query.answer()

# ===========================================
# СТАТИСТИКА (С ГРАФИКАМИ И ТЕКСТОМ)
# ===========================================
@dp.message(Command("stats"))
@dp.message(F.text == "📊 Статистика")
async def show_statistics(message: Message):
    """Показать статистику чтения (2 графика + текст)"""
    user_id = message.from_user.id
    
    msg = await message.answer("📊 Загружаю статистику...")
    
    async with AsyncSessionLocal() as session:
        try:
            # === ОСНОВНЫЕ ПОКАЗАТЕЛИ ===
            cat_result = await session.execute(
                select(func.count(Category.id)).where(Category.user_id == user_id)
            )
            categories_count = cat_result.scalar() or 0
            
            notes_result = await session.execute(
                select(func.count(Note.id)).where(
                    Note.user_id == user_id, 
                    Note.is_deleted == False
                )
            )
            notes_count = notes_result.scalar() or 0
            
            sessions_result = await session.execute(
                select(ReadingSession).where(ReadingSession.user_id == user_id)
            )
            all_sessions = sessions_result.scalars().all()
            
            total_time = 0
            completed_sessions = [s for s in all_sessions if s.duration_seconds]
            sessions_count = len(completed_sessions)
            
            for s in completed_sessions:
                total_time += s.duration_seconds
            
            avg_session_time = total_time / sessions_count if sessions_count > 0 else 0
            hours = total_time / 3600
            
            # === ЗАМЕТКИ ПО КАТЕГОРИЯМ ===
            cat_stats = await session.execute(
                select(Category.name, func.count(Note.id))
                .join(Note, Category.id == Note.category_id)
                .where(
                    Category.user_id == user_id,
                    Note.is_deleted == False
                )
                .group_by(Category.id, Category.name)
                .order_by(func.count(Note.id).desc())
            )
            notes_by_category = dict(cat_stats.all())
            
            # === АКТИВНОСТЬ ПО ДНЯМ ===
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            
            # Заметки по дням
            daily_notes = await session.execute(
                select(func.date(Note.created_at), func.count(Note.id))
                .where(
                    Note.user_id == user_id,
                    Note.created_at >= thirty_days_ago,
                    Note.is_deleted == False
                )
                .group_by(func.date(Note.created_at))
                .order_by(func.date(Note.created_at))
            )
            
            notes_by_date = {}
            for date_str, count in daily_notes.all():
                if date_str:
                    try:
                        date_obj = datetime.strptime(str(date_str), '%Y-%m-%d')
                        notes_by_date[date_obj.strftime('%d.%m.%Y')] = count
                    except:
                        continue
            
            # Время по дням
            daily_time = await session.execute(
                select(func.date(ReadingSession.start_time), func.sum(ReadingSession.duration_seconds))
                .where(
                    ReadingSession.user_id == user_id,
                    ReadingSession.start_time >= thirty_days_ago,
                    ReadingSession.is_completed == True
                )
                .group_by(func.date(ReadingSession.start_time))
            )
            
            time_by_date = {}
            for date_str, seconds in daily_time.all():
                if date_str and seconds:
                    try:
                        date_obj = datetime.strptime(str(date_str), '%Y-%m-%d')
                        time_by_date[date_obj.strftime('%d.%m.%Y')] = seconds
                    except:
                        continue
            
            # === СТРЕЙК ===
            today = datetime.utcnow().date()
            streak = 0
            check_date = today
            
            while True:
                day_activity = await session.execute(
                    select(Note.id)
                    .where(
                        Note.user_id == user_id,
                        func.date(Note.created_at) == check_date.strftime('%Y-%m-%d'),
                        Note.is_deleted == False
                    )
                    .limit(1)
                )
                
                if day_activity.first():
                    streak += 1
                    check_date -= timedelta(days=1)
                else:
                    break
                    
        except Exception as e:
            await msg.delete()
            await message.answer(f"❌ Ошибка загрузки статистики: {e}")
            return
    
    # === ОТПРАВКА ГРАФИКОВ ===
    try:
        chart_buf = create_reading_stats_chart(notes_by_category, notes_by_date, time_by_date)
        await msg.delete()
        await message.answer_photo(
            BufferedInputFile(chart_buf.getvalue(), filename="stats.png"),
            caption="📈 Статистика чтения (графики)"
        )
    except Exception as e:
        print(f"Ошибка создания графиков: {e}")
        await msg.delete()
        await message.answer("📊 Загружаю текстовую статистику...")
    
    # === ТЕКСТОВАЯ СТАТИСТИКА ===
    
    # --- Огонек ---
    if streak == 0:
        fire = "🕯️"
        streak_text = "Нет серии"
    elif streak == 1:
        fire = "🔥"
        streak_text = "1 день"
    elif streak == 2:
        fire = "🔥🔥"
        streak_text = "2 дня"
    elif streak == 3:
        fire = "🔥🔥🔥"
        streak_text = "3 дня"
    elif streak == 4:
        fire = "🔥🔥🔥🔥"
        streak_text = "4 дня"
    elif streak == 5:
        fire = "🔥🔥🔥🔥🔥"
        streak_text = "5 дней"
    elif streak == 6:
        fire = "🔥🔥🔥🔥🔥🔥"
        streak_text = "6 дней"
    elif streak >= 7:
        fire = "🔥" * 7 + ("➕" if streak > 7 else "")
        streak_text = f"{streak} дней"
    
    # --- Уровень ---
    level = min(50, notes_count // 5 + 1)
    exp_current = notes_count % 5
    
    if level <= 5:
        level_title = "🌱 НОВИЧОК"
        next_level = 10
        next_level_title = "📖 ЧИТАТЕЛЬ"
    elif level <= 10:
        level_title = "📖 ЧИТАТЕЛЬ"
        next_level = 15
        next_level_title = "📚 КНИГОЛЮБ"
    elif level <= 15:
        level_title = "📚 КНИГОЛЮБ"
        next_level = 20
        next_level_title = "🔍 ИССЛЕДОВАТЕЛЬ"
    elif level <= 20:
        level_title = "🔍 ИССЛЕДОВАТЕЛЬ"
        next_level = 25
        next_level_title = "🧠 МЫСЛИТЕЛЬ"
    else:
        level_title = "🧠 МЫСЛИТЕЛЬ"
        next_level = 30
        next_level_title = "⚡ ЭРУДИТ"
    
    level_bar = '█' * exp_current + '░' * (5 - exp_current)
    level_progress = (notes_count / (next_level * 5)) * 100 if next_level else 0
    level_progress_bar = '█' * int(level_progress / 5) + '░' * (20 - int(level_progress / 5))
    
    # --- Достижения ---
    achievements = []
    if notes_count >= 10:
        achievements.append("🌱 Начинающий: 10+ заметок")
    if notes_count >= 20:
        achievements.append("📚 Активист: 20+ заметок")
    if total_time >= 3600:
        achievements.append("⏱️ В ритме книг: 1+ час")
    if streak >= 7:
        achievements.append("🔥 Недельная серия")
    if categories_count >= 3:
        achievements.append("📚 Три книги")
    
    # --- Следующая цель ---
    if notes_count < 10:
        next_goal = "📄 10 заметок"
        next_goal_current = notes_count
        next_goal_target = 10
    elif notes_count < 20:
        next_goal = "📚 20 заметок"
        next_goal_current = notes_count
        next_goal_target = 20
    elif notes_count < 50:
        next_goal = "📚 50 заметок"
        next_goal_current = notes_count
        next_goal_target = 50
    else:
        next_goal = "📖 100 заметок"
        next_goal_current = notes_count
        next_goal_target = 100
    
    goal_progress = (next_goal_current / next_goal_target * 100)
    goal_bar = '█' * int(goal_progress / 5) + '░' * (20 - int(goal_progress / 5))
    
    # --- ФОРМИРУЕМ ТЕКСТ ---
    text = f"📊 <b>СТАТИСТИКА ЧТЕНИЯ</b>\n"
    text += f"{'─' * 35}\n\n"
    
    text += f"{fire} <b>{streak_text}</b>\n"
    text += f"{level_title} • Уровень {level}\n"
    text += f"{level_bar} {exp_current}/5 XP\n"
    text += f"✨ Всего опыта: {notes_count} XP\n\n"
    
    text += f"📂 Категории: {categories_count}\n"
    text += f"📝 Заметки: {notes_count}\n"
    text += f"⏱️ Сессии: {sessions_count}\n"
    text += f"🕐 Время: {format_time_short(int(total_time))} ({hours:.1f}ч)\n"
    text += f"📊 Среднее: {format_time_short(int(avg_session_time))}\n\n"
    
    if notes_by_category:
        text += f"📚 <b>ТОП КАТЕГОРИЙ:</b>\n"
        for i, (cat, cnt) in enumerate(list(notes_by_category.items())[:3], 1):
            percent = (cnt / notes_count * 100) if notes_count > 0 else 0
            cat_short = cat[:20] + '...' if len(cat) > 20 else cat
            text += f"{i}. {cat_short}: {cnt} ({percent:.0f}%)\n"
        text += f"\n"
    
    if achievements:
        text += f"🏆 <b>ДОСТИЖЕНИЯ:</b>\n"
        for ach in achievements[:3]:
            text += f"  {ach}\n"
        text += f"\n"
    
    text += f"🎯 <b>ТЕКУЩИЙ УРОВЕНЬ: {level_title}</b>\n"
    text += f"До «{next_level_title}»: {notes_count}/{next_level * 5} XP\n"
    text += f"{level_progress_bar} {level_progress:.0f}%\n\n"
    
    text += f"🎯 <b>СЛЕДУЮЩАЯ ЦЕЛЬ:</b>\n"
    text += f"{next_goal}\n"
    text += f"{goal_bar} {next_goal_current}/{next_goal_target} ({goal_progress:.0f}%)\n\n"
    
    # Совет дня
    import random
    tips = [
        "📚 Читайте каждый день хотя бы 15 минут",
        "🎯 Цель: 5 заметок в неделю",
        "⏱️ Используйте таймер чтения",
        "📸 Фотографируйте интересные страницы",
        f"🔥 {streak} дней подряд! Отлично!"
    ]
    tip = random.choice(tips) if streak > 0 else "🔥 Сделайте первую заметку сегодня!"
    
    text += f"💡 <b>СОВЕТ ДНЯ:</b>\n{tip}"
    
    await message.answer(text, parse_mode='HTML')
    

    # О НАС
# ===========================================
@dp.message(Command("about"))
@dp.message(F.text == "ℹ️ О нас")
async def about_us(message: Message):
    """Показать информацию о проекте"""
    
    about_text = (
        "📚 <b>HSEBookNotes </b> - ваш умный помощник для систематизации знаний из книг\n\n"
        
        "🌟 <b>Основные возможности:</b>\n"
        "• Создание категорий для разных книг и тем\n"
        "• Сохранение текстовых заметок с цитатами и идеями\n" 
        "• Редактирование и удаление заметок\n"
        "• Статистика чтения с визуальными графиками\n"
        "• Управление категориями (переименование, удаление)\n"
        "• Поддержка фото, видео, голосовых и документов\n\n"
        
        "🆕 <b>Новые функции в версии 3.0:</b>\n"
        "• ⏱️ <b>Таймер чтения</b> - отслеживайте время, проведенное за книгами\n"
        "• 📈 <b>Статистика времени</b> - анализируйте свои привычки чтения\n"
        "• 🎯 <b>Сессии чтения</b> - фиксируйте прогресс по каждой книге\n"
        "• 📝 <b>Заметки во время чтения</b> - добавляйте мысли без прерывания таймера\n\n"
        
        "🎯 <b>Цель проекта:</b>\n"
        "Помочь вам систематизировать мысли, цитаты и идеи из прочитанных книг,\n"
        "а также развить полезные привычки регулярного чтения.\n\n"
        
        "📈 <b>Планы на будущее:</b>\n"
        "• 📅 Умные напоминания о чтении\n" 
        "• 📊 Продвинутая аналитика с рекомендациями\n"
        "• 🤖 ИИ-ассистент для анализа заметок\n"
        "• 📱 Мобильное приложение\n"
        "• 👥 Совместные книжные клубы\n\n"
        
        "💡 <b>Советы по использованию:</b>\n"
        "• Используйте таймер чтения для формирования привычки\n"
        "• Делайте заметки сразу после прочтения главы\n"
        "• Создавайте отдельные категории для разных жанров\n"
        "• Регулярно проверяйте статистику для мотивации\n\n"
        
        "<b>Разработчики:</b> @bezdarn_ost, @VlaDragonborn, @osjf00, @kot_buterbrot, @shieruu\n"
        "<b>Версия:</b> 3.0.0 (с таймером чтения)\n"
        "<b>Дата обновления:</b> 2026\n"
        "<b>Проект создан в рамках майнора по UX/UI дизайну НИУ ВШЭ</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📞 Связаться", url="https://t.me/bezdarn_ost"),
            InlineKeyboardButton(text="⭐ Оценить", callback_data="rate_bot")
        ],
        [
            InlineKeyboardButton(text="⏱️ Про таймер", callback_data="about_timer"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="about_stats")
        ],
        [
            InlineKeyboardButton(text="🔄 Обновления", callback_data="updates"),
            InlineKeyboardButton(text="📚 Помощь", callback_data="help_info")
        ]
    ])
    
    await message.answer(about_text, reply_markup=keyboard, parse_mode='HTML')

# ===========================================
# ОБРАБОТЧИКИ ДЛЯ КНОПОК "О НАС"
# ===========================================
@dp.callback_query(F.data == "about_timer")
async def about_timer_handler(query: CallbackQuery):
    """Информация о таймере"""
    timer_info = (
        "⏱️ <b>Таймер чтения - новая функция версии 3.0!</b>\n\n"
        
        "<b>Как работает:</b>\n"
        "1. Выберите книгу (категорию) для чтения\n"
        "2. Запустите таймер с помощью кнопки '⏱️ Таймер чтения'\n"
        "3. Читайте книгу - время отслеживается в реальном времени\n"
        "4. Делайте заметки во время чтения\n"
        "5. Остановите таймер по окончании сессии\n\n"
        
        "<b>Преимущества:</b>\n"
        "• 📊 Отслеживание времени чтения в статистике\n"
        "• 🎯 Формирование привычки регулярного чтения\n"
        "• 📈 Анализ продуктивности по разным книгам\n"
        "• 🏆 Достижения и мотивация\n"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Попробовать таймер", callback_data="start_timer"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_about")
        ]
    ])
    
    await query.message.edit_text(timer_info, reply_markup=keyboard, parse_mode='HTML')
    await query.answer()

@dp.callback_query(F.data == "about_stats")
async def about_stats_handler(query: CallbackQuery):
    """Информация о статистике"""
    stats_info = (
        "📊 <b>Расширенная статистика чтения</b>\n\n"
        
        "<b>Что отслеживается:</b>\n"
        "• 📝 Количество заметок по категориям\n"
        "• ⏱️ Общее время чтения\n"
        "• 📅 Активность по дням и неделям\n"
        "• 📈 Среднее время за сессию\n"
        "• 🏆 Самые читаемые книги\n"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Посмотреть статистику", callback_data="show_stats_from_about"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_about")
        ]
    ])
    
    await query.message.edit_text(stats_info, reply_markup=keyboard, parse_mode='HTML')
    await query.answer()

@dp.callback_query(F.data == "show_stats_from_about")
async def show_stats_from_about_handler(query: CallbackQuery):
    """Показ статистики из раздела 'О нас'"""
    await show_statistics(query.message)
    await query.answer()

@dp.callback_query(F.data == "updates")
async def updates_handler(query: CallbackQuery):
    """Обновления"""
    updates_text = (
        "🔄 <b>Обновления и новости</b>\n\n"
        
        "<b>Версия 3.0.0 (Текущая) - 'Таймер Чтения'</b>\n"
        "<i>Дата выпуска: 2026</i>\n\n"
        
        "<b>Новые функции:</b>\n"
        "✅ <b>Таймер чтения</b> - отслеживание времени за книгами\n"
        "✅ <b>Статистика времени</b> - аналитика привычек чтения\n"
        "✅ <b>Сессии чтения</b> - сохранение данных о каждой сессии\n"
        "✅ <b>Заметки во время чтения</b> - без прерывания таймера\n"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_about")
        ]
    ])
    
    await query.message.edit_text(updates_text, reply_markup=keyboard, parse_mode='HTML')
    await query.answer()

@dp.callback_query(F.data == "help_info")
async def help_info_handler(query: CallbackQuery):
    """Помощь"""
    help_text = (
        "📚 <b>Помощь и инструкции</b>\n\n"
        
        "<b>Основные команды:</b>\n"
        "/start - Главное меню\n"
        "/timer - Запустить таймер чтения\n"
        "/stop_timer - Остановить текущий таймер\n"
        "/timer_status - Проверить состояние таймера\n"
        "/category - Выбрать категорию\n"
        "/notes - Просмотреть заметки\n"
        "/stats - Статистика чтения\n"
        "/addmedia – добавить медиа\n"
        "/about - Информация о боте\n"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_about")
        ]
    ])
    
    await query.message.edit_text(help_text, reply_markup=keyboard, parse_mode='HTML')
    await query.answer()

@dp.callback_query(F.data == "rate_bot")
async def rate_bot_handler(query: CallbackQuery):
    """Оценка бота"""
    thank_you_text = (
        "⭐ <b>Спасибо за вашу оценку!</b> ⭐\n\n"
        "Ваше мнение очень важно для нас и помогает делать бота лучше!\n"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏱️ Протестировать таймер", callback_data="start_timer"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_about")
        ]
    ])
    
    await query.message.edit_text(thank_you_text, reply_markup=keyboard, parse_mode='HTML')
    await query.answer()

@dp.callback_query(F.data == "back_to_about")
async def back_to_about_handler(query: CallbackQuery):
    """Возврат к меню 'О нас'"""
    await about_us(query.message)
    await query.answer()

# ===========================================
# ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ
# ===========================================
@dp.message(Command("create_tables"))
async def create_tables_cmd(message: Message):
    try:
        from init_db import init_db
        await init_db()
        await message.answer("✅ Таблицы созданы!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ===========================================
# ОСНОВНАЯ ФУНКЦИЯ
# ===========================================
async def cleanup_timers():
    """Очистка всех активных таймеров при завершении"""
    print("🛑 Останавливаю все таймеры...")
    for user_id in list(active_timers.keys()):
        try:
            await stop_and_report(user_id)
        except:
            pass

async def main():
    print("=" * 50)
    print("📚 HSEBookNotes Bot с Таймером Чтения")
    print("=" * 50)
    
    try:
        # Инициализируем базу данных
        from init_db import init_db
        await init_db()
        
        print("✅ База данных готова")
        print("🚀 Запуск бота...")
        
        # Удаляем вебхук если он есть
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Запускаем поллинг
        await dp.start_polling(bot, skip_updates=True)
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Очищаем таймеры при завершении
        await cleanup_timers()

if __name__ == "__main__":
    print("🚀 Запуск бота HSEBookNotes...")
    asyncio.run(main())