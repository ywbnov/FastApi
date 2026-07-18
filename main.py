r"""FastAPI + SQLAlchemy 2.0 异步 ORM 学习应用。

完整的软件工程分层、请求链路和 Session 生命周期说明见
同目录下的 MAIN_ARCHITECTURE.md。

启动命令：
    .\.venv\python.exe .\main.py

需要热重载时：
    .\.venv\python.exe -m uvicorn main:app --reload --loop main:create_selector_event_loop

启动后访问：
    Swagger 接口文档：http://127.0.0.1:8000/docs
    ReDoc 接口文档：http://127.0.0.1:8000/redoc

应用启动时会自动连接 MySQL、创建 fastapidba 数据库和 orm_users 表；
如果表为空，则自动写入 120 条模拟数据。所有 ORM 学习操作都可通过
FastAPI 接口访问，无需直接在 Python 代码中调用。

连接配置读取优先级：
1. 环境变量 MYSQL_HOST、MYSQL_PORT、MYSQL_USER、MYSQL_PASSWORD；
2. 本机 MySQL 安装生成的 root-initial-password.txt；
3. host、port、user 使用 127.0.0.1、3306、root 作为默认值。

密码不会写入源码或返回给接口。生产项目应使用应用专用账户和经过 CA
校验的 TLS 证书，不应长期使用 root 账户。
"""

from __future__ import annotations

import asyncio
import os
import ssl
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, AsyncIterator, Literal
from uuid import uuid4

import aiomysql
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Path as ApiPath,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ---------------------------------------------------------------------------
# 运行环境与基础配置
# ---------------------------------------------------------------------------
# aiomysql 在 Windows 下使用 Selector 事件循环兼容性更好。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # 统一为 UTF-8，避免中文日志在部分 PowerShell 终端中出现乱码。
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


DATABASE_NAME = "fastapidba"
LOCAL_CONFIG_FILE = Path(r"E:\Program Files\MySQL\root-initial-password.txt")
DEFAULT_SQLITE_FILE = Path("fastapidba.sqlite")
DEFAULT_SEED_SIZE = 120


def create_selector_event_loop() -> asyncio.AbstractEventLoop:
    """供 Uvicorn 使用的事件循环工厂，兼容 Windows 下 aiomysql TLS。

    Uvicorn 负责运行 ASGI 应用，事件循环负责调度 HTTP 请求、数据库 I/O 等
    异步任务。这里显式使用 SelectorEventLoop，是为了避开 Windows 默认事件
    循环与部分 aiomysql/TLS 组合的兼容性问题。
    """

    return asyncio.SelectorEventLoop()

# @dataclass 根据字段声明生成 __init__、__repr__、__eq__ 等方法；
# frozen=True 禁止连接参数在实例创建后被意外改写。
@dataclass(frozen=True)
class MySQLSettings:
    """集中保存一组 MySQL 连接参数，作为配置层与建库逻辑之间的数据载体。"""

    host: str
    port: int
    user: str
    password: str


def read_key_value_file(path: Path) -> dict[str, str]:
    """读取简单的 key=value 配置文件，忽略空行、注释和无效行。

    该函数只负责解析文件，不了解 MySQL 业务规则；缺少文件时返回空字典，
    让上层配置加载函数继续尝试环境变量和默认值。
    """

    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().lower()] = value.strip()
    return values


def load_mysql_settings() -> MySQLSettings:
    """从环境变量或本机安装配置中组装并校验 MySQL 连接参数。

    将配置读取集中在一个函数中，可以避免启动、建库和连接池分别读取环境
    变量而产生不一致。密码没有安全默认值，因此缺失时直接阻止应用启动。
    """

    local_values = read_key_value_file(LOCAL_CONFIG_FILE)
    host = os.getenv("MYSQL_HOST") or local_values.get("host") or "127.0.0.1"
    port_text = os.getenv("MYSQL_PORT") or local_values.get("port") or "3306"
    user = os.getenv("MYSQL_USER") or local_values.get("user") or "root"
    password = os.getenv("MYSQL_PASSWORD") or local_values.get("password")

    if not password:
        raise RuntimeError(
            "未找到 MySQL 密码。请设置 MYSQL_PASSWORD，"
            f"或检查配置文件：{LOCAL_CONFIG_FILE}"
        )

    try:
        port = int(port_text)
    except ValueError as exc:
        raise RuntimeError(f"MYSQL_PORT 必须是整数，当前值为：{port_text!r}") from exc

    return MySQLSettings(host=host, port=port, user=user, password=password)


