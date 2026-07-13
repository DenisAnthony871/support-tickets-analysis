import json
import streamlit as st
from src.triage import triage_ticket
from src.account_summary import summarize_account

st.set_page_config(page_title="TAM AI Assistant", page_icon="⚙️", layout="wide")

st.title("TAM AI Assistant")
st.markdown("A thin UI demo for Technical Account Managers to interact with AI models.")

tab1, tab2 = st.tabs(["Ticket Triage", "Account Summary"])

with tab1:
    st.header("Intelligent Ticket Triage")
    st.markdown("Paste a customer support ticket below to categorize it and generate a draft response.")
    
    ticket_text = st.text_area("Ticket Content", height=200, placeholder="Subject: ...\nBody: ...")
    
    if st.button("Triage Ticket", type="primary"):
        if not ticket_text.strip():
            st.error("Please enter a ticket to triage.")
        else:
            with st.spinner("Analyzing ticket..."):
                placeholder = st.empty()
                stream = triage_ticket(ticket_text, stream=True)
                
                full_json = ""
                for chunk in stream:
                    full_json += chunk
                    # Display the streaming JSON nicely formatted in a code block
                    placeholder.code(full_json, language="json")
                
                try:
                    result = json.loads(full_json)
                    placeholder.empty() # Clear the raw JSON
                    
                    st.success("Triage Complete!")
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Product Area", result.get("product_area"))
                    col2.metric("Issue Category", result.get("issue_category"))
                    
                    urgency = result.get("urgency_tier")
                    col3.metric("Urgency", urgency)
                    
                    st.markdown(f"**Recommended Team:** {result.get('recommended_team')}")
                    st.markdown(f"**Reasoning:** {result.get('reasoning')}")
                    
                    st.subheader("Draft Response")
                    st.info(result.get("draft_response"))
                    
                    if result.get("matched_kb_doc"):
                        st.markdown(f"**Matched KB:** `{result.get('matched_kb_doc')}`")
                        
                except Exception as e:
                    st.error(f"Failed to parse structured output: {e}")

with tab2:
    st.header("Account Health Summary")
    st.markdown("Select an account to generate a health briefing based on the last 90 days of tickets.")
    
    # Dynamically load valid accounts
    try:
        with open("starter-repo/data/accounts.json", encoding="utf-8") as f:
            account_data = json.load(f)
            accounts = [a["account_id"] for a in account_data]
    except Exception:
        # Fallback to known valid accounts if file load fails
        accounts = ["ACC-3336", "ACC-3033", "ACC-8113", "ACC-7893", "ACC-4654"]
        
    selected_account = st.selectbox("Select Account", accounts)
    
    if st.button("Generate Summary", type="primary"):
        with st.spinner(f"Analyzing last 90 days for {selected_account}..."):
            placeholder = st.empty()
            stream = summarize_account(selected_account, stream=True)
            
            full_json = ""
            for chunk in stream:
                full_json += chunk
                placeholder.code(full_json, language="json")
                
            try:
                result = json.loads(full_json)
                placeholder.empty()
                
                st.success("Summary Generated!")
                st.subheader("Executive Summary")
                st.write(result.get("executive_summary"))
                
                st.subheader("Talking Points")
                for pt in result.get("talking_points", []):
                    st.markdown(f"- {pt}")
                    
                st.subheader("Risks & Flags")
                flags = result.get("risks_and_flags", [])
                if flags:
                    for flag in flags:
                        with st.expander(f"Flagged Ticket: {flag.get('ticket_id')} - {flag.get('reason')}"):
                            st.markdown(f"**Quote:**\n> {flag.get('verbatim_quote')}")
                else:
                    st.success("No critical risks flagged.")
                    
            except Exception as e:
                st.error(f"Failed to parse structured output: {e}")
