import asyncio
import datetime
import json
from pprint import pprint
from urllib.parse import quote
import aiohttp

RASP_URL = 'https://rasp.omgtu.ru/'
RASP_CONFIG = RASP_URL + 'ruz/assets/config/config.json'
LANG_CONFIG = RASP_URL + 'ruz/assets/i18n/ru.json'
SEARCH_BASE_URL = RASP_URL + 'api/search?term={}'
SCHEDULE_URL = RASP_URL + 'api/schedule/{}/{}?'


class SearchType:
    GROUP = 'group'
    STUDENT = 'student'
    TEACHER = 'person'
    ROOM = 'auditorium'


async def get_schedule(
        id_: int | str,
        search_type='group',
        dates: str | tuple[str, str] | tuple[datetime.date, datetime.date] = ()
) -> list[dict]:
    url = SCHEDULE_URL.format(search_type, id_)
    if dates:
        if isinstance(dates, str):
            url += ('start=' + dates)
        else:
            start, finish = str(dates[0]), str(dates[-1])
            url += f'start={quote(start)}&finish={quote(finish)}'
            print(url)
    return await get_data(url)


async def search(term: str, search_type: str) -> list[dict[str, str | int]]:
    url = SEARCH_BASE_URL.format(term)
    url = (url + f'&type={quote(search_type)}') if search_type else url
    return await get_data(url)


async def get_data(url: str) -> dict | list | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as resp:
                open('main.json', 'w+', encoding='utf-8').write(
                    await resp.text()
                )
                try:
                    return await resp.json()
                except json.JSONDecodeError:
                    return await resp.json(encoding='utf-8-sig')
    except aiohttp.ClientError as _exc:
        return None


async def main():
    rasp = await search('п', SearchType.GROUP)

    pprint(rasp)


if __name__ == '__main__':
    asyncio.run(main())
