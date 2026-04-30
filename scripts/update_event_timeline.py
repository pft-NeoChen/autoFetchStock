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
    
    storage = DataStorage(config.data_dir)
    processor = NewsProcessor(config, storage)
    
    print("Generating News Event Timeline... (This might take a minute)")
    try:
        event_file = processor.build_event_timeline()
        if event_file and event_file.clusters:
            print(f"Success! Generated timeline with {len(event_file.clusters)} events.")
        else:
            print("Finished, but no events were generated or the timeline is empty.")
    except Exception as e:
        print(f"Failed to generate event timeline: {e}")

if __name__ == "__main__":
    main()
