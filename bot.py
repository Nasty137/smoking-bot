import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
import aiosqlite

# --- Конфигурация ---
BOT_TOKEN = "8713595114:AAHX5n1B-HAZFwg3lCkf-aQQDsU0WLpUmq4"
DB_NAME = "smoking_bot.db"

# --- Логирование ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Клавиатура ---
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚬 Выкурила сигарету")],
            [KeyboardButton(text="📊 Моя статистика")]
        ],
        resize_keyboard=True
    )

# --- Машина состояний ---
class SmokingStates(StatesGroup):
    waiting_for_first_cigarette = State()
    waiting_for_bed_time = State()
    waiting_for_planned_count = State()

# --- Работа с базой данных ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
                user_id INTEGER PRIMARY KEY,
                first_cigarette_time TEXT,
                bed_time TEXT,
                planned_count INTEGER,
                smoked_count INTEGER,
                last_update_time TEXT
            )
        """)
        await db.commit()

async def get_user_data(user_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT first_cigarette_time, bed_time, planned_count, smoked_count, last_update_time FROM user_data WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "first_cigarette_time": datetime.fromisoformat(row[0]),
                    "bed_time": datetime.fromisoformat(row[1]),
                    "planned_count": row[2],
                    "smoked_count": row[3],
                    "last_update_time": datetime.fromisoformat(row[4]) if row[4] else None
                }
            return None

async def save_user_data(user_id: int, data: Dict):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR REPLACE INTO user_data (user_id, first_cigarette_time, bed_time, planned_count, smoked_count, last_update_time)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            data["first_cigarette_time"].isoformat(),
            data["bed_time"].isoformat(),
            data["planned_count"],
            data["smoked_count"],
            data["last_update_time"].isoformat() if data["last_update_time"] else None
        ))
        await db.commit()

# --- Хендлеры команд ---
async def start_command(message: Message, state: FSMContext):
    await message.answer(
        "Привет! Я бот, который поможет тебе контролировать курение. 🚭\n"
        "Давай настроим твой план на сегодня.\n\n"
        "Во сколько ты выкурила ПЕРВУЮ сигарету сегодня? (Напиши в формате ЧЧ:ММ, например, 08:30)"
    )
    await state.set_state(SmokingStates.waiting_for_first_cigarette)

async def process_first_cigarette(message: Message, state: FSMContext):
    try:
        first_time = datetime.strptime(message.text, "%H:%M").time()
        now = datetime.now()
        first_datetime = datetime.combine(now.date(), first_time)
        await state.update_data(first_cigarette_time=first_datetime)
        await message.answer(
            "Отлично! А во сколько ты планируешь лечь спать? (Напиши в формате ЧЧ:ММ, например, 23:00)"
        )
        await state.set_state(SmokingStates.waiting_for_bed_time)
    except ValueError:
        await message.answer("Пожалуйста, используй формат ЧЧ:ММ. Например, 08:30.")

async def process_bed_time(message: Message, state: FSMContext):
    try:
        bed_time_str = message.text
        bed_time = datetime.strptime(bed_time_str, "%H:%M").time()
        now = datetime.now()
        
        user_data = await state.get_data()
        first_time = user_data.get("first_cigarette_time")
        
        if first_time:
            first_time_of_day = first_time.time()
            if bed_time < first_time_of_day:
                bed_datetime = datetime.combine(now.date() + timedelta(days=1), bed_time)
            else:
                bed_datetime = datetime.combine(now.date(), bed_time)
        else:
            bed_datetime = datetime.combine(now.date(), bed_time)
        
        await state.update_data(bed_time=bed_datetime)
        await message.answer("Сколько сигарет ты планируешь выкурить за сегодня? (Введи число)")
        await state.set_state(SmokingStates.waiting_for_planned_count)
    except ValueError:
        await message.answer("Пожалуйста, используй формат ЧЧ:ММ. Например, 23:00.")

async def process_planned_count(message: Message, state: FSMContext):
    try:
        planned_count = int(message.text)
        if planned_count <= 0:
            raise ValueError
        
        user_data = await state.get_data()
        first_time = user_data["first_cigarette_time"]
        bed_time = user_data["bed_time"]
        
        data_to_save = {
            "first_cigarette_time": first_time,
            "bed_time": bed_time,
            "planned_count": planned_count,
            "smoked_count": 1,
            "last_update_time": first_time
        }
        await save_user_data(message.from_user.id, data_to_save)
        await send_schedule(message, data_to_save, first_time)
        await state.clear()
        await message.answer(
            "Настройка завершена! Первая сигарета уже учтена ✅\n"
            "Не забывай отмечать каждую следующую сигарету кнопкой ниже 👇",
            reply_markup=get_main_keyboard()
        )
    except ValueError:
        await message.answer("Пожалуйста, введи целое положительное число.")

def adjust_bed_time_for_comparison(bed_time: datetime, now: datetime, first_time: datetime) -> datetime:
    """Корректирует bed_time для корректного сравнения с now"""
    if bed_time.time() < first_time.time():
        bed_time_today = datetime.combine(now.date(), bed_time.time())
        if now > bed_time_today:
            return datetime.combine(now.date() + timedelta(days=1), bed_time.time())
        else:
            return bed_time_today
    return bed_time

async def send_schedule(message: Message, user_data: Dict, current_time: datetime):
    bed_time = user_data["bed_time"]
    planned_count = user_data["planned_count"]
    smoked_count = user_data["smoked_count"]
    
    remaining_count = planned_count - smoked_count
    if remaining_count <= 0:
        await message.answer("Поздравляю! Ты выполнила дневной план! 🎉")
        return
    
    # Для расчётов используем исходное bed_time
    if smoked_count == 0:
        time_diff = bed_time - current_time
    else:
        last_update = user_data["last_update_time"]
        if last_update:
            time_diff = bed_time - last_update
        else:
            time_diff = bed_time - current_time
    
    if time_diff.total_seconds() <= 0:
        await message.answer("Время сна уже прошло. Пожалуйста, настрой план заново командой /start.")
        return
    
    interval = time_diff / remaining_count
    next_time = (current_time if smoked_count > 0 else current_time) + interval
    
    schedule_text = f"Твой план на сегодня:\n"
    schedule_text += f"🎯 Всего запланировано: {planned_count} сигарет\n"
    schedule_text += f"✅ Выкурено: {smoked_count}\n"
    schedule_text += f"🚬 Осталось: {remaining_count}\n\n"
    schedule_text += f"Следующая сигарета: {next_time.strftime('%H:%M')}\n"
    
    await message.answer(schedule_text)

async def smoke_command(message: Message):
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    
    if not user_data:
        await message.answer("Пожалуйста, сначала настрой бота командой /start.")
        return
    
    now = datetime.now()
    bed_time = user_data["bed_time"]
    first_time = user_data["first_cigarette_time"]
    
    # Корректируем bed_time для сравнения
    adjusted_bed = adjust_bed_time_for_comparison(bed_time, now, first_time)
    
    if now > adjusted_bed:
        await message.answer("Время сна уже прошло. Пожалуйста, настрой план на завтра командой /start.")
        return
    
    new_smoked_count = user_data["smoked_count"] + 1
    user_data["smoked_count"] = new_smoked_count
    user_data["last_update_time"] = now
    await save_user_data(user_id, user_data)
    
    await message.answer(f"🚬 Выкуренная сигарета отмечена! Выкурила за сегодня: {new_smoked_count} из {user_data['planned_count']}")
    await send_schedule(message, user_data, now)

async def stats_command(message: Message):
    user_data = await get_user_data(message.from_user.id)
    if not user_data:
        await message.answer("Нет данных. Пожалуйста, настрой бота командой /start.")
        return
    
    stats_text = f"📊 Твоя статистика за сегодня:\n"
    stats_text += f"🎯 План: {user_data['planned_count']} сигарет\n"
    stats_text += f"✅ Выкурено: {user_data['smoked_count']}\n"
    stats_text += f"🚬 Осталось: {user_data['planned_count'] - user_data['smoked_count']}\n"
    await message.answer(stats_text)

# --- Запуск бота ---
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.message.register(start_command, Command("start"))
    dp.message.register(smoke_command, F.text == "🚬 Выкурила сигарету")
    dp.message.register(stats_command, F.text == "📊 Моя статистика")
    
    dp.message.register(process_first_cigarette, StateFilter(SmokingStates.waiting_for_first_cigarette))
    dp.message.register(process_bed_time, StateFilter(SmokingStates.waiting_for_bed_time))
    dp.message.register(process_planned_count, StateFilter(SmokingStates.waiting_for_planned_count))
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
