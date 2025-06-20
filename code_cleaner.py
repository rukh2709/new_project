
import os
import re

def extract_and_clean_cagen_code(file_path_for_clean, output_dir):
    try:
        with open(file_path_for_clean, "r", encoding="utf-8") as cob_file:
            lines = cob_file.readlines()

        # Extract lines between "* +..." and "* ---"
        cagen_code_lines = []
        is_cagen_code = False
        for line in lines:
            if re.match(r"^\s*\d+\s*\*\s*\+\-+", line):
                is_cagen_code = True
            if is_cagen_code:
                cagen_code_lines.append(line)
            if re.match(r"^\s*\d+\s*\*\s*\-\-+", line):
                is_cagen_code = False

        # Clean the extracted lines
        cleaned_lines = []
        for i, line in enumerate(cagen_code_lines):
            if i == 0:
                # First line: remove "*  +--"
                cleaned_line = re.sub(r"^\s*\d+\s*\*\s*\+\-+", "", line)
                cleaned_line = re.sub(r"\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}", "", cleaned_line)
            elif re.match(r"^\s*\d+\s*\*\s*\-\-+", line):
                continue  # End marker
            else:
                # Remove line numbers, "*", maintain indentation
                cleaned_line = re.sub(r"^\s*\d+\s*\*\s*", "", line)
                cleaned_line = re.sub(r"[<>]=?", "", cleaned_line)
            cleaned_lines.append(cleaned_line.rstrip())

        # Save cleaned file
        component_name = os.path.splitext(os.path.basename(file_path_for_clean))[0]
        output_file_path = os.path.join(output_dir, f"{component_name}_cleaned.txt")
        with open(output_file_path, "w", encoding="utf-8") as output_file:
            output_file.write("\n".join(cleaned_lines))

        return output_file_path
    except Exception as e:
        return f"Error cleaning file {file_path_for_clean}: {str(e)}"
