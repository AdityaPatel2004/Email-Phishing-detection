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
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Retrieve the API key from the environment
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    raise ValueError("API key not found. Please set it in the .env file.")

# Try importing validators with fallback
try:
    import validators
except ImportError:
    validators = None
    logging.warning("The 'validators' library is not installed. Link validation will be skipped.")

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Update API configuration
API_KEY = "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"  # Replace with your OpenAI API key
API_URL = "https://api.openai.com/v1/chat/completions"  

# Update model configuration
MODEL_NAME = "gpt-3.5-turbo"  # or "gpt-4" if you have access

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
    risk_assessment: str
    error: Optional[str] = None
    link_scan_results: Optional[dict] = None  # Add this field to include link scanning results

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

def validate_payload(data: dict) -> bool:
    """Validate the payload structure before sending it to OpenAI's API."""
    if not isinstance(data, dict):
        logging.error("Payload must be a dictionary.")
        return False

    if "model" not in data or "messages" not in data:
        logging.error("Payload must contain 'model' and 'messages' fields.")
        return False

    if not isinstance(data["messages"], list) or not all(isinstance(msg, dict) for msg in data["messages"]):
        logging.error("'messages' must be a list of dictionaries.")
        return False

    for msg in data["messages"]:
        if "role" not in msg or "content" not in msg:
            logging.error("Each message must contain 'role' and 'content' fields.")
            return False

    return True

def validate_response(response: dict) -> Optional[str]:
    """Validate the structure of the API response."""
    if not isinstance(response, dict):
        return "Response must be a dictionary."

    if "choices" not in response or not isinstance(response["choices"], list):
        return "Response must contain a 'choices' field with a list."

    if not response["choices"]:
        return "The 'choices' list is empty."

    if "message" not in response["choices"][0] or "content" not in response["choices"][0]["message"]:
        return "The first choice must contain a 'message' field with 'content'."

    return None

def extract_links(body: str) -> list:
    """Extract all URLs from the email body."""
    return re.findall(r'(https?://\S+)', body)

def scan_links(links: list) -> dict:
    """Scan links for potential risks."""
    scanned_results = {}
    for link in links:
        if validators and validators.url(link):
            scanned_results[link] = "SAFE"
        else:
            scanned_results[link] = "INVALID" if validators else "UNKNOWN"
    return scanned_results

# Update the data configuration in summarize_email function
@app.post("/summarize", response_model=APIResponse)
async def summarize_email(email: EmailRequest):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    # Enhanced prompt with stricter format requirements
    data = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": """You are an email security analyzer. Analyze emails and respond EXACTLY in this format with no additional text:
SUMMARY: Brief one-line description of email content
RISK_LEVEL: LOW|MEDIUM|HIGH
RISK_DETAILS: One-sentence explanation of risk assessment"""
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
        "temperature": 0.3,
        "max_tokens": 150
    }
    # Validate payload
    if not validate_payload(data):
        return APIResponse(
            summary="",
            status="error",
            risk_assessment="",
            error="Invalid payload structure."
        )
    try:
        # Extract and scan links
        links = extract_links(email.body)
        link_scan_results = scan_links(links)
        logging.debug(f"Link scan results: {link_scan_results}")

        # Send request to OpenAI API
        response = session.post(
            API_URL,
            json=data,
            headers=headers,
            timeout=(5.0, 60.0)  # (connect timeout, read timeout)
        )

        if response.status_code == 200:
            result = response.json()
            # Validate response structure
            error = validate_response(result)
            if error:
                return APIResponse(
                    summary="",
                    status="error",
                    risk_assessment="",
                    error=error
                )

            # Process and clean the response
            raw_content = result["choices"][0]["message"]["content"].strip()
            logging.debug(f"Raw API response: {raw_content}")
            content = clean_response(raw_content)
            logging.debug(f"Cleaned response: {content}")

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

            # Include link scan results in the response
            return APIResponse(
                summary=parsed_data["SUMMARY:"],
                status="success",
                risk_assessment=f"{risk_level} - {parsed_data['RISK_DETAILS:']}",
                error=None,
                link_scan_results=link_scan_results
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


