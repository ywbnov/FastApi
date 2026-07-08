from fastapi import FastAPI, Path, Query
# 导入BaseModel函数
from pydantic import BaseModel

# 1、创建FastApi实例：app
app = FastAPI()

# 如何访问对应的函数与返回值呢？通过路由
# 其中：FastApi的路由定义基于python的装饰器模式

# 装饰器 @app.get("/")
# 其中app是fastapi实例，get是请求方式，"/"是路由路径
# 装饰器就是请求这个路径时，执行装饰器内的函数并返回结果
# 如 http://127.0.0.1:8000/ 执行的就是@app.get("/")下的root()函数
# async 异步
@app.get("/")
async def root():
    return {"message": "Hello World11"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}

@app.get("/hello/{name}/{price}")
async def say_hello(name: str, price: float):
    return {"message": f"Hello {name}, the price is ${price:.2f}"}

@app.get("/add/{a}/{b}")
async def add(a: int = Path(gt=0,lt=100), b: int = Path(..., gt=0,lt=100)):
    return {"result": a + b}

@app.get("/author/{name}/{b}")
async def author(name: str = Path(..., description="The author's name", min_length=2, max_length=10), b: int = Path(..., gt=0, lt=100)):
    return {"message": f"Author {name}, the number is {b}"}


@app.get("/divide/find")
async def divide(a: int, b: int=10):
    if b == 0:
        return {"error": "Division by zero is not allowed."}
    return {"result": a / b}

@app.get("/divide/find2")
async def divide(a: int = Query(0, gt=0, lt=100), b: int = Query(10, gt=0, lt=100)):
    if b == 0:
        return {"error": "Division by zero is not allowed."}
    return {"result": a * b}


# 定义类型
class User(BaseModel):
    username: str
    password: str

# 类型注解
@app.post("/register")
async def register(user: User):
    return user
