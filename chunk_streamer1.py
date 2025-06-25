import os
import re
import logging
from component_loader import ComponentLoader

logger = logging.getLogger(__name__)

class ChunkStreamer:
    def __init__(self, loader: ComponentLoader, output_dir: str):
        self.loader = loader
        self.output_dir = output_dir
        self.visited_irns = set()  # Prevent redundant IRN chunks
        self.call_tree = {}  # Track call relationships

    def stream_irn(self, irn_id: str):
        logger.info(f"📦 Starting chunking for IRN: {irn_id}")
        if irn_id in self.visited_irns:
            logger.info(f"🔁 IRN {irn_id} already processed. Skipping.")
            return None

        self.visited_irns.add(irn_id)
        try:
            irn_text = self.loader.get(irn_id)
            content_lines = [f"# Start of IRN: {irn_id}", irn_text.strip()]
            mrn_ids = self._extract_called_components(irn_text, ['mrn'])

            self.call_tree[irn_id] = []

            for mrn_id in mrn_ids:
                self.call_tree[irn_id].append(mrn_id)
                mrn_text = self.loader.get(mrn_id)
                content_lines.append(f"# Start of MRN: {mrn_id}")
                content_lines.append(mrn_text.strip())

                nested_output = self._embed_all_nested(mrn_text, parent=mrn_id)
                content_lines.extend(nested_output)

                content_lines.append(f"# End of MRN: {mrn_id}")

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
        match = re.match(r"^(\s*)USE\s+((mrn|trn|prn|crn|drn|srn|irr|mrr|irn)\d{5}(?:_[a-zA-Z0-9_]+)?)", line, re.IGNORECASE)
        if match:
            indent = match.group(1)
            child_id = match.group(2).upper()

            self._add_to_call_tree(parent, child_id)

            # Skip this line + all lines that are WHICH IMPORTS/EXPORTS (immediate indented)
            i += 1
            while i < len(lines) and re.match(r"^\s*(WHICH IMPORTS|WHICH EXPORTS|FROM|TO|Entity|Work View)", lines[i], re.IGNORECASE):
                i += 1

            if child_id in visited:
                output.append(f"{indent}# [Skipped duplicate: {child_id}]")
                continue
            visited.add(child_id)

            try:
                comp_text = self.loader.get(child_id)
                comp_lines = comp_text.strip().splitlines()

                output.append(f"{indent}# Start of {child_id}")
                output.extend(f"{indent}{l}" for l in comp_lines)
                output.append(f"{indent}# End of {child_id}")

                if child_id.lower().startswith("irn") and child_id not in self.visited_irns:
                    logger.info(f"📎 Found nested IRN {child_id} — will generate separate chunk")
                    self.stream_irn(child_id)
                    output.append(f"{indent}# [Nested IRN {child_id} streamed separately]")
                else:
                    nested_output = self._embed_all_nested(comp_text, parent=child_id, visited=visited)
                    output.extend(f"{indent}{l}" for l in nested_output)

            except FileNotFoundError:
                output.append(f"{indent}# [Missing component: {child_id}]")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load {child_id}: {e}")
                output.append(f"{indent}# [Error loading {child_id}: {str(e)}]")
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
