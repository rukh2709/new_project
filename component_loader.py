import os
import re

class ComponentLoader:
    def __init__(self, component_dir: str):
        self.component_dir = component_dir
        self.components = self._load_components()

    def _load_components(self):
        components = {}
        for filename in os.listdir(self.component_dir):
            if filename.endswith(".txt"):
                path = os.path.join(self.component_dir, filename)
                with open(path, "r", encoding="utf-8") as f:
                    components[filename[:-4]] = f.read()
        return components

    # def get(self, component_id: str) -> str:
    #     return self.components.get(component_id, f"# [Missing component: {component_id}]")
    def get(self, component_id: str) -> str:
        # Normalize the component ID to its base 8-character prefix (e.g., MRN13381)
        match = re.match(r"^(MRN|TRN|PRN|CRN|DRN|SRN|IRR|MRR|IRN)\d{5}", component_id, re.IGNORECASE)
        if not match:
            raise FileNotFoundError(f"Invalid component ID: {component_id}")
        base_id = match.group(0).upper()
        file_path = os.path.join(self.component_dir, f"{base_id}.txt")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Component file not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()


    def detect_entry_irns(self):
        all_irns = {cid for cid in self.components if cid.startswith("IRN")}
        called_irns = set()

        for content in self.components.values():
            matches = re.findall(r"USE\s+(IRN\d{5})", content)
            called_irns.update(matches)

        entry_irns = all_irns - called_irns
        return sorted(entry_irns)
