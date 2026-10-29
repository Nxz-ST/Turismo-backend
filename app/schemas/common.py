from pydantic import BaseModel


class Message(BaseModel):
    message: str


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str

