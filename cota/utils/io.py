import os
import re
from pathlib import Path
import yaml
from typing import Text, Any, Union, Dict

DEFAULT_ENCODING = "utf-8"

def read_yaml_from_path(path: Text, encoding: Text = DEFAULT_ENCODING) -> Dict:
    try:
        with open(path, encoding=encoding) as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        raise ValueError(f"File '{path}' does not exist.")