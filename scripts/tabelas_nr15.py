import json, os, re, subprocess, sys
from datetime import date

FOOTER = re.compile(r'Este texto não substitui')


def layout(pdf):
    t = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-layout', pdf, '-'], capture_output=True, text=True, check=True).stdout
    return [l for l in t.replace('\f', '\n').split('\n') if not FOOTER.search(l)]


def num(s):
    return float(s.replace('.', '').replace(',', '.')) if re.search(r',', s) else (int(s) if s.isdigit() else float(s))


def minutos(s):
    h = re.search(r'(\d+)\s*hora', s)
    m = re.search(r'(\d+)\s*minuto', s)
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def trecho(linhas, inicio, fim):
    i = next(k for k, l in enumerate(linhas) if re.search(inicio, l))
    j = next(k for k in range(i + 1, len(linhas)) if re.search(fim, linhas[k]))
    return linhas[i:j]


def anexo1(linhas):
    bloco = trecho(linhas, r'^\s*ANEXO Nº 1\s*$', r'^1\. Entende-se por Ruído')
    out = []
    for l in bloco:
        m = re.match(r'^\s*(\d{2,3})\s{3,}(.+?)\s*$', l)
        if m:
            out.append({'nivel_db_a': int(m.group(1)), 'maxima_exposicao_diaria': m.group(2), 'maxima_exposicao_minutos': minutos(m.group(2))})
    return out


def anexo3_q1(linhas):
    bloco = trecho(linhas, r'Quadro 1 - Limite de exposição ocupacional ao calor', r'Quadro 2 - Taxa metabólica')
    out = []
    for l in bloco:
        vals = re.findall(r'\d+(?:,\d+)?', l)
        if len(vals) >= 2 and len(vals) % 2 == 0 and all(',' not in v for v in vals[0::2]) and all(',' in v for v in vals[1::2]):
            for m, ib in zip(vals[0::2], vals[1::2]):
                out.append({'taxa_metabolica_w': int(m), 'ibutg_max_c': num(ib)})
    return sorted(out, key=lambda x: x['taxa_metabolica_w'])


def anexo3_q2(linhas):
    bloco = trecho(linhas, r'Quadro 2 - Taxa metabólica', r'^\s*ANEXO Nº 4\s*$')[3:]
    topo = {'Sentado', 'Em pé, agachado ou ajoelhado', 'Em pé, em movimento'}
    itens = []
    cat, sub, subsub = None, None, None
    ultimo = None
    for l in bloco:
        s = l.strip()
        if not s:
            continue
        m = re.match(r'^(.*?\S)\s{2,}(\d{2,4})$', s)
        texto, valor = (m.group(1), int(m.group(2))) if m else (s, None)
        bullet = texto.startswith('•')
        texto = texto.lstrip('• ').strip()
        if valor is None and ultimo is not None and (texto[:1].islower() or texto.startswith('(')):
            if ultimo == 'hdr':
                if subsub:
                    subsub += ' ' + texto
                else:
                    sub += ' ' + texto
            else:
                itens[-1]['atividade'] += ' ' + texto
            continue
        if valor is None and texto in topo:
            cat, sub, subsub = texto, None, None
            ultimo = 'hdr'
            continue
        if valor is None and re.match(r'^\d\.\s', texto):
            subsub = texto
            ultimo = 'hdr'
            continue
        if valor is None:
            sub, subsub = texto, None
            ultimo = 'hdr'
            continue
        if not bullet:
            sub, subsub = None, None
        itens.append({'categoria': cat, 'subcategoria': sub, 'grupo': subsub, 'atividade': texto, 'taxa_metabolica_w': valor})
        ultimo = 'item'
    for it in itens:
        it['atividade'] = it['atividade'].replace('minu- to', 'minuto')
        if it['subcategoria']:
            it['subcategoria'] = it['subcategoria'].replace('minu- to', 'minuto')
    return itens


GRAU = r'(máximo|médio|mínimo|-|_)'


