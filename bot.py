import logging
import os

import aiogram.exceptions
import dateutil.parser
from aiogram import Bot, Dispatcher, types, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.storage.redis import RedisStorage
import redis.asyncio as redis
from dotenv import load_dotenv
import api
import db

import datetime

load_dotenv()

TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TOKEN:
    raise Exception('Telegram token not provided,'
                    ' please add TELEGRAM_TOKEN to env vars.')


class FSMPrefixes:
    SCHEDULE_PREFIX = 'schedule:'
    GROUP_SETUP = 'group:'


class FSMStates:
    CREATE_PROFILE = 'create_profile'
    CANCEL_ALL = 'cancel_all'
    MY_SCHEDULE_TODAY = f'{FSMPrefixes.SCHEDULE_PREFIX}my@today'
    MY_SCHEDULE_TOMORROW = f'{FSMPrefixes.SCHEDULE_PREFIX}my@tomorrow'
    MY_SCHEDULE_WEEK = f'{FSMPrefixes.SCHEDULE_PREFIX}my@week'
    MY_SCHEDULE_WEEK_CURRENT = f'{FSMPrefixes.SCHEDULE_PREFIX}my@week~current'
    MY_SCHEDULE_WEEK_NEXT = f'{FSMPrefixes.SCHEDULE_PREFIX}my@week~next'
    GROUP_SCHEDULE_GENERAL = f'{FSMPrefixes.GROUP_SETUP}group@start'
    SCHEDULE_TODAY = f'{FSMPrefixes.SCHEDULE_PREFIX}group@today'
    SCHEDULE_TOMORROW = f'{FSMPrefixes.SCHEDULE_PREFIX}group@tomorrow'
    SCHEDULE_WEEK_CURRENT = f'{FSMPrefixes.SCHEDULE_PREFIX}group@week~current'
    SCHEDULE_WEEK_NEXT = f'{FSMPrefixes.SCHEDULE_PREFIX}group@week~next'
    SCHEDULE_WEEK = f'{FSMPrefixes.SCHEDULE_PREFIX}group@week'
    #SCHEDULE_NEXT_WEEK = f'{FSMPrefixes.SCHEDULE_PREFIX}'

dp = Dispatcher(storage=RedisStorage(redis.Redis()))
_bot = Bot(TOKEN, parse_mode="HTML")
bot: Bot = _bot
logger = logging.getLogger(__name__)

cancel_button = InlineKeyboardBuilder(). \
    button(text='Отмена', callback_data=FSMStates.CANCEL_ALL).as_markup()


def _key(query_data: CallbackQuery | Message):
    if isinstance(query_data, CallbackQuery):
        key = StorageKey(
            chat_id=query_data.message.chat.id,
            bot_id=bot.id,
            user_id=query_data.from_user.id
        )
        return key
    else:
        return StorageKey(
            chat_id=query_data.chat.id,
            bot_id=bot.id,
            user_id=query_data.from_user.id
        )


def generate_schedule_str(schedule: list[dict], dates=()) -> str:
    res = ''
    dates_dict = {}

    for elect in schedule:
        try:
            date = datetime.datetime.strptime(elect.get('date'),
                                              '%Y.%m.%d').date()
        except (ValueError, TypeError):
            date = elect.get('date')
        if date is None:
            continue
        if date in dates_dict:
            dates_dict[date].append(elect)
        else:
            dates_dict.update({date: [elect]})
    if dates:
        start = dates[0]
        if not isinstance(start, datetime.date):
            start = dateutil.parser.parse(start).date()
        finish = dates[-1]
        if not isinstance(start, datetime.date):
            finish = dateutil.parser.parse(start).date()
        dates_dict = {k: v for k, v in dates_dict.items() if
                      start <= k <= finish}
    for date in dates_dict:
        res += str(date) + '\n'
        for elect in dates_dict[date]:
            res += f'\t\t<u>{elect.get("beginLesson")}</u> <b>{elect.get("discipline")}</b>\n'
            res += '\t\t' + elect.get('lecturer') + '\n'
        res += '\n\n'
    return res


