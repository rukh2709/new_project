import os
import re

class ChunkStreamer:
    def __init__(self, loader, output_dir="stream_chunks"):
        self.loader = loader
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.embedded_cache = {}

    def stream_irn_chunk(self, irn_id: str) -> str:
        self.embedded_cache = {}
        chunk_lines = self._embed(irn_id, parent="ROOT")
        chunk_text = "\n".join(chunk_lines).strip()

        chunk_file_path = os.path.join(self.output_dir, f"{irn_id}.txt")
        with open(chunk_file_path, "w", encoding="utf-8") as f:
            f.write(chunk_text + "\n")

        return chunk_file_path

    def _embed(self, component_id: str, parent: str):
        content = self.loader.get(component_id)
        output = []
        for line in content.splitlines():
            match = re.match(r"USE\s+([A-Z]{3}\d{5})", line.strip())
            if match:
                child_id = match.group(1)
                if child_id in self.embedded_cache:
                    output.append(f"# Embedded {child_id} (skipped)")
                    continue
                self.embedded_cache[child_id] = True
                output.append(f"# Start of embedded: {child_id}")
                embedded = self._embed(child_id, parent=component_id)
                output.extend(embedded)
                output.append(f"# End of embedded: {child_id}")
            else:
                output.append(line)
        return output
