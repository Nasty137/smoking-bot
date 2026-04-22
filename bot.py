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

# --- Состояния ---
class SmokingStates(StatesGroup):
    waiting_for_first_cigarette = State()
    waiting_for_bed_time = State()
    waiting_for_planned_count = State()

# --- База данных ---
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

# --- Вспомогательная функция для корректировки времени сна ---
def get_correct_bed_time(bed_time: datetime, first_time: datetime, now: datetime) -> datetime:
    """Возвращает bed_time с правильной датой для сравнения и расчётов"""
    # Если время сна меньше времени первой сигареты — это сон на следующий день
    if bed_time.time() < first_time.time():
        # Предполагаем, что сон сегодня
        bed_candidate = datetime.combine(now.date(), bed_time.time())
        # Если сегодняшний сон уже прошёл — берём завтра
        if now > bed_candidate:
            return datetime.combine(now.date() + timedelta(days=1), bed_time.time())
        return bed_candidate
    else:
        return datetime.combine(now.date(), bed_time.time())

# --- Хендлеры ---
async def start_command(message: Message, state: FSMContext):
    await message.answer(
        "Привет! Я бот для контроля курения. 🚭\n\n"
        "Во сколько ты выкурила ПЕРВУЮ сигарету сегодня?\n"
        "(Напиши в формате ЧЧ:ММ, например 08:30)"
    )
    await state.set_state(SmokingStates.waiting_for_first_cigarette)

async def process_first_cigarette(message: Message, state: FSMContext):
    try:
        time_str = message.text.strip()
        first_time = datetime.strptime(time_str, "%H:%M").time()
        now = datetime.now()
        first_datetime = datetime.combine(now.date(), first_time)
        await state.update_data(first_cigarette_time=first_datetime)
        await message.answer(
            "Во сколько ты планируешь лечь спать?\n"
            "(Напиши в формате ЧЧ:ММ, например 23:00 или 02:00)"
        )
        await state.set_state(SmokingStates.waiting_for_bed_time)
    except:
        await message.answer("Ошибка! Используй формат ЧЧ:ММ, например 08:30")

async def process_bed_time(message: Message, state: FSMContext):
    try:
        time_str = message.text.strip()
        bed_time_tm = datetime.strptime(time_str, "%H:%M").time()
        user_data = await state.get_data()
        first_datetime = user_data.get("first_cigarette_time")
        
        if not first_datetime:
            await message.answer("Сначала укажи время первой сигареты. Начни заново с /start")
            return
        
        now = datetime.now()
        
        # Если время сна меньше времени первой сигареты — значит, сон на следующий день
        if bed_time_tm < first_datetime.time():
            bed_datetime = datetime.combine(now.date() + timedelta(days=1), bed_time_tm)
        else:
            bed_datetime = datetime.combine(now.date(), bed_time_tm)
        
        await state.update_data(bed_time=bed_datetime)
        await message.answer("Сколько сигарет ты планируешь выкурить за сегодня? (Введи число)")
        await state.set_state(SmokingStates.waiting_for_planned_count)
    except:
        await message.answer("Ошибка! Используй формат ЧЧ:ММ, например 23:00")

async def process_planned_count(message: Message, state: FSMContext):
    try:
        planned = int(message.text.strip())
        if planned <= 0:
            raise ValueError
        
        user_data = await state.get_data()
        first_time = user_data["first_cigarette_time"]
        bed_time = user_data["bed_time"]
        
        await save_user_data(message.from_user.id, {
            "first_cigarette_time": first_time,
            "bed_time": bed_time,
            "planned_count": planned,
            "smoked_count": 1,
            "last_update_time": first_time
        })
        
        remaining = planned - 1
        if remaining > 0:
            interval = (bed_time - first_time) / remaining
            next_time = first_time + interval
            await message.answer(
                f"📋 Твой план на сегодня:\n"
                f"🎯 Всего: {planned} сигарет\n"
                f"✅ Выкурено: 1 (первая учтена)\n"
                f"🚬 Осталось: {remaining}\n\n"
                f"⏰ Следующая сигарета: {next_time.strftime('%H:%M')}"
            )
        else:
            await message.answer("Поздравляю! Твой план на сегодня выполнен! 🎉")
        
        await state.clear()
        await message.answer(
            "Готово! Теперь отмечай каждую сигарету кнопкой ниже:",
            reply_markup=get_main_keyboard()
        )
    except:
        await message.answer("Ошибка! Введи целое положительное число, например 5")

async def smoke_command(message: Message):
    user_id = message.from_user.id
    data = await get_user_data(user_id)
    
    if not data:
        await message.answer("Сначала настрой бота командой /start")
        return
    
    now = datetime.now()
    first_time = data["first_cigarette_time"]
    bed_time_raw = data["bed_time"]
    
    # Получаем bed_time с правильной датой
    bed_time = get_correct_bed_time(bed_time_raw, first_time, now)
    
    # Проверяем, не наступило ли время сна
    if now > bed_time:
        await message.answer(
            "⏰ Время сна уже прошло! Дневной план завершён.\n"
            "Завтра начни заново командой /start"
        )
        return
    
    # Обновляем счётчик
    new_smoked = data["smoked_count"] + 1
    data["smoked_count"] = new_smoked
    data["last_update_time"] = now
    await save_user_data(user_id, data)
    
    remaining = data["planned_count"] - new_smoked
    
    if remaining > 0:
        # Используем правильный bed_time для расчёта интервала
        interval = (bed_time - now) / remaining
        next_time = now + interval
        
        # Если следующее время оказалось меньше текущего (ошибка) — корректируем
        if next_time <= now:
            # Принудительно добавляем небольшой интервал (10 минут)
            next_time = now + timedelta(minutes=10)
        
        await message.answer(
            f"✅ Отмечено! Выкурено: {new_smoked} из {data['planned_count']}\n"
            f"🚬 Осталось: {remaining}\n\n"
            f"⏰ Следующая сигарета: {next_time.strftime('%H:%M')}"
        )
    elif remaining == 0:
        await message.answer(
            f"🎉 Поздравляю! Ты выполнила дневной план!\n"
            f"Выкурено: {new_smoked} из {data['planned_count']}"
        )
    else:
        over = abs(remaining)
        await message.answer(
            f"⚠️ Внимание! Ты превысила план на {over} сигарет(ы)!\n"
            f"Запланировано: {data['planned_count']}, выкурено: {new_smoked}\n"
            f"Постарайся завтра не превышать норму 🙏"
        )

async def stats_command(message: Message):
    data = await get_user_data(message.from_user.id)
    if not data:
        await message.answer("Нет данных. Начни с /start")
        return
    
    await message.answer(
        f"📊 Твоя статистика:\n"
        f"🎯 План: {data['planned_count']} сигарет\n"
        f"✅ Выкурено: {data['smoked_count']}\n"
        f"🚬 Осталось: {data['planned_count'] - data['smoked_count']}"
    )

# --- Запуск ---
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.message.register(start_command, Command("start"))
    dp.message.register(process_first_cigarette, StateFilter(SmokingStates.waiting_for_first_cigarette))
    dp.message.register(process_bed_time, StateFilter(SmokingStates.waiting_for_bed_time))
    dp.message.register(process_planned_count, StateFilter(SmokingStates.waiting_for_planned_count))
    dp.message.register(smoke_command, F.text == "🚬 Выкурила сигарету")
    dp.message.register(stats_command, F.text == "📊 Моя статистика")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
