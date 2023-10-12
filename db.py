# TODO: ПЕРЕПИСАТЬ ВЕСЬ ФАЙЛ. занести связанные функции Group и User
#  (инкапсулировать)
import asyncio
from typing import Self

from sqlalchemy.orm import DeclarativeBase, Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import MappedAsDataclass
from sqlalchemy.ext.asyncio import create_async_engine as create_engine,\
    async_sessionmaker
from sqlalchemy import insert, select, update, Row

__engine = create_engine("sqlite+aiosqlite:///db.sqlite3")
_session = async_sessionmaker(__engine, expire_on_commit=False)

class Base(MappedAsDataclass, DeclarativeBase):
    """subclasses will be converted to dataclasses"""
    pass


class Group(Base):
    __tablename__ = "group"
    id: Mapped[int] = mapped_column(init=True, primary_key=True, unique=True)
    label: Mapped[str] = mapped_column(init=True, nullable=False)
    description: Mapped[str] = mapped_column(init=True, nullable=True)


class User(Base):
    __tablename__ = "user_account"
    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    chat_id: Mapped[int] = mapped_column(init=False, unique=True)
    group_id: Mapped[int] = mapped_column(nullable=False, default=546)
    username: Mapped[str] = mapped_column(nullable=True, init=False)


class Teacher(Base):
    __tablename__ = 'teacher'
    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    name: Mapped[str] = mapped_column(nullable=True)
    description: Mapped[str] = mapped_column(nullable=True)

    @classmethod
    async def update_or_create(cls, **kwargs) -> Self:
        """Updates row with provided id. If id not found, creates new row"""
        async with _session.begin() as session:
            teacher = await cls.get(kwargs.get('id'))
            if not teacher:
                return (await session.execute(insert(Teacher).returning(Teacher), kwargs)).first()[0]
            else:
                return (await session.execute(
                    update(Teacher).where(Teacher.id == teacher.id).values(
                        name=kwargs.get('name') or teacher.name,
                        description=kwargs.get('description') or teacher.description
                    ).returning(Teacher)
                )).first()[0]

    @classmethod
    async def get(cls, value, field='id') -> Self:
        """Get one by id (or any field)"""
        async with _session.begin() as session:
            res = (await
                session.execute(
                    select(Teacher).filter_by(**{field: value})
                )
            ).first()
            if not res:
                return None
            return res[0]

    @property
    def label(self):
        return self.name

    @label.setter
    def label(self, value):
        self.name = value

async def get_group(id_: int) -> Group | None:
    # TODO: Incapsulate into model.
    async with _session.begin() as session:
        res = (await session.execute(select(Group).filter_by(id=id_))).first()
        if not res:
            return
        return res[0]


async def set_group(id_: int, label: str, description: str = None):
    async with _session.begin() as session:
        group = await get_group(id_)
        if not group:
            return await session.execute(insert(Group), {
                'id': id_,
                'label': label,
                'description': description
            })
        return await session.execute(
            update(Group).where(Group.id == id_).values(
                label=label or group.label,
                description=description or group.description
            )
        )


async def set_profile(chat_id: int, group_id: int,
                      username: str | None, new: bool = False):
    async with _session.begin() as conn:
        if new:
            return (await conn.execute(insert(User).returning(User), {
                'chat_id': chat_id,
                'group_id': group_id,
                'username': username
            })).first()[0]
        else:
            return (await conn.execute(
                update(User).where(User.chat_id == chat_id).values(
                    group_id=group_id, username=username
                ).returning(User)
            )).first()[0]


async def get_profile(chat_id: int) -> User | None:
    async with _session.begin() as session:
        res = (await session.execute(
            select(User).filter_by(chat_id=chat_id)
        )).first()
        if not res:
            return
        return res[0]


async def update_profile(chat_id: int,
                         group_id: int, username: str | None) -> User:
    profile = await get_profile(chat_id)
    return await set_profile(chat_id, group_id, username, new=not profile)


if __name__ == '__main__':

    async def x():
        s = await get_profile(1)
        print(str(s.group_id))
    pass
    async def init_models():
        res = await Teacher.get(1)
        res = await Teacher.update_or_create(id=2, name='artasdasddudr', description='descriptionsadasd')
        print(res)

        return
        async with __engine.begin() as conn:
            #await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init_models())
