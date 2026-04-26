import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # Python 3.9+
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

BOT_TOKEN = "8713595114:AAHX5n1B-HAZFwg3lCkf-aQQDsU0WLpUmq4"
TIMEZONE = "Europe/Moscow"  # Замените на ваш часовой пояс

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Хранилище в памяти ---
user_data_store: Dict[int, Dict] = {}

def get_user_data(user_id: int) -> Optional[Dict]:
    return user_data_store.get(user_id)

def save_user_data(user_id: int, data: Dict):
    user_data_store[user_id] = data
    logger.info(f"Сохранено для {user_id}")

def reset_user(user_id: int):
    if user_id in user_data_store:
        del user_data_store[user_id]

def now_local():
    """Возвращает текущее время в вашем часовом поясе"""
    return datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)

# --- Клавиатура ---
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚬 Выкурили сигарету")],
            [KeyboardButton(text="📊 Моя статистика")]
        ],
        resize_keyboard=True
    )

# --- Состояния ---
class SmokingStates(StatesGroup):
    waiting_for_first_cigarette = State()
    waiting_for_bed_time = State()
    waiting_for_planned_count = State()

async def reset_command(message: Message, state: FSMContext):
    reset_user(message.from_user.id)
    await state.clear()
    await message.answer("✅ Все данные удалены. Начни с /start")

async def start_command(message: Message, state: FSMContext):
    reset_user(message.from_user.id)
    await state.clear()
    await message.answer(
        "Привет! Я бот для контроля курения. 🚭\n\n"
        "Во сколько Вы выкурили ПЕРВУЮ сигарету сегодня?\n"
        "(Напишите в формате ЧЧ:ММ, например 08:30)"
    )
    await state.set_state(SmokingStates.waiting_for_first_cigarette)

async def process_first_cigarette(message: Message, state: FSMContext):
    try:
        time_str = message.text.strip()
        first_time = datetime.strptime(time_str, "%H:%M").time()
        now = now_local()
        first_datetime = datetime.combine(now.date(), first_time)
        await state.update_data(first_cigarette_time=first_datetime)
        await message.answer(
            "Во сколько планируете лечь спать?\n"
            "(Напишите в формате ЧЧ:ММ, например 23:00 или 02:00)"
        )
        await state.set_state(SmokingStates.waiting_for_bed_time)
    except:
        await message.answer("Ошибка! Используйте формат ЧЧ:ММ, например 08:30")

async def process_bed_time(message: Message, state: FSMContext):
    try:
        time_str = message.text.strip()
        bed_time_tm = datetime.strptime(time_str, "%H:%M").time()
        user_data = await state.get_data()
        first_datetime = user_data.get("first_cigarette_time")
        if not first_datetime:
            await message.answer("Сначала укажите время первой сигареты. /start")
            return
        now = now_local()
        if bed_time_tm < first_datetime.time():
            bed_datetime = datetime.combine(now.date() + timedelta(days=1), bed_time_tm)
        else:
            bed_datetime = datetime.combine(now.date(), bed_time_tm)
        await state.update_data(bed_time=bed_datetime)
        await message.answer("Сколько сигарет планируете выкурить? (Введите число)")
        await state.set_state(SmokingStates.waiting_for_planned_count)
    except:
        await message.answer("Ошибка! Используйте формат ЧЧ:ММ, например 23:00")

async def process_planned_count(message: Message, state: FSMContext):
    try:
        planned = int(message.text.strip())
        if planned <= 0:
            raise ValueError
        user_data = await state.get_data()
        first_time = user_data["first_cigarette_time"]
        bed_time = user_data["bed_time"]
        save_user_data(message.from_user.id, {
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
                f"📋 Твой план:\n"
                f"🎯 Всего: {planned}\n"
                f"✅ Выкурено: 1 (первая учтена)\n"
                f"🚬 Осталось: {remaining}\n\n"
                f"⏰ Следующая: {next_time.strftime('%H:%M')}"
            )
        else:
            await message.answer("Поздравляю! План выполнен! 🎉")
        await state.clear()
        await message.answer(
            "Готово! Отмечайте сигареты кнопкой ниже:",
            reply_markup=get_main_keyboard()
        )
    except:
        await message.answer("Ошибка! Введите целое число, например 5")

async def smoke_command(message: Message):
    user_id = message.from_user.id
    data = get_user_data(user_id)
    if not data:
        await message.answer("Сначала настройте бота командой /start")
        return

    now = now_local()
    bed_time = data["bed_time"]

    while bed_time <= now:
        bed_time += timedelta(days=1)

    if now > bed_time:
        await message.answer("⏰ Время сна прошло! Завтра начните /start")
        return

    new_smoked = data["smoked_count"] + 1
    data["smoked_count"] = new_smoked
    data["last_update_time"] = now
    save_user_data(user_id, data)

    remaining = data["planned_count"] - new_smoked

    if remaining > 0:
        total_seconds = (bed_time - now).total_seconds()
        interval_seconds = total_seconds / remaining
        next_time = now + timedelta(seconds=interval_seconds)
        if next_time <= now:
            next_time = now + timedelta(minutes=10)
        await message.answer(
            f"✅ Отмечено! Выкурено: {new_smoked} из {data['planned_count']}\n"
            f"🚬 Осталось: {remaining}\n\n"
            f"⏰ Следующая: {next_time.strftime('%H:%M')}"
        )
    elif remaining == 0:
        await message.answer(f"🎉 Поздравляю! Дневной план выполнен!")
    else:
        await message.answer(f"⚠️ Превышение плана на {abs(remaining)} сигарет(ы)!")

async def stats_command(message: Message):
    data = get_user_data(message.from_user.id)
    if not data:
        await message.answer("Нет данных. Начните с /start")
        return
    await message.answer(
        f"📊 Статистика:\n"
        f"🎯 План: {data['planned_count']}\n"
        f"✅ Выкурено: {data['smoked_count']}\n"
        f"🚬 Осталось: {data['planned_count'] - data['smoked_count']}"
    )

# --- Запуск ---
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.register(start_command, Command("start"))
    dp.message.register(reset_command, Command("reset"))
    dp.message.register(process_first_cigarette, StateFilter(SmokingStates.waiting_for_first_cigarette))
    dp.message.register(process_bed_time, StateFilter(SmokingStates.waiting_for_bed_time))
    dp.message.register(process_planned_count, StateFilter(SmokingStates.waiting_for_planned_count))
    dp.message.register(smoke_command, F.text == "🚬 Выкурили сигарету")
    dp.message.register(stats_command, F.text == "📊 Моя статистика")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
