import streamlit as st
from dotenv import load_dotenv

from agents.orchestrator import Orchestrator

load_dotenv()

st.set_page_config(page_title="Betting Assistant", page_icon="🎲")
st.title("Betting Assistant")

if "orchestrator" not in st.session_state:
    st.session_state.orchestrator = Orchestrator()

prompt = st.text_area("Ask something")

if st.button("Submit") and prompt:
    with st.spinner("Thinking..."):
        answer = st.session_state.orchestrator.run(prompt)
    st.write(answer)
