import re
from difflib import SequenceMatcher

class PDFComparator:
    def __init__(self):
        self.mapa_sinonimos = {
            'SALARIO': ['SALARIO', 'SALÁRIO', 'REMUNERAÇÃO', 'VENCIMENTO', 'SUBSIDIO', 'SUBSÍDIO'],
            'INSS': ['INSS', 'PREVIDÊNCIA', 'CONTRIBUIÇÃO SOCIAL'],
            'IRPF': ['IRPF', 'IRRF', 'IMPOSTO DE RENDA', 'I.R.R.F'],
            'PENSAO': ['PENSAO', 'PENSÃO', 'ALIMENTÍCIAS', 'ALIMENTOS', 'JUDICIAL'],
            'BENEFICIOS': ['CESTA BASICA', 'VALE ALIMENTAÇÃO', 'AUXÍLIO REFEIÇÃO'],
        }
        self.filtros_ativos = list(self.mapa_sinonimos.keys())

    def normalizar_texto(self, texto):
        texto = texto.upper()
        substituicoes = {'Ç': 'C', 'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U', 'Ã': 'A', 'Õ': 'O'}
        for antigo, novo in substituicoes.items():
            texto = texto.replace(antigo, novo)
        return re.sub(r'[^A-Z0-9]', '', texto)

    def extrair_dados_pdf(self, text):
        dados = []
        # Regex melhorada
        matches = re.finditer(
            r'^\s*([^\n\d]+?)\s+([\d]{1,3}(?:\.\d{3})*(?:,\d{2})?)\n',
            text, re.MULTILINE  # Adicionada flag MULTILINE
        )
        for match in matches:
            descricao = match.group(1).strip()
            valor_str = match.group(2).replace('.', '').replace(',', '.')
            try:
                valor = float(valor_str)
                item = {
                    'descricao': descricao,
                    'valor': valor,
                    'normalizado': self.normalizar_texto(descricao)
                }
                if any(any(sin in item['normalizado'] for sin in self.mapa_sinonimos[categoria]) for categoria in self.filtros_ativos):
                    dados.append(item)
            except ValueError:
                print(f"Valor inválido: {match.group(2)}")
                continue
        return dados

    def eh_similar(self, item1, item2, filtros=None):
        if filtros is None:
            filtros = self.filtros_ativos

        for categoria in filtros:
            sinonimos = self.mapa_sinonimos.get(categoria, [])
            if (any(sin in item1['normalizado'] for sin in sinonimos) and
                    any(sin in item2['normalizado'] for sin in sinonimos)):
                return True

        return SequenceMatcher(None, item1['normalizado'], item2['normalizado']).ratio() > 0.7

    def comparar_pdfs(self, dados_mestre, dados_secundario, filtros=None):
        if filtros is None:
            filtros = self.filtros_ativos

        resultados = {
            'correspondencias': [],
            'erros_potenciais': [],
            'exclusivos_mestre': [],
            'exclusivos_secundario': []
        }

        dados_mestre_filtrados = [
            item for item in dados_mestre
            if any(sin in item['normalizado'] for cat in filtros for sin in self.mapa_sinonimos[cat])
        ]
        dados_secundario_filtrados = [
            item for item in dados_secundario
            if any(sin in item['normalizado'] for cat in filtros for sin in self.mapa_sinonimos[cat])
        ]

        for categoria in filtros:
            sinonimos = self.mapa_sinonimos[categoria]
            for item_m in [i for i in dados_mestre_filtrados if any(sin in i['normalizado'] for sin in sinonimos)]:
                for item_s in [i for i in dados_secundario_filtrados if any(sin in i['normalizado'] for sin in sinonimos)]:
                    diff = abs(item_m['valor'] - item_s['valor'])
                    diff_pct = (diff / item_m['valor']) * 100 if item_m['valor'] != 0 else 0

                    if diff_pct > 10:
                        resultados['erros_potenciais'].append({
                            'categoria': categoria,
                            'descricao_mestre': item_m['descricao'],
                            'descricao_secundario': item_s['descricao'],
                            'valor_mestre': item_m['valor'],
                            'valor_secundario': item_s['valor'],
                            'diferenca_absoluta': diff,
                            'diferenca_percentual': diff_pct,
                            'severidade': 'CRITICA' if diff_pct > 50 else 'ALTA' if diff_pct > 20 else 'MEDIA'
                        })

        resultados['exclusivos_mestre'] = [
            item for item in dados_mestre_filtrados
            if not any(self.eh_similar(item, item_s, filtros) for item_s in dados_secundario_filtrados)
        ]
        resultados['exclusivos_secundario'] = [
            item for item in dados_secundario_filtrados
            if not any(self.eh_similar(item, item_m, filtros) for item_m in dados_mestre_filtrados)
        ]

        return resultados
