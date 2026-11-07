import re, sys, os, json, unicodedata

ITEM = re.compile(r'^(\d{1,2}(?:\.\d+)+)\.?\s+\S')
ALINEA = re.compile(r'^([a-z]{1,2}|[ivx]+)\)\s')
INCISO = re.compile(r'^[IVXL]+\s*[-–—]\s')
STARTERS = re.compile(r'^([A-Z]\.\d+(?:\.\d+)*\s*[-–]\s|ANEXO|Anexo\b|QUADRO|Quadro\b|TABELA|Tabela\b|GLOSSÁRIO|Glossário|Nota|NOTA|Parágrafo|Observaç|OBS|CAPÍTULO|Capítulo|SEÇÃO|Seção|APÊNDICE|Apêndice|\(Redação|\(Incluíd|\(Alterad|\(Revogad|\(Inserid|\(Vide)')
FOOTER = re.compile(r'^Este texto não substitui o publicado no D\.?O\.?U\.?$')
DATE = re.compile(r'^\d{2}/\d{2}/\d{2,4}$')

def norm(s):
    s = unicodedata.normalize('NFC', s).replace('­', '').replace('\t', ' ')
    s = s.replace('', '•').replace('', '•')
    return re.sub(r'\s+', ' ', s).strip()

def key(l):
    return re.sub(r'[\s.;:,–-]+$', '', l).lower()

def parse_header(lines):
    title_lines, portarias, dates, notes = [], [], [], []
    i = 0
    phase = 'title'
    while i < len(lines):
        l = lines[i]
        if l.lower() == 'sumário' or ITEM.match(l) or re.match(r'^\d+\.\s+[A-ZÁ-Ú]', l):
            break
        if phase == 'title' and l and re.match(r'^(Entra em vigor|\()', l):
            notes.append(l)
        elif phase == 'title' and l and not re.match(r'^(Publicação|D\.O\.U|Portaria|Criad)', l):
            title_lines.append(l)
        elif l:
            phase = 'meta'
            if re.match(r'^(Publicação|Alterações|D\.O\.U|Criad)', l):
                pass
            elif l.startswith('Portaria'):
                portarias.append(l)
            elif DATE.match(l) or l.startswith('Rep.'):
                dates.append(l)
            else:
                notes.append(l)
        i += 1
    title = ' '.join(title_lines)
    merged = []
    for n in notes:
        if merged and not n.startswith('(') and not merged[-1].endswith(')') and n[:1].isupper() and n.isupper() and sum(c.isupper() for c in merged[-1]) > 0.7*sum(c.isalpha() for c in merged[-1]) and not merged[-1].startswith('('):
            merged[-1] += ' ' + n
        elif merged and merged[-1].startswith('(') and not merged[-1].endswith(')'):
            merged[-1] += ' ' + n
        else:
            merged.append(n)
    return title, portarias, dates, merged, i

def strip_sumario(lines, i):
    if i < len(lines) and lines[i].lower() == 'sumário':
        i += 1
        j = i
        while j < len(lines) and not lines[j]:
            j += 1
        if j >= len(lines):
            return j
        first = key(lines[j])
        k = j + 1
        while k < len(lines):
            if key(lines[k]) == first:
                return k
            k += 1
        return j
    return i

def is_heading(l):
    m = ITEM.match(l)
    if not m:
        return 0
    rest = l[len(m.group(1)):].lstrip('. ').strip()
    if len(rest) > 90 or rest.endswith(('.', ';', ':', ',')) or not rest[:1].isupper():
        return 0
    depth = m.group(1).count('.')
    return 2 if depth == 1 else (3 if depth == 2 else 4)

def starts_block(l):
    return bool(ITEM.match(l) or ALINEA.match(l) or INCISO.match(l) or STARTERS.match(l) or l.startswith('•'))

def body_to_md(lines):
    paras = []
    cur = None
    pending_blank = False
    for l in lines:
        if l.startswith('\x00TABLE'):
            if cur is not None:
                paras.append(cur)
                cur = None
            paras.append(l)
            pending_blank = False
            continue
        if not l:
            pending_blank = True
            continue
        if FOOTER.match(l):
            continue
        new = cur is None or starts_block(l)
        if not new and pending_blank:
            prev = cur.rstrip()
            if prev.endswith(('.', ';', ':')) and not l[:1].islower():
                new = True
        if new:
            if cur is not None:
                paras.append(cur)
            cur = l
        else:
            if cur.endswith('-') and not cur.endswith(' -'):
                cur = cur[:-1] + l
            else:
                cur = cur + ' ' + l
        pending_blank = False
    if cur is not None:
        paras.append(cur)
    out = []
    for p in paras:
        if p.startswith('\x00TABLE'):
            out.append('```text\n' + TABLES[int(p[6:])] + '\n```')
            continue
        h = is_heading(p)
        if h:
            out.append('#' * h + ' ' + p)
        elif re.match(r'^\d{1,2}\.\s+[A-ZÁ-Ú]', p) and len(p) < 90 and not p.endswith(('.', ';', ':')):
            out.append('## ' + p)
        elif re.match(r'^(ANEXO|Anexo)\b', p) and len(p) < 160:
            out.append('## ' + p)
        elif ALINEA.match(p) or INCISO.match(p):
            out.append('- ' + p)
        else:
            out.append(p)
    return '\n\n'.join(out)

