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
def create_reading_stats_chart(user_id: int, categories_count: int, notes_count: int, 
                              notes_by_category: dict, notes_by_date: dict):
    """Создать график статистики чтения с поддержкой эмодзи"""
    
    # === ПРИНУДИТЕЛЬНАЯ НАСТРОЙКА ШРИФТОВ ===
    import matplotlib
    matplotlib.rcParams['font.family'] = 'sans-serif'
    matplotlib.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica', 'Liberation Sans']
    matplotlib.rcParams['axes.unicode_minus'] = False
    
    # Создаем фигуру
    fig, axes = plt.subplots(2, 2, figsize=(14, 10), facecolor='white')
    fig.suptitle('📚 Статистика чтения', fontsize=20, fontweight='bold', y=0.98)
    
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD']
    
    # === 1. КРУГОВАЯ ДИАГРАММА ===
    ax1 = axes[0, 0]
    ax1.set_facecolor('white')
    
    if notes_by_category and sum(notes_by_category.values()) > 0:
        category_names = list(notes_by_category.keys())
        category_counts = list(notes_by_category.values())
        
        # Обрезаем длинные названия
        short_names = [name[:15] + '...' if len(name) > 15 else name for name in category_names]
        
        wedges, texts, autotexts = ax1.pie(
            category_counts, 
            labels=short_names, 
            colors=colors[:len(category_names)],
            autopct='%1.1f%%',
            startangle=90,
            wedgeprops={'edgecolor': 'white', 'linewidth': 2}
        )
        
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
        
        ax1.set_title('Распределение заметок по категориям', fontsize=14, pad=20, fontweight='bold')
        ax1.axis('equal')
    else:
        ax1.text(0.5, 0.5, 'Нет данных', ha='center', va='center', fontsize=14, transform=ax1.transAxes)
        ax1.set_title('Распределение заметок по категориям', fontsize=14, pad=20, fontweight='bold')
        ax1.axis('off')
    
    # === 2. СТОЛБЧАТАЯ ДИАГРАММА ===
    ax2 = axes[0, 1]
    ax2.set_facecolor('white')
    
    if notes_by_date and len(notes_by_date) > 0 and sum(notes_by_date.values()) > 0:
        dates = list(notes_by_date.keys())
        counts = list(notes_by_date.values())
        
        bars = ax2.bar(dates, counts, color=colors[0], edgecolor='white', linewidth=2, alpha=0.8)
        
        for bar, count in zip(bars, counts):
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f'{count}', ha='center', va='bottom', fontweight='bold')
        
        ax2.set_title('Активность по дням (30 дней)', fontsize=14, pad=20, fontweight='bold')
        ax2.set_xlabel('Дата', fontsize=11)
        ax2.set_ylabel('Количество заметок', fontsize=11)
        ax2.tick_params(axis='x', rotation=45)
        ax2.grid(True, alpha=0.3, linestyle='--')
    else:
        ax2.text(0.5, 0.5, 'Нет данных за 30 дней', ha='center', va='center', fontsize=14, transform=ax2.transAxes)
        ax2.set_title('Активность по дням (30 дней)', fontsize=14, pad=20, fontweight='bold')
        ax2.axis('off')
    
    # === 3. ОБЩАЯ СТАТИСТИКА ===
    ax3 = axes[1, 0]
    ax3.axis('off')
    ax3.set_facecolor('white')
    
    first_note = 'Н/Д'
    last_note = 'Н/Д'
    most_active = 'Н/Д'
    avg_per_day = 0
    
    if notes_by_date and len(notes_by_date) > 0:
        try:
            dates_list = list(notes_by_date.keys())
            first_note = dates_list[0] if dates_list else 'Н/Д'
            last_note = dates_list[-1] if dates_list else 'Н/Д'
            most_active = max(notes_by_date, key=notes_by_date.get) if notes_by_date else 'Н/Д'
            avg_per_day = notes_count / 30 if notes_count > 0 else 0
        except:
            pass
    
    stats_text = (
        f"📊 ОБЩАЯ СТАТИСТИКА\n"
        f"{'─' * 25}\n\n"
        f"📂 Категорий:        {categories_count}\n"
        f"📝 Всего заметок:    {notes_count}\n"
        f"📅 Первая заметка:   {first_note}\n"
        f"📅 Последняя заметка: {last_note}\n"
        f"🔥 Самый активный:   {most_active}\n"
        f"📈 Среднее в день:   {avg_per_day:.1f}"
    )
    
    ax3.text(0.1, 0.95, stats_text, fontsize=12, verticalalignment='top',
            transform=ax3.transAxes,
            bbox=dict(boxstyle='round,pad=0.7', facecolor='#F8F9FA', 
                     alpha=0.9, edgecolor='#DEE2E6', linewidth=2))
    
    # === 4. ПРОГРЕСС И ДОСТИЖЕНИЯ ===
    ax4 = axes[1, 1]
    ax4.axis('off')
    ax4.set_facecolor('white')
    
    if categories_count > 0:
        # Определение уровня
        if notes_count >= 50:
            level = "🏆 ЗАЯДЛЫЙ ЧИТАТЕЛЬ"
            level_icon = "🏆"
        elif notes_count >= 20:
            level = "👍 АКТИВНЫЙ ЧИТАТЕЛЬ"
            level_icon = "👍"
        elif notes_count >= 10:
            level = "🌱 НАЧИНАЮЩИЙ"
            level_icon = "🌱"
        else:
            level = "🚀 СТАРТ"
            level_icon = "🚀"
        
        progress_text = (
            f"🎯 ПРОГРЕСС И ДОСТИЖЕНИЯ\n"
            f"{'─' * 25}\n\n"
            f"{level_icon} Уровень: {level}\n\n"
            f"📚 Категорий: {categories_count}/10\n"
            f"📝 Заметок:   {notes_count}/100\n\n"
        )
        
        # Мотивационное сообщение
        if notes_count >= 50:
            progress_text += "✨ Потрясающий результат!"
        elif notes_count >= 20:
            progress_text += "💪 Отличный прогресс!"
        elif notes_count >= 10:
            progress_text += "🌟 Так держать!"
        else:
            progress_text += "📖 Продолжайте читать каждый день!"
        
        ax4.text(0.1, 0.95, progress_text, fontsize=12, verticalalignment='top',
                transform=ax4.transAxes,
                bbox=dict(boxstyle='round,pad=0.7', facecolor='#E3F2FD', 
                         alpha=0.9, edgecolor='#90CAF9', linewidth=2))
    else:
        ax4.text(0.1, 0.5, "🎯 Начните создавать категории!\n\n👉 Нажмите '➕ Новая категория'", 
                fontsize=14, verticalalignment='center',
                transform=ax4.transAxes,
                bbox=dict(boxstyle='round,pad=0.7', facecolor='#E3F2FD', 
                         alpha=0.9, edgecolor='#90CAF9', linewidth=2))
    
    plt.tight_layout()
    
    # Сохраняем
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    plt.close(fig)
    
    return buf
