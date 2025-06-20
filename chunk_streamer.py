# component_loader.py
import os
import re

class ComponentLoader:
    def __init__(self, component_dir):
        self.component_dir = component_dir

    def get_component_path(self, component_id):
        filename = f"{component_id[:3]}{component_id[3:]}.txt"
        return os.path.join(self.component_dir, filename)

    def read_component(self, component_id):
        path = self.get_component_path(component_id)
        if not os.path.isfile(path):import os
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

            return None
        with open(path, 'r') as f:
            return f.read()

    def list_irns(self):
        return {
            filename.replace(".txt", "")
            for filename in os.listdir(self.component_dir)
            if filename.startswith("IRN") and filename.endswith(".txt")
        }

    def find_used_irns(self):
        used = set()
        for filename in os.listdir(self.component_dir):
            if not filename.endswith(".txt"):
                continue
            with open(os.path.join(self.component_dir, filename), 'r') as f:
                content = f.read()
                used.update(self.extract_irns(content))
        return used

    @staticmethod
    def extract_irns(text):
        return set(re.findall(r"USE\s+(IRN\d{5})", text))
