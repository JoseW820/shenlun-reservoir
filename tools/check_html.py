# -*- coding: utf-8 -*-
"""校验生成的 HTML 清单结构是否完整。"""
import io
import sys
from html.parser import HTMLParser

path = sys.argv[1] if len(sys.argv) > 1 else ''
raw = io.open(path, encoding='utf-8').read()


class Checker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []
        self.items = 0
        self.links = []
        self.summaries = 0
        self.nones = 0
        self.colls = 0
        self.table_rows = 0
        self._in_item = False
        self._in_a = False
        self._a_href = ''
        self._a_text = []

    VOID = {'meta', 'br', 'img', 'hr', 'input', 'link'}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get('class', '')
        if tag not in self.VOID:
            self.stack.append(tag)
        if tag == 'div' and 'item' in cls.split():
            self.items += 1
            self._in_item = True
        if tag == 'div' and cls.split() == ['sum']:
            self.summaries += 1
        if tag == 'div' and cls.split() == ['none']:
            self.nones += 1
        if tag == 'span' and cls.split() == ['coll']:
            self.colls += 1
        if tag == 'tr':
            self.table_rows += 1
        if tag == 'a' and 't' in cls.split():
            self._in_a = True
            self._a_href = a.get('href', '')
            self._a_text = []

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            self.errors.append('标签未正确闭合: <%s>（栈顶是 <%s>）' % (tag, self.stack[-1]))
            while self.stack and self.stack[-1] != tag:
                self.stack.pop()
            if self.stack:
                self.stack.pop()
        else:
            self.errors.append('多余的结束标签: </%s>' % tag)
        if tag == 'a' and self._in_a:
            self.links.append((self._a_href, ''.join(self._a_text).strip()))
            self._in_a = False

    def handle_data(self, data):
        if self._in_a:
            self._a_text.append(data)


c = Checker()
c.feed(raw)
c.close()

print('文件:', path)
print('大小: %.1f KB' % (len(raw.encode('utf-8')) / 1024))
print('-' * 52)
print('条目 div (class=item) :', c.items)
print('标题链接 <a class=t>  :', len(c.links))
print('摘要 div (class=sum)  :', c.summaries)
print('无正文 div(class=none):', c.nones)
print('集合标签 span(coll)   :', c.colls)
print('统计表行 <tr>         :', c.table_rows)
print('-' * 52)
print('未闭合标签:', c.stack if c.stack else '无 ✓')
print('结构错误  :', c.errors if c.errors else '无 ✓')
bad = [h for h, _ in c.links if not h.startswith('http')]
print('非 http 链接:', bad if bad else '无 ✓')
dup = len(c.links) - len({h for h, _ in c.links})
print('重复链接  :', dup)
print('-' * 52)
print('前 2 条链接:')
for h, t in c.links[:2]:
    print('  %s' % t[:40])
    print('    %s' % h[:76])
