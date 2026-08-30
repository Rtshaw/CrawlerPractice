"""Compatibility launcher for the authenticated OTP relay in main.py."""

import os

import uvicorn

from main import app


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("OTP_HOST", "127.0.0.1"), port=int(os.environ.get("OTP_PORT", "8000")))
