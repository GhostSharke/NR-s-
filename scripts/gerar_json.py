import json, os, re, sys, unicodedata
from datetime import date

ITEM = re.compile(r'^(\d{1,2}(?:\.\d+)*)\.?\s+(.*)$', re.S)
ALINEA = re.compile(r'^([a-z]{1,2}|[ivx]+)\)\s+(.*)$', re.S)
SUBANEXO = re.compile(r'^([A-Z]\.\d+(?:\.\d+)*)\s*[-–]\s+(.*)$', re.S)
INCISO = re.compile(r'^([IVXL]+)\s*[-–—]\s+(.*)$', re.S)
ANEXO = re.compile(r'^(ANEXO|Anexo)\b\s*(?:N[º°o.]*\s*)?([IVXL]+|\d+(?:-[A-Z])?|[“"]?[A-Z][”"]?)?', re.I)
NOTA = re.compile(r'\((?:[^()]*?\b(?:Redação|Revogad[oa]s?|Incluíd[oa]s?|Inserid[oa]s?|Alterad[oa]s?|Renumerad[oa]s?|Acrescid[oa]s?|Excluíd[oa]s?|Texto dado|Vide|Vigência)\b[^()]*)\)', re.I)
REVOGADO = re.compile(r'\b(Revogad[oa]s?|Excluíd[oa]s?)\b', re.I)
PORTARIA = re.compile(r'Portaria\s+([A-Z]+)\s*n\.?\s*[º°o]?\s*([\d.]+)', re.I)


def slug(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^A-Za-z0-9]+', '-', s).strip('-').upper()


def blocks(body):
    out, buf, fence = [], [], False
    for line in body.split('\n'):
        if line.startswith('```'):
            if fence:
                buf.append(line)
                out.append('\n'.join(buf))
                buf, fence = [], False
            else:
                if buf:
                    out.append('\n'.join(buf))
                buf, fence = [line], True
            continue
        if fence:
            buf.append(line)
        elif not line.strip():
            if buf:
                out.append('\n'.join(buf))
                buf = []
        else:
            buf.append(line)
    if buf:
        out.append('\n'.join(buf))
    return out


def header(md):
    head, _, body = md.partition('\n---\n')
    titulo = re.search(r'^# (.+)$', head, re.M).group(1).strip()
    pdf = re.search(r'\[PDF original\]\(([^)]+)\)', head)
    atos = []
    for a, d in re.findall(r'^\| (Portaria[^|]*?) \| ([^|]*?) \|$', head, re.M):
        atos.append({'ato': a.replace('\\|', '|').strip(), 'dou': d.strip() or None})
    notas = [m.strip('*').strip() for m in re.findall(r'^\*{1,2}[^*].*?\*{1,2}$', head, re.M)]
    return titulo, (pdf.group(1) if pdf else None), atos, notas, body


def limpar(texto):
    notas = [n.strip('() ') for n in NOTA.findall(texto)]
    limpo = re.sub(r'\s+', ' ', NOTA.sub('', texto)).strip()
    return limpo, notas


def status_de(limpo, notas):
    if any(REVOGADO.search(n) for n in notas) and len(limpo) < 400:
        return 'revogado'
    if re.fullmatch(r'[\d.]*\s*Revogad[oa]s?\.?', limpo, re.I):
        return 'revogado'
    return 'vigente'


