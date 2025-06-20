from component_loader import ComponentLoader
from chunk_streamer import ChunkStreamer

def main():
    component_dir = "components"
    output_dir = "stream_chunks"

    loader = ComponentLoader(component_dir)
    streamer = ChunkStreamer(loader, output_dir)

    entry_irns = loader.detect_entry_irns()
    print(f"Detected Entry IRNs: {entry_irns}")

    for irn in entry_irns:
        streamer.process_irn(irn)

if __name__ == "__main__":
    main()
