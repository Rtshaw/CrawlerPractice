from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import uvicorn

app = FastAPI()
verification_code: Optional[str] = None

class SMSData(BaseModel):
    code: str

@app.post("/sms")
async def receive_sms(data: SMSData):
    global verification_code
    verification_code = data.code
    return {"message": "SMS received", "code": verification_code}

@app.get("/get_code")
async def get_code():
    if verification_code:
        return {"code": verification_code}
    raise HTTPException(status_code=404, detail="No code available")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