# ===========================================
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
# СТАТИСТИКА (ИСПРАВЛЕННАЯ ВЕРСИЯ)
# ===========================================
@dp.message(Command("stats"))
@dp.message(F.text == "📊 Статистика")
async def show_statistics(message: Message):
    """Показать расширенную геймифицированную статистику"""
    user_id = message.from_user.id
    
    loading_msg = await message.answer("📊 Собираю статистику...")
    
    async with AsyncSessionLocal() as session:
        try:
            # === БАЗОВАЯ СТАТИСТИКА ===
            # Категории
            cat_result = await session.execute(
                select(func.count(Category.id)).where(Category.user_id == user_id)
            )
            categories_count = cat_result.scalar() or 0
            
            # Заметки
            notes_result = await session.execute(
                select(func.count(Note.id)).where(Note.user_id == user_id)
            )
            notes_count = notes_result.scalar() or 0
            
            # Сессии чтения
            sessions_result = await session.execute(
                select(ReadingSession).where(ReadingSession.user_id == user_id)
            )
            all_sessions = sessions_result.scalars().all()
            
            # === РАСЧЕТ ВРЕМЕНИ ===
            total_reading_time = 0
            completed_sessions = [s for s in all_sessions if s.duration_seconds]
            total_sessions = len(completed_sessions)
            
            for s in completed_sessions:
                total_reading_time += s.duration_seconds
            
            avg_session_time = total_reading_time / total_sessions if total_sessions > 0 else 0
            
            # === СТАТИСТИКА ПО ДНЯМ (30 ДНЕЙ) ===
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            
            # Заметки по дням
            daily_notes = await session.execute(
                select(func.date(Note.created_at), func.count(Note.id))
                .where(
                    Note.user_id == user_id,
                    Note.created_at >= thirty_days_ago,
                    Note.is_deleted == False
                )
                .group_by(func.date(Note.created_at))
            )
            notes_by_date = {}
            for date_str, count in daily_notes.all():
                if date_str:
                    date_obj = datetime.strptime(str(date_str), '%Y-%m-%d')
                    notes_by_date[date_obj.date()] = count
            
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
                if date_str:
                    date_obj = datetime.strptime(str(date_str), '%Y-%m-%d')
                    time_by_date[date_obj.date()] = seconds
            
            # === ПОСЛЕДНИЕ 7 ДНЕЙ ===
            last_7_days_notes = 0
            last_7_days_time = 0
            for date, count in notes_by_date.items():
                if date >= seven_days_ago.date():
                    last_7_days_notes += count
            for date, seconds in time_by_date.items():
                if date >= seven_days_ago.date():
                    last_7_days_time += seconds
            
            # === СТАТИСТИКА ПО КАТЕГОРИЯМ ===
            cat_stats = await session.execute(
                select(Category.name, func.count(Note.id))
                .join(Note, Category.id == Note.category_id)
                .where(Category.user_id == user_id)
                .group_by(Category.id, Category.name)
                .order_by(func.count(Note.id).desc())
            )
            notes_by_category = dict(cat_stats.all())
            
            # Время по категориям
            time_by_category_result = await session.execute(
                select(Category.name, func.sum(ReadingSession.duration_seconds))
                .join(ReadingSession, Category.id == ReadingSession.category_id)
                .where(
                    Category.user_id == user_id,
                    ReadingSession.is_completed == True
                )
                .group_by(Category.id, Category.name)
                .order_by(func.sum(ReadingSession.duration_seconds).desc())
            )
            time_by_category = dict(time_by_category_result.all())
            
            # === СТАТИСТИКА ПО МЕДИА ===
            media_stats = await session.execute(
                select(Note.media_type, func.count(Note.id))
                .where(Note.user_id == user_id, Note.is_deleted == False)
                .group_by(Note.media_type)
            )
            media_counts = dict(media_stats.all())
            
            text_count = media_counts.get(MediaType.TEXT, 0)
            photo_count = media_counts.get(MediaType.PHOTO, 0)
            video_count = media_counts.get(MediaType.VIDEO, 0)
            voice_count = media_counts.get(MediaType.VOICE, 0)
            doc_count = media_counts.get(MediaType.DOCUMENT, 0)
            
            # === СТАТИСТИКА ПО ВРЕМЕНИ СУТОК ===
            morning = 0  # 6-12
            afternoon = 0  # 12-18
            evening = 0  # 18-24
            night = 0  # 0-6
            
            for session_obj in completed_sessions:
                hour = session_obj.start_time.hour
                if 6 <= hour < 12:
                    morning += session_obj.duration_seconds
                elif 12 <= hour < 18:
                    afternoon += session_obj.duration_seconds
                elif 18 <= hour < 24:
                    evening += session_obj.duration_seconds
                else:
                    night += session_obj.duration_seconds
            
                # === СТРЕЙК-СЕРИЯ (ОГОНЕК ДЛЯ ТЕСТОВОГО ПЕРИОДА) ===
                today = datetime.utcnow().date()
                streak = 0
                check_date = today

                # Считаем дни подряд с сегодняшнего дня вниз
                while True:
                    has_activity = await session.execute(
                        select(Note.id)
                        .where(
                            Note.user_id == user_id,
                            func.date(Note.created_at) == check_date.strftime('%Y-%m-%d'),
                            Note.is_deleted == False
                        )
                        .limit(1)
                    )
    
                    if has_activity.first():
                        streak += 1
                        check_date -= timedelta(days=1)
                    else:
                        break

                # Максимальный стрейк за всё время (пока просто равен текущему)
                max_streak = streak
            # === ЕЖЕНЕДЕЛЬНАЯ СТАТИСТИКА ===
            weeks_ago = datetime.utcnow() - timedelta(days=90)
            weekly_stats = await session.execute(
                select(
                    func.strftime('%Y-%W', Note.created_at).label('week'),
                    func.count(Note.id).label('notes'),
                    func.count(func.distinct(func.date(Note.created_at))).label('days')
                )
                .where(
                    Note.user_id == user_id,
                    Note.created_at >= weeks_ago,
                    Note.is_deleted == False
                )
                .group_by('week')
                .order_by('week')
            )
            weekly_data = weekly_stats.all()
            
            # === СРЕДНИЕ ПОКАЗАТЕЛИ ===
            active_days = len(notes_by_date)
            avg_notes_per_day = notes_count / 30 if notes_count > 0 else 0
            avg_time_per_day = total_reading_time / 30 if total_reading_time > 0 else 0
            avg_time_per_active_day = total_reading_time / active_days if active_days > 0 else 0
            
            # === ПРОГНОЗ НА 30 ДНЕЙ ===
            if avg_notes_per_day > 0:
                projected_notes = int(notes_count + avg_notes_per_day * 30)
            else:
                projected_notes = notes_count
            
            if avg_time_per_day > 0:
                projected_time = int(total_reading_time + avg_time_per_day * 30)
            else:
                projected_time = total_reading_time
            
        except Exception as e:
            await loading_msg.edit_text(f"❌ Ошибка: {e}")
            return
    
    # === СОЗДАНИЕ ГРАФИКОВ ===
    try:
        fig = plt.figure(figsize=(16, 12), facecolor='white')
        fig.suptitle('📊 Статистика чтения', fontsize=22, fontweight='bold', y=0.98)
        
        gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
        
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD', '#FF9F1C', '#2EC4B6']
        
        # === ГРАФИК 1: КРУГОВАЯ - КАТЕГОРИИ ===
        ax1 = fig.add_subplot(gs[0, 0])
        ax1.set_facecolor('white')
        
        if notes_by_category and sum(notes_by_category.values()) > 0:
            names = list(notes_by_category.keys())
            counts = list(notes_by_category.values())
            
            short_names = [n[:12] + '...' if len(n) > 12 else n for n in names]
            
            wedges, texts, autotexts = ax1.pie(
                counts, 
                labels=short_names,
                colors=colors,
                autopct='%1.0f%%',
                startangle=90,
                wedgeprops={'edgecolor': 'white', 'linewidth': 2}
            )
            
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')
            
            ax1.set_title('Заметки по категориям', fontsize=14, pad=15, fontweight='bold')
            ax1.axis('equal')
        
        # === ГРАФИК 2: СТОЛБЦЫ - АКТИВНОСТЬ ===
        ax2 = fig.add_subplot(gs[0, 1])
        ax2.set_facecolor('white')
        
        if notes_by_date:
            dates = sorted(notes_by_date.keys())[-10:]  # последние 10 дней
            date_labels = [d.strftime('%d.%m') for d in dates]
            note_counts = [notes_by_date.get(d, 0) for d in dates]
            time_mins = [time_by_date.get(d, 0) / 60 for d in dates]
            
            x = range(len(dates))
            width = 0.35
            
            bars1 = ax2.bar([i - width/2 for i in x], note_counts, width, 
                           label='Заметки', color=colors[0], edgecolor='white')
            bars2 = ax2.bar([i + width/2 for i in x], time_mins, width,
                           label='Минуты', color=colors[1], edgecolor='white')
            
            ax2.set_title('Активность (10 дней)', fontsize=14, pad=15, fontweight='bold')
            ax2.set_xticks(x)
            ax2.set_xticklabels(date_labels, rotation=45, ha='right')
            ax2.legend(fontsize=10)
            ax2.grid(True, alpha=0.3, axis='y', linestyle='--')
        
        # === ГРАФИК 3: ВРЕМЯ ПО КАТЕГОРИЯМ ===
        ax3 = fig.add_subplot(gs[0, 2])
        ax3.set_facecolor('white')
        
        if time_by_category and sum(time_by_category.values()) > 0:
            cat_names = list(time_by_category.keys())[:5]
            cat_times = [t / 3600 for t in list(time_by_category.values())[:5]]  # в часах
            
            y_pos = range(len(cat_names))
            bars = ax3.barh(y_pos, cat_times, color=colors[2], edgecolor='white', linewidth=2)
            
            ax3.set_yticks(y_pos)
            ax3.set_yticklabels([n[:15] + '...' if len(n) > 15 else n for n in cat_names])
            ax3.set_xlabel('Часы')
            ax3.set_title('Время по категориям', fontsize=14, pad=15, fontweight='bold')
            ax3.grid(True, alpha=0.3, axis='x', linestyle='--')
            
            for bar, hours in zip(bars, cat_times):
                ax3.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
                        f'{hours:.1f}ч', va='center', fontweight='bold')
        
        # === ГРАФИК 4: ТИПЫ МЕДИА ===
        ax4 = fig.add_subplot(gs[1, 0])
        ax4.set_facecolor('white')
        
        media_labels = []
        media_values = []
        media_colors = []
        
        if text_count > 0:
            media_labels.append('Текст')
            media_values.append(text_count)
            media_colors.append(colors[3])
        if photo_count > 0:
            media_labels.append('Фото')
            media_values.append(photo_count)
            media_colors.append(colors[4])
        if video_count > 0:
            media_labels.append('Видео')
            media_values.append(video_count)
            media_colors.append(colors[5])
        if voice_count > 0:
            media_labels.append('Голос')
            media_values.append(voice_count)
            media_colors.append(colors[6])
        if doc_count > 0:
            media_labels.append('Документы')
            media_values.append(doc_count)
            media_colors.append(colors[7])
        
        if media_values:
            wedges, texts, autotexts = ax4.pie(
                media_values, 
                labels=media_labels,
                colors=media_colors,
                autopct='%1.0f%%',
                startangle=90,
                wedgeprops={'edgecolor': 'white', 'linewidth': 2}
            )
            
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')
            
            ax4.set_title('Типы заметок', fontsize=14, pad=15, fontweight='bold')
            ax4.axis('equal')
        
        # === ГРАФИК 5: ВРЕМЯ СУТОК ===
        ax5 = fig.add_subplot(gs[1, 1])
        ax5.set_facecolor('white')
        
        if total_reading_time > 0:
            time_labels = ['Утро', 'День', 'Вечер', 'Ночь']
            time_values = [morning/3600, afternoon/3600, evening/3600, night/3600]
            time_colors = ['#FFD93D', '#FF9F1C', '#2EC4B6', '#5E60CE']
            
            bars = ax5.bar(time_labels, time_values, color=time_colors, edgecolor='white', linewidth=2)
            
            ax5.set_ylabel('Часы')
            ax5.set_title('Время чтения', fontsize=14, pad=15, fontweight='bold')
            ax5.grid(True, alpha=0.3, axis='y', linestyle='--')
            
            for bar, hours in zip(bars, time_values):
                if hours > 0:
                    ax5.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                            f'{hours:.1f}ч', ha='center', va='bottom', fontweight='bold')
        
        # === ГРАФИК 6: НЕДЕЛЬНАЯ АКТИВНОСТЬ ===
        ax6 = fig.add_subplot(gs[1, 2])
        ax6.set_facecolor('white')
        
        if weekly_data:
            weeks = [f'Нед {i+1}' for i in range(min(len(weekly_data), 8))]
            week_notes = [w[1] for w in weekly_data[-8:]]
            week_days = [w[2] for w in weekly_data[-8:]]
            
            x = range(len(weeks))
            width = 0.35
            
            bars1 = ax6.bar([i - width/2 for i in x], week_notes, width,
                           label='Заметки', color=colors[5], edgecolor='white')
            bars2 = ax6.bar([i + width/2 for i in x], week_days, width,
                           label='Дни', color=colors[6], edgecolor='white')
            
            ax6.set_title('Активность по неделям', fontsize=14, pad=15, fontweight='bold')
            ax6.set_xticks(x)
            ax6.set_xticklabels(weeks, rotation=45, ha='right')
            ax6.legend(fontsize=10)
            ax6.grid(True, alpha=0.3, axis='y', linestyle='--')
        
        # === ГРАФИК 7: ПРОГРЕСС УРОВНЯ ===
        ax7 = fig.add_subplot(gs[2, :])
        ax7.set_facecolor('white')
        
        # Уровни от 1 до 50
        current_level = min(49, notes_count // 5 + 1)
        current_exp = notes_count % 5
        next_level_exp = 5
        
        # Визуализация прогресса
        level_colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#FF9F1C']
        
        # Полоса прогресса
        progress_bars = []
        for i in range(10):
            if i < current_exp:
                progress_bars.append(1)
            else:
                progress_bars.append(0)
        
        bar_x = range(10)
        bar_colors = [colors[0] if x == 1 else '#E0E0E0' for x in progress_bars]
        
        bars = ax7.bar(bar_x, [1]*10, color=bar_colors, edgecolor='white', linewidth=2)
        
        ax7.set_xlim(-0.5, 9.5)
        ax7.set_ylim(0, 1.5)
        ax7.set_xticks([])
        ax7.set_yticks([])
        ax7.spines['top'].set_visible(False)
        ax7.spines['right'].set_visible(False)
        ax7.spines['bottom'].set_visible(False)
        ax7.spines['left'].set_visible(False)
        
        ax7.text(5, 0.5, f'Уровень {current_level} • {current_exp}/5 XP',
                ha='center', va='center', fontsize=14, fontweight='bold')
        
        ax7.set_title('Прогресс уровня', fontsize=14, pad=20, fontweight='bold')
        
        plt.tight_layout()
        
        # Сохраняем график
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor='white')
        buf.seek(0)
        plt.close(fig)
        
        await loading_msg.delete()
        await message.answer_photo(
            BufferedInputFile(buf.getvalue(), filename="stats.png"),
            caption="📈 Продвинутая статистика чтения"
        )
        
    except Exception as e:
        print(f"Ошибка графиков: {e}")
        await loading_msg.edit_text("📊 Загружаю текстовую статистику...")
    
    # === ТЕКСТОВАЯ СТАТИСТИКА С ДОСТИЖЕНИЯМИ ===
    
    # === СИСТЕМА УРОВНЕЙ (50 УРОВНЕЙ) ===
    level = min(50, notes_count // 5 + 1)
    exp_current = notes_count % 5
    exp_next = 5
    exp_total = notes_count
    exp_for_next = level * 5
    
    # Названия уровней
    level_titles = {
        range(1, 6): "🌱 НОВИЧОК",
        range(6, 11): "📖 ЧИТАТЕЛЬ",
        range(11, 16): "📚 КНИГОЛЮБ",
        range(16, 21): "🔍 ИССЛЕДОВАТЕЛЬ",
        range(21, 26): "🧠 МЫСЛИТЕЛЬ",
        range(26, 31): "⚡ ЭРУДИТ",
        range(31, 36): "💫 МАСТЕР",
        range(36, 41): "🏆 ПРОФЕССОР",
        range(41, 46): "👑 МАГИСТР",
        range(46, 51): "✨ ЛЕГЕНДА"
    }
    
    level_title = "🌱 НОВИЧОК"
    for level_range, title in level_titles.items():
        if level in level_range:
            level_title = title
            break
    
    # === ОГОНЕК (DUOLINGO СТИЛЬ) ===
    if streak == 0:
        fire_icon = "🕯️"
        fire_text = "Начните серию сегодня! 🔥"
        fire_color = "⚪"
    elif streak == 1:
        fire_icon = "🔥"
        fire_text = "1 день! Продолжайте! 🔥"
    elif streak == 2:
        fire_icon = "🔥🔥"
        fire_text = "2 дня подряд! 👍"
    elif streak == 3:
        fire_icon = "🔥🔥🔥"
        fire_text = "3 дня! Маленькая победа! 🎯"
    elif streak == 4:
        fire_icon = "🔥🔥🔥🔥"
        fire_text = "4 дня! Вы в ритме! ⚡"
    elif streak == 5:
        fire_icon = "🔥🔥🔥🔥🔥"
        fire_text = "5 дней! Половина недели! 🌟"
    elif streak == 6:
        fire_icon = "🔥🔥🔥🔥🔥🔥"
        fire_text = "6 дней! Завтра будет НЕДЕЛЯ! 📅"
    elif streak == 7:
        fire_icon = "🔥🔥🔥🔥🔥🔥🔥"
        fire_text = "🌟 НЕДЕЛЯ! Поздравляем! 🏆"
    elif streak == 8:
        fire_icon = "🔥🔥🔥🔥🔥🔥🔥🔥"
        fire_text = "8 дней! Неделя +1! 💪"
    elif streak == 9:
        fire_icon = "🔥🔥🔥🔥🔥🔥🔥🔥🔥"
        fire_text = "9 дней! Скоро 2 недели! ⏳"
    elif streak == 10:
        fire_icon = "🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥"
        fire_text = "10 ДНЕЙ! Двойная цифра! 🎉"
    elif streak == 11:
        fire_icon = "🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥"
        fire_text = "11 дней! Вы неутомимы! ✨"
    elif streak == 12:
        fire_icon = "🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥"
        fire_text = "12 дней! Ещё 2 дня до рекорда! 🚀"
    elif streak == 13:
        fire_icon = "🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥"
        fire_text = "13 дней! Завтра 2 НЕДЕЛИ! ⚡"
    elif streak == 14:
        fire_icon = "⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡"
        fire_text = "🎯 2 НЕДЕЛИ! Фантастика! 👑"
    else:
    # На случай если тесты затянутся
    weeks = streak // 7
    days = streak % 7
    if weeks == 2:
        fire_icon = "🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆"
        fire_text = f"{streak} дней! 2 полные недели! 🎯"
    elif weeks == 3:
        fire_icon = "👑👑👑👑👑👑👑👑👑👑👑👑👑👑"
        fire_text = f"{streak} дней! 3 недели! Вы легенда! ✨"
    else:
        fire_icon = "🔥" * 7 + f" +{streak-7}"
        fire_text = f"{streak} дней! Отличный результат! 🌟"    
    # === ДОСТИЖЕНИЯ (30+ ШТУК) ===
    achievements = []
    
    # 1-5. КАТЕГОРИИ
    if categories_count >= 1:
        achievements.append(("📁 Первая категория", categories_count >= 1))
    if categories_count >= 3:
        achievements.append(("📚 Три книги", categories_count >= 3))
    if categories_count >= 5:
        achievements.append(("🏛️ Библиотека", categories_count >= 5))
    if categories_count >= 10:
        achievements.append(("🎓 Книжный клуб", categories_count >= 10))
    if categories_count >= 20:
        achievements.append(("🏰 Архив знаний", categories_count >= 20))
    
    # 6-15. ЗАМЕТКИ
    if notes_count >= 1:
        achievements.append(("📝 Первая заметка", notes_count >= 1))
    if notes_count >= 10:
        achievements.append(("📄 10 заметок", notes_count >= 10))
    if notes_count >= 25:
        achievements.append(("📑 25 заметок", notes_count >= 25))
    if notes_count >= 50:
        achievements.append(("📚 50 заметок", notes_count >= 50))
    if notes_count >= 100:
        achievements.append(("📖 100 заметок", notes_count >= 100))
    if notes_count >= 250:
        achievements.append(("📕 250 заметок", notes_count >= 250))
    if notes_count >= 500:
        achievements.append(("📘 500 заметок", notes_count >= 500))
    if notes_count >= 1000:
        achievements.append(("📗 1000 заметок", notes_count >= 1000))
    if notes_count >= 2500:
        achievements.append(("📙 Энциклопедия", notes_count >= 2500))
    if notes_count >= 5000:
        achievements.append(("🏆 Библиотекарь", notes_count >= 5000))
    
    # 16-20. ВРЕМЯ
    hours_reading = total_reading_time / 3600
    if hours_reading >= 1:
        achievements.append(("⏱️ 1 час", hours_reading >= 1))
    if hours_reading >= 5:
        achievements.append(("🕐 5 часов", hours_reading >= 5))
    if hours_reading >= 10:
        achievements.append(("⌛ 10 часов", hours_reading >= 10))
    if hours_reading >= 50:
        achievements.append(("⏳ 50 часов", hours_reading >= 50))
    if hours_reading >= 100:
        achievements.append(("⌚ 100 часов", hours_reading >= 100))
    
    # 21-25. СТРЕЙК
    if streak >= 3:
        achievements.append(("🔥 3 дня", streak >= 3))
    if streak >= 7:
        achievements.append(("🔥🔥 Неделя", streak >= 7))
    if streak >= 14:
        achievements.append(("⚡ 2 недели", streak >= 14))
    if streak >= 30:
        achievements.append(("🌋 Месяц", streak >= 30))
    if streak >= 100:
        achievements.append(("🌟 100 дней", streak >= 100))
    
    # 26-30. МЕДИА
    if photo_count >= 1:
        achievements.append(("📸 Первое фото", photo_count >= 1))
    if photo_count >= 10:
        achievements.append(("📷 Фотоальбом", photo_count >= 10))
    if voice_count >= 1:
        achievements.append(("🎤 Первый голос", voice_count >= 1))
    if video_count >= 1:
        achievements.append(("🎥 Первое видео", video_count >= 1))
    if doc_count >= 1:
        achievements.append(("📎 Первый документ", doc_count >= 1))
    
    # 31-35. СПЕЦИАЛЬНЫЕ
    if len(notes_by_category) >= 2 and max(notes_by_category.values()) >= 10:
        achievements.append(("🎯 Фокус", True))
    if total_sessions >= 10:
        achievements.append(("🎯 10 сессий", total_sessions >= 10))
    if avg_session_time >= 1800:  # 30 минут
        achievements.append(("🧘 Глубокое чтение", avg_session_time >= 1800))
    if morning > afternoon and morning > evening and morning > night:
        achievements.append(("🌅 Жаворонок", True))
    if night > 7200:  # 2 часа ночью
        achievements.append(("🦉 Сова", night >= 7200))
    
    # Подсчет выполненных достижений
    earned_achievements = [a[0] for a in achievements if a[1]]
    achievement_count = len(earned_achievements)
    total_achievements = len([a for a in achievements if a[1] is not False])  # Примерно
    
    # === ЕЖЕДНЕВНЫЕ ЦЕЛИ ===
    daily_goals = []
    
    # Цель 1: Заметки сегодня
    today_notes = notes_by_date.get(today, 0)
    daily_goals.append(("📝 Заметки сегодня", today_notes, 3))
    
    # Цель 2: Время сегодня
    today_time = time_by_date.get(today, 0) / 60  # в минутах
    daily_goals.append(("⏱️ Минуты сегодня", int(today_time), 30))
    
    # Цель 3: Серия
    daily_goals.append(("🔥 Дней подряд", streak, 7))
    
    # Цель 4: Недельная цель
    weekly_goal = last_7_days_notes
    daily_goals.append(("📊 Заметок за 7 дней", weekly_goal, 10))
    
    # === ФОРМИРУЕМ ТЕКСТ ===
    stats_text = (
        f"📊 <b>СТАТИСТИКА ЧТЕНИЯ</b>\n"
        f"{'═' * 35}\n\n"
        
        f"<b>{level_title}</b> • Уровень {level}\n"
        f"{'█' * exp_current}{'░' * (exp_next - exp_current)} {exp_current}/{exp_next} XP\n"
        f"✨ Всего опыта: {exp_total} XP\n\n"
        
        f"{fire} <b>СЕРИЯ:</b> {fire_text}\n"
        f"🏆 <b>Рекорд:</b> {max_streak} дней\n"
        f"🎯 <b>Достижений:</b> {achievement_count}+ / 35\n\n"
    )
    
    # Ежедневные цели
    stats_text += f"📋 <b>ЕЖЕДНЕВНЫЕ ЦЕЛИ:</b>\n"
    for goal_name, current, target in daily_goals:
        if current >= target:
            stats_text += f"  ✅ {goal_name}: {current}/{target}\n"
        else:
            progress = int((current / target) * 10)
            bar = '█' * progress + '░' * (10 - progress)
            stats_text += f"  ⏳ {goal_name}: {bar} {current}/{target}\n"
    stats_text += "\n"
    
    # Основная статистика
    stats_text += (
        f"📂 <b>КАТЕГОРИИ:</b> {categories_count}\n"
        f"📝 <b>ЗАМЕТКИ:</b> {notes_count}\n"
        f"⏱️ <b>СЕССИИ:</b> {total_sessions}\n"
        f"🕐 <b>ВРЕМЯ:</b> {format_time_short(int(total_reading_time))} ({hours_reading:.1f}ч)\n"
        f"📊 <b>АКТИВНЫХ ДНЕЙ:</b> {active_days}/30\n\n"
    )
    
    # Средние показатели
    stats_text += (
        f"📈 <b>СРЕДНИЕ ПОКАЗАТЕЛИ:</b>\n"
        f"  • Заметок в день: {avg_notes_per_day:.1f}\n"
        f"  • Времени в день: {format_time_short(int(avg_time_per_day))}\n"
        f"  • В активный день: {format_time_short(int(avg_time_per_active_day))}\n"
        f"  • За сессию: {format_time_short(int(avg_session_time))}\n"
        f"  • Эффективность: {notes_count/max(1, total_reading_time/3600):.1f} зам/час\n\n"
    )
    
    # Прогноз
    stats_text += (
        f"🔮 <b>ПРОГНОЗ НА 30 ДНЕЙ:</b>\n"
        f"  • Заметки: {projected_notes} (+{projected_notes - notes_count})\n"
        f"  • Время: {format_time_short(projected_time)} (+{format_time_short(projected_time - total_reading_time)})\n"
        f"  • Уровень: {min(50, projected_notes // 5 + 1)} ({projected_notes // 5 + 1 - level} ур.)\n\n"
    )
    
    # Топ категории
    if notes_by_category:
        stats_text += f"📚 <b>ТОП КАТЕГОРИЙ:</b>\n"
        for i, (cat, cnt) in enumerate(list(notes_by_category.items())[:3], 1):
            percent = (cnt / notes_count * 100) if notes_count > 0 else 0
            stats_text += f"  {i}. <b>{cat[:20]}</b>: {cnt} ({percent:.0f}%)\n"
        stats_text += "\n"
    
    # Достижения
    if earned_achievements:
        stats_text += f"🏆 <b>ПОСЛЕДНИЕ ДОСТИЖЕНИЯ:</b>\n"
        for ach in earned_achievements[-5:]:
            stats_text += f"  {ach}\n"
        stats_text += "\n"
    
    # Следующие достижения
    next_achievements = []
    if notes_count < 10:
        next_achievements.append(f"📄 10 заметок ({notes_count}/10)")
    elif notes_count < 25:
        next_achievements.append(f"📑 25 заметок ({notes_count}/25)")
    elif notes_count < 50:
        next_achievements.append(f"📚 50 заметок ({notes_count}/50)")
    elif notes_count < 100:
        next_achievements.append(f"📖 100 заметок ({notes_count}/100)")
    
    if hours_reading < 5:
        next_achievements.append(f"🕐 5 часов ({hours_reading:.1f}/5)")
    elif hours_reading < 10:
        next_achievements.append(f"⌛ 10 часов ({hours_reading:.1f}/10)")
    
    if streak < 7:
        next_achievements.append(f"🔥 Неделя ({streak}/7)")
    
    if next_achievements:
        stats_text += f"🎯 <b>СЛЕДУЮЩИЕ ДОСТИЖЕНИЯ:</b>\n"
        for ach in next_achievements[:3]:
            stats_text += f"  {ach}\n"
        stats_text += "\n"
    
    # Совет дня (персонализированный)
    if streak == 0:
        tip = "🔥 Начните серию сегодня! Сделайте хотя бы 1 заметку"
    elif streak == 1:
        tip = "🔥 Уже 1 день! Завтра сделайте ещё заметку — будет серия!"
    elif streak == 6:
        tip = "🔥 Ещё 1 день до недели! Вы справитесь!"
    elif streak == 13:
        tip = "⚡ Завтра будет 2 недели! Фантастика!"
    elif streak == 29:
        tip = "🌋 Завтра будет МЕСЯЦ чтения! Вы легенда!"
    elif notes_count < 10:
        tip = "📝 Осталось {}/10 до достижения '10 заметок'".format(10 - notes_count)
    elif hours_reading < 5:
        tip = "⏱️ Ещё {:.1f} часов до 5 часов чтения".format(5 - hours_reading)
    elif level < 10:
        tip = "📚 До уровня ЧИТАТЕЛЬ: {} XP".format(level * 5 - exp_total)
    elif not media_counts.get(MediaType.PHOTO, 0):
        tip = "📸 Попробуйте добавить фото к заметкам!"
    elif not media_counts.get(MediaType.VOICE, 0):
        tip = "🎤 Запишите голосовую заметку — это удобно!"
    else:
        tips = [
            "📚 Читайте каждый день хотя бы 20 минут",
            "🎯 Поставьте цель на неделю: 10 заметок",
            "⏱️ Используйте таймер чтения для статистики",
            "📸 Фотографируйте интересные страницы",
            "💭 Делайте заметки сразу после чтения",
            "🔥 {streak} дней подряд — отличный результат!",
            "📈 Сравните свою активность с прошлой неделей",
            "🏆 Следующая цель: 100 заметок"
        ]
        tip = random.choice(tips)
    
    tip = tip.replace("{streak}", str(streak))
    stats_text += f"💡 <b>СОВЕТ ДНЯ:</b>\n{tip}"
    
    await message.answer(stats_text, parse_mode='HTML')# ===========================================
# ТЕКСТОВЫЕ СООБЩЕНИЯ
# ===========================================
@dp.message(F.text)
async def save_note(message: Message, state: FSMContext):
    """Обработка текстовых сообщений для сохранения заметок"""
    text = message.text
    
    # Проверяем, является ли текст callback-данными
    callback_prefixes = [
        "cat_", "showcat_", "edit_", "delete_", "renamecat_", 
        "deletecat_", "view_", "add_media_", "media_cat_", "timer_cat_"
    ]
    
    if any(text.startswith(prefix) for prefix in callback_prefixes):
        return
    
    if text.startswith('/'):
        return
    
    # Обработка кнопок меню
    if text == "📚 Категории":
        await choose_category(message, state)
        return
    
    if text == "➕ Новая категория":
        await state.set_state(CategoryState.waiting_for_category_name)
        await message.answer("Введите название новой категории (обычно название книги):")
        return
    
    if text == "📸 Медиа":
        await start_media_note(message, state)
        return
    
    if text == "📝 Заметки":
        await cmd_notes(message)
        return
    
    if text == "📊 Статистика":
        await show_statistics(message)
        return
    
    if text == "ℹ️ О нас":
        await about_us(message)
        return
    
    if text == "⏱️ Таймер чтения":
        await start_timer_command(message, state)
        return
    
    # Проверяем, не находимся ли мы в состоянии FSM
    current_state = await state.get_state()
    if current_state and current_state not in [
        AddMediaNoteState.waiting_for_media.state,
        TimerState.timer_running.state
    ]:
        return
    
    # Если пользователь в режиме таймера и пишет заметку
    user_id = message.from_user.id
    if user_id in active_timers:
        timer_data = active_timers[user_id]
        category_id = timer_data.get("category_id")
        
        if category_id:
            # Сохраняем заметку в категорию таймера
            session_id = timer_data.get("session_id")
            await create_text_note(user_id, category_id, text, session_id)
            
            # Обновляем счетчики в таймере
            timer_data["notes_count"] = timer_data.get("notes_count", 0) + 1
            
            await message.answer(
                f"✅ <b>Заметка сохранена во время чтения!</b>\n\n"
                f"📖 Книга: <b>{timer_data.get('category_name', 'Неизвестно')}</b>\n"
                f"⏱️ Таймер: <b>Продолжает работать</b>\n\n"
                f"<blockquote>{text[:100]}...</blockquote>",
                parse_mode='HTML'
            )
            return
    
    # Стандартная логика сохранения заметок
    data = await state.get_data()
    category_id = data.get("current_category")
    
    if not category_id:
        await message.answer(
            "❌ Сначала выбери категорию!\n\n"
            "Нажми «📚 Категории» или используй /category"
        )
        return
    
    await create_text_note(user_id, category_id, text)
    await message.answer(
        "✅ <b>Текстовая заметка сохранена!</b>\n\n"
        f"<blockquote>{text[:100]}...</blockquote>",
        parse_mode='HTML'
    )

# ===========================================
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