async def set_menu_message(key: StorageKey, msg: Message):
    data = await dp.storage.get_data(bot, key)
    prev = data.get('menu_messages', [])
    prev.append(msg.message_id)
    return await dp.storage.update_data(bot, key, {'menu_messages': prev})


async def delete_menu_messages(key: StorageKey):
    data = await dp.storage.get_data(bot, key)
    prev = data.get('menu_messages', [])
    for msg_id in prev:
        await delete_user_message(key, msg_id)
    return await dp.storage.update_data(bot, key, {'menu_messages': []})


async def set_last_schedule_message(key: StorageKey, msg: Message):
    return await dp.storage.update_data(bot, key, {
        'last_schedule': msg.message_id
    })


async def add_to_delete_message(key: StorageKey, msg: Message):
    res = await dp.storage.get_data(bot, key)
    res = res.get('messages_delete_after', [])
    res.append(msg.message_id)
    print('SAVED', res)
    await dp.storage.update_data(bot, key,
                                 {'messages_delete_after': list(set(res))})


async def delete_previous_messages_markup(key: StorageKey):
    print('REMOVE!')
    res = await dp.storage.get_data(bot, key)
    last_schedule = res.get('last_schedule', -100)
    res = res.get('messages_delete_after', [])
    for message in res:
        try:
            if message == last_schedule:
                continue
            n = await bot.delete_message(key.chat_id, message)
            print(message, n)
        except TelegramBadRequest:
            pass
    await dp.storage.update_data(bot, key, {'messages_delete_after': []})


async def delete_last_schedule_message(key):
    data = await dp.storage.get_data(bot, key)
    if last := data.get('last_schedule'):
        await delete_user_message(key, last)
    return await dp.storage.update_data(bot, key, {
        'last_schedule': None
    })


def week_from_date(date_: datetime.date):
    today = date_
    start = today - datetime.timedelta(days=today.weekday())
    finish = start + datetime.timedelta(days=6)
    return start, finish


def __add_cancel_button(builder: InlineKeyboardBuilder):
    builder. \
        button(text='Отмена', callback_data=FSMStates.CANCEL_ALL)
    builder.adjust(1, repeat=True)
    return builder


def construct_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text='Настройки',
                   callback_data=FSMStates.CREATE_PROFILE)
    builder.button(text='Мое расписание на сегодня',
                   callback_data=FSMStates.MY_SCHEDULE_TODAY)
    builder.button(text='Мое расписание на завтра',
                   callback_data=FSMStates.MY_SCHEDULE_TOMORROW)
    builder.button(text='Мое расписание на неделю',
                   callback_data=FSMStates.MY_SCHEDULE_WEEK)
    builder.button(text='Поиск расписания по группе',
                   callback_data=FSMStates.GROUP_SCHEDULE_GENERAL)
    builder.adjust(1, repeat=True)
    return builder.as_markup()


def construct_weeks_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text='Текущая неделя',
                   callback_data=FSMStates.SCHEDULE_WEEK_CURRENT)
    builder.button(text='Следующая неделя',
                   callback_data=FSMStates.SCHEDULE_WEEK_NEXT)
    __add_cancel_button(builder)
    return builder

def construct_schedule_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text='Расписание на сегодня',
                   callback_data=FSMStates.SCHEDULE_TODAY)
    builder.button(text='Расписание на завтра',
                   callback_data=FSMStates.SCHEDULE_TOMORROW)
    __add_cancel_button(builder)
    return builder


