import json, os, re, subprocess, sys
from datetime import date

ROW = re.compile(r'^\s*(.*?\S)\s+(\d{6}-\d)(?:\s+(\d)\s+([SMsm]))?\s*$|^\s*(\d{6}-\d)(?:\s+(\d)\s+([SMsm]))?\s*$')
NR_HDR = re.compile(r'^\s*NR[\s-](\d{1,2})(?:\s*[-–]\s*(ANEXO|Anexo)\s+([\w-]+))?\s*(\([^)]*\))?\s*$')
COL_HDR = re.compile(r'^\s*(Item/Subitem|ITEM/SUBITEM)\b', re.I)
PORT_HDR = re.compile(r'^\s*\(?Portaria\b.*\d{4}.*\)?\s*$')
FOOTER = re.compile(r'Este texto não substitui')
FAIXA = re.compile(r'^\s*(\d{2,3}-\d{2,4}|Mais de)\s*(.*)$')


def texto_layout(pdf):
    return subprocess.run(['pdftotext', '-enc', 'UTF-8', '-layout', pdf, '-'], capture_output=True, text=True, check=True).stdout


def romano(s):
    v = {'I': 1, 'V': 5, 'X': 10, 'L': 50}
    t = 0
    for a, b in zip(s, s[1:] + ' '):
        t += -v[a] if v.get(b, 0) > v[a] else v[a]
    return t


def referencias(item):
    refs = []
    base = None
    alinea = None
    for tok in re.finditer(r'(\d{1,2}(?:\.\d+)+|(?<![\d.])\d{1,2}(?![\d.]))|al[íi]neas?\s+((?:"[a-z]{1,2}"(?:\s*,\s*|\s+e\s+)?)+)|incisos?\s+((?:"?[IVXL]+"?(?:\s*,\s*|\s+e\s+)?)+)', item):
        if tok.group(1):
            base = tok.group(1)
            alinea = None
            refs.append(base)
        elif tok.group(2) and base:
            letras = re.findall(r'"([a-z]{1,2})"', tok.group(2))
            if refs and refs[-1] == base:
                refs.pop()
            for l in letras:
                refs.append(f'{base}.{l})')
            alinea = letras[-1] if letras else None
        elif tok.group(3) and base:
            roms = re.findall(r'"?([IVXL]+)"?', tok.group(3))
            if alinea and refs and refs[-1] == f'{base}.{alinea})':
                refs.pop()
            for r in roms:
                refs.append(f'{base}.{alinea}).{r}' if alinea else f'{base}.{r}')
    out = []
    for r in refs:
        if r not in out:
            out.append(r)
    return out


def carregar_ids(raiz):
    ids = {}
    pasta = os.path.join(raiz, 'data')
    for f in os.listdir(pasta):
        m = re.fullmatch(r'NR-(\d{2})\.json', f)
        if not m:
            continue
        d = json.load(open(os.path.join(pasta, f), encoding='utf-8'))
        ids[int(m.group(1))] = {r['id'] for r in d['itens']}
    return ids


def resolver(nr, anexo, ref, ids):
    conj = ids.get(nr, set())
    pre = f'NR-{nr:02d}'
    cands = []
    if anexo:
        cands.append(f'{pre}/ANEXO-{anexo}/{ref}')
        if re.fullmatch(r'[IVXL]+', anexo):
            cands.append(f'{pre}/ANEXO-{romano(anexo)}/{ref}')
        elif anexo.isdigit():
            cands.append(f'{pre}/ANEXO-{anexo}/{ref}')
    cands.append(f'{pre}/{ref}')
    m = re.fullmatch(r'(.+)\.([a-z]{1,2})\)\.([IVXL]+)', ref)
    if m:
        cands.append(f'{pre}/{m.group(1)}.{m.group(3)}')
    for c in cands:
        if c in conj:
            return c
    if anexo:
        alvos = {f'ANEXO-{anexo}', f'ANEXO-{romano(anexo)}' if re.fullmatch(r'[IVXL]+', anexo) else f'ANEXO-{anexo}'}
        for x in sorted(conj):
            partes = x.split('/')
            if len(partes) == 3 and partes[2] == ref and any(partes[1] == a or partes[1].startswith(a + '-B') for a in alvos):
                return x
    return None


