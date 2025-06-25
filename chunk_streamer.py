# chunk_streamer.py (updated _embed_all_nested using correct USE replacement logic)
import os
import re
import logging
from component_loader import ComponentLoader

logger = logging.getLogger(__name__)

class ChunkStreamer:
    def __init__(self, loader: ComponentLoader, output_dir: str):
        self.loader = loader
        self.output_dir = output_dir
        self.visited_irns = set()
        self.call_tree = {}

    def stream_irn(self, irn_id: str):
        logger.info(f"📦 Starting chunking for IRN: {irn_id}")
        if irn_id in self.visited_irns:
            logger.info(f"🔁 IRN {irn_id} already processed. Skipping.")
            return None

        self.visited_irns.add(irn_id)
        try:
            irn_text = self.loader.get(irn_id)
            content_lines = [f"# Start of IRN: {irn_id}"]
            content_lines.extend(self._embed_all_nested(irn_text, parent=irn_id))
            content_lines.append(f"# End of IRN: {irn_id}")

            chunk_path = os.path.join(self.output_dir, f"{irn_id}.txt")
            with open(chunk_path, "w", encoding="utf-8") as f:
                f.write("\n".join(content_lines))

            logger.info(f"✅ Chunk created for IRN {irn_id}: {chunk_path}")
            return chunk_path

        except Exception as e:
            logger.error(f"❌ Failed to create chunk for {irn_id}: {str(e)}")
            return None

    def _embed_all_nested(self, text: str, parent: str, visited=None):
        if visited is None:
            visited = set()
        output = []

        lines = text.splitlines()
        for line in lines:
            match = re.match(r"^\s*USE\s+((mrn|trn|prn|crn|drn|srn|irr|mrr|irn)\d{5}(?:_[a-zA-Z0-9_]+)?)", line.strip(), re.IGNORECASE)
            if match:
                child_id = match.group(1).upper()
                self._add_to_call_tree(parent, child_id)

                if child_id in visited:
                    output.append(f"# Start of {child_id}")
                    output.append(f"# [Skipped duplicate: {child_id}]")
                    output.append(f"# End of {child_id}")
                    continue

                visited.add(child_id)
                try:
                    comp_text = self.loader.get(child_id)
                    output.append(f"# Start of {child_id}")
                    embedded_block = self._embed_all_nested(comp_text, parent=child_id, visited=visited)
                    output.extend(embedded_block)
                    output.append(f"# End of {child_id}")

                    if child_id.lower().startswith("irn") and child_id not in self.visited_irns:
                        logger.info(f"📌 Found nested IRN {child_id} — will generate separate chunk")
                        self.stream_irn(child_id)
                        output.append(f"# [Nested IRN {child_id} streamed separately]")

                except Exception as e:
                    output.append(f"# Start of {child_id}")
                    output.append(f"# [Missing component: {child_id}]")
                    output.append(f"# End of {child_id}")
                    logger.warning(f"Could not embed {child_id}: {e}")
            else:
                output.append(line)

        return output

    def _add_to_call_tree(self, parent, child):
        if parent not in self.call_tree:
            self.call_tree[parent] = []
        if child not in self.call_tree[parent]:
            self.call_tree[parent].append(child)
