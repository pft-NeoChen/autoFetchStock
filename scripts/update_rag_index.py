import os
import sys
import logging

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.config import AppConfig, setup_logging
from src.storage.data_storage import DataStorage
from src.news.news_processor import NewsProcessor

def main():
    # Load environment variables
    load_dotenv("config.env")
    
    # Initialize configuration and dependencies
    config = AppConfig()
    setup_logging(config)
    
    if not config.news_rag_enabled:
        print("Error: NEWS_RAG_ENABLED is not set to true in config.env")
        return
        
    storage = DataStorage(config.data_dir)
    processor = NewsProcessor(config, storage)
    
    print("Building/Updating RAG index... (This might take a few minutes depending on the number of articles)")
    count = processor.update_rag_index()
    print(f"Success! Added {count} new articles to the RAG index.")

if __name__ == "__main__":
    main()
