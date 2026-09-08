#!/usr/bin/env python3
"""Extract paragraphs and tables from a .docx without external deps."""
import zipfile, sys
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def cell_text(tc):
    parts = []
    for p in tc.iter(W + 'p'):
        seg = ''.join(t.text or '' for t in p.iter(W + 't'))
        parts.append(seg)
    return ' '.join(x.strip() for x in parts if x.strip()).strip()


def para_text(p):
    return ''.join(t.text or '' for t in p.iter(W + 't')).strip()


def read_docx(path):
    """Return list of ('p', text) and ('table', rows) in document order."""
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read('word/document.xml'))
    body = root.find(W + 'body')
    out = []
    if body is None:
        return out
    for child in body:
        if child.tag == W + 'p':
            t = para_text(child)
            if t:
                out.append(('p', t))
        elif child.tag == W + 'tbl':
            rows = []
            for tr in child.findall(W + 'tr'):
                rows.append([cell_text(tc) for tc in tr.findall(W + 'tc')])
            out.append(('table', rows))
    return out


if __name__ == '__main__':
    for kind, val in read_docx(sys.argv[1]):
        if kind == 'p':
            print('P:', val)
        else:
            print(f'TABLE ({len(val)} rows):')
            for r in val:
                print('   |', ' | '.join(r))
