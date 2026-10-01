from fastapi import FastAPI

app = FastAPI(
    title="AI Support Ticket Triage API",
    version="1.0.0",
)


@app.get("/")
def root():
    return {"message": "AI Support Ticket Triage API is running"}