def build_sqlite_database_url(path: Path) -> str:
    """把本地文件路径转换为 SQLAlchemy 异步 SQLite URL。"""

    absolute_path = path if path.is_absolute() else Path.cwd() / path
    return f"sqlite+aiosqlite:///{absolute_path.as_posix()}"


def use_sqlite() -> bool:
    """根据环境变量判断是否显式要求使用 SQLite。"""

    if os.getenv("DATABASE_URL", "").startswith("sqlite"):
        return True
    if os.getenv("SQLITE_PATH"):
        return True
    return os.getenv("USE_SQLITE", "").lower() in {"1", "true", "yes"}


def get_database_url() -> tuple[str, str, bool]:
    """统一决定本次进程使用的数据库连接信息。

    返回值依次是：供 SQLAlchemy 使用的 URL、供日志展示且不暴露密码的描述、
    是否按 MySQL 初始化。固定的三项结构使用 tuple，调用方可以直接解包。
    """

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        description = database_url
        return database_url, description, database_url.startswith("sqlite")

    sqlite_path = os.getenv("SQLITE_PATH")
    if sqlite_path:
        url = build_sqlite_database_url(Path(sqlite_path))
        description = str(Path(sqlite_path).resolve())
        return url, description, False

    if use_sqlite():
        url = build_sqlite_database_url(DEFAULT_SQLITE_FILE)
        description = str(DEFAULT_SQLITE_FILE.resolve())
        return url, description, False

    settings = load_mysql_settings()
    database_url = URL.create(
        drivername="mysql+aiomysql",
        username=settings.user,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=DATABASE_NAME,
        query={"charset": "utf8mb4"},
    )
    description = f"{settings.user}@{settings.host}:{settings.port}/{DATABASE_NAME}"
    return database_url, description, True


