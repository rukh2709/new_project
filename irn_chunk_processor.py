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
        if not os.path.isfile(path):
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