async def return_schedule(
        *, query_data: CallbackQuery = None,
        message: Message = None,
        dates: tuple = (),
        group_id: int = None,
        when: str
):

    handler = query_data or message
    message = message or query_data.message
    group = await db.get_group(group_id)
    key = _key(handler)
    schedule = await api.get_schedule(group_id, dates=dates)
    print(schedule)
    str_schedule = generate_schedule_str(schedule, dates)
    str_date = "сегодня " if when == "today" else \
        f"{str(dates[0]).replace('-', '.')} - " \
        f"{str(dates[-1]).replace('-', '.')}" if \
            when == "week" else "завтра"
    if not str_schedule:
        msg = await message.answer(
            text=f"На {str_date} для группы "
                 f"<b>{group.label}</b> пар не найдено",
        )
        await delete_last_schedule_message(key)
        await set_last_schedule_message(key, msg)
        await dp.storage.set_state(bot, _key(handler), state=None)
        await echo_handler(message)
        return
    else:
        str_schedule = f'Расписание группы <b>{group.label}</b>' \
                       f' на {str_date} {"("+str(dates[0]).replace("-", ".")+")" if when != "week" else "" }\n\n' + str_schedule
        await delete_last_schedule_message(key)
        if query_data:
            try:
                res = await message.edit_text(text=str_schedule)
            except (aiogram.exceptions.AiogramError,
                    aiogram.exceptions.TelegramBadRequest) as _exc:
                res = await message.answer(text=str_schedule)
        else:
            res = await message.answer(text=str_schedule)
        await set_last_schedule_message(key, res)
        await delete_previous_messages_markup(key)
        msg = await command_start_handler(message)
        await add_to_delete_message(key, msg)


async def delete_user_message(key: StorageKey, message_id: int):
    try:
        await bot.delete_message(key.chat_id, message_id)
    except TelegramBadRequest:
        pass


@dp.message(Command(commands=["start"]))
async def command_start_handler(
        message: Message = None, query_data: CallbackQuery | None = None
) -> Message:
    message = message if not query_data else query_data.message
    if query_data:
        res = await message.edit_text(
            f"Привет, <b>{message.chat.full_name}!"
            f"\nЗдесь ты можешь узнать расписание.</b>",
            reply_markup=construct_menu()
        )
    else:
        res = await message.answer(
            f"Привет, <b>{message.chat.full_name}!"
            f"\nЗдесь ты можешь узнать расписание.</b>",
            reply_markup=construct_menu()
        )
    #await set_menu_message(_key(query_data or message), res)
    return res


@dp.message(StateFilter(FSMStates.MY_SCHEDULE_WEEK))
async def input_week(message: Message | CallbackQuery):
    #TODO: currently can't handle week requests for any group. FIX.
    key = _key(message)
    state = await dp.storage.get_state(bot, key)
    if state == FSMStates.MY_SCHEDULE_WEEK:  # TODO: check of any schedule week.
        group_id = (await db.get_profile(message.chat.id)).group_id
    else:
        group_id = (await dp.storage.get_data(bot, key)).get('group')

    if isinstance(message, CallbackQuery):
        # It's case if we clicked current or next week button.
        match message.data:
            case FSMStates.SCHEDULE_WEEK_CURRENT:
                start, finish = week_from_date(datetime.date.today())
            case FSMStates.SCHEDULE_WEEK_NEXT:
                start, finish = week_from_date(
                    datetime.date.today() + datetime.timedelta(days=7)
                )
            case _:
                await message.answer(
                    'Я не знаю как вы умудрились, но вы залезли куда не надо.'
                )
                await dp.storage.set_state(bot, key=key, state=None)
                msg = await command_start_handler(query_data=message)
                await add_to_delete_message(key, msg)
                return
        await return_schedule(query_data=message, dates=(start, finish),
                              group_id=int(group_id), when='week')
        return
    try:
        date = dateutil.parser.parse(message.text.strip()).date()
    except dateutil.parser.ParserError:
        to_delete = await message.answer(
            text='Ошибка при считывании даты. '
                 'Попробуйте еще раз. Пример даты: 2023-04-22',
            reply_markup=cancel_button
        )
        await delete_previous_messages_markup(_key(message))
        await delete_user_message(_key(message), message.message_id)
        await add_to_delete_message(_key(message), to_delete)
        return
    start, finish = week_from_date(date)
    await return_schedule(message=message, dates=(start, finish),
                          group_id=int(group_id), when='week')


