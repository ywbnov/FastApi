from fastapi import FastAPI, Path, Query, HTTPException
# 导入BaseModel函数
from pydantic import BaseModel, Field

from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

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
    username: str = Field(default="张三", description="The username", min_length=2, max_length=100)
    password: str = Field(default="123456", description="The password", min_length=6, max_length=100)

# 类型注解
@app.post("/register")
async def register(user: User):
    return user


# 定义类型
class Book(BaseModel):
    title: str = Field(default="跨时代的AI", description="The title of the book", min_length=2, max_length=200)
    author: str = Field(default="不留名的X先生", description="The author of the book", min_length=2, max_length=100)
    price: float = Field(default=20.0, description="The price of the book", ge=0)

# 类型注解
@app.post("/createBook")
async def create_book(book: Book):
    return book

# HTMLResponse示例
@app.get("/books/{book_id}", response_class=HTMLResponse)
async def get_book(book_id: int):
    # 模拟从数据库中获取书籍信息
    book_info = {
        "id": book_id,
        "title": "跨时代的AI",
        "author": "不留名的X先生",
        "price": 20.0
    }
    html_content = f"""
    <html>
        <head>
            <title>Book Info</title>
        </head>
        <body>
            <h1>Book ID: {book_info['id']}</h1>
            <p>Title: {book_info['title']}</p>
            <p>Author: {book_info['author']}</p>
            <p>Price: ${book_info['price']:.2f}</p>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


# FileResponse示例
@app.get("/download/{file_name}", response_class=FileResponse)
async def download_file(file_name: str):
    file_path = f"./images/{file_name}"
    return FileResponse(path=file_path, filename=file_name, media_type='application/octet-stream')

class news(BaseModel):
    id: int
    title: str
    content: str

@app.get("/createNews/{id}", response_model=news)


@app.get("/createNews1/{id}", response_model=news)
async def create_news(id: int):
    return {
        "id": id,
        "title": f"News Title {id}",
        # 注意，如果不按news中的返回会报错，如你删除content字段，返回的json中没有content字段，就会报错
        "content": f"This is the content of news item {id}."
    }



# httpexception示例
@app.get("/get_news/{id}")
async def get_news(id: int):
    if id < 1 or id > 100:
        raise HTTPException(status_code=404, detail="News item not found")
    return {"id": id, "title": f"News Title {id}", "content": f"This is the content of news item {id}."}