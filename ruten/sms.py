from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class SMS(BaseModel):
    sender: str
    receiver: str
    message: str

@app.post("/receive-sms")
async def receive_sms(sms: SMS):
    try:
        with open("sms.txt", "a") as f:
            f.write(f"{sms.dict()}\n")
        return {"status": "received", "data": sms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Run the application using a command like `uvicorn main:app --reload`
