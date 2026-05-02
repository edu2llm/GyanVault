import hashlib
import re


def get_unique_file_id(file_path: str) -> str:
    return hashlib.md5(file_path.encode()).hexdigest()[:10]


def sanitize_latex_in_json(json_str: str) -> str:
    json_str = re.sub(r"(?<!\\)\\([a-zA-Z]+)", r"\\\\\1", json_str)
    json_str = re.sub(r"(?<!\\)\\([{}[\]])", r"\\\\\1", json_str)
    json_str = re.sub(r"(?<!\\)\\([_^-])", r"\\\\\1", json_str)
    return json_str
