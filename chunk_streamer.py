import os
import re

class ChunkStreamer:
    def __init__(self, loader, output_dir="stream_chunks"):
        self.loader = loader
        self.output_dir = output_dir
        self.embedded_cache = set()
        self.call_tree = {}
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    def embed(self, text, parent):
        output = []
        lines = text.splitlines()

        for line in lines:
            match = re.match(r"USE\s+([A-Z]{3}\d{5})", line.strip())
            if match:
                comp_id = match.group(1)
                if parent not in self.call_tree:
                    self.call_tree[parent] = []
                self.call_tree[parent].append(comp_id)

                if comp_id in self.embedded_cache:
                    output.append(f"# Embedded {comp_id} [Skipped]")
                    continue

                self.embedded_cache.add(comp_id)
                content = self.loader.read_component(comp_id)
                embedded = self.embed(content, parent=comp_id)
                output.append(f"# Start: {comp_id}\n{embedded}\n# End: {comp_id}")
            else:
                output.append(line)
        return "\n".join(output)

    def process_irn(self, irn_id):
        self.embedded_cache.clear()
        self.call_tree.clear()

        content = self.loader.read_component(irn_id)
        self.embedded_cache.add(irn_id)
        full_chunk = self.embed(content, parent=irn_id)

        chunk_path = os.path.join(self.output_dir, f"{irn_id}_chunk.txt")
        with open(chunk_path, "w", encoding="utf-8") as f:
            for line in full_chunk.splitlines():
                f.write(line + "\n")
        print(f"[✓] Chunk saved: {chunk_path}")
        return chunk_path
