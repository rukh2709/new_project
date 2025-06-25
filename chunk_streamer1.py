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
        pattern = re.compile(rf"^(?P<indent>\s*)USE\s+((?P<id>({'mrn|trn|drn|prn|srn|crn|irr|mrr|irn'})\d{{5}}(?:_[a-zA-Z0-9_]+)?))", re.IGNORECASE | re.MULTILINE)

        last_pos = 0
        for match in pattern.finditer(text):
            start, end = match.span()
            indent = match.group("indent")
            child_id = match.group("id").upper()

            # Append everything before the USE line
            output.append(text[last_pos:start].rstrip())

            if child_id in visited:
                output.append(f"{indent}# [Skipped duplicate: {child_id}]")
                last_pos = end
                continue

            visited.add(child_id)
            self._add_to_call_tree(parent, child_id)

            try:
                comp_text = self.loader.get(child_id)
                comp_lines = comp_text.strip().splitlines()

                output.append(f"{indent}# Start of {child_id}")
                output.extend(f"{indent}{line}" for line in comp_lines)
                output.append(f"{indent}# End of {child_id}")

                if child_id.lower().startswith("irn") and child_id not in self.visited_irns:
                    logger.info(f"📎 Found nested IRN {child_id} — will generate separate chunk")
                    self.stream_irn(child_id)
                    output.append(f"{indent}# [Nested IRN {child_id} streamed separately]")
                else:
                    nested_output = self._embed_all_nested(comp_text, parent=child_id, visited=visited)
                    output.extend(f"{indent}{line}" for line in nested_output)

            except FileNotFoundError:
                output.append(f"{indent}# [Missing component: {child_id}]")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load {child_id}: {e}")
                output.append(f"{indent}# [Error loading {child_id}: {str(e)}]")

            last_pos = end

        # Add any remaining text after the last USE
        output.append(text[last_pos:].rstrip())
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
