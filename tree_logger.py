import os

def log_call_tree(call_tree: dict, output_path: str):
    """
    Logs the component call hierarchy from the provided call_tree dictionary.

    Args:
        call_tree (dict): Dictionary of parent -> list of children
        output_path (str): File path to save the component tree log
    """

    def walk_tree(node, prefix=""):
        lines = [f"{prefix}{node}"]
        children = call_tree.get(node, [])
        for i, child in enumerate(children):
            connector = "└── " if i == len(children) - 1 else "├── "
            new_prefix = prefix + ("    " if i == len(children) - 1 else "│   ")
            lines.extend(walk_tree(child, prefix=new_prefix + connector))
        return lines

    # Identify top-level nodes (entry IRNs)
    all_nodes = set(call_tree.keys())
    called_nodes = set(child for children in call_tree.values() for child in children)
    root_nodes = all_nodes - called_nodes

    all_lines = []
    for root in sorted(root_nodes):
        all_lines.extend(walk_tree(root))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_lines))

    print(f"📄 Call tree saved to {output_path}")
