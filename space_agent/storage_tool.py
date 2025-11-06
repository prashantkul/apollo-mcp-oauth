"""Storage tool for saving conversations."""
import os
from google.cloud import storage
from datetime import datetime

def get_storage_bucket():
    """Get storage bucket from environment variables."""
    return os.getenv("STORAGE_BUCKET")

def save_conversation(conversation: str) -> str:
    """Saves the conversation to a GCS bucket.

    Args:
        conversation: The conversation to save.

    Returns:
        The path to the saved conversation.
    """
    storage_bucket = get_storage_bucket()
    if not storage_bucket:
        return "Error: STORAGE_BUCKET environment variable not set."

    storage_client = storage.Client()
    bucket = storage_client.bucket(storage_bucket)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    blob = bucket.blob(f"conversation-{timestamp}.txt")

    blob.upload_from_string(conversation)

    return f"Conversation saved to gs://{storage_bucket}/conversation-{timestamp}.txt"