def create_local_ssl_context() -> ssl.SSLContext:
    """创建仅供本机自签名 MySQL 证书使用的 TLS 配置。

    TLS 仍会加密传输，但关闭证书和主机名验证后无法确认服务端身份，因此
    该配置不能照搬到生产环境。生产环境应加载可信 CA 并启用完整校验。
    """

    context = ssl.create_default_context()
    # 本机 MySQL 使用自签名证书；生产环境必须改为可信 CA 校验。
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def ensure_database(settings: MySQLSettings, ssl_context: ssl.SSLContext) -> None:
    """连接 MySQL 服务，在 fastapidba 不存在时创建它。

    ORM 引擎只能连接已经存在的数据库，因此只有建库步骤直接使用
    aiomysql；建表和所有数据操作均由 SQLAlchemy ORM 完成。
    """

    connection = await aiomysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=5,
        ssl=ssl_context,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA "
                "WHERE SCHEMA_NAME = %s",
                (DATABASE_NAME,),
            )
            if await cursor.fetchone() is None:
                await cursor.execute(
                    f"CREATE DATABASE `{DATABASE_NAME}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# SQLAlchemy 引擎、ORM 映射与 HTTP 数据模型
# ---------------------------------------------------------------------------
def create_database_engine(
    database_url: str, ssl_context: ssl.SSLContext | None = None
) -> AsyncEngine:
    """创建应用级 SQLAlchemy 异步引擎和底层连接池。

    Engine 是整个应用共享的重量级对象，不应为每个 HTTP 请求重复创建。
    请求只创建轻量的 AsyncSession；Session 在真正执行 SQL 时才从 Engine
    的连接池借用连接，并在会话结束后把连接归还池中。
    """

    echo_sql = os.getenv("SQL_ECHO", "").lower() in {"1", "true", "yes"}
    connect_args = {"ssl": ssl_context} if ssl_context is not None else {}
    return create_async_engine(
        database_url,
        echo=echo_sql,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


class Base(DeclarativeBase):
    """所有 ORM 模型的基类，集中保存模型对应的表结构元数据。"""


class User(Base):
    """用户 ORM 模型：一个 User 实例对应 orm_users 表中的一行。"""

    __tablename__ = "orm_users"
    
    # Mapped[int] 描述 Python/ORM 属性类型，mapped_column(Integer) 描述数据库列；
    # 两者结合后，类型检查器、SQLAlchemy 映射器和数据库都能理解这个字段。

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    balance: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


# ORM 模型表达“数据库如何保存数据”；下面的 Pydantic 模型表达“HTTP 接口允许
# 客户端传入和看见哪些数据”。分开建模可以防止数据库内部字段被直接暴露。
class UserCreate(BaseModel):
    """新增用户的请求体。"""

    name: str = Field(min_length=1, max_length=50, examples=["张三"])
    email: str = Field(
        min_length=5,
        max_length=120,
        pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
        examples=["zhangsan@example.com"],
    )
    age: int = Field(ge=0, le=150, examples=[25])
    balance: Decimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2
    )
    is_active: bool = True


class UserUpdate(BaseModel):
    """修改用户的请求体；只传需要修改的字段。"""

    name: str | None = Field(default=None, min_length=1, max_length=50)
    email: str | None = Field(
        default=None,
        min_length=5,
        max_length=120,
        pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
    )
    age: int | None = Field(default=None, ge=0, le=150)
    balance: Decimal | None = Field(
        default=None, ge=0, max_digits=10, decimal_places=2
    )
    is_active: bool | None = None


class UserResponse(BaseModel):
    """返回给客户端的完整用户数据。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    age: int
    balance: Decimal
    is_active: bool
    created_at: datetime


class UserListResponse(BaseModel):
    """分页查询响应，同时返回总数和本页数据。"""

    total: int
    offset: int
    limit: int
    items: list[UserResponse]


class CountResponse(BaseModel):
    count: int


class SeedResponse(BaseModel):
    inserted: int
    total: int


class ResetResponse(BaseModel):
    message: str
    inserted: int
    total: int


class HealthResponse(BaseModel):
    status: str
    database: str


class CrudDemoResponse(BaseModel):
    """一次完整 CRUD 演示的每一步结果。"""

    created: UserResponse
    read: UserResponse
    updated: UserResponse
    deleted: bool
    after_delete: UserResponse | None


# ---------------------------------------------------------------------------
# 数据访问与业务操作
# ---------------------------------------------------------------------------
async def create_tables(engine: AsyncEngine, reset: bool = False) -> None:
    """根据 ORM 元数据建表；reset=True 时先删除本应用管理的表。

    建表属于应用级结构操作，所以直接使用 Engine，而不是某个请求的 Session。
    正式项目通常应改用 Alembic 迁移，以保留可审计、可回滚的结构变更历史。
    """

    async with engine.begin() as connection:
        if reset:
            await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


async def seed_users_if_empty(session: AsyncSession, seed_size: int) -> int:
    """仅在空表时批量插入模拟数据，并在同一数据库会话中提交事务。"""

    count = await session.scalar(select(func.count()).select_from(User))
    if count:
        return 0

    users = [
        User(
            name=f"学习用户{i:03d}",
            email=f"student{i:03d}@example.com",
            age=18 + i % 43,
            balance=Decimal("100.00") + Decimal(i) * Decimal("3.25"),
            is_active=i % 7 != 0,
        )
        for i in range(1, seed_size + 1)
    ]
    session.add_all(users)
    await session.commit()
    return len(users)


async def count_users(session: AsyncSession) -> int:
    """执行只读聚合查询，统计用户表中的记录总数。"""

    return int(await session.scalar(select(func.count()).select_from(User)) or 0)


async def create_user_record(session: AsyncSession, payload: UserCreate) -> User:
    """Create：新增用户并提交事务；邮箱冲突时回滚后返回 409。"""

    user = User(**payload.model_dump())
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="该邮箱已经存在") from exc
    await session.refresh(user)
    return user


async def get_user_record(session: AsyncSession, user_id: int) -> User:
    """Read：在当前请求的 Session 中按主键查询，不存在时返回 404。"""

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")
    return user


async def update_user_record(
    session: AsyncSession, user_id: int, payload: UserUpdate
) -> User:
    """Update：修改已加载对象并提交，SQLAlchemy 自动生成所需的 UPDATE。"""

    user = await get_user_record(session, user_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="至少需要提供一个修改字段")
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="用户字段不能设置为 null")

    for field_name, value in changes.items():
        setattr(user, field_name, value)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="该邮箱已经存在") from exc
    await session.refresh(user)
    return user


async def delete_user_record(session: AsyncSession, user_id: int) -> None:
    """Delete：在当前请求的事务中删除 ORM 对象并提交。"""

    user = await get_user_record(session, user_id)
    await session.delete(user)
    await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """管理与应用进程同生命周期的数据库资源。

    yield 之前是启动阶段：选择数据库、按需建库建表、创建会话工厂和初始化
    教学数据；yield 期间应用开始接收 HTTP 请求；yield 之后是关闭阶段，释放
    Engine 持有的连接池。这样可以确保全局资源只初始化一次且一定被清理。
    """

    database_url, database_description, is_mysql = get_database_url()
    ssl_context = create_local_ssl_context() if is_mysql else None

    if is_mysql:
        settings = load_mysql_settings()
        await ensure_database(settings, ssl_context)

    engine = create_database_engine(database_url, ssl_context)
    try:
        await create_tables(engine)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with session_factory() as session:
            inserted = await seed_users_if_empty(session, DEFAULT_SEED_SIZE)

        # app.state 用来保存整个应用生命周期内共享的引擎和会话工厂。
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.database_description = database_description
        print(
            f"数据库已就绪：{database_description}，本次初始化 {inserted} 条数据。"
        )
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title="异步 ORM 学习 API",
    version="1.0.0",
    description="通过 FastAPI 学习 SQLAlchemy 异步 ORM 的建表和 CRUD 操作。",
    lifespan=lifespan,
)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """为一次 HTTP 请求提供独立的 SQLAlchemy 异步数据库会话。

    AsyncSession 是数据库工作的边界：它跟踪本次请求加载和修改的 ORM 对象，
    并承载查询、事务提交与回滚。每个请求独立创建可以避免并发请求共享事务、
    未提交修改或 ORM 对象缓存，从而防止一个请求污染另一个请求。

    这里的 Session 不是“用户登录会话”，不保存登录身份、Cookie 或 Token，
    也不能据此判断当前用户只能操作自己的数据。认证通常由 JWT、Cookie 或
    服务端登录会话实现，再将解析出的用户身份用于查询条件和权限校验。

    它没有按分钟设置的固定有效期：FastAPI 进入依赖时创建会话，响应完成或
    请求异常时退出 async with 并关闭会话。真正的数据库连接按需从 Engine
    连接池借出，关闭 Session 后归还；网络超时、请求超时和登录过期应分别配置。
    """

    session_factory: async_sessionmaker[AsyncSession] = (
        request.app.state.session_factory
    )
    async with session_factory() as session:
        try:
            # yield 把同一个会话注入当前路由及其调用的数据访问函数。
            yield session
        except Exception:
            # 业务函数可能已经提交成功；这里只回滚异常发生时仍未提交的事务，
            # 让连接回到池中之前恢复为可安全复用的状态。
            await session.rollback()
            raise


# Annotated 把“参数类型”和“如何由 FastAPI 创建它”组合成可复用的依赖类型。
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


# ---------------------------------------------------------------------------
# HTTP 接口层：解析请求、注入依赖，并把工作委托给业务/数据访问函数
# ---------------------------------------------------------------------------
@app.get("/", tags=["应用"], summary="查看 API 入口")
async def api_root() -> dict[str, object]:
    """返回服务入口；具体操作可在 /docs 中直接调用。"""

    return {
        "message": "FastAPI 异步 ORM 学习服务",
        "database": DATABASE_NAME,
        "swagger_docs": "/docs",
        "redoc": "/redoc",
    }


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["应用"],
    summary="检查 API 和数据库连接",
)
async def health_check(session: SessionDependency) -> HealthResponse:
    """执行 SELECT 1，确认连接池中的数据库连接可以正常工作。"""

    await session.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok", database=request.app.state.database_description
    )


@app.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["用户 CRUD"],
    summary="新增用户",
)
async def create_user(payload: UserCreate, session: SessionDependency) -> User:
    """接收 JSON 请求体，通过 ORM INSERT 新用户。"""

    return await create_user_record(session, payload)


@app.get(
    "/users",
    response_model=UserListResponse,
    tags=["用户 CRUD"],
    summary="分页和条件查询用户",
)
async def list_users(
    session: SessionDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    min_age: Annotated[int | None, Query(ge=0, le=150)] = None,
    max_age: Annotated[int | None, Query(ge=0, le=150)] = None,
    is_active: bool | None = None,
) -> UserListResponse:
    """演示 ORM 的 WHERE、ORDER BY、OFFSET 和 LIMIT。"""

    if min_age is not None and max_age is not None and min_age > max_age:
        raise HTTPException(status_code=400, detail="min_age 不能大于 max_age")

    conditions = []
    if min_age is not None:
        conditions.append(User.age >= min_age)
    if max_age is not None:
        conditions.append(User.age <= max_age)
    if is_active is not None:
        conditions.append(User.is_active.is_(is_active))

    total_statement = select(func.count()).select_from(User).where(*conditions)
    list_statement = (
        select(User)
        .where(*conditions)
        .order_by(User.id.asc())
        .offset(offset)
        .limit(limit)
    )
    total = int(await session.scalar(total_statement) or 0)
    users = list((await session.scalars(list_statement)).all())
    return UserListResponse(total=total, offset=offset, limit=limit, items=users)


# 固定路径 /users/count 要写在动态路径 /users/{user_id} 前面。
@app.get(
    "/users/count",
    response_model=CountResponse,
    tags=["用户查询"],
    summary="统计用户总数",
)
async def get_user_count(session: SessionDependency) -> CountResponse:
    return CountResponse(count=await count_users(session))


@app.get(
    "/users/{user_id}",
    response_model=UserResponse,
    tags=["用户 CRUD"],
    summary="按 ID 查询用户",
)
async def get_user(
    user_id: Annotated[int, ApiPath(gt=0)], session: SessionDependency
) -> User:
    return await get_user_record(session, user_id)


@app.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    tags=["用户 CRUD"],
    summary="修改用户",
)
async def update_user(
    user_id: Annotated[int, ApiPath(gt=0)],
    payload: UserUpdate,
    session: SessionDependency,
) -> User:
    return await update_user_record(session, user_id, payload)


@app.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["用户 CRUD"],
    summary="删除用户",
)
async def delete_user(
    user_id: Annotated[int, ApiPath(gt=0)], session: SessionDependency
) -> Response:
    await delete_user_record(session, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/admin/seed",
    response_model=SeedResponse,
    tags=["数据管理"],
    summary="在空表中生成模拟数据",
)
async def seed_users(
    session: SessionDependency,
    size: Annotated[int, Query(ge=100, le=200)] = DEFAULT_SEED_SIZE,
) -> SeedResponse:
    """表为空时插入指定数量；已有数据时 inserted 返回 0。"""

    inserted = await seed_users_if_empty(session, size)
    return SeedResponse(inserted=inserted, total=await count_users(session))


@app.post(
    "/admin/reset",
    response_model=ResetResponse,
    tags=["数据管理"],
    summary="重建教学表并生成模拟数据",
)
async def reset_users_table(
    request: Request,
    confirm: Annotated[
        bool, Query(description="必须传 true，确认清空并重建 orm_users 表")
    ],
    seed_size: Annotated[int, Query(ge=100, le=200)] = DEFAULT_SEED_SIZE,
) -> ResetResponse:
    """删除并重建 orm_users 表；该接口会清空表中的全部现有数据。"""

    if not confirm:
        raise HTTPException(status_code=400, detail="请传入 confirm=true 确认重建表")

    engine: AsyncEngine = request.app.state.engine
    session_factory: async_sessionmaker[AsyncSession] = (
        request.app.state.session_factory
    )
    await create_tables(engine, reset=True)
    async with session_factory() as session:
        inserted = await seed_users_if_empty(session, seed_size)
        total = await count_users(session)
    return ResetResponse(
        message="orm_users 表已重建",
        inserted=inserted,
        total=total,
    )


@app.post(
    "/demo/crud",
    response_model=CrudDemoResponse,
    tags=["学习演示"],
    summary="一次请求演示完整 CRUD",
)
async def demonstrate_crud(session: SessionDependency) -> CrudDemoResponse:
    """依次新增、查询、修改和删除临时用户，并返回每一步结果。"""

    payload = UserCreate(
        name="ORM 演示用户",
        email=f"orm-demo-{uuid4().hex[:8]}@example.com",
        age=28,
        balance=Decimal("88.50"),
    )
    created_user = await create_user_record(session, payload)
    created = UserResponse.model_validate(created_user)

    read_user = await get_user_record(session, created_user.id)
    read = UserResponse.model_validate(read_user)

    updated_user = await update_user_record(
        session,
        created_user.id,
        UserUpdate(balance=Decimal("188.80")),
    )
    updated = UserResponse.model_validate(updated_user)

    await delete_user_record(session, created_user.id)
    after_delete = await session.get(User, created_user.id)
    return CrudDemoResponse(
        created=created,
        read=read,
        updated=updated,
        deleted=True,
        after_delete=(
            UserResponse.model_validate(after_delete) if after_delete else None
        ),
    )


if __name__ == "__main__":
    import uvicorn

    # 使用字符串导入路径，便于以后按需增加 reload=True 热重载。
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        loop="main:create_selector_event_loop",
    )
