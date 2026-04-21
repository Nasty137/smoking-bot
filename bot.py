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

# --- Функция для корректировки времени сна ---
def adjust_bed_time(bed_time: datetime, now: datetime, first_time: datetime) -> datetime:
    """Возвращает правильную дату для времени сна"""
    if bed_time.time() < first_time.time():
        bed_today = datetime.combine(now.date(), bed_time.time())
        if now > bed_today:
            return datetime.combine(now.date() + timedelta(days=1), bed_time.time())
        return bed_today
    return bed_time

# --- Хендлеры ---
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
        bed_time = datetime.strptime(message.text, "%H:%M").time()
        now = datetime.now()
        user_data = await state.get_data()
        first_time = user_data.get("first_cigarette_time")
        
        if first_time and bed_time < first_time.time():
            bed_datetime = datetime.combine(now.date() + timedelta(days=1), bed_time)
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
        
        # Отправляем расписание
        remaining = planned_count - 1
        if remaining > 0:
            interval = (bed_time - first_time) / remaining
            next_time = first_time + interval
            response = (
                f"Твой план на сегодня:\n"
                f"🎯 Всего запланировано: {planned_count} сигарет\n"
                f"✅ Выкурено: 1\n"
                f"🚬 Осталось: {remaining}\n\n"
                f"Следующая сигарета: {next_time.strftime('%H:%M')}"
            )
        else:
            response = "Поздравляю! Ты выполнила дневной план! 🎉"
        
        await message.answer(response)
        await state.clear()
        await message.answer(
            "Настройка завершена! Первая сигарета уже учтена ✅\n"
            "Не забывай отмечать каждую следующую сигарету кнопкой ниже 👇",
            reply_markup=get_main_keyboard()
        )
    except ValueError:
        await message.answer("Пожалуйста, введи целое положительное число.")

async def smoke_command(message: Message):
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    
    if not user_data:
        await message.answer("Пожалуйста, сначала настрой бота командой /start.")
        return
    
    now = datetime.now()
    bed_time = user_data["bed_time"]
    first_time = user_data["first_cigarette_time"]
    
    adjusted_bed = adjust_bed_time(bed_time, now, first_time)
    
    if now > adjusted_bed:
        await message.answer("Время сна уже прошло. Пожалуйста, настрой план на завтра командой /start.")
        return
    
    new_smoked_count = user_data["smoked_count"] + 1
    user_data["smoked_count"] = new_smoked_count
    user_data["last_update_time"] = now
    await save_user_data(user_id, user_data)
    
    remaining = user_data["planned_count"] - new_smoked_count
    if remaining > 0:
        interval = (adjusted_bed - now) / remaining
        next_time = now + interval
        response = (
            f"🚬 Выкуренная сигарета отмечена!\n"
            f"✅ Выкурено: {new_smoked_count} из {user_data['planned_count']}\n"
            f"🚬 Осталось: {remaining}\n\n"
            f"Следующая сигарета: {next_time.strftime('%H:%M')}"
        )
    else:
        response = f"🚬 Выкуренная сигарета отмечена! Поздравляю! Ты выполнила дневной план! 🎉"
    
    await message.answer(response)

async def stats_command(message: Message):
    user_data = await get_user_data(message.from_user.id)
    if not user_data:
        await message.answer("Нет данных. Пожалуйста, настрой бота командой /start.")
        return
    
    await message.answer(
        f"📊 Твоя статистика за сегодня:\n"
        f"🎯 План: {user_data['planned_count']} сигарет\n"
        f"✅ Выкурено: {user_data['smoked_count']}\n"
        f"🚬 Осталось: {user_data['planned_count'] - user_data['smoked_count']}"
    )

# --- Запуск ---
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
