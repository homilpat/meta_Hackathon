from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="QualityOps AI", version="0.0.1")


class Health(BaseModel):
    status: str
    stage: str


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", stage="S0")

