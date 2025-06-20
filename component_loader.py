import os
import re

class ComponentLoader:
    def __init__(self, component_dir):
        self.component_dir = component_dir

    def get_all_irns(self):
        return {
            fname.replace(".txt", "")
            for fname in os.listdir(self.component_dir)
            if fname.startswith("IRN") and fname.endswith(".txt")
        }

    def get_used_irns(self):
        used = set()
        for fname in os.listdir(self.component_dir):
            if not fname.endswith(".txt"):
                continue
            path = os.path.join(self.component_dir, fname)
            with open(path, "r") as f:
                content = f.read()
                used.update(re.findall(r"USE\s+(IRN\d{5})", content))
        return used

    def detect_entry_irns(self):
        all_irns = self.get_all_irns()
        used_irns = self.get_used_irns()
        return all_irns - used_irns

    def read_component(self, comp_id):
        filename = f"{comp_id[:3]}{comp_id[3:]}.txt"
        path = os.path.join(self.component_dir, filename)
        if not os.path.isfile(path):
            return f"# [Missing component: {comp_id}]"
        with open(path, "r") as f:
            return f.read().strip()
