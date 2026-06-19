from fastapi import FastAPI

app = FastAPI(title="Clinical Reasoning Assistant")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
