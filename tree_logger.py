import os
from typing import Dict, List

def log_call_tree(call_tree: Dict[str, List[str]], output_path: str = "component_tree.log") -> None:
    """
    Logs the component call hierarchy tree into a file in a readable format.

    Args:
        call_tree (Dict[str, List[str]]): A dictionary representing the component call hierarchy.
        output_path (str): Path to the output log file.
    """

    def walk_tree(node, prefix=""):
        lines = [f"{prefix}{node}"]
        children = call_tree.get(node, [])
        for i, child in enumerate(children):
            connector = "└── " if i == len(children) - 1 else "├── "
            next_prefix = prefix + ("    " if i == len(children) - 1 else "│   ")
            lines.extend(walk_tree(child, next_prefix))
        return lines

    # Detect roots: nodes that are not called by any other node
    all_nodes = set(call_tree.keys())
    called_nodes = set(child for children in call_tree.values() for child in children)
    roots = all_nodes - called_nodes

    all_lines = []
    for root in sorted(roots):
        all_lines.extend(walk_tree(root))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_lines))