@dp.callback_query(F.data.startswith(FSMPrefixes.SCHEDULE_PREFIX))
async def get_schedule_handler(query_data: CallbackQuery):
    """Кнопки показа расписания"""
    key = _key(query_data)
    profile = await db.get_profile(query_data.message.chat.id)
    data = query_data.data.replace(FSMPrefixes.SCHEDULE_PREFIX, '')
    who, when = data.split('@')
    when, when_prefix, *_ = [*when.split('~'), None]
    group_id = None
    if who == 'my':
        if not profile or not profile.group_id:
            await query_data.message.edit_text(
                text=f'Мы не знаем вашу группу, чтобы дать ваше расписание на '
                     f'{"сегодня" if when == "today" else "завтра"}.'
                     f' Задайте группу в настройках, '
                     'или просмотрите расписание конкретной группы.',
                reply_markup=construct_menu()
            )
            return
        group_id = profile.group_id
    elif who == 'group':
        group_id = (await dp.storage.get_data(bot, key)).get('group')
    match when:
        case 'today':
            today = datetime.date.today()
            dates = today, today
        case 'tomorrow':
            dates = datetime.date.today() + datetime.timedelta(days=1)
            dates = dates, dates
        case 'week':
            # TODO: get from state data.
            # if when_prefix
            await query_data.message.edit_text(
                'введите дату (любую дату в промежутке нужной недели)',
                reply_markup=construct_weeks_keyboard().as_markup()
            )
            # await query_data.message.edit_reply_markup()
            # TODO: RENAME MY_SCHEDULE_WEEK TO JUST SCHEDULE_WEEK (IN HANDLER TOO)
            await dp.storage.set_state(bot, key, FSMStates.MY_SCHEDULE_WEEK)
            await add_to_delete_message(key, query_data.message)
            return
        case _:
            dates = ()
    await return_schedule(query_data=query_data,
                          dates=dates, group_id=group_id, when=when)
    # await delete_user_message(key, query_data.message.message_id)


@dp.callback_query(F.data == FSMStates.GROUP_SCHEDULE_GENERAL)
async def pick_group_pressed(query_data: CallbackQuery):
    key = _key(query_data)
    await dp.storage.set_state(bot, key, query_data.data)
    await query_data.message.edit_text('Введите группу:',
                                       reply_markup=cancel_button)
    await add_to_delete_message(key, query_data.message)


@dp.callback_query(StateFilter(FSMStates.CREATE_PROFILE))
async def on_create_profile_group_setter(query_data: CallbackQuery):
    key = _key(query_data)
    print('PROFILE_CREATE', await dp.storage.get_state(bot, key=key))

    match query_data.data.split(':'):
        case ['set_group', group]:
            group = await db.get_group(group)
            if not group:
                await dp.fsm.storage.set_state(bot, key, state=None)
                await query_data.message.edit_text(
                    text='Извините, бот очень тупой, и где-то ошибся, '
                         'попробуйте еще раз,'
                         ' или напишите на artur.2002.artur@gmail.com'
                )
                msg = await command_start_handler(
                    message=query_data.message
                )
                await add_to_delete_message(key, msg)
            profile = await db.update_profile(key.chat_id, group.id,
                                              query_data.from_user.full_name)
            await query_data.message.edit_text(
                text='Группа сохранена. Теперь по умолчанию бот считает, '
                     f'что вы в группе <b>{group.label}</b>'
            )
            await dp.storage.set_state(bot, key=key, state=None)
            msg = await command_start_handler(query_data=query_data)
            await add_to_delete_message(key, msg)
        case [FSMStates.CANCEL_ALL]:
            await dp.storage.set_state(bot, key=key, state=None)
            msg = await command_start_handler(query_data=query_data)
            await add_to_delete_message(key, msg)


@dp.callback_query()
async def on_button_pressed(query_data: CallbackQuery):
    key = _key(query_data)
    print('DEFAULT_HANDLER', await dp.storage.get_state(bot, key=key))
    match query_data.data.split(':'):
        case [FSMStates.CREATE_PROFILE]:
            await dp.storage.set_state(bot, key=key,
                                       state=FSMStates.CREATE_PROFILE)

            await query_data.message.edit_text(
                'Введите свою группу (будет показываться по умолчанию):',
                reply_markup=cancel_button)
            await add_to_delete_message(key, query_data.message)
        case [FSMStates.CANCEL_ALL]:
            await dp.storage.set_state(bot, key=key, state=None)
            msg = await command_start_handler(query_data=query_data)
            await add_to_delete_message(key, msg)
        case ['set_group', group]:
            group_label = await db.get_group(id_=int(group))
            await dp.fsm.storage.update_data(bot, key, {'group': group})
            construct_schedule_keyboard()
            await delete_previous_messages_markup(key)
            await query_data.message.answer(
                text=f'Что показать для группы <b>{group_label.label}</b>',
                reply_markup=construct_schedule_keyboard().as_markup(),
                parse_mode='html'
            )


