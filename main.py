from fastapi import FastAPI, Path, Query, HTTPException

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World11"}


@app.middleware("http")
async def add_custom_header(request, call_next):
    # 打印在终端
    print("请求1 Request URL:", request.url)
    response = await call_next(request)
    # 打印在终端
    print("响应1 Response status code:", response.status_code)
    # response.headers["X-Custom-Header"] = "Custom Value"
    return response


@app.middleware("http")
async def add_custom_header2(request, call_next):
    # 打印在终端
    print("请求2 Request URL 2:", request.url)
    response = await call_next(request)
    # 打印在终端
    print("响应2 Response status code 2:", response.status_code)
    # response.headers["X-Custom-Header"] = "Custom Value"
    return response
