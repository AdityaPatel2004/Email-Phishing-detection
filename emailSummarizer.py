import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import logging
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# DeepSeek API configuration
API_KEY = "sk-ed3a28f399e5411f8335a84558158c25"  # Replace with your DeepSeek API key
API_URL = "https://api.deepseek.com/v1/summarize"

app = FastAPI()

# Add CORS middleware to allow requests from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class EmailRequest(BaseModel):
    subject: str
    sender: str
    recipient: str
    body: str

class APIResponse(BaseModel):
    summary: str
    status: str
    error: Optional[str] = None

@app.post("/summarize", response_model=APIResponse)
async def summarize_email(request: EmailRequest):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    prompt = f"Summarize the following email:\nFrom: {request.sender}\nTo: {request.recipient}\nSubject: {request.subject}\n\n{request.body}"

    data = {
        "prompt": prompt,
        "max_tokens": 256,
        "temperature": 0.7,
        "top_p": 0.9
    }

    try:
        response = requests.post(API_URL, json=data, headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        summary = result.get("summary", "").strip()
        
        if not summary:
            return APIResponse(summary="", status="error", error="No summary generated")

        return APIResponse(summary=summary, status="success", error=None)

    except requests.exceptions.RequestException as e:
        error_message = f"API request failed: {str(e)}"
        logging.error(error_message)
        return APIResponse(summary="", status="error", error=error_message)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