TABLES = []

def table_page(lines):
    ne = [l for l in lines if l]
    if len(ne) < 12:
        return False
    short = sum(1 for l in ne if len(l.split()) <= 4)
    return short / len(ne) >= 0.55

def layout_block(text):
    ls = [l.rstrip() for l in text.split('\n') if not FOOTER.match(l.strip())]
    while ls and not ls[0].strip(): ls.pop(0)
    while ls and not ls[-1].strip(): ls.pop()
    ind = min((len(l) - len(l.lstrip()) for l in ls if l.strip()), default=0)
    ls = [l[ind:] for l in ls]
    out = []
    for l in ls:
        if not l.strip() and out and not out[-1].strip():
            continue
        out.append(l)
    return '\n'.join(out).replace('```', "'''")

def esc(s):
    return s.replace('|', '\\|')

def convert(txt_path, nr, pdf_name, label=None):
    raw = open(txt_path, encoding='utf-8').read()
    lay = open(txt_path.replace('/txt/', '/txtL/'), encoding='utf-8').read().split('\f')
    pages = raw.split('\f')
    lines, pg = [], []
    for n, ptxt in enumerate(pages):
        pl = [norm(x) for x in ptxt.split('\n')]
        nzp = [k for k, l in enumerate(pl) if l and not FOOTER.match(l)]
        if nzp and pl[nzp[-1]] == str(n + 1):
            pl[nzp[-1]] = ''
        for x in pl:
            lines.append(x); pg.append(n)
    while lines and not lines[0]:
        lines.pop(0); pg.pop(0)
    nz = [k for k, l in enumerate(lines) if l]
    cand = [nz[j] for j in range(1, len(nz)) if re.fullmatch(r'\d{1,3}', lines[nz[j]]) and FOOTER.match(lines[nz[j - 1]])]
    vals = [int(lines[k]) for k in cand]
    if vals and all(b > a for a, b in zip(vals, vals[1:])):
        for k in cand:
            lines[k] = ''
    title, portarias, dates, notes, i = parse_header(lines)
    i = strip_sumario(lines, i)
    first_page = pg[i] if i < len(pg) else 0
    body_lines = []
    seen = set()
    for l, n in zip(lines[i:], pg[i:]):
        if n > first_page and n < len(lay) and table_page([norm(x) for x in pages[n].split('\n')]):
            if n not in seen:
                seen.add(n)
                TABLES.append(layout_block(lay[n]))
                body_lines.append('\x00TABLE' + str(len(TABLES) - 1))
            continue
        body_lines.append(l)
    body = body_to_md(body_lines)
    md = [f'# {title}', '']
    md.append('> Texto extraído do PDF oficial publicado pelo MTE. Este texto não substitui o publicado no DOU. '
              f'Em caso de divergência, vale o [PDF original](pdf/{pdf_name}).')
    md.append('')
    for n in notes:
        md.append(f'**{n}**' if n.isupper() else f'*{n}*')
        md.append('')
    if portarias:
        md.append('## Publicação e alterações')
        md.append('')
        md.append('| Ato | D.O.U. |')
        md.append('|---|---|')
        for k, a in enumerate(portarias):
            d = dates[k] if k < len(dates) else ''
            md.append(f'| {esc(a)} | {d} |')
        md.append('')
    md.append('---')
    md.append('')
    md.append(body)
    md.append('')
    return title, md, len(portarias), (dates[-1] if dates else '')

if __name__ == '__main__':
    src, txtdir, out = sys.argv[1], sys.argv[2], sys.argv[3]
    index = []
    for f in sorted(os.listdir(src)):
        if not f.endswith('.pdf'):
            continue
        base = f[:-4]
        clean = re.sub(r'^[0-9a-f]{8}-', '', base)
        m = re.search(r'nr-?(\d{1,2})', clean, re.I)
        nr = int(m.group(1))
        folder = os.path.join(out, f'NR-{nr:02d}')
        os.makedirs(os.path.join(folder, 'pdf'), exist_ok=True)
        anexo = re.search(r'anexo-?(\d+)', clean, re.I)
        mdname = f'NR-{nr:02d}-anexo-{int(anexo.group(1)):02d}.md' if anexo else f'NR-{nr:02d}.md'
        pdf_name = clean.lower() + '.pdf'
        os.system(f'cp "{os.path.join(src, f)}" "{os.path.join(folder, "pdf", pdf_name)}"')
        title, md, nalts, last = convert(os.path.join(txtdir, base + '.txt'), nr, pdf_name)
        open(os.path.join(folder, mdname), 'w', encoding='utf-8').write('\n'.join(md))
        index.append({'nr': nr, 'file': f'NR-{nr:02d}/{mdname}', 'title': title, 'last': last, 'anexo': bool(anexo), 'pdf': f'NR-{nr:02d}/pdf/{pdf_name}'})
    json.dump(index, open(os.path.join(out, '.index.json'), 'w'), ensure_ascii=False, indent=1)
    for e in index:
        print(e['nr'], e['last'], e['title'][:80], '|', e['file'])
