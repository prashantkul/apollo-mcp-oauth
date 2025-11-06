#!/bin/bash
# Run the Space Explorer Chatbot UI

echo "🚀 Starting Space Explorer Chatbot UI..."
echo ""

# Check if running in correct directory
if [ ! -f "app.py" ]; then
    echo "❌ Error: app.py not found. Please run this script from the chatbot_ui directory."
    exit 1
fi

# Check if streamlit is installed
if ! command -v streamlit &> /dev/null; then
    echo "⚠️  Streamlit not found. Installing dependencies..."
    pip install -r requirements.txt
fi

# Check Google Cloud authentication
if ! gcloud auth application-default print-access-token &> /dev/null; then
    echo "⚠️  Google Cloud authentication not configured."
    echo "   Run: gcloud auth application-default login"
    echo ""
    read -p "Press Enter to continue anyway (will fail without auth)..."
fi

echo "✅ Starting Streamlit app..."
echo ""
streamlit run app.py
