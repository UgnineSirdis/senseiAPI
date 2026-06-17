from fastapi import FastAPI

app = FastAPI(title="SenseiAPI", version="0.1.0")


@app.get("/")
def root():
    return {"message": "Welcome to SenseiAPI"}


@app.get("/health")
def health():
    return {"status": "ok"}
