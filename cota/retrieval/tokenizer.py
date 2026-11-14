"""CJK-aware tokenizer: Latin words plus Chinese characters and bigrams."""
import re
import unicodedata


def tokens(text):
    """Latin words plus Chinese characters/bigrams, with no tokenizer download."""
    parts = re.findall(r'[a-z0-9_]+|[㐀-鿿]+', unicodedata.normalize('NFKC', text).casefold())
    result = []
    for part in parts:
        if '㐀' <= part[0] <= '鿿':
            result.extend(part)
            result.extend(part[i:i + 2] for i in range(len(part) - 1))
        else:
            result.append(part)
    return result