def anexo11_q1(linhas):
    bloco = trecho(linhas, r'TABELA DE LIMITES DE TOLERÂNCIA', r'^\s*ANEXO Nº 12\s*$')
    rows = []
    for l in bloco:
        if not l.strip() or re.match(r'^\s*\*', l) or re.search(r'AGENTES QUÍMICOS|Grau de|Absorção|Valor\s*$|teto|p/pele|ppm\*|caracterização', l):
            continue
        asf0 = re.search(r'A\w*f\w*x\w*\s+simples', l)
        m = None if asf0 else re.match(r'^\s*(\S.*?)\s{2,}(?:(\+)\s+)?(?:(\+)\s+)?(\S+)\s+(\S+)\s+' + GRAU + r'\s*$', l)
        so_mg = re.match(r'^\s*(\S.*?)\s{2,}(?:(\+)\s+)?(?:(\+)\s+)?(\d[\d,]*)\s+' + GRAU + r'\s*$', l)
        asf = re.match(r'^\s*(\S.*?)\s{2,}(?:(\+)\s+)?(?:(\+)\s+)?(A\w*f\w*x\w*\s+simples)\s+' + GRAU + r'\s*$', l)
        exc = re.match(r'^\s*(\S.*?)\s{2,}(\(Exclu[ií]d.*\))\s*$', l)
        if exc:
            rows.append({'agente': exc.group(1).strip(), 'status': 'excluido', 'nota': exc.group(2).strip('()'), '_linha': l})
            continue
        if so_mg and not m and not asf:
            nome = so_mg.group(1).strip()
            ref_col = l.index(so_mg.group(4), len(so_mg.group(1)))
            pos_plus = [mt.start() for mt in re.finditer(r'(?<=\s)\+(?=\s)', l)]
            rows.append({'agente': nome, '_plus': [ref_col - 10 - p for p in pos_plus], 'ppm': None, 'mg': so_mg.group(4), 'grau': so_mg.group(5), 'asfixiante': False, '_linha': l})
            continue
        if asf or m:
            mm = asf or m
            nome = mm.group(1).strip()
            pos_plus = [mt.start() for mt in re.finditer(r'(?<=\s)\+(?=\s)', l)]
            if asf:
                ppm, mg, grau, asfix = None, None, asf.group(5), True
                ref_col = l.index(asf.group(4))
            else:
                ppm, mg, grau, asfix = m.group(4), m.group(5), m.group(6), False
                ref_col = l.rindex(m.group(4), 0, l.rindex(m.group(5)))
            rows.append({'agente': nome, '_plus': [ref_col - p for p in pos_plus], 'ppm': ppm, 'mg': mg, 'grau': grau, 'asfixiante': asfix, '_linha': l})
            continue
        if l.strip() == 'e':
            continue
        if rows and l.strip() and not re.match(r'^\s*\(\d\)', l):
            rows[-1]['agente'] += ' ' + l.strip()
    notas = {}
    for l in bloco:
        mn = re.match(r'^\s*\((\d)\)\s*\((.+)\)\s*$', l)
        if mn:
            notas[mn.group(1)] = mn.group(2)
    out = []
    for r in rows:
        nref = re.search(r'\((\d)\)$', r['agente'].strip())
        if nref:
            r['agente'] = r['agente'].strip()[:nref.start()].strip()
            r['nota'] = notas.get(nref.group(1))
        if r.get('status') == 'excluido':
            out.append({'agente': r['agente'], 'vide': None, 'valor_teto': False, 'absorcao_pele': False, 'asfixiante_simples': False,
                        'ppm': None, 'mg_m3': None, 'grau_insalubridade': None, 'status': 'excluido', 'nota': r['nota']})
            continue
        teto = pele = False
        dists = r['_plus']
        if len(dists) >= 2:
            teto = pele = True
        elif len(dists) == 1:
            if dists[0] >= 15:
                teto = True
            else:
                pele = True
        nome = re.sub(r'\s+', ' ', r['agente'])
        vide = re.search(r'\(vide\s+([^)]+)\)?', nome)
        def val(x):
            if x in (None, '-', '_'):
                return None
            try:
                return num(x)
            except ValueError:
                return x
        out.append({
            'agente': nome,
            'vide': vide.group(1).strip() if vide else None,
            'valor_teto': teto,
            'absorcao_pele': pele,
            'asfixiante_simples': r['asfixiante'],
            'ppm': val(r['ppm']),
            'mg_m3': val(r['mg']),
            'grau_insalubridade': None if r['grau'] in ('-', '_') else r['grau'],
            'status': 'remissivo' if vide and r['grau'] in ('-', '_') else 'vigente',
            'nota': r.get('nota'),
        })
    return out


def anexo11_q2(linhas):
    bloco = trecho(linhas, r'^\s*QUADRO Nº 2\s*$', r'^8\. O limite de tolerância')[1:]
    faixas, fds = [], []
    for l in bloco:
        a = re.match(r'^\s*(\d+)\s+a\s+(\d+)(?:\s+(\d+(?:,\d+)?))?\s*$', l)
        b = re.match(r'^\s*acima de\s+(\d+)', l)
        if a:
            faixas.append((int(a.group(1)), int(a.group(2))))
            if a.group(3):
                fds.append(num(a.group(3)))
        elif b:
            faixas.append((int(b.group(1)), None))
        else:
            for v in re.findall(r'(?<![\w,])(\d+(?:,\d+)?)\s*$', l):
                fds.append(num(v))
    return [{'lt_de': f[0], 'lt_ate': f[1], 'fator_desvio': fd} for f, fd in zip(faixas, fds)]


def main(raiz):
    pasta = os.path.join(raiz, 'NR-15', 'pdf')
    pdf = os.path.join(pasta, next(f for f in os.listdir(pasta) if f.endswith('.pdf')))
    linhas = layout(pdf)
    meta = {'versao_esquema': 1, 'gerado_em': date.today().isoformat(), 'fonte': {'nr': 15, 'pdf': os.path.relpath(pdf, raiz)}}
    dados = {
        'anexo_1_ruido': {'titulo': 'Limites de tolerância para ruído contínuo ou intermitente', 'valores': anexo1(linhas)},
        'anexo_3_calor_quadro_1': {'titulo': 'Limite de exposição ocupacional ao calor', 'valores': anexo3_q1(linhas)},
        'anexo_3_calor_quadro_2': {'titulo': 'Taxa metabólica por tipo de atividade', 'valores': anexo3_q2(linhas)},
        'anexo_11_quadro_1': {'titulo': 'Tabela de limites de tolerância - agentes químicos', 'unidades': {'ppm': 'partes de vapor ou gás por milhão de partes de ar contaminado', 'mg_m3': 'miligramas por metro cúbico de ar'}, 'jornada': 'até 48 horas/semana', 'valores': anexo11_q1(linhas)},
        'anexo_11_quadro_2': {'titulo': 'Fator de desvio (valor máximo = L.T. x F.D.)', 'valores': anexo11_q2(linhas)},
    }
    saida = os.path.join(raiz, 'data', 'tabelas')
    os.makedirs(saida, exist_ok=True)
    json.dump(meta | dados, open(os.path.join(saida, 'nr15-limites-tolerancia.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for k, v in dados.items():
        print(k, len(v['valores']))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
