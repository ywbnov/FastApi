from fastapi import FastAPI, Path, Query, HTTPException, Depends
# 依赖注入：2.导入depends
from fastapi import Depends
app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World11"}

# 中间件1
@app.middleware("http")
async def add_custom_header(request, call_next):
    # 打印在终端
    print("请求1 Request URL:", request.url)
    response = await call_next(request)
    # 打印在终端
    print("响应1 Response status code:", response.status_code)
    # response.headers["X-Custom-Header"] = "Custom Value"
    return response


# 中间件2
@app.middleware("http")
async def add_custom_header2(request, call_next):
    # 打印在终端
    print("请求2 Request URL 2:", request.url)
    response = await call_next(request)
    # 打印在终端
    print("响应2 Response status code 2:", response.status_code)
    # response.headers["X-Custom-Header"] = "Custom Value"
    return response


# 依赖注入
# 1. 定义一个依赖函数
def common_parameters(
        q: str = Query(None, max_length=50), 
        skip: int = Query(0, ge=0), 
        limit: int = Query(100, le=100)
        ):
    return {"q": q, "skip": skip, "limit": limit} 
 # 3,在路径操作函数中使用Depends来声明依赖关系
@app.get("/items/")
async def read_items(commons: dict = Depends(common_parameters)):
    return commons
