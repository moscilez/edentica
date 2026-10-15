"""Generate a verified certificate. JSON on stdin; binary PDF on stdout."""
import io, json, os, sys
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

data = json.loads(sys.stdin.buffer.read().decode('utf-8'))
font_path = os.environ.get('CERTIFICATE_FONT')
if not font_path:
    candidates = [os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', 'arial.ttf'), '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    font_path = next((p for p in candidates if os.path.exists(p)), None)
if not font_path:
    raise RuntimeError('Set CERTIFICATE_FONT to a Cyrillic TTF font')
pdfmetrics.registerFont(TTFont('Edentica', font_path))
buf = io.BytesIO()
c = canvas.Canvas(buf, pagesize=(842, 595))
c.setTitle('Edentica - Certificate ' + data['id'])
c.setFillColorRGB(.96, .98, .96); c.rect(0, 0, 842, 595, fill=1, stroke=0)
c.setStrokeColorRGB(.22, .42, .33); c.setLineWidth(2); c.rect(26, 26, 790, 543)
c.setLineWidth(.5); c.rect(34, 34, 774, 527)
def centered(text, y, size, max_width=690):
    text = ' '.join(str(text).split())
    while pdfmetrics.stringWidth(text, 'Edentica', size) > max_width and size > 9:
        size -= 1
    c.setFont('Edentica', size); c.setFillColorRGB(.12, .27, .21); c.drawCentredString(421, y, text)
centered('EDENTICA', 515, 22)
centered('CREATE. LEARN. ACHIEVE.', 491, 10)
centered('СЕРТИФИКАТ', 416, 38)
centered('об успешном завершении образовательного курса', 382, 14)
centered(data['name'], 324, 28)
def title_lines(text, size):
    result, line = [], ''
    for char in text:
        if pdfmetrics.stringWidth(line + char, 'Edentica', size) > 690:
            split = line.rfind(' ')
            if split > 0:
                result.append(line[:split]); line = line[split + 1:] + char
            else:
                result.append(line); line = char
        else:
            line += char
    if line: result.append(line)
    return result
size = 25
title = ' '.join(data['title'].split())
lines = title_lines(title, size)
while len(lines) > 3 and size > 9:
    size -= 1; lines = title_lines(title, size)
y = 273 if len(lines) == 1 else 285
for line in lines:
    centered(line, y, size); y -= 24
author_y = min(238, y - 6)
centered('Автор: ' + data['author'], author_y, 13)
centered('Дата завершения: ' + data['created'][:10], author_y - 30, 12)
if data.get('hours'):
    centered('Продолжительность: ' + str(data['hours']) + ' ч.', author_y - 57, 12)
centered('Подтверждает прохождение курса на платформе Edentica.', max(130, author_y - 80), 10)
qr = QrCodeWidget(data['url']); bounds = qr.getBounds(); w=bounds[2]-bounds[0]; h=bounds[3]-bounds[1]
d=Drawing(90,90,transform=[90/w,0,0,90/h,0,0]); d.add(qr); renderPDF.draw(d,c,680,64)
c.setFont('Edentica', 9); c.drawString(66, 125, 'Номер: ' + data['id'])
c.drawString(66, 105, 'Проверка подлинности по QR-коду или ссылке:')
url=data['url']; size=8
while pdfmetrics.stringWidth(url,'Edentica',size)>590 and size>5: size-=.5
c.setFont('Edentica',size); c.drawString(66,86,url)
c.linkURL(url,(66,80,656,100),relative=0)
c.save(); sys.stdout.buffer.write(buf.getvalue())