def converter(md_path, nr, arquivo_md):
    md = open(md_path, encoding='utf-8').read()
    titulo, pdf, atos, notas_cab, body = header(md)
    nr_id = f'NR-{nr:02d}'
    registros, ids = [], {}
    anexo = None
    secao = None
    ultimo_item = None
    ultimo_alvo = None
    ordem = 0

    def novo_id(base):
        k = base
        n = 2
        while k in ids:
            k = f'{base}~{n}'
            n += 1
        ids[k] = True
        return k

    def prefixo():
        return nr_id + (f'/{anexo}' if anexo else '')

    def add(tipo, texto, numero=None, pai=None, nivel=None, extra=None):
        nonlocal ordem
        ordem += 1
        limpo, notas = limpar(texto) if tipo != 'tabela' else (texto, [])
        base = prefixo() + (f'/{numero}' if numero else f'/{tipo}-{ordem}')
        rid = novo_id(base)
        r = {
            'id': rid,
            'nr': nr,
            'anexo': anexo,
            'tipo': tipo,
            'numero': numero,
            'nivel': nivel,
            'pai': pai,
            'secao': secao,
            'ordem': ordem,
            'texto': limpo,
            'texto_original': texto if notas else None,
            'alteracoes': notas,
            'portarias_citadas': sorted({f'{a.upper()} {b.rstrip(".")}' for a, b in PORTARIA.findall(' '.join(notas))}),
            'status': status_de(limpo, notas) if tipo != 'tabela' else 'vigente',
        }
        if extra:
            r.update(extra)
        registros.append(r)
        return rid

    for b in blocks(body):
        if b.startswith('```'):
            conteudo = '\n'.join(b.split('\n')[1:-1])
            add('tabela', conteudo, pai=ultimo_alvo or (prefixo() if anexo else None))
            continue
        h = 0
        if b.startswith('#'):
            h = len(b) - len(b.lstrip('#'))
            b = b[h:].strip()
        if h and ANEXO.match(b):
            m = ANEXO.match(b)
            ident = (m.group(2) or '').strip('“”"')
            anexo = 'ANEXO-' + (slug(ident) if ident else str(sum(1 for r in registros if r['tipo'] == 'anexo') + 1))
            while any(r['tipo'] == 'anexo' and r['anexo'] == anexo for r in registros):
                anexo += '-B'
            secao = None
            ultimo_item = ultimo_alvo = None
            rid = add('anexo', b, nivel=0)
            ultimo_alvo = rid
            continue
        m = ALINEA.match(b.lstrip('- ').strip()) if b.startswith('- ') else None
        if m and not ultimo_item:
            ultimo_item = ultimo_alvo
        if m and ultimo_item:
            letra = m.group(1)
            pai = ultimo_item
            base_num = registros_por_id(registros, pai).get('numero')
            numero = f'{base_num}.{letra})' if base_num else None
            add('alinea', b[2:].strip(), numero=numero, pai=pai, nivel=None, extra={'letra': letra})
            continue
        m = INCISO.match(b.lstrip('- ').strip()) if b.startswith('- ') else None
        if m and not ultimo_item:
            ultimo_item = ultimo_alvo
        if m and ultimo_item:
            rom = m.group(1)
            pai = ultimo_item
            base_num = registros_por_id(registros, pai).get('numero')
            numero = f'{base_num}.{rom}' if base_num else None
            add('inciso', b[2:].strip(), numero=numero, pai=pai, extra={'inciso': rom})
            continue
        m = ITEM.match(b)
        if m and re.match(r'^\d', b):
            numero = m.group(1)
            partes = numero.split('.')
            nivel = len(partes) - 1
            pai = None
            for k in range(len(partes) - 1, 0, -1):
                cand = prefixo() + '/' + '.'.join(partes[:k])
                if cand in ids:
                    pai = cand
                    break
            if pai is None and anexo:
                pai = next((r['id'] for r in reversed(registros) if r['tipo'] == 'anexo' and r['anexo'] == anexo), None)
            if h:
                secao = f"{numero} {m.group(2).strip()}"
                rid = add('titulo', b, numero=numero, pai=pai, nivel=nivel)
            else:
                rid = add('item', b, numero=numero, pai=pai, nivel=nivel)
            ultimo_item = ultimo_alvo = rid
            continue
        m = SUBANEXO.match(b)
        if m and anexo:
            numero = m.group(1)
            partes = numero.split('.')
            pai = None
            for k in range(len(partes) - 1, 0, -1):
                cand = prefixo() + '/' + '.'.join(partes[:k])
                if cand in ids:
                    pai = cand
                    break
            if pai is None:
                pai = next((r['id'] for r in reversed(registros) if r['tipo'] == 'anexo' and r['anexo'] == anexo), None)
            rid = add('item', b, numero=numero, pai=pai, nivel=len(partes) - 1)
            ultimo_item = ultimo_alvo = rid
            continue
        tipo = 'titulo' if h else ('nota' if b.startswith('(') and b.endswith(')') else 'texto')
        if tipo == 'nota' and registros:
            alvo = registros[-1]
            alvo['alteracoes'].append(b.strip('() '))
            alvo['portarias_citadas'] = sorted(set(alvo['portarias_citadas']) | {f'{a.upper()} {c.rstrip(".")}' for a, c in PORTARIA.findall(b)})
            if REVOGADO.search(b) and alvo['tipo'] != 'tabela':
                alvo['status'] = 'revogado'
            continue
        if tipo == 'titulo':
            secao = b.strip()
        rid = add(tipo, b.lstrip('- ').strip() if b.startswith('- ') else b, pai=ultimo_alvo if tipo == 'texto' else None)
        if tipo == 'texto' and b.rstrip().endswith(':'):
            ultimo_item = rid

    filhos = {}
    for r in registros:
        if r['pai']:
            filhos.setdefault(r['pai'], []).append(r['id'])
    for r in registros:
        r['filhos'] = filhos.get(r['id'], [])

    meta = {
        'nr': nr,
        'id': nr_id,
        'titulo': re.sub(r'^(NR[\s-]*0?\d+|NORMA REGULAMENTADORA N\.?º?\s*\d+)\s*[-–]\s*', '', titulo).strip(),
        'titulo_original': titulo,
        'arquivo_md': arquivo_md,
        'pdf': f'{os.path.dirname(arquivo_md)}/{pdf}' if pdf else None,
        'publicacao_e_alteracoes': atos,
        'ultima_alteracao_dou': atos[-1]['dou'] if atos else None,
        'notas': notas_cab,
        'anexos': [{'id': r['anexo'], 'titulo': r['texto']} for r in registros if r['tipo'] == 'anexo'],
        'totais': {t: sum(1 for r in registros if r['tipo'] == t) for t in ['titulo', 'item', 'alinea', 'inciso', 'texto', 'tabela', 'anexo']},
        'revogados': sum(1 for r in registros if r['status'] == 'revogado'),
    }
    return meta, registros