@dp.message(StateFilter(FSMStates.GROUP_SCHEDULE_GENERAL))
async def find_group(message: types.Message):
    key = _key(message)
    # TODO: сохранять результат, делать реальный запрос не чаще, чем раз в 20 секунд
    filtered = await api.search(message.text, search_type=api.SearchType.GROUP)
    builder = InlineKeyboardBuilder()
    if not filtered:
        msg = await message.answer(
            'Мы не смогли найти ни одной подходящей группы,'
            ' попробуйте ввести другой запрос.',
            reply_markup=cancel_button
        )
        await delete_previous_messages_markup(key=_key(message))
        await add_to_delete_message(_key(message), msg)
        await delete_user_message(key, message.message_id)
        return
    if len(filtered) == 1:
        group = await db.get_group(id_=int(filtered[0].get('id')))
        await dp.fsm.storage.update_data(bot, key, {'group': group.id})
        await delete_previous_messages_markup(key)
        await message.answer(
            text=f'Что показать для группы <b>{group.label}</b>',
            reply_markup=construct_schedule_keyboard().as_markup(),
            parse_mode='html'
        )
        await delete_user_message(key, message.message_id)
        return
    for group in filtered:
        await db.set_group(int(group.get('id')), group.get('label'),
                           group.get('description'))
        builder.button(text=group.get('label'),
                       callback_data=f'set_group:{group.get("id")}')
    __add_cancel_button(builder)
    builder.adjust(1)
    msg = await message.answer(text='По вашему запросу есть вот такие группы:',
                               reply_markup=builder.as_markup())
    await delete_previous_messages_markup(key=_key(message))
    await add_to_delete_message(_key(message), msg)
    await delete_user_message(key, message.message_id)


@dp.message(StateFilter(FSMStates.CREATE_PROFILE))
async def create_profile(message: types.Message):
    key = _key(message)
    message_text = message.text
    groups = await api.search(message_text, api.SearchType.GROUP)
    res = None
    if len(groups) == 1:
        group = groups[0]
        res = groups[0].get('id'), groups[0].get('label')
        await db.update_profile(key.chat_id, group_id=res[0],
                                username=message.from_user.full_name)
        await message.answer(
            text=f'Отлично! По умолчанию будет показываться группа {res[1]}'
        )
        await db.set_group(group.get('id'), group.get('label'),
                           group.get('description'))
        await dp.storage.set_state(_bot, key, None)
        await delete_previous_messages_markup(key=key)
        msg = await command_start_handler(message)
        await add_to_delete_message(key, msg)

    elif len(groups) > 1:
        res = groups
        print(groups, len(groups))
        builder = InlineKeyboardBuilder()
        for group in res:
            await db.set_group(group.get('id'), group.get('label'),
                               group.get('description'))
            builder.button(text=group.get('label'),
                           callback_data=f'set_group:{group.get("id")}')
        __add_cancel_button(builder)
        builder.adjust(1)
        msg = await message.answer(
            text='По вашему запросу есть вот такие группы:',
            reply_markup=builder.as_markup())
        await delete_previous_messages_markup(key=_key(message))
        await add_to_delete_message(_key(message), msg)
    if res is None:
        res = await message.answer('Группа не найдена, попробуйте еще раз:')
        print(res)
        print(type(res))
    await delete_user_message(key, message.message_id)


@dp.message()
async def echo_handler(message: types.Message):
    msg = await command_start_handler(message)
    await add_to_delete_message(_key(msg), msg)
    await delete_user_message(_key(message), message.message_id)


@dp.startup()
async def startup_bot(dispatcher: Dispatcher, bots: tuple[Bot],
                      router: Dispatcher, **kwargs):
    global bot
    bot = kwargs.get('bot', _bot)
    print('BOT ready and available at ',
          f'https://t.me/{(await bot.get_me()).username}')


def main() -> None:
    # And the run events dispatching
    dp.run_polling(_bot)


if __name__ == "__main__":
    main()
