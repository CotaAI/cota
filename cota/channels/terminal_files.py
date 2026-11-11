"""Bounded attachment presentation for a local terminal; no model/tool calls."""
import asyncio
from collections import OrderedDict
from pathlib import Path

_TEXT = {'.txt', '.md', '.markdown', '.rst', '.json', '.yaml', '.yml', '.csv', '.tsv', '.log'}
_VIEWABLE = _TEXT | {'.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp',
                     '.docx', '.xlsx', '.pptx', '.odt', '.ods', '.odp', '.rtf'}


class TerminalFiles:
    def __init__(self, write):
        self.write = write
        self.entries = OrderedDict()
        self._next = 0

    async def show(self, message, storage):
        for item in message.attachments:
            key = (message.session_id, item['id'])
            number = next((n for n, (sid, ref) in self.entries.items()
                           if (sid, ref['id']) == key), None)
            if number is None:
                self._next += 1
                number = self._next
            self.entries[number] = (message.session_id, dict(item))
            self.entries.move_to_end(number)
            while len(self.entries) > 64:
                self.entries.popitem(last=False)
            self.write(f"File [{number}]: {item['name']} · {item['size']:,} bytes")
            try:
                if storage is None:
                    raise ValueError('未配置附件存储')
                path = await asyncio.to_thread(storage.resolve, message.session_id, item['id'])
                self.write(f'  Path: {path}')
                if Path(item['name']).suffix.lower() in _TEXT or item['mime_type'].startswith('text/'):
                    preview = await asyncio.to_thread(self._preview, path)
                    if preview:
                        self.write('  Preview:')
                        for line in preview:
                            self.write('    ' + line)
                self.write(f'  打开：/open {number} · 附件列表：/files')
            except (OSError, ValueError) as error:
                self.write(f"  附件不可用：{item['name']}（{type(error).__name__}）；可稍后用 /open {number} 重试。")

    @staticmethod
    def _preview(path):
        with path.open('rb') as source:
            data = source.read(4097)
        if b'\0' in data:
            return []
        text = data[:4096].decode('utf-8-sig', errors='replace')
        text = ''.join(c for c in text if c.isprintable() or c in '\n\t').replace('\t', '    ')
        lines = text.splitlines()
        result, remaining, truncated = [], 1600, len(data) > 4096 or len(lines) > 12
        for line in lines[:12]:
            value = line[:min(200, remaining)]
            truncated |= len(value) < len(line)
            result.append(value)
            remaining -= len(value)
            if not remaining:
                truncated = True
                break
        if truncated:
            result.append('…（预览已省略，使用 /open 编号查看全文）')
        return result

    def listing(self):
        if not self.entries:
            self.write('本次 Shell 尚未收到附件。')
        for number, (_, item) in self.entries.items():
            self.write(f"[{number}] {item['name']} · {item['size']:,} bytes · /open {number}")

    async def open_path(self, argument, storage):
        try:
            number = int(argument)
        except ValueError:
            raise ValueError('用法：/open 附件编号；/files 查看最近收到的附件') from None
        if number not in self.entries:
            raise ValueError('附件编号不存在；/files 查看最近收到的 64 个附件')
        session_id, item = self.entries[number]
        if storage is None:
            raise ValueError('未配置附件存储')
        if Path(item['name']).suffix.lower() not in _VIEWABLE:
            raise ValueError('此类型不支持自动打开，请根据已显示的文件路径自行查看')
        return await asyncio.to_thread(storage.named_copy, session_id, item['id'])
