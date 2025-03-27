import streamlit as st
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime

# Configure page
st.set_page_config(
    page_title="Email Summarizer",
    page_icon="📧",
    layout="wide"
)

# Initialize session state for history
if 'summary_history' not in st.session_state:
    st.session_state.summary_history = []

# Update retry configuration
def create_request_session():
    retry_strategy = Retry(
        total=1,          # Reduced to 1 retry
        backoff_factor=0.5, # Reduced backoff time
        status_forcelist=[429, 500, 502, 503, 504],
        connect=1,        # Reduced connect retries
        read=1           # Reduced read retries
    )
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=retry_strategy))
    session.mount("https://", HTTPAdapter(max_retries=retry_strategy))
    return session

def clean_summary(summary: str) -> str:
    """Clean up the summary by removing the thinking process"""
    if "<think>" in summary:
        # Remove everything between <think> and the next newline
        summary = summary.split("<think>")[-1].strip()
    return summary.strip()

def summarize_email(subject, sender, recipient, body):
    url = "http://localhost:8000/summarize"
    payload = {
        "subject": subject,
        "sender": sender,
        "recipient": recipient,
        "body": body
    }
    
    try:
        session = create_request_session()
        response = session.post(url, json=payload, timeout=20)  # Reduced timeout to 20 seconds
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "success":
                # Clean the summary before returning
                if result.get("summary"):
                    result["summary"] = clean_summary(result["summary"])
                return result
            else:
                st.error(f"API Error: {result.get('error', 'Unknown error')}")
                return result
        else:
            st.error(f"API Error: {response.status_code}")
            return {
                "status": "error",
                "error": f"API returned {response.status_code}",
                "summary": ""
            }
    except requests.exceptions.Timeout:
        st.error("Request timed out. Please try again.")
        return {
            "status": "error",
            "error": "Request timed out",
            "summary": ""
        }
    except Exception as e:
        st.error(f"Connection Error: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "summary": ""
        }

# UI Components
st.title("📧 Email Summarizer")

# Sidebar with history
with st.sidebar:
    st.title("History")
    if st.session_state.summary_history:
        for item in st.session_state.summary_history:
            risk_level = item.get('risk_assessment', '').split(" - ")[0]
            risk_color = {
                "LOW": "green",
                "MEDIUM": "orange",
                "HIGH": "red"
            }.get(risk_level, "gray")
            
            with st.expander(f"{item['timestamp']} - From: {item['sender']}"):
                st.write(f"**Subject:** {item['subject']}")
                st.write(f"**Summary:**\n{item['summary']}")
                st.markdown(f"**Risk Assessment:**\n:{risk_color}[{item.get('risk_assessment', 'N/A')}]")
                st.write(f"**Original Email:**\n{item['body'][:100]}...")
    else:
        st.info("No history yet. Start summarizing emails!")

# Main content
col1, col2 = st.columns(2)

with col1:
    sender = st.text_input("From:", placeholder="sender@example.com")
    subject = st.text_input("Subject:", placeholder="Enter email subject")

with col2:
    recipient = st.text_input("To:", placeholder="recipient@example.com")

body = st.text_area("Email Content:", height=200, placeholder="Paste your email content here...")

if st.button("Summarize Email", type="primary"):
    if not all([subject, sender, recipient, body]):
        st.error("Please fill in all fields")
    else:
        with st.spinner("Generating summary..."):
            result = summarize_email(subject, sender, recipient, body)
            
            if result.get("status") == "success":
                st.success("Summary generated successfully!")
                
                # Get risk level for color coding
                risk_assessment = result.get("risk_assessment", "")
                risk_level = risk_assessment.split(" - ")[0] if " - " in risk_assessment else ""
                risk_color = {
                    "LOW": "green",
                    "MEDIUM": "orange",
                    "HIGH": "red"
                }.get(risk_level, "gray")
                
                # Display summary in a prominent box
                st.markdown("---")
                st.markdown("### 📝 Generated Summary")
                summary = result.get("summary", "No summary generated")
                with st.container():
                    st.markdown(f"""
                    **Email Details:**
                    - **From:** {sender}
                    - **To:** {recipient}
                    - **Subject:** {subject}
                    
                    **Summary:**
                    > {summary}
                    
                    **Risk Assessment:**
                    > :{risk_color}[{risk_assessment}]
                    """)

                # Display scanned links and their statuses
                scanned_links = result.get("link_scan_results", {})
                if scanned_links:
                    st.markdown("### 🔗 Link Scan Results")
                    for link, status in scanned_links.items():
                        status_color = "green" if status == "SAFE" else "red"
                        st.markdown(f"- [{link}]({link}) :{status_color}[{status}]")
                
                st.markdown("---")
                
                # Add to history with risk assessment
                st.session_state.summary_history.append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "sender": sender,
                    "subject": subject,
                    "body": body,
                    "summary": summary,
                    "risk_assessment": risk_assessment,
                    "link_scan_results": scanned_links
                })
            else:
                st.error(f"Failed to generate summary: {result.get('error', 'Unknown error')}")