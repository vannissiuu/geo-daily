#!/usr/bin/env python3
"""把 site/index.html（无 doctype/html/head/body 的片段）包成完整 HTML。

用法：python3 tools/wrap_page.py site/index.html _site/index.html
规则：片段里的 <title>、<meta>、<link>、<style> 提到 <head>，其余（含 <script>）放进 <body>。
若输入已是完整文档（含 <html），原样输出。
"""
import re
import sys

HEAD_RE = re.compile(
    r"<title\b[^>]*>.*?</title>|<meta\b[^>]*>|<link\b[^>]*>|<style\b[^>]*>.*?</style>",
    re.S | re.I,
)


def wrap(src: str) -> str:
    if re.search(r"<html\b", src, re.I):
        return src
    head_parts = []
    has_charset = has_viewport = False

    def grab(m):
        nonlocal has_charset, has_viewport
        tag = m.group(0)
        if re.match(r"<meta\b", tag, re.I):
            if re.search(r"charset\s*=", tag, re.I):
                has_charset = True
                return ""  # 统一由下方固定写入
            if re.search(r'name\s*=\s*["\']viewport', tag, re.I):
                has_viewport = True
                return ""
        head_parts.append(tag)
        return ""

    body = HEAD_RE.sub(grab, src)
    head = (
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        + "\n".join(head_parts)
    )
    return (
        '<!doctype html>\n<html lang="zh-CN">\n<head>\n'
        + head
        + "\n</head>\n<body>\n"
        + body.strip()
        + "\n</body>\n</html>\n"
    )


def main():
    if len(sys.argv) != 3:
        sys.exit("用法：wrap_page.py <输入片段> <输出完整页面>")
    with open(sys.argv[1], encoding="utf-8") as f:
        out = wrap(f.read())
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(out)
    print(f"已生成 {sys.argv[2]}（{len(out)} 字符）")


if __name__ == "__main__":
    main()
