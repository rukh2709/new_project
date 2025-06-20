import argparse
import os
import logging
import tempfile

from component_loader import ComponentLoader
from chunk_streamer import ChunkStreamer
from bedrock_client import BedrockClient

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Claude system prompt
SYSTEM_PROMPT = (
    "You are a COBOL reverse engineering assistant. Analyze legacy components "
    "with embedded structures and generate detailed, clear documentation. Explain "
    "the logic, purpose, flow, and relationships of all included components. Use headings, "
    "bullets, and technical tone suitable for developers."
)

def summarize_chunk(chunk_path, claude: BedrockClient, output_dir: str):
    with open(chunk_path, "r", encoding="utf-8") as f:
        content = f.read()

    prompt = f"Analyze the following COBOL component and its embedded components:\n\n{content}"
    try:
        summary = claude.generate_text(prompt, system_prompt=SYSTEM_PROMPT)
        irn_id = os.path.splitext(os.path.basename(chunk_path))[0]
        out_file = os.path.join(output_dir, f"{irn_id}_summary.md")
        with open(out_file, "w", encoding="utf-8") as out:
            out.write(summary)
        logger.info(f"✅ Saved summary: {out_file}")
    except Exception as e:
        logger.error(f"❌ Failed to summarize {chunk_path}: {e}")

def main():
    parser = argparse.ArgumentParser(description="IRN-level chunk expansion and summarization")
    parser.add_argument("--component-dir", default="components", help="Directory with COBOL .txt files")
    parser.add_argument("--output-dir", default="summaries", help="Directory to save Claude summaries")
    parser.add_argument("--region", default="us-east-1", help="AWS region (default: us-east-1)")
    parser.add_argument("--model", default="anthropic.claude-3-7-sonnet-20250219-v1:0", help="Claude model ID")
    parser.add_argument("--aws-access-key", help="AWS Access Key")
    parser.add_argument("--aws-secret-key", help="AWS Secret Key")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    loader = ComponentLoader(args.component_dir)
    streamer = ChunkStreamer(loader)

    entry_irns = loader.detect_entry_irns()
    logger.info(f"Found entry IRNs: {entry_irns}")

    claude = BedrockClient(
        model_id=args.model,
        region=args.region,
        aws_access_key=args.aws_access_key,
        aws_secret_key=args.aws_secret_key
    )

    for irn_id in entry_irns:
        chunk_path = streamer.stream_irn_chunk(irn_id)
        summarize_chunk(chunk_path, claude, args.output_dir)
        os.remove(chunk_path)  # 🧹 Clean up temp chunk file
        logger.info(f"🗑️ Deleted temp chunk: {chunk_path}")

    logger.info("✅ All summaries generated.")

if __name__ == "__main__":
    main()