def infracoes(linhas, ids):
    linhas = list(linhas)
    for i in range(len(linhas) - 2):
        a, b, c = linhas[i].strip(), linhas[i + 1], linhas[i + 2].strip()
        mb = re.match(r'^\s*(.*?)\s{2,}(\d)\s+([SM])\s*$', b)
        if re.fullmatch(r'\d{6}-', a) and re.fullmatch(r'\d', c) and mb:
            linhas[i] = ''
            linhas[i + 1] = f'{mb.group(1)}   {a}{c}   {mb.group(2)}   {mb.group(3)}'
            linhas[i + 2] = ''
    i0 = next(i for i, l in enumerate(linhas) if l.strip() == 'ANEXO II')
    toks = []
    nr, anexo = None, None
    for l in linhas[i0 + 1:]:
        if not l.strip() or FOOTER.search(l):
            continue
        m = NR_HDR.match(l)
        if m:
            nr, anexo = int(m.group(1)), (m.group(3).upper() if m.group(3) else None)
            toks.append(('hdr', None))
            continue
        if COL_HDR.match(l) or l.strip() == 'NORMAS REGULAMENTADORAS - NR' or (PORT_HDR.match(l) and not ROW.match(l)):
            toks.append(('hdr', None))
            continue
        m = ROW.match(l)
        if m:
            if m.group(2):
                toks.append(('row', dict(nr=nr, anexo=anexo, item=m.group(1).strip(), codigo=m.group(2), infracao=int(m.group(3)) if m.group(3) else None, tipo=m.group(4).upper() if m.group(4) else None)))
            else:
                toks.append(('row', dict(nr=nr, anexo=anexo, item='', codigo=m.group(5), infracao=int(m.group(6)) if m.group(6) else None, tipo=m.group(7).upper() if m.group(7) else None)))
            continue
        toks.append(('txt', l.strip()))
    regs = []
    k = 0
    while k < len(toks):
        t, v = toks[k]
        if t == 'row':
            if not v['item']:
                antes = []
                j = k - 1
                while j >= 0 and toks[j][0] == 'txt':
                    antes.insert(0, toks[j][1])
                    j -= 1
                depois = []
                j = k + 1
                while j < len(toks) and toks[j][0] == 'txt':
                    depois.append(toks[j][1])
                    j += 1
                v['item'] = ' '.join(antes + depois)
                for jj in range(k - len(antes), k):
                    toks[jj] = ('used', None)
                for jj in range(k + 1, k + 1 + len(depois)):
                    toks[jj] = ('used', None)
            else:
                j = k + 1
                extra = []
                while j < len(toks) and toks[j][0] == 'txt' and not (j + 1 < len(toks) and toks[j + 1][0] == 'row' and not toks[j + 1][1]['item']):
                    extra.append(toks[j][1])
                    toks[j] = ('used', None)
                    j += 1
                if extra:
                    v['item'] = ' '.join([v['item']] + extra)
            regs.append(v)
        k += 1
    sobras = [v for t, v in toks if t == 'txt']
    out = []
    for v in regs:
        nota = re.search(r'\((Port[^)]*)\)\s*$', v['item'])
        item = v['item'][:nota.start()].strip() if nota else v['item']
        refs = referencias(item)
        out.append({
            'codigo': v['codigo'],
            'nr': v['nr'],
            'anexo': v['anexo'],
            'item': item,
            'referencias': refs,
            'itens_relacionados': [x for x in (resolver(v['nr'], v['anexo'], r, ids) for r in refs) if x],
            'infracao': v['infracao'],
            'tipo': v['tipo'],
            'tipo_descricao': {'S': 'Segurança do Trabalho', 'M': 'Medicina do Trabalho'}.get(v['tipo']),
            'nota': nota.group(1) if nota else None,
        })
    return out, sobras


