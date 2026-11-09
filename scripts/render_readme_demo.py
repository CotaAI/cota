"""Render the original README workflow illustration (authoring only).

Requires Pillow >= 10 and an installed Chinese font; neither is a Bot runtime
dependency. See docs/assets/readme/README.md for reproducible commands.
"""
import argparse
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT, SCALE = 1040, 610, 2
COLORS = {
    'paper': '#fbf8ef', 'ink': '#252638', 'muted': '#666776', 'line': '#dcd9d0',
    'white': '#fffefa', 'purple': '#7066e0', 'yellow': '#f6e9bc',
    'violet': '#ebe7fb', 'green': '#dce9d8', 'coral': '#f2dcd3',
}
STEPS = (
    ('定义', '能力 + 业务规则', 'yellow'),
    ('运行', 'Bot 回应用户', 'violet'),
    ('验证', '执行记录 + 评测', 'green'),
    ('交付', '把 Bot 用起来', 'coral'),
)
CAPTIONS = (
    ('先教它，业务应该怎么做。', '用 Skill 定义能力，用 Policy 写下正确处理问题的案例。',
     '澄清条件、选择能力、处理异常，都可以用业务案例指导。'),
    ('让 Bot 结合对话，选择与调用能力。', '用户：周末带孩子去哪玩？',
     'Bot：在哪个城市？预算大概多少？'),
    ('看清执行过程，再用案例验证。', '保留对话、工具调用与结果，按回复要求逐项评测。',
     '查看记录 → 人工修改 Skill / Policy → 再评测'),
    ('交付完整 Bot，供自己或别人使用。', '你维护聊天服务，或把 Bot 文件夹交给对方独立部署。',
     '角色 + 能力 + 规则 + 配置 + 验证案例'),
)


def installed_font(explicit, candidates):
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ValueError('Font file does not exist: ' + str(path))
        return path
    for name in candidates:
        path = Path(name)
        if path.is_file():
            return path
    raise ValueError('No suitable font found; provide --font /path/to/Chinese-font.ttf and --mono-font if needed')


