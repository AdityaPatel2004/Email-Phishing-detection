import os
from fastapi import FastAPI, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import logging
from typing import Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import re

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Update API configuration
API_KEY = ""
API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"  # Update the API URL to include the endpoint

# Add API version and model configuration
API_VERSION = "v1"
MODEL_NAME = "deepseek-ai/deepseek-r1"

# Improved retry strategy
retry_strategy = Retry(
    total=2,              # Increase total retries
    backoff_factor=1,    # More conservative backoff
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST"],
    raise_on_status=True,
    respect_retry_after_header=True
)

# Update session configuration with separate timeouts
session = requests.Session()
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)

app = FastAPI()

# Update CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://localhost:8000"],  # Streamlit default port
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
    risk_assessment: str  # Add risk assessment field
    error: Optional[str] = None

def clean_response(content: str) -> str:
    """Clean the API response by removing thinking markers and normalizing format."""
    # Remove thinking markers and their content
    if '<think>' in content:
        content = content.split('<think>')[-1]  # Take content after last think marker
    
    # Remove any other XML-like tags
    content = re.sub(r'<[^>]+>', '', content)
    
    # Ensure proper line endings
    content = content.replace('\r\n', '\n').strip()
    return content

# Update the data configuration in summarize_email function
@app.post("/summarize", response_model=APIResponse)
async def summarize_email(email: EmailRequest):
    headers = {
        "Authorization": f"Bearer {API_KEY}",  # Add Bearer prefix
        "Content-Type": "application/json",
    }

    # Enhanced prompt with stricter format requirements
    data = {
        "messages": [
            {
                "role": "system",
                "content": """You are an email security analyzer. Analyze emails and respond EXACTLY in this format with no additional text:

SUMMARY: Brief one-line description of email content
RISK_LEVEL: LOW|MEDIUM|HIGH
RISK_DETAILS: One-sentence explanation of risk assessment

Assessment criteria:
- LOW: Standard business communication with no suspicious elements
- MEDIUM: Contains some unusual elements but no immediate threat
- HIGH: Contains multiple red flags or direct security threats"""
            },
            {
                "role": "user",
                "content": f"""Analyze this email based on:
- Sender domain legitimacy
- Urgency/pressure tactics
- Unusual requests
- Links/attachments
- Financial/credential requests

Email details:
SUBJECT: {email.subject}
FROM: {email.sender}
TO: {email.recipient}
BODY: {email.body}"""
            }
        ],
        "model": MODEL_NAME,
        "max_tokens": 150,
        "temperature": 0.1  # Reduced further for more deterministic output
    }

    try:
        # Updated request with separate timeouts
        response = session.post(
            API_URL,
            json=data,
            headers=headers,
            timeout=(5.0, 60.0)  # (connect timeout, read timeout)
        )

        if response.status_code == 200:
            result = response.json()
            raw_content = result["choices"][0]["message"]["content"].strip()
            logging.debug(f"Raw API response: {raw_content}")
            
            # Clean and validate response
            content = clean_response(raw_content)
            logging.debug(f"Cleaned response: {content}")
            
            if not content:
                logging.error("Empty response after cleaning")
                return APIResponse(
                    summary="Error: Empty response",
                    status="error",
                    risk_assessment="UNKNOWN - Empty response",
                    error="API returned empty or invalid response"
                )
            
            # Strict response validation
            required_fields = {"SUMMARY:", "RISK_LEVEL:", "RISK_DETAILS:"}
            if not all(field in content for field in required_fields):
                logging.error(f"Missing required fields in response: {content}")
                return APIResponse(
                    summary="Error: Invalid response format",
                    status="error",
                    risk_assessment="UNKNOWN - Response format error",
                    error="API response missing required fields"
                )
            
            # Enhanced parsing with validation
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            parsed_data = {
                "SUMMARY:": "No summary available",
                "RISK_LEVEL:": "UNKNOWN",
                "RISK_DETAILS:": "No details provided"
            }
            
            for line in lines:
                for field in parsed_data.keys():
                    if line.startswith(field):
                        value = line.replace(field, "").strip()
                        if value:  # Only update if we got a non-empty value
                            parsed_data[field] = value
            
            # Validate risk level format
            risk_level = parsed_data["RISK_LEVEL:"]
            if risk_level not in ["LOW", "MEDIUM", "HIGH", "UNKNOWN"]:
                risk_level = "UNKNOWN"
                logging.warning(f"Invalid risk level received: {risk_level}")
            
            return APIResponse(
                summary=parsed_data["SUMMARY:"],
                status="success",
                risk_assessment=f"{risk_level} - {parsed_data['RISK_DETAILS:']}",
                error=None
            )
                
        else:
            error_message = f"API Error: {response.status_code} - {response.text}"
            logging.error(error_message)
            return APIResponse(
                summary="",
                status="error",
                risk_assessment="",
                error=error_message
            )

    except requests.exceptions.Timeout as e:
        timeout_type = "connection" if isinstance(e, requests.exceptions.ConnectTimeout) else "read"
        error_msg = f"{timeout_type.capitalize()} timeout occurred. Please try again."
        logging.error(f"Request {timeout_type} timeout: {str(e)}")
        return APIResponse(
            summary="",
            status="error",
            risk_assessment="",
            error=error_msg
        )

    except requests.exceptions.RetryError as e:
        logging.error(f"Max retries exceeded: {str(e)}")
        return APIResponse(
            summary="",
            status="error",
            risk_assessment="",
            error="Service temporarily unavailable. Please try again later."
        )

    except Exception as e:
        logging.error(f"Request failed: {str(e)}")
        return APIResponse(
            summary="",
            status="error",
            risk_assessment="",
            error=f"Request failed: {str(e)}"
        )

@app.get("/")
async def read_root():
    return {"message": "Welcome to the Email Summarization API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)  # Change port if necessary


