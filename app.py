from flask import Flask, render_template, request, jsonify
import PyPDF2
import re
import os
from difflib import SequenceMatcher
from werkzeug.utils import secure_filename
import logging

# Configuração básica de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

class PDFComparator:
    def __init__(self):
        self.mapa_sinonimos = {
            'SALARIO': ['SALARIO', 'SALÁRIO', 'REMUNERAÇÃO', 'VENCIMENTO', 'SUBSIDIO', 'SUBSÍDIO'],
            'INSS': ['INSS', 'PREVIDÊNCIA', 'CONTRIBUIÇÃO SOCIAL'],
            'IRPF': ['IRPF', 'IRRF', 'IMPOSTO DE RENDA', 'I.R.R.F'],
            'PENSAO': ['PENSAO', 'PENSÃO', 'ALIMENTÍCIAS', 'ALIMENTOS', 'JUDICIAL'],
            'BENEFICIOS': ['CESTA BASICA', 'VALE ALIMENTAÇÃO', 'AUXÍLIO REFEIÇÃO'],
        }
        self.filtros_ativos = list(self.mapa_sinonimos.keys())  # Todas ativas por padrão

    def normalizar_texto(self, texto):
        """Padroniza texto para comparação (remove acentos, espaços, etc.)"""
        texto = texto.upper()
        substituicoes = {'Ç':'C', 'Á':'A', 'É':'E', 'Í':'I', 'Ó':'O', 'Ú':'U', 'Ã':'A', 'Õ':'O'}
        for antigo, novo in substituicoes.items():
            texto = texto.replace(antigo, novo)
        return re.sub(r'[^A-Z0-9]', '', texto)

    def extrair_dados_pdf(self, filepath):
        """Extrai dados de PDFs com tratamento robusto"""
        dados = []
        try:
            with open(filepath, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                logger.info(f"Processando PDF: {filepath} ({len(reader.pages)} páginas)")

                for page in reader.pages:
                    text = page.extract_text()
                    if not text:
                        continue

                    # Regex melhorado (captura descrição + valor)
                    matches = re.finditer(
                        r'(?:^|\n)([^\n\d]+?)\s+([\d]{1,3}(?:\.\d{3})*(?:,\d{2})?)', 
                        text
                    )
                    
                    for match in matches:
                        descricao = match.group(1).strip()
                        valor_str = match.group(2).replace('.', '').replace(',', '.')
                        try:
                            valor = float(valor_str)
                            dados.append({
                                'descricao': descricao,
                                'valor': valor,
                                'normalizado': self.normalizar_texto(descricao)
                            })
                            logger.debug(f"Item extraído: {descricao} = {valor}")
                        except ValueError:
                            logger.warning(f"Valor inválido: {match.group(2)}")
                            continue

        except Exception as e:
            logger.error(f"Erro ao extrair PDF: {str(e)}", exc_info=True)
        
        return dados

    def eh_similar(self, item1, item2, filtros=None):
        """Compara itens com sinônimos + similaridade textual, considerando filtros"""
        if filtros is None:
            filtros = self.filtros_ativos
        
        for categoria in filtros:
            sinonimos = self.mapa_sinonimos.get(categoria, [])
            if (any(sin in item1['normalizado'] for sin in sinonimos) and 
                any(sin in item2['normalizado'] for sin in sinonimos)):
                return True
        
        return SequenceMatcher(None, item1['normalizado'], item2['normalizado']).ratio() > 0.7

    def comparar_pdfs(self, mestre_path, secundario_path, filtros=None):
        """Compara dois PDFs e retorna discrepâncias, considerando filtros"""
        if filtros is None:
            filtros = self.filtros_ativos

        dados_mestre = self.extrair_dados_pdf(mestre_path)
        dados_secundario = self.extrair_dados_pdf(secundario_path)

        resultados = {
            'correspondencias': [],
            'erros_potenciais': [],
            'exclusivos_mestre': [],
            'exclusivos_secundario': []
        }

        # Filtra itens baseados nas categorias selecionadas
        dados_mestre_filtrados = [
            item for item in dados_mestre
            if any(sin in item['normalizado'] for cat in filtros for sin in self.mapa_sinonimos[cat])
        ]
        dados_secundario_filtrados = [
            item for item in dados_secundario
            if any(sin in item['normalizado'] for cat in filtros for sin in self.mapa_sinonimos[cat])
        ]

        # Identifica correspondências e erros
        for categoria in filtros:
            sinonimos = self.mapa_sinonimos[categoria]
            for item_m in [i for i in dados_mestre_filtrados if any(sin in i['normalizado'] for sin in sinonimos)]:
                for item_s in [i for i in dados_secundario_filtrados if any(sin in i['normalizado'] for sin in sinonimos)]:
                    diff = abs(item_m['valor'] - item_s['valor'])
                    diff_pct = (diff / item_m['valor']) * 100 if item_m['valor'] != 0 else 0

                    if diff_pct > 10:  # Threshold para discrepância
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

        # Identifica itens exclusivos (considerando apenas os filtros)
        resultados['exclusivos_mestre'] = [
            item for item in dados_mestre_filtrados
            if not any(self.eh_similar(item, item_s, filtros) for item_s in dados_secundario_filtrados)
        ]
        resultados['exclusivos_secundario'] = [
            item for item in dados_secundario_filtrados
            if not any(self.eh_similar(item, item_m, filtros) for item_m in dados_mestre_filtrados)
        ]

        return resultados

# Instância global do comparador
comparator = PDFComparator()

@app.route('/')
def index():
    return render_template('index.html', categorias=comparator.mapa_sinonimos.keys())

@app.route('/comparar', methods=['POST'])
def comparar():
    if 'mestre' not in request.files or 'secundario' not in request.files:
        return jsonify({'erro': 'Envie ambos os arquivos'}), 400
    
    filtros = request.form.getlist('filtros[]')
    mestre = request.files['mestre']
    secundario = request.files['secundario']
    
    if mestre.filename == '' or secundario.filename == '':
        return jsonify({'erro': 'Nenhum arquivo selecionado'}), 400
    
    try:
        # Valida extensão
        if not (mestre.filename.lower().endswith('.pdf') and secundario.filename.lower().endswith('.pdf')):
            return jsonify({'erro': 'Apenas arquivos PDF são aceitos'}), 400

        # Salva arquivos temporariamente
        mestre_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(mestre.filename))
        secundario_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(secundario.filename))
        mestre.save(mestre_path)
        secundario.save(secundario_path)

        # Processa comparação com filtros
        resultados = comparator.comparar_pdfs(mestre_path, secundario_path, filtros)
        
        # Limpeza
        os.remove(mestre_path)
        os.remove(secundario_path)
        
        return jsonify(resultados)
    
    except PyPDF2.PdfReadError:
        return jsonify({'erro': 'Arquivo PDF inválido ou corrompido'}), 400
    except Exception as e:
        logger.error(f"Erro durante comparação: {str(e)}", exc_info=True)
        return jsonify({'erro': 'Falha interna ao processar arquivos'}), 500

if __name__ == '__main__':
    app.run(debug=True)