def faixas(bloco, unidade):
    linhas = [l for l in bloco.split('\n') if l.strip()]
    res = []
    pend = None
    for l in linhas:
        s = l.strip()
        if s == 'Mais de':
            pend = 'Mais de 1000'
            continue
        if s == '1000' and pend:
            continue
        m = FAIXA.match(l)
        nums = re.findall(r'\d[\d.]*,\d{2}|\d+-\d+', s)
        if m and m.group(1) != 'Mais de' and re.fullmatch(r'\d{2,3}-\d{2,4}', m.group(1)):
            faixa = m.group(1)
            nums = nums[1:]
        elif pend and nums:
            faixa = pend
            pend = None
        else:
            continue
        if unidade == 'BTN':
            pares = [tuple(int(x) for x in n.split('-')) for n in nums]
        else:
            vals = [float(n.replace('.', '').replace(',', '.')) for n in nums]
            pares = list(zip(vals[0::2], vals[1::2]))
        res.append((faixa, pares))
    return res


def gradacao(texto):
    p4 = texto[texto.index('GRADAÇÃO DE MULTAS (EM BTN)'):texto.index('ANEXO IA')]
    a1 = []
    for faixa, pares in faixas(p4, 'BTN'):
        for idx, (mn, mx) in enumerate(pares):
            a1.append({'tipo': 'S' if idx < 4 else 'M', 'faixa_empregados': faixa, 'infracao': idx % 4 + 1, 'minimo': mn, 'maximo': mx})
    ia = texto[texto.index('ANEXO IA'):texto.index('ANEXO II\n') if 'ANEXO II\n' in texto else None]
    seg = ia[ia.index('SEGURANÇA DO TRABALHO'):ia.index('MEDICINA DO TRABALHO')]
    med = ia[ia.index('MEDICINA DO TRABALHO'):]
    med = med[:med.index('ANEXO II')] if 'ANEXO II' in med else med
    a1a = []
    for tipo, bloco in (('S', seg), ('M', med)):
        for faixa, pares in faixas(bloco, 'R$'):
            for idx, (mn, mx) in enumerate(pares):
                a1a.append({'tipo': tipo, 'faixa_empregados': faixa, 'infracao': idx + 1, 'minimo': mn, 'maximo': mx})
    return {
        'anexo_I': {'titulo': 'Gradação de multas', 'unidade': 'BTN', 'valores': a1},
        'anexo_IA': {'titulo': 'Valor das multas específicas de trabalho portuário (NR-29)', 'unidade': 'R$', 'valores': a1a},
    }


def main(raiz):
    pdf = next(os.path.join(raiz, 'NR-28', 'pdf', f) for f in os.listdir(os.path.join(raiz, 'NR-28', 'pdf')) if f.endswith('.pdf'))
    texto = texto_layout(pdf).replace('\f', '\n')
    ids = carregar_ids(raiz)
    regs, sobras = infracoes(texto.split('\n'), ids)
    saida = os.path.join(raiz, 'data', 'tabelas')
    os.makedirs(saida, exist_ok=True)
    fonte = {'nr': 28, 'pdf': os.path.relpath(pdf, raiz)}
    json.dump({'versao_esquema': 1, 'gerado_em': date.today().isoformat(), 'fonte': fonte | {'anexo': 'II'}, 'total': len(regs), 'infracoes': regs},
              open(os.path.join(saida, 'nr28-infracoes.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump({'versao_esquema': 1, 'gerado_em': date.today().isoformat(), 'fonte': fonte, **gradacao(texto)},
              open(os.path.join(saida, 'nr28-gradacao-multas.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('infrações:', len(regs), 'linhas não usadas:', len(sobras))
    for s in sobras[:40]:
        print('  sobra:', s)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
