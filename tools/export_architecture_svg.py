"""Exporta el diagrama local a SVG nativo, sin servicios externos ni dependencias.

Renderizador acotado a las formas y conexiones de este diagrama, no a todo Draw.io.
Si se agregan formas nuevas, conviene exportar el SVG desde diagrams.net.
"""
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

class Label(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines = ['']

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.lines.append('')

    def handle_data(self, data):
        self.lines[-1] += data

def style(cell):
    return dict(item.split('=', 1) for item in cell.get('style', '').split(';') if '=' in item)

def geometry(cell):
    g = cell.find('mxGeometry')
    return tuple(float(g.get(k, 0)) for k in ('x', 'y', 'width', 'height'))

def text_lines(value):
    parser = Label()
    parser.feed(value)
    return parser.lines

def wrap(lines, width, size):
    # Ancho aproximado para etiquetas en Arial; las líneas explícitas se conservan.
    limit = max(12, int(width / (size * .48)))
    result = []
    for line in lines:
        current = ''
        for word in line.split():
            if current and len(current) + len(word) + 1 > limit:
                result.append(current)
                current = word
            else:
                current = (current + ' ' + word).strip()
        result.append(current)
    return result

def main():
    diagram = ET.parse(ROOT / 'arquitectura-graphrag.drawio')
    cells = diagram.findall('.//mxCell')
    nodes = {c.get('id'): c for c in cells if c.get('vertex') == '1'}
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1330" viewBox="0 0 1800 1330" preserveAspectRatio="xMidYMid meet" role="img" aria-labelledby="title description">',
        '<title id="title">Arquitectura del asesor académico GraphRAG</title>',
        '<desc id="description">Aplicación local con Streamlit y Python; interpretación y generación con Bedrock; base de conocimiento GraphRAG con Neptune Analytics; ingestión de documentos Markdown desde S3. Sin identificadores ni regiones específicas.</desc>',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"/></marker></defs>',
        '<rect width="1800" height="1330" fill="#ffffff"/>',
    ]
    # Contenedores primero; sin grilla de edición en la imagen del README.
    for key in ['local', 'aws']:
        cell = nodes[key]
        x, y, w, h = geometry(cell)
        s = style(cell)
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{s["swimlaneFillColor"]}" stroke="{s["strokeColor"]}"/>')
        parts.append(f'<path d="M {x+18} {y} H {x+w-18} Q {x+w} {y} {x+w} {y+18} V {y+45} H {x} V {y+18} Q {x} {y} {x+18} {y} Z" fill="{s["fillColor"]}" stroke="{s["strokeColor"]}"/>')

    edge_labels = []
    for cell in cells:
        if cell.get('edge') != '1':
            continue
        s = style(cell)
        source, target = nodes[cell.get('source')], nodes[cell.get('target')]
        sx, sy, sw, sh = geometry(source)
        tx, ty, tw, th = geometry(target)
        if 'exitX' in s:
            start = (sx + sw * float(s['exitX']), sy + sh * float(s.get('exitY', '.5')))
        elif abs(tx+tw/2-sx-sw/2) > abs(ty+th/2-sy-sh/2):
            start = (sx+sw if tx > sx else sx, sy+sh/2)
        else:
            start = (sx+sw/2, sy+sh if ty > sy else sy)
        if 'entryX' in s:
            end = (tx + tw * float(s['entryX']), ty + th * float(s.get('entryY', '.5')))
        elif abs(tx+tw/2-sx-sw/2) > abs(ty+th/2-sy-sh/2):
            end = (tx if tx > sx else tx+tw, ty+th/2)
        else:
            end = (tx+tw/2, ty if ty > sy else ty+th)
        mids = [(float(p.get('x')), float(p.get('y'))) for p in cell.findall('mxGeometry/Array/mxPoint')]
        if not mids and start[0] != end[0] and start[1] != end[1]:
            mids = [(start[0], end[1])]
        points = [start, *mids, end]
        color = s.get('strokeColor', '#6C7F8C')
        attrs = ' stroke-dasharray="5 4"' if s.get('dashed') == '1' else ''
        if s.get('startArrow') == 'block':
            attrs += ' marker-start="url(#arrow)"'
        parts.append('<path d="' + ' '.join(('M' if i == 0 else 'L') + f' {x} {y}' for i, (x, y) in enumerate(points)) + f'" fill="none" stroke="{color}" stroke-width="1.5" marker-end="url(#arrow)"{attrs}/>')
        positions = {
            'e1': (195, 350), 'e2': (455, 365), 'e3': (630, 395),
            'e4': (200, 541), 'e5': (340, 626), 'e6': (823, 430),
            'e7': (1380, 550), 'e8': (1190, 418), 'e9': (200, 748),
            'e10': (145, 720), 'i1': (886, 762), 'i2': (1180, 753),
            'i3': (1420, 783), 'i4': (1450, 685),
        }
        edge_labels.append((cell.get('value', ''), positions[cell.get('id')]))

    for key, cell in nodes.items():
        x, y, w, h = geometry(cell)
        s = style(cell)
        is_text = cell.get('style', '').startswith('text;')
        if key not in ['local', 'aws'] and not is_text:
            fill, stroke = s.get('fillColor', '#fff'), s.get('strokeColor', '#999')
            if s.get('shape') == 'cylinder3':
                ry = 15
                parts.append(f'<path d="M {x} {y+ry} V {y+h-ry} C {x} {y+h+ry/3} {x+w} {y+h+ry/3} {x+w} {y+h-ry} V {y+ry} Z" fill="{fill}" stroke="{stroke}"/>')
                parts.append(f'<ellipse cx="{x+w/2}" cy="{y+ry}" rx="{w/2}" ry="{ry}" fill="{fill}" stroke="{stroke}"/>')
            else:
                parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="20" fill="{fill}" stroke="{stroke}"/>')
        if key in ['local', 'aws']:
            lines, size, anchor = text_lines(cell.get('value', '')), 16, 'middle'
            text_x, text_y, gap = x+w/2, y+28, 19
        else:
            size = float(s.get('fontSize', '15')) if is_text else 13
            lines = wrap(text_lines(cell.get('value', '')), w-30, size)
            if not is_text:
                while len(lines)*size*1.35 > h-24 and size > 10:
                    size -= .5
                    lines = wrap(text_lines(cell.get('value', '')), w-30, size)
            gap = size * 1.35
            anchor = 'start' if is_text or s.get('align') == 'left' else 'middle'
            text_x = x+15 if anchor == 'start' else x+w/2
            text_y = y+size+5 if is_text else y+(h-len(lines)*gap)/2+size
        color = s.get('fontColor', '#162029')
        for index, line in enumerate(lines):
            bold = index == 0 and (not is_text or s.get('fontStyle') == '1')
            parts.append(f'<text x="{text_x}" y="{text_y+index*gap}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{700 if bold else 400}">{escape(line)}</text>')

    for value, (x, y) in edge_labels:
        width = len(value)*5.8 + 12
        parts.append(f'<rect x="{x-width/2}" y="{y-13}" width="{width}" height="18" rx="3" fill="#ffffff" fill-opacity=".94"/>')
        parts.append(f'<text x="{x}" y="{y}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="11" fill="#263238">{escape(value)}</text>')
    parts.append('</svg>')
    svg = '\n'.join(parts)
    ET.fromstring(svg)
    if re.search(r'\b\d{12}\b|arn:aws|eu-west-1|EntregaViernes', svg):
        raise ValueError('El diagrama contiene referencias específicas; revisar antes de exportar.')
    destination = ROOT / 'arquitectura-graphrag.svg'
    destination.write_text(svg, encoding='utf-8')
    print(f'SVG generado: {destination.name}')

if __name__ == '__main__':
    main()
