import re
from html.parser import HTMLParser


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def normalize_reply(text):
    # Quoted outbound facts are not a new inbound payment claim.
    text = text.replace("\r\n", "\n").replace("\x00", "")
    text = re.split(r"(?im)^On .+wrote:\s*$|^-{2,}\s*Original Message\s*-*\s*$", text)[0]
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith(">")
    ).strip()[:12000]
