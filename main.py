import argparse
import os
import logging
from chunk_streamer import ChunkStreamer
from component_loader import ComponentLoader
from bedrock_client import BedrockClient  # ✅ your module
from datetime import datetime

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
    parser = argparse.ArgumentParser(description="Stream IRN chunks and summarize them with Claude")
    parser.add_argument("--component-dir", default="components", help="Directory of COBOL component .txt files")
    parser.add_argument("--chunk-dir", default="stream_chunks", help="Where to save streamed IRN-level chunks")
    parser.add_argument("--region", default="us-east-1", help="AWS Region for Bedrock")
    parser.add_argument("--aws-access-key", help="AWS Access Key")
    parser.add_argument("--aws-secret-key", help="AWS Secret Key")
    parser.add_argument("--model", default="anthropic.claude-3-7-sonnet-20250219-v1:0", help="Claude Model ID")
    args = parser.parse_args()

    os.makedirs(args.chunk_dir, exist_ok=True)

    loader = ComponentLoader(args.component_dir)
    streamer = ChunkStreamer(loader, output_dir=args.chunk_dir)

    bedrock = BedrockClient(
        model_id=args.model,
        region=args.region,
        aws_access_key=args.aws_access_key,
        aws_secret_key=args.aws_secret_key
    )

    entry_irns = loader.detect_entry_irns()
    logger.info(f"🔍 Entry IRNs detected: {entry_irns}")

    for irn_id in entry_irns:
        chunk_path = streamer.stream_irn_chunk(irn_id)

        if not chunk_path or not os.path.exists(chunk_path):
            logger.warning(f"⚠️ No chunk file created for {irn_id}. Skipping.")
            continue

        with open(chunk_path, "r", encoding="utf-8") as f:
            chunk_text = f.read().strip()

        if not chunk_text:
            logger.warning(f"⚠️ Chunk for {irn_id} is empty. Skipping summarization.")
            continue

        logger.info(f"🧠 Sending {irn_id} chunk to Claude for summarization...")

        try:
            system_prompt = "You are an expert in COBOL reverse engineering. Summarize this IRN-level embedded chunk..."
            summary = bedrock.generate_text(prompt=chunk_text, system_prompt=system_prompt)

            summary_path = os.path.join(args.chunk_dir, f"{irn_id}_summary.md")
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(f"# Summary for {irn_id}\n\n")
                f.write(summary.strip())
            logger.info(f"✅ Summary written to {summary_path}")

        except Exception as e:
            logger.error(f"❌ Failed to summarize {irn_id}: {e}")

if __name__ == "__main__":
    main()
