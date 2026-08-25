"""Production entry point: uvicorn server:app"""
from engine.app import create_app

app = create_app()
