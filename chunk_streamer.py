# chunk_streamer.py (cleaned _embed_all_nested logic to only replace USE line)
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
        i = 0
        while i < len(lines):
            line = lines[i]
            match = re.match(r"^(\s*)USE\s+((mrn|trn|prn|crn|drn|srn|irr|mrr|irn)\d{5}(?:_[a-zA-Z0-9_]+)?)", line.strip(), re.IGNORECASE)
            if match:
                indent = match.group(1)
                child_id = match.group(2).upper()
                self._add_to_call_tree(parent, child_id)

                if child_id in visited:
                    output.append(f"{indent}# [Skipped duplicate: {child_id}]")
                    i += 1
                    continue

                visited.add(child_id)
                try:
                    comp_text = self.loader.get(child_id)
                    comp_lines = comp_text.strip().splitlines()

                    output.append(f"{indent}# Start of {child_id}")
                    output.extend(f"{indent}{l}" for l in comp_lines)
                    output.append(f"{indent}# End of {child_id}")

                    if child_id.lower().startswith("irn") and child_id not in self.visited_irns:
                        logger.info(f"📌 Found nested IRN {child_id} — will generate separate chunk")
                        self.stream_irn(child_id)
                        output.append(f"{indent}# [Nested IRN {child_id} streamed separately]")
                    else:
                        nested_output = self._embed_all_nested(comp_text, parent=child_id, visited=visited)
                        output.extend(f"{indent}{l}" for l in nested_output)

                except Exception as e:
                    output.append(f"{indent}# [Missing component: {child_id}]")
                    logger.warning(f"Could not embed {child_id}: {e}")

                i += 1  # ✅ Only skip the USE line, do not touch lines after it
            else:
                output.append(line)
                i += 1

        return output

    def _extract_called_components(self, text: str, prefixes: list):
        matches = re.findall(
            rf"\bUSE\s+(({ '|'.join(prefixes) })\d{{5}}(?:_[a-zA-Z0-9_]+)?)",
            text,
            flags=re.IGNORECASE
        )
        return [m[0].upper() for m in matches]

    def _add_to_call_tree(self, parent, child):
        if parent not in self.call_tree:
            self.call_tree[parent] = []
        if child not in self.call_tree[parent]:
            self.call_tree[parent].append(child)