class Diagram:
    def __init__(self, chinese, mono):
        self.chinese, self.mono = chinese, mono

    @lru_cache(maxsize=None)
    def font(self, size, bold=False, mono=False):
        path = self.mono if mono else self.chinese
        index = 2 if bold and path.name == 'Hiragino Sans GB.ttc' else 0
        return ImageFont.truetype(str(path), size * SCALE, index=index)

    @staticmethod
    def points(values):
        return tuple(round(value * SCALE) for value in values)

    def rect(self, box, fill, radius=12, outline='ink', width=1.5):
        self.draw.rounded_rectangle(self.points(box), radius=round(radius * SCALE),
                                   fill=COLORS.get(fill, fill),
                                   outline=COLORS.get(outline, outline) if outline else None,
                                   width=round(width * SCALE))

    def text(self, position, value, size=20, color='ink', bold=False, mono=False):
        self.draw.text(self.points(position), value, font=self.font(size, bold, mono),
                       fill=COLORS.get(color, color), anchor='lt')

    def line(self, points, color='ink', width=1.5):
        self.draw.line([self.points(point) for point in points], fill=COLORS.get(color, color),
                       width=round(width * SCALE), joint='curve')

    def dot(self, center, radius=5, color='purple'):
        x, y = center
        self.draw.ellipse(self.points((x-radius, y-radius, x+radius, y+radius)), fill=COLORS[color])

    def paper(self, x, y, label, fill):
        self.rect((x+3, y+3, x+174, y+44), 'ink', radius=6)
        self.rect((x, y, x+171, y+41), fill, radius=6)
        self.line(((x+13, y+11), (x+13, y+29), (x+26, y+29), (x+26, y+11), (x+13, y+11)), width=1)
        self.text((x+38, y+12), label, size=16, mono=label.endswith('/'))

    def robot(self, x, y):
        self.rect((x+3, y+3, x+62, y+61), 'ink', radius=15)
        self.rect((x, y, x+59, y+58), 'purple', radius=15)
        self.dot((x+30, y-8), 5, 'ink')
        self.dot((x+30, y-8), 3.5, 'yellow')
        self.rect((x+15, y+19, x+23, y+32), 'white', radius=4, width=1)
        self.rect((x+36, y+19, x+44, y+32), 'white', radius=4, width=1)
        self.dot((x+19, y+27), 1.5, 'ink')
        self.dot((x+40, y+27), 1.5, 'ink')
        self.draw.arc(self.points((x+23, y+31, x+36, y+41)), 0, 180,
                      fill=COLORS['ink'], width=SCALE)

    def card(self, index, active):
        x, y, w = 36 + index * 246, 157, 230
        fill = STEPS[index][2] if active else 'white'
        if active:
            self.rect((x+3, y+4, x+w+3, y+245), 'ink', radius=13)
        self.rect((x, y, x+w, y+241), fill, radius=13, width=2 if active else 1.2)
        self.text((x+18, y+18), '0' + str(index+1), size=15, color='purple' if active else 'muted', mono=True)
        self.text((x+55, y+17), STEPS[index][0], size=21, bold=True)
        self.text((x+18, y+57), STEPS[index][1], size=21, bold=True)
        if index == 0:
            self.paper(x+18, y+102, 'Skill：业务能力', 'yellow')
            self.paper(x+18, y+157, 'Policy：正确做法', 'coral')
            self.text((x+18, y+213), '配置随 Bot 一起维护', size=14, color='muted')
        elif index == 1:
            self.robot(x+18, y+108)
            self.rect((x+88, y+97, x+210, y+136), 'white', radius=8, width=1)
            self.text((x+101, y+110), '去哪玩？', size=17)
            self.text((x+89, y+152), '先问清城市', size=16)
            self.text((x+89, y+180), '与预算', size=16)
            self.text((x+18, y+213), '按任务读取 Skill、调用工具', size=13, color='muted')
        elif index == 2:
            for row, label in enumerate(('看真实执行记录', '逐条检查回复要求', '比较修改前后结果')):
                yy = y+110 + row*38
                self.dot((x+24, yy+9), 3, 'purple')
                self.text((x+37, yy), label, size=17)
            self.text((x+18, y+213), '人工修改，再用同一验证集检查', size=12, color='muted')
        else:
            self.rect((x+18, y+102, x+210, y+150), 'white', radius=8, width=1)
            self.text((x+30, y+114), '聊天入口', size=18, bold=True)
            self.text((x+113, y+117), '你维护服务', size=13, color='muted')
            self.rect((x+18, y+164, x+210, y+212), 'white', radius=8, width=1)
            self.text((x+30, y+176), 'Bot 文件夹', size=17, bold=True)
            self.text((x+130, y+179), '独立部署', size=13, color='muted')

    def render(self, phase=None, progress=1):
        image = Image.new('RGB', (WIDTH*SCALE, HEIGHT*SCALE), COLORS['paper'])
        self.draw = ImageDraw.Draw(image)
        self.text((36, 30), 'Cota', size=28, bold=True)
        self.text((126, 39), 'BOT DEVELOPMENT & DELIVERY', size=13, color='muted', mono=True)
        self.text((36, 79), '从业务经验，到可以交付的 Bot。', size=35, bold=True)
        self.rect((892, 32, 1004, 62), 'white', radius=15, outline='line', width=1)
        self.text((907, 41), '原理示意动画', size=13, color='muted')
        for index in range(4):
            self.card(index, index == phase)
            if index < 3:
                xx = 272 + index*246
                self.line(((xx, 280), (xx+8, 280)), color='muted')
                self.line(((xx+4, 276), (xx+8, 280), (xx+4, 284)), color='muted')
        if phase is not None:
            end = 151 + phase*246
            start = 151 + max(phase-1, 0)*246
            eased = progress*progress*(3-2*progress)
            self.dot((start + (end-start)*eased, 140), 5)

        fill = STEPS[phase][2] if phase is not None else 'violet'
        self.rect((36, 432, 1004, 576), fill, radius=13)
        if phase is None:
            title = '能力、规则、记录与验证，围绕同一个 Bot。'
            first = '可以服务自己、客户或群聊；选择适合自己的交付入口。'
            second = '定义 → 运行 → 验证 → 交付'
        else:
            title, first, second = CAPTIONS[phase]
        self.text((57, 454), title, size=30, bold=True)
        self.text((57, 504), first, size=20)
        self.text((57, 541), second, size=17, color='muted')
        self.text((37, 590), '概念演示，非实时对话或真实评测结果。', size=12, color='muted')
        self.text((722, 590), '人工迭代业务案例，再验证效果。', size=12, color='muted')
        return image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', help='Installed Chinese .ttf/.otf/.ttc font')
    parser.add_argument('--mono-font', help='Installed Latin monospace font')
    parser.add_argument('--out', type=Path, default=ROOT / 'docs/assets/readme')
    args = parser.parse_args()
    try:
        chinese = installed_font(args.font, (
            '/System/Library/Fonts/Hiragino Sans GB.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
            'C:/Windows/Fonts/msyh.ttc',
        ))
        mono = installed_font(args.mono_font, (
            '/System/Library/Fonts/SFNSMono.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
            'C:/Windows/Fonts/consola.ttf',
        ))
    except ValueError as error:
        parser.error(str(error))
    diagram = Diagram(chinese, mono)
    poster = diagram.render()
    # One shared palette keeps unchanged pixels stable across GIF frames.
    samples = [poster] + [diagram.render(phase) for phase in range(4)]
    palette_source = Image.new('RGB', (WIDTH, HEIGHT*len(samples)))
    for i, sample in enumerate(samples):
        palette_source.paste(sample, (0, HEIGHT*i))
    palette = palette_source.quantize(colors=96, method=Image.Quantize.MEDIANCUT)
    frames = [poster.quantize(palette=palette, dither=Image.Dither.NONE)]
    durations = [1400]
    for phase in range(4):
        for step in range(9):
            frames.append(diagram.render(phase, step/8).quantize(palette=palette, dither=Image.Dither.NONE))
            durations.append(3200 if step == 8 else 100)
    args.out.mkdir(parents=True, exist_ok=True)
    poster.save(args.out / 'cota-workflow.png', optimize=True)
    animation = args.out / 'cota-workflow.gif'
    frames[0].save(animation, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, disposal=1, optimize=True)
    with Image.open(animation) as result:
        count = result.n_frames
    print(f'Rendered {animation.name}: {WIDTH}x{HEIGHT}, {count} frames, '
          f'{sum(durations)/1000:.1f}s, {animation.stat().st_size/1024:.0f} KiB')


if __name__ == '__main__':
    main()
