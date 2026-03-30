import streamlit as st
import boto3
import json
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="AFLD - Agentic Audit", layout="wide")
st.title("🕵️‍♂️ Autonomous Financial Leak Detector")
st.subheader("Real-Time AI Auditing via Amazon Bedrock")

# Sidebar para inyectar datos
with st.sidebar:
    st.header("Simulate Transaction")
    amount = st.number_input("Amount ($)", value=150.0)
    category = st.selectbox("Category", ["Software", "Electronics", "Travel", "Consulting"])
    if st.button("🚀 Send to AWS"):
        # Aquí llamarías a tu script de inyección que ya hicimos
        st.success(f"Transaction of ${amount} sent to S3!")

# Main Panel: Resultados del Agente
st.write("### Recent Audit Reports (from S3)")
# Aquí el script lee el bucket 'audit-reports' y muestra los JSON formateados