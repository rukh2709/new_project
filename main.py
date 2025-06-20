import argparse
import os
import logging

from component_loader import ComponentLoader
from chunk_streamer import ChunkStreamer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("main.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Generate IRN-level chunks with streaming")
    parser.add_argument("--component-dir", default="components", help="Directory containing COBOL component .txt files")
    parser.add_argument("--chunk-dir", default="stream_chunks", help="Directory to store streamed IRN-level chunks")
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    os.makedirs(args.chunk_dir, exist_ok=True)

    logger.info("Initializing component loader...")
    loader = ComponentLoader(args.component_dir)

    logger.info("Detecting entry IRNs...")
    entry_irns = loader.detect_entry_irns()
    logger.info(f"Found entry IRNs: {entry_irns}")

    logger.info("Starting chunk streaming...")
    streamer = ChunkStreamer(loader, output_dir=args.chunk_dir)
    for irn_id in entry_irns:
        streamer.stream_irn(irn_id)

    logger.info("✅ All chunks generated.")

if __name__ == "__main__":
    main()