def registros_por_id(registros, rid):
    for r in reversed(registros):
        if r['id'] == rid:
            return r
    return {}


def main(raiz):
    saida = os.path.join(raiz, 'data')
    os.makedirs(saida, exist_ok=True)
    indice = []
    todos = open(os.path.join(saida, 'itens.jsonl'), 'w', encoding='utf-8')
    for pasta in sorted(os.listdir(raiz)):
        m = re.fullmatch(r'NR-(\d{2})', pasta)
        if not m:
            continue
        nr = int(m.group(1))
        arquivos = sorted(f for f in os.listdir(os.path.join(raiz, pasta)) if f.endswith('.md'))
        principal = f'{pasta}.md' if f'{pasta}.md' in arquivos else arquivos[0]
        partes = []
        for f in arquivos:
            if f != principal and f'{pasta}.md' in arquivos:
                continue
            meta, regs = converter(os.path.join(raiz, pasta, f), nr, f'{pasta}/{f}')
            partes.append((meta, regs))
        meta, regs = partes[0]
        doc = {'versao_esquema': 1, 'gerado_em': date.today().isoformat(), **meta, 'itens': regs}
        json.dump(doc, open(os.path.join(saida, f'{pasta}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        for r in regs:
            todos.write(json.dumps(r, ensure_ascii=False) + '\n')
        indice.append({k: meta[k] for k in ['nr', 'id', 'titulo', 'ultima_alteracao_dou', 'arquivo_md', 'pdf', 'anexos', 'totais', 'revogados']} | {'arquivo_json': f'data/{pasta}.json'})
    todos.close()
    json.dump({'versao_esquema': 1, 'gerado_em': date.today().isoformat(), 'nrs': indice}, open(os.path.join(saida, 'indice.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for i in indice:
        print(i['id'], i['totais'], 'revogados:', i['revogados'])


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
