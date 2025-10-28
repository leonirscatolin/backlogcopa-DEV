# VERSÃO v0.9.30-742

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import base64
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from github import Github, Auth, GithubException
from io import StringIO, BytesIO
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageFont
from urllib.parse import quote
import json
import colorsys
import re

st.set_page_config(
    layout="wide",
    page_title="Backlog Copa Energia + Belago",
    page_icon="minilogo.png",
    initial_sidebar_state="collapsed"
)

st.html("""
<style>
#GithubIcon { visibility: hidden; }
.metric-box {
    border: 1px solid #CCCCCC;
    padding: 10px;
    border-radius: 5px;
    text-align: center;
    box-shadow: 0px 2px 4px rgba(0,0,0,0.1);
    margin-bottom: 10px;
    height: 120px; /* Altura fixa para alinhar */
    display: flex; /* Para centralizar verticalmente */
    flex-direction: column; /* Organiza os spans verticalmente */
    justify-content: center; /* Centraliza verticalmente */
}
a.metric-box { /* Estilo para os cards clicáveis da Tab1 */
    display: block;
    color: inherit;
    text-decoration: none !important;
}
a.metric-box:hover {
    background-color: #f0f2f6;
    text-decoration: none !important;
}
.metric-box span { /* Aplica a todos os spans dentro de metric-box */
    display: block;
    width: 100%;
    text-decoration: none !important;
}
.metric-box .label { /* Label (Nome da faixa) */
    font-size: 1em;
    color: #666666;
    margin-bottom: 5px; /* Espaço entre label e value */
}
.metric-box .value { /* Número principal */
    font-size: 2.5em;
    font-weight: bold;
    color: #375623;
}
.metric-box .delta { /* Texto de comparação (delta) */
    font-size: 0.9em;
    margin-top: 5px; /* Espaço entre value e delta */
}
/* Classes para colorir o delta */
.delta-positive { color: #d9534f; } /* Vermelho para aumento */
.delta-negative { color: #5cb85c; } /* Verde para redução */
.delta-neutral { color: #666666; } /* Cinza para sem mudança ou N/A */
</style>
""")


@st.cache_resource
def get_github_repo():
    try:
        expected_repo_name = st.secrets.get("EXPECTED_REPO")
        if not expected_repo_name:
            st.error("Configuração de segurança incompleta. O segredo do repositório não foi encontrado.")
            st.stop()
        auth = Auth.Token(st.secrets["GITHUB_TOKEN"])
        g = Github(auth=auth)
        return g.get_repo(expected_repo_name)
    except GithubException as e:
        if e.status == 404:
            st.error("Erro de segurança: O token não tem acesso ao repositório esperado ou o repositório não existe.")
            st.stop()
        st.error(f"Erro de conexão com o repositório: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Erro de conexão com o repositório: {e}")
        st.stop()

def update_github_file(_repo, file_path, file_content, commit_message):
    try:
        contents = _repo.get_contents(file_path)
        if isinstance(file_content, str):
            file_content = file_content.encode('utf-8')
        _repo.update_file(contents.path, commit_message, file_content, contents.sha)
        if file_path not in ["contacted_tickets.json", "ticket_observations.json", "datas_referencia.txt"]: # Evitar spam de msg
            st.sidebar.info(f"Arquivo '{file_path}' atualizado.")
    except GithubException as e:
        if e.status == 404:
            if isinstance(file_content, str):
                file_content = file_content.encode('utf-8')
            _repo.create_file(file_path, commit_message, file_content)
            if file_path not in ["contacted_tickets.json", "ticket_observations.json", "datas_referencia.txt"]: # Evitar spam de msg
                st.sidebar.info(f"Arquivo '{file_path}' criado.")
        else:
            st.sidebar.error(f"Falha ao salvar '{file_path}': {e}")
            raise # Re-levanta a exceção para o bloco superior tratar

@st.cache_data(ttl=300)
def read_github_file(_repo, file_path):
    try:
        content_file = _repo.get_contents(file_path)
        content_bytes = content_file.decoded_content

        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content = content_bytes.decode("latin-1")
                if file_path == "dados_fechados.csv":
                    st.sidebar.warning(f"Arquivo '{file_path}' lido com encoding 'latin-1'. Verifique se o arquivo foi salvo corretamente.")
            except Exception as decode_err:
                st.error(f"Não foi possível decodificar o arquivo '{file_path}' com utf-8 ou latin-1: {decode_err}")
                return pd.DataFrame()

        if not content.strip():
            return pd.DataFrame()

        try:
            df = pd.read_csv(StringIO(content), delimiter=';', encoding='utf-8',
                             dtype={'ID do ticket': str, 'ID do Ticket': str}, low_memory=False,
                             on_bad_lines='warn')
        except pd.errors.ParserError as parse_err:
            st.error(f"Erro ao parsear o CSV '{file_path}': {parse_err}. Verifique o delimitador (;) e a estrutura do arquivo.")
            return pd.DataFrame()
        except Exception as read_err:
            st.error(f"Erro inesperado ao ler o conteúdo CSV de '{file_path}': {read_err}")
            return pd.DataFrame()

        df.columns = df.columns.str.strip()
        df.dropna(how='all', inplace=True)
        return df

    except GithubException as e:
        if e.status == 404:
            return pd.DataFrame()
        st.error(f"Erro ao acessar o arquivo do GitHub '{file_path}': {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro inesperado ao ler o arquivo '{file_path}': {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def read_github_text_file(_repo, file_path):
    try:
        content_file = _repo.get_contents(file_path)
        content = content_file.decoded_content.decode("utf-8")
        dates = {}
        for line in content.strip().split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                dates[key.strip()] = value.strip()
        return dates
    except GithubException as e:
        if e.status == 404: # Arquivo pode não existir na primeira vez
            return {}
        else:
            st.warning(f"Erro ao ler {file_path}: {e}")
            return {}
    except Exception as e:
        st.warning(f"Erro inesperado ao ler {file_path}: {e}")
        return {}


@st.cache_data(ttl=300)
def read_github_json_dict(_repo, file_path):
    try:
        file_content = _repo.get_contents(file_path).decoded_content.decode("utf-8")
        return json.loads(file_content) if file_content else {}
    except GithubException as e:
        if e.status == 404: return {}
        st.error(f"Erro ao carregar JSON '{file_path}': {e}")
        return {}
    except json.JSONDecodeError:
        st.error(f"Erro ao decodificar JSON '{file_path}'. Verifique o conteúdo.")
        return {}
    except Exception as e:
        st.error(f"Erro inesperado ao ler JSON '{file_path}': {e}")
        return {}

def process_uploaded_file(uploaded_file):
    if uploaded_file is None:
        return None
    try:
        dtype_spec = {'ID do ticket': str, 'ID do Ticket': str, 'ID': str}
        if uploaded_file.name.endswith('.xlsx'):
            df = pd.read_excel(uploaded_file, dtype=dtype_spec)
        else:
            try:
                content = uploaded_file.getvalue().decode('utf-8')
            except UnicodeDecodeError:
                content = uploaded_file.getvalue().decode('latin1')
            df = pd.read_csv(StringIO(content), delimiter=';', dtype=dtype_spec)
        df.columns = df.columns.str.strip()

        df.dropna(how='all', inplace=True)

        output = StringIO()
        df.to_csv(output, index=False, sep=';', encoding='utf-8')
        return output.getvalue().encode('utf-8')
    except Exception as e:
        st.sidebar.error(f"Erro ao ler o arquivo {uploaded_file.name}: {e}")
        return None

def processar_dados_comparativos(df_atual, df_15dias):
    contagem_atual = df_atual.groupby('Atribuir a um grupo').size().reset_index(name='Atual')
    contagem_15dias = df_15dias.groupby('Atribuir a um grupo').size().reset_index(name='15 Dias Atrás')
    df_comparativo = pd.merge(contagem_atual, contagem_15dias, on='Atribuir a um grupo', how='outer').fillna(0)
    df_comparativo['Diferença'] = df_comparativo['Atual'] - df_comparativo['15 Dias Atrás']
    df_comparativo[['Atual', '15 Dias Atrás', 'Diferença']] = df_comparativo[['Atual', '15 Dias Atrás', 'Diferença']].astype(int)
    return df_comparativo

@st.cache_data
def categorizar_idade_vetorizado(dias_series):
    condicoes = [
        dias_series >= 30, (dias_series >= 21) & (dias_series <= 29),
        (dias_series >= 11) & (dias_series <= 20), (dias_series >= 6) & (dias_series <= 10),
        (dias_series >= 3) & (dias_series <= 5), (dias_series >= 0) & (dias_series <= 2)
    ]
    opcoes = ["30+ dias", "21-29 dias", "11-20 dias", "6-10 dias", "3-5 dias", "0-2 dias"]
    return np.select(condicoes, opcoes, default="Erro de Categoria")

@st.cache_data
def analisar_aging(_df_atual):
    df = _df_atual.copy()
    date_col_name = None
    if 'Data de criação' in df.columns: date_col_name = 'Data de criação'
    elif 'Data de Criacao' in df.columns: date_col_name = 'Data de Criacao'
    if not date_col_name:
        return pd.DataFrame()
    df[date_col_name] = pd.to_datetime(df[date_col_name], errors='coerce')
    linhas_invalidas = df[df[date_col_name].isna()]
    if not linhas_invalidas.empty:
        with st.expander(f"⚠️ Atenção: {len(linhas_invalidas)} chamados foram descartados por data inválida ou vazia."):
            st.dataframe(linhas_invalidas.head())
    df.dropna(subset=[date_col_name], inplace=True)
    hoje = pd.to_datetime('today').normalize()
    data_criacao_normalizada = df[date_col_name].dt.normalize()
    dias_calculados = (hoje - data_criacao_normalizada).dt.days
    df['Dias em Aberto'] = (dias_calculados - 1).clip(lower=0)
    df['Faixa de Antiguidade'] = categorizar_idade_vetorizado(df['Dias em Aberto'])
    return df

def get_status(row):
    diferenca = row['Diferença']
    if diferenca > 0: return "Alta Demanda"
    elif diferenca == 0: return "Estável / Atenção"
    else: return "Redução de Backlog"

def get_image_as_base64(path):
    try:
        with open(path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode()
    except FileNotFoundError:
        return None

def sync_ticket_data():
    if 'ticket_editor' not in st.session_state or not st.session_state.ticket_editor.get('edited_rows'):
        return
    edited_rows = st.session_state.ticket_editor['edited_rows']
    contact_changed = False
    observation_changed = False
    for row_index, changes in edited_rows.items():
        try:
            ticket_id = str(st.session_state.last_filtered_df.iloc[row_index]['ID do ticket'])
            if 'Contato' in changes:
                current_contact_status = ticket_id in st.session_state.contacted_tickets
                new_contact_status = changes['Contato']
                if current_contact_status != new_contact_status:
                    if new_contact_status: st.session_state.contacted_tickets.add(ticket_id)
                    else: st.session_state.contacted_tickets.discard(ticket_id)
                    contact_changed = True
            if 'Observações' in changes:
                current_observation = st.session_state.observations.get(ticket_id, '')
                new_observation = changes['Observações']
                if current_observation != new_observation:
                    st.session_state.observations[ticket_id] = new_observation
                    observation_changed = True
        except IndexError:
            st.warning(f"Erro ao processar linha {row_index}.")
            continue

    if contact_changed or observation_changed:
        now_str = datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')
        if contact_changed:
            data_to_save = list(st.session_state.contacted_tickets)
            json_content = json.dumps(data_to_save, indent=4)
            commit_msg = f"Atualizando contatos em {now_str}"
            update_github_file(st.session_state.repo, "contacted_tickets.json", json_content.encode('utf-8'), commit_msg)
        if observation_changed:
            json_content = json.dumps(st.session_state.observations, indent=4, ensure_ascii=False)
            commit_msg = f"Atualizando observações em {now_str}"
            update_github_file(st.session_state.repo, "ticket_observations.json", json_content.encode('utf-8'), commit_msg)

    st.session_state.ticket_editor['edited_rows'] = {}
    st.session_state.scroll_to_details = True


@st.cache_data(ttl=3600)
def carregar_dados_evolucao(_repo, closed_ticket_ids_list, dias_para_analisar=7):
    try:
        all_files_content = _repo.get_contents("snapshots")
        all_files = [f.path for f in all_files_content]
        df_evolucao_list = []
        end_date = date.today()
        start_date = end_date - timedelta(days=max(dias_para_analisar, 10))

        closed_ids_set = set(closed_ticket_ids_list)

        processed_dates = []
        for file_name in all_files:
            if file_name.startswith("snapshots/backlog_") and file_name.endswith(".csv"):
                try:
                    date_str = file_name.replace("snapshots/backlog_", "").replace(".csv", "")
                    file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if start_date <= file_date <= end_date:
                        processed_dates.append((file_date, file_name))
                except ValueError: continue
                except Exception: continue

        processed_dates.sort(key=lambda x: x[0], reverse=True)
        files_to_process = [f[1] for f in processed_dates[:dias_para_analisar]]

        for file_name in files_to_process:
            try:
                date_str = file_name.replace("snapshots/backlog_", "").replace(".csv", "")
                file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                df_snapshot = read_github_file(_repo, file_name)
                if not df_snapshot.empty and 'Atribuir a um grupo' in df_snapshot.columns:
                    df_snapshot_filtrado_rh = df_snapshot[~df_snapshot['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]
                    id_col_snapshot = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_snapshot_filtrado_rh.columns), None)
                    df_snapshot_final = df_snapshot_filtrado_rh
                    if id_col_snapshot and closed_ids_set:
                        ids_limpos_snapshot = df_snapshot_filtrado_rh[id_col_snapshot].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                        df_snapshot_final = df_snapshot_filtrado_rh[~ids_limpos_snapshot.isin(closed_ids_set)]
                    contagem_diaria = df_snapshot_final.groupby('Atribuir a um grupo').size().reset_index(name='Total Chamados')
                    contagem_diaria['Data'] = pd.to_datetime(file_date)
                    df_evolucao_list.append(contagem_diaria)
            except Exception: continue

        if not df_evolucao_list: return pd.DataFrame()

        df_consolidado = pd.concat(df_evolucao_list, ignore_index=True)
        return df_consolidado.sort_values(by=['Data', 'Atribuir a um grupo'])
    except GithubException as e:
        if e.status == 404: return pd.DataFrame()
        st.warning(f"Não foi possível carregar snapshots: {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar evolução: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def find_closest_snapshot_before(_repo, current_report_date, target_date):
    try:
        all_files_content = _repo.get_contents("snapshots")
        snapshots = []
        search_start_date = target_date - timedelta(days=10)

        for file in all_files_content:
            match = re.search(r"backlog_(\d{4}-\d{2}-\d{2})\.csv", file.path)
            if match:
                snapshot_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                if search_start_date <= snapshot_date <= target_date:
                    snapshots.append((snapshot_date, file.path))

        if not snapshots:
            return None, None

        snapshots.sort(key=lambda x: x[0], reverse=True)
        return snapshots[0]

    except Exception as e:
        st.warning(f"Erro ao buscar snapshots: {e}")
        return None, None

@st.cache_data(ttl=3600)
def carregar_evolucao_aging(_repo, closed_ticket_ids_list, dias_para_analisar=90):
    try:
        all_files_content = _repo.get_contents("snapshots")
        all_files = [f.path for f in all_files_content]
        lista_historico = []

        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=max(dias_para_analisar, 60))

        closed_ids_set = set(closed_ticket_ids_list)

        processed_files = []
        for file_name in all_files:
            if file_name.startswith("snapshots/backlog_") and file_name.endswith(".csv"):
                try:
                    date_str = file_name.replace("snapshots/backlog_", "").replace(".csv", "")
                    file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if start_date <= file_date <= end_date:
                        processed_files.append((file_date, file_name))
                except Exception:
                    continue

        processed_files.sort(key=lambda x: x[0])

        for file_date, file_name in processed_files:
            try:
                df_snapshot = read_github_file(_repo, file_name)
                if df_snapshot.empty:
                    continue

                df_filtrado = df_snapshot[~df_snapshot['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]

                id_col_snapshot = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_filtrado.columns), None)
                if id_col_snapshot and closed_ids_set:
                    ids_limpos_snapshot = df_filtrado[id_col_snapshot].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    df_final = df_filtrado[~ids_limpos_snapshot.isin(closed_ids_set)]
                else:
                    df_final = df_filtrado

                date_col_name = next((col for col in ['Data de criação', 'Data de Criacao'] if col in df_final.columns), None)
                if not date_col_name:
                    continue

                df_final[date_col_name] = pd.to_datetime(df_final[date_col_name], errors='coerce')
                df_final.dropna(subset=[date_col_name], inplace=True)

                snapshot_date_dt = pd.to_datetime(file_date)
                data_criacao_normalizada = df_final[date_col_name].dt.normalize()
                dias_calculados = (snapshot_date_dt - data_criacao_normalizada).dt.days
                dias_em_aberto_corrigido = (dias_calculados - 1).clip(lower=0)

                faixas_antiguidade = categorizar_idade_vetorizado(dias_em_aberto_corrigido)

                contagem_faixas = pd.Series(faixas_antiguidade).value_counts().reset_index()
                contagem_faixas.columns = ['Faixa de Antiguidade', 'total']

                ordem_faixas_scaffold = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
                df_todas_faixas = pd.DataFrame({'Faixa de Antiguidade': ordem_faixas_scaffold})

                contagem_completa = pd.merge(
                    df_todas_faixas,
                    contagem_faixas,
                    on='Faixa de Antiguidade',
                    how='left'
                ).fillna(0)

                contagem_completa['total'] = contagem_completa['total'].astype(int)
                contagem_completa['data'] = snapshot_date_dt

                lista_historico.append(contagem_completa)

            except Exception:
                continue

        if not lista_historico:
            return pd.DataFrame()

        return pd.concat(lista_historico, ignore_index=True)

    except Exception as e:
        st.error(f"Erro ao carregar evolução de aging: {e}")
        return pd.DataFrame()

def formatar_delta_card(delta_abs, delta_perc, valor_comparacao, data_comparacao_str):
    delta_abs = int(delta_abs)
    if valor_comparacao > 0:
        delta_perc_str = f"{delta_perc * 100:.1f}%"
        delta_text = f"{delta_abs:+} ({delta_perc_str}) vs. {data_comparacao_str}"
    elif valor_comparacao == 0 and delta_abs > 0:
        delta_text = f"+{delta_abs} (Novo) vs. {data_comparacao_str}"
    elif valor_comparacao == 0 and delta_abs < 0:
         delta_text = f"{delta_abs} vs. {data_comparacao_str}"
    else:
        delta_text = f"{delta_abs} (0.0%) vs. {data_comparacao_str}"

    if delta_abs > 0:
        delta_class = "delta-positive"
    elif delta_abs < 0:
        delta_class = "delta-negative"
    else:
        delta_class = "delta-neutral"

    return delta_text, delta_class


def lighten_color(hex_color, amount=0.2):
    try:
        hex_color = hex_color.lstrip('#')
        h, l, s = colorsys.rgb_to_hls(*[int(hex_color[i:i+2], 16)/255.0 for i in (0, 2, 4)])
        new_l = l + (1 - l) * amount
        r, g, b = colorsys.hls_to_rgb(h, new_l, s)
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    except Exception: return hex_color


try:
    FONT_LABEL = ImageFont.truetype("Roboto-Regular.ttf", 16)
    FONT_VALUE = ImageFont.truetype("Roboto-Bold.ttf", 36)
    FONT_DELTA = ImageFont.truetype("Roboto-Regular.ttf", 12)
    FONT_TITULO_SECAO = ImageFont.truetype("Roboto-Bold.ttf", 24)
    FONT_PLACEHOLDER = ImageFont.truetype("Roboto-Regular.ttf", 20)
except IOError:
    st.warning("Arquivos de fonte (Roboto-Regular.ttf, Roboto-Bold.ttf) não encontrados. A qualidade do PNG pode ser baixa.")
    FONT_LABEL = ImageFont.load_default()
    FONT_VALUE = ImageFont.load_default()
    FONT_DELTA = ImageFont.load_default()
    FONT_TITULO_SECAO = ImageFont.load_default()
    FONT_PLACEHOLDER = ImageFont.load_default()

COLOR_BACKGROUND = (255, 255, 255)
COLOR_LABEL = (102, 102, 102)
COLOR_VALUE = (55, 86, 35)
COLOR_DELTA_POS = (217, 83, 79)
COLOR_DELTA_NEG = (92, 184, 92)
COLOR_DELTA_NEU = (102, 102, 102)
COLOR_BORDER = (204, 204, 204)
COLOR_TITULO_SECAO = (0, 0, 0)
COLOR_PLACEHOLDER_BG = (238, 238, 238)
COLOR_PLACEHOLDER_TEXT = (150, 150, 150)

CARD_WIDTH = 380
CARD_HEIGHT = 120
CARD_PADDING = 10

def _desenhar_card(draw, x_offset, y_offset, label, value_str, delta_str="", delta_class="delta-neutral"):
    """Função auxiliar para desenhar um único card no estilo metric-box."""
    draw.rectangle(
        (x_offset, y_offset, x_offset + CARD_WIDTH, y_offset + CARD_HEIGHT),
        outline=COLOR_BORDER, fill=COLOR_BACKGROUND
    )
    
    label_bbox = draw.textbbox((0, 0), label, font=FONT_LABEL)
    value_bbox = draw.textbbox((0, 0), value_str, font=FONT_VALUE)
    
    label_x = x_offset + (CARD_WIDTH - (label_bbox[2] - label_bbox[0])) / 2
    value_x = x_offset + (CARD_WIDTH - (value_bbox[2] - value_bbox[0])) / 2
    
    total_text_height = (label_bbox[3] - label_bbox[1]) + (value_bbox[3] - value_bbox[1]) + 5
    if delta_str:
        total_text_height += 15
    
    current_y = y_offset + (CARD_HEIGHT - total_text_height) / 2
    
    draw.text((label_x, current_y), label, font=FONT_LABEL, fill=COLOR_LABEL)
    current_y += (label_bbox[3] - label_bbox[1]) + 5
    
    draw.text((value_x, current_y), value_str, font=FONT_VALUE, fill=COLOR_VALUE)
    current_y += (value_bbox[3] - value_bbox[1]) + 5
    
    if delta_str:
        delta_bbox = draw.textbbox((0, 0), delta_str, font=FONT_DELTA)
        delta_x = x_offset + (CARD_WIDTH - (delta_bbox[2] - delta_bbox[0])) / 2
        
        if delta_class == "delta-positive": delta_color = COLOR_DELTA_POS
        elif delta_class == "delta-negative": delta_color = COLOR_DELTA_NEG
        else: delta_color = COLOR_DELTA_NEU
            
        draw.text((delta_x, current_y), delta_str, font=FONT_DELTA, fill=delta_color)

def _criar_imagem_kpis_topo(total_aberto, total_fechado, data_atual, hora_atual):
    """Cria os dois KPIs principais: Total Aberto e Fechados no Dia."""
    img_width = CARD_WIDTH * 2 + CARD_PADDING * 3
    img_height = CARD_HEIGHT + CARD_PADDING * 2
    
    img = Image.new('RGB', (img_width, img_height), color=COLOR_BACKGROUND)
    draw = ImageDraw.Draw(img)
    
    data_str = f"Data: {data_atual} (às {hora_atual})" if hora_atual else f"Data: {data_atual}"
    
    _desenhar_card(draw, CARD_PADDING, CARD_PADDING,
                   "Total de Chamados Abertos",
                   str(total_aberto),
                   data_str,
                   "delta-neutral")
    
    valor_fechados_str = str(total_fechado) if total_fechado > 0 else "N/A"
    _desenhar_card(draw, CARD_WIDTH + CARD_PADDING * 2, CARD_PADDING,
                   "Chamados Fechados no Dia",
                   valor_fechados_str)
                   
    return img

def _criar_imagem_kpis_aging(aging_counts_df):
    """Cria os 6 cards das faixas de antiguidade (da tab1)."""
    img_width = CARD_WIDTH * 3 + CARD_PADDING * 4
    img_height = (CARD_HEIGHT * 2) + (CARD_PADDING * 3)
    
    img = Image.new('RGB', (img_width, img_height), color=COLOR_BACKGROUND)
    draw = ImageDraw.Draw(img)
    
    x_pos = [CARD_PADDING, CARD_WIDTH + CARD_PADDING * 2, CARD_WIDTH * 2 + CARD_PADDING * 3]
    y_pos = [CARD_PADDING, CARD_HEIGHT + CARD_PADDING * 2]
    
    col = 0
    row = 0
    
    for _, r in aging_counts_df.iterrows():
        _desenhar_card(draw, x_pos[col], y_pos[row],
                       r['Faixa de Antiguidade'],
                       str(r['Quantidade']))
        col += 1
        if col > 2:
            col = 0
            row += 1
            
    return img

def _criar_imagem_kpis_comparativo_aging(hoje_counts_df, df_comparacao_dados, data_comparacao_str, ordem_faixas, formatar_delta_card_func):
    """Cria os 6 cards de comparativo de aging (da tab4)."""
    img_width = CARD_WIDTH * 3 + CARD_PADDING * 4
    img_height = (CARD_HEIGHT * 2) + (CARD_PADDING * 3)
    
    img = Image.new('RGB', (img_width, img_height), color=COLOR_BACKGROUND)
    draw = ImageDraw.Draw(img)
    
    x_pos = [CARD_PADDING, CARD_WIDTH + CARD_PADDING * 2, CARD_WIDTH * 2 + CARD_PADDING * 3]
    y_pos = [CARD_PADDING, CARD_HEIGHT + CARD_PADDING * 2]
    
    col = 0
    row = 0
    
    for faixa in ordem_faixas:
        valor_hoje = 'N/A'
        if not hoje_counts_df.empty:
            valor_hoje_series = hoje_counts_df.loc[hoje_counts_df['Faixa de Antiguidade'] == faixa, 'total']
            if not valor_hoje_series.empty:
                valor_hoje = int(valor_hoje_series.iloc[0])

        valor_comparacao = 0
        delta_text = "N/A"
        delta_class = "delta-neutral"

        if data_comparacao_str != "N/A" and not df_comparacao_dados.empty and isinstance(valor_hoje, int):
            valor_comp_series = df_comparacao_dados.loc[df_comparacao_dados['Faixa de Antiguidade'] == faixa, 'total']
            if not valor_comp_series.empty:
                valor_comparacao = int(valor_comp_series.iloc[0])

            delta_abs = valor_hoje - valor_comparacao
            delta_perc = (delta_abs / valor_comparacao) if valor_comparacao > 0 else 0
            delta_text, delta_class = formatar_delta_card_func(delta_abs, delta_perc, valor_comparacao, data_comparacao_str)
        elif isinstance(valor_hoje, int):
            delta_text = "Sem dados para comparar"

        _desenhar_card(draw, x_pos[col], y_pos[row],
                       faixa,
                       str(valor_hoje),
                       delta_text,
                       delta_class)
        col += 1
        if col > 2:
            col = 0
            row += 1
            
    return img

def _add_titulo_secao(draw, titulo, y_pos, img_width):
    """Desenha um título de seção centralizado."""
    bbox = draw.textbbox((0, 0), titulo, font=FONT_TITULO_SECAO)
    x_pos = (img_width - (bbox[2] - bbox[0])) / 2
    draw.text((x_pos, y_pos), titulo, font=FONT_TITULO_SECAO, fill=COLOR_TITULO_SECAO)
    return y_pos + (bbox[3] - bbox[1]) + 20

def _criar_imagem_placeholder(titulo_secao, width=1200, height=450):
    """Cria uma imagem de placeholder para gráficos sem dados."""
    img = Image.new('RGB', (width, height), color=COLOR_PLACEHOLDER_BG)
    draw = ImageDraw.Draw(img)
    
    texto = "Gráfico indisponível (sem dados históricos)"
    
    bbox_titulo = draw.textbbox((0,0), titulo_secao, font=FONT_PLACEHOLDER)
    bbox_texto = draw.textbbox((0,0), texto, font=FONT_PLACEHOLDER)
    
    x_titulo = (width - (bbox_titulo[2] - bbox_titulo[0])) / 2
    y_titulo = (height / 2) - (bbox_titulo[3] - bbox_titulo[1]) - 10
    
    x_texto = (width - (bbox_texto[2] - bbox_texto[0])) / 2
    y_texto = (height / 2) + 10
    
    draw.text((x_titulo, y_titulo), titulo_secao, font=FONT_PLACEHOLDER, fill=COLOR_PLACEHOLDER_TEXT)
    draw.text((x_texto, y_texto), texto, font=FONT_PLACEHOLDER, fill=COLOR_PLACEHOLDER_TEXT)
    
    return img

def gerar_relatorio_png(
    fig_composicao_grupo,
    total_aberto, total_fechados, data_atual, hora_atual,
    df_aging_counts,
    fig_evol_geral,
    fig_evol_grupo,
    hoje_counts_df, df_comparacao_dados, data_comparacao_str, ordem_faixas, formatar_delta_card_func,
    fig_evol_7_dias
):
    """
    Gera o relatório PNG.
    Verifica se os gráficos têm dados e usa scale=2 para alta resolução.
    """
    
    lista_imagens_pillow = []
    
    img_kpis_topo = _criar_imagem_kpis_topo(total_aberto, total_fechados, data_atual, hora_atual)
    lista_imagens_pillow.append(("Cards Principais", img_kpis_topo))

    img_kpis_aging = _criar_imagem_kpis_aging(df_aging_counts)
    lista_imagens_pillow.append(("Cards de Antiguidade", img_kpis_aging))

    titulo_secao_3 = "Composição da Idade do Backlog por Grupo"
    if fig_composicao_grupo and fig_composicao_grupo.data:
        try:
            img_data = fig_composicao_grupo.to_image(format="png", width=1200, height=600, engine="kaleido", scale=2)
            lista_imagens_pillow.append((titulo_secao_3, Image.open(BytesIO(img_data))))
        except Exception as e:
            st.warning(f"Erro ao exportar '{titulo_secao_3}': {e}")
            lista_imagens_pillow.append((titulo_secao_3, _criar_imagem_placeholder(titulo_secao_3, height=600)))
    else:
        lista_imagens_pillow.append((titulo_secao_3, _criar_imagem_placeholder(titulo_secao_3, height=600)))

    titulo_secao_4 = "Evolução do Total Geral"
    if fig_evol_geral and fig_evol_geral.data:
        try:
            img_data = fig_evol_geral.to_image(format="png", width=1200, height=450, engine="kaleido", scale=2)
            lista_imagens_pillow.append((titulo_secao_4, Image.open(BytesIO(img_data))))
        except Exception as e:
            st.warning(f"Erro ao exportar '{titulo_secao_4}': {e}")
            lista_imagens_pillow.append((titulo_secao_4, _criar_imagem_placeholder(titulo_secao_4, height=450)))
    else:
        lista_imagens_pillow.append((titulo_secao_4, _criar_imagem_placeholder(titulo_secao_4, height=450)))

    titulo_secao_5 = "Evolução por Grupo"
    if fig_evol_grupo and fig_evol_grupo.data:
        try:
            img_data = fig_evol_grupo.to_image(format="png", width=1200, height=600, engine="kaleido", scale=2)
            lista_imagens_pillow.append((titulo_secao_5, Image.open(BytesIO(img_data))))
        except Exception as e:
            st.warning(f"Erro ao exportar '{titulo_secao_5}': {e}")
            lista_imagens_pillow.append((titulo_secao_5, _criar_imagem_placeholder(titulo_secao_5, height=600)))
    else:
        lista_imagens_pillow.append((titulo_secao_5, _criar_imagem_placeholder(titulo_secao_5, height=600)))

    img_kpis_comp_aging = _criar_imagem_kpis_comparativo_aging(
        hoje_counts_df, df_comparacao_dados, data_comparacao_str, ordem_faixas, formatar_delta_card_func
    )
    lista_imagens_pillow.append(("Comparativo de Antiguidade (Hoje vs. 7 dias)", img_kpis_comp_aging))

    titulo_secao_7 = "Evolução do Aging (Últimos 7 dias)"
    if fig_evol_7_dias and fig_evol_7_dias.data:
        try:
            img_data = fig_evol_7_dias.to_image(format="png", width=1200, height=500, engine="kaleido", scale=2)
            lista_imagens_pillow.append((titulo_secao_7, Image.open(BytesIO(img_data))))
        except Exception as e:
            st.warning(f"Erro ao exportar '{titulo_secao_7}': {e}")
            lista_imagens_pillow.append((titulo_secao_7, _criar_imagem_placeholder(titulo_secao_7, height=500)))
    else:
        lista_imagens_pillow.append((titulo_secao_7, _criar_imagem_placeholder(titulo_secao_7, height=500)))

    
    max_width = 0
    for _, img in lista_imagens_pillow:
        if img.width > max_width:
            max_width = img.width
    if max_width < 1200: max_width = 1200 

    total_height = 0
    padding_vertical = 50 
    for _ in lista_imagens_pillow:
        total_height += padding_vertical + 40
        
    total_height += sum(img.height for _, img in lista_imagens_pillow)
    
    report_image = Image.new('RGB', (max_width, total_height), color=COLOR_BACKGROUND)
    draw = ImageDraw.Draw(report_image)
    
    current_y = padding_vertical
    
    for titulo, img in lista_imagens_pillow:
        current_y = _add_titulo_secao(draw, titulo, current_y, max_width)
        img_x_pos = (max_width - img.width) // 2
        report_image.paste(img, (img_x_pos, current_y))
        current_y += img.height + padding_vertical

    img_buffer = BytesIO()
    report_image.save(img_buffer, format="PNG")
    img_buffer.seek(0)
    
    return img_buffer


logo_copa_b64 = get_image_as_base64("logo_sidebar.png")
logo_belago_b64 = get_image_as_base64("logo_belago.png")
if logo_copa_b64 and logo_belago_b64:
    st.markdown(f"""<div style="display: flex; justify-content: space-between; align-items: center;"><img src="data:image/png;base64,{logo_copa_b64}" width="150"><h1 style='text-align: center; margin: 0;'>Backlog Copa Energia + Belago</h1><img src="data:image/png;base64,{logo_belago_b64}" width="150"></div>""", unsafe_allow_html=True)
else:
    st.error("Arquivos de logo não encontrados.")

repo = get_github_repo()
st.session_state.repo = repo

st.sidebar.header("Área do Administrador")
password = st.sidebar.text_input("Senha para atualizar dados:", type="password")
is_admin = password == st.secrets.get("ADMIN_PASSWORD", "")

if is_admin:
    st.sidebar.success("Acesso de administrador liberado.")
    st.sidebar.subheader("Atualização Completa")
    uploaded_file_atual = st.sidebar.file_uploader("1. Backlog ATUAL", type=["csv", "xlsx"], key="uploader_atual")
    uploaded_file_15dias = st.sidebar.file_uploader("2. Backlog de 15 DIAS ATRÁS", type=["csv", "xlsx"], key="uploader_15dias")
    if st.sidebar.button("Salvar Novos Dados no Site"):
        if uploaded_file_atual and uploaded_file_15dias:
            with st.spinner("Processando e salvando atualização completa..."):
                now_sao_paulo = datetime.now(ZoneInfo('America/Sao_Paulo'))
                commit_msg = f"Dados atualizados em {now_sao_paulo.strftime('%d/%m/%Y %H:%M')}"
                content_atual = process_uploaded_file(uploaded_file_atual)
                content_15dias = process_uploaded_file(uploaded_file_15dias)
                if content_atual is not None and content_15dias is not None:
                    try:
                        update_github_file(repo, "dados_atuais.csv", content_atual, commit_msg)
                        update_github_file(repo, "dados_15_dias.csv", content_15dias, commit_msg)
                        today_str = now_sao_paulo.strftime('%Y-%m-%d')
                        snapshot_path = f"snapshots/backlog_{today_str}.csv"
                        update_github_file(repo, snapshot_path, content_atual, f"Snapshot de {today_str}")
                        data_do_upload = now_sao_paulo.date()
                        data_arquivo_15dias = data_do_upload - timedelta(days=15)
                        hora_atualizacao = now_sao_paulo.strftime('%H:%M')
                        datas_referencia_content = (f"data_atual:{data_do_upload.strftime('%d/%m/%Y')}\n"
                                                  f"data_15dias:{data_arquivo_15dias.strftime('%d/%m/%Y')}\n"
                                                  f"hora_atualizacao:{hora_atualizacao}")
                        update_github_file(repo, "datas_referencia.txt", datas_referencia_content.encode('utf-8'), commit_msg)
                        st.cache_data.clear()
                        st.cache_resource.clear()
                        st.sidebar.success("Arquivos salvos! Forçando recarregamento...")
                        st.rerun()
                    except Exception as e:
                        st.sidebar.error(f"Erro durante a atualização completa: {e}")

        else:
            st.sidebar.warning("Para a atualização completa, carregue os arquivos ATUAL e de 15 DIAS.")
    st.sidebar.markdown("---")
    st.sidebar.subheader("Atualização Rápida")
    uploaded_file_fechados = st.sidebar.file_uploader("Apenas Chamados FECHADOS no dia", type=["csv", "xlsx"], key="uploader_fechados")
    if st.sidebar.button("Salvar Apenas Chamados Fechados"):
        if uploaded_file_fechados:
            with st.spinner("Salvando arquivo de chamados fechados..."):
                now_sao_paulo = datetime.now(ZoneInfo('America/Sao_Paulo'))
                commit_msg = f"Atualizando chamados fechados em {now_sao_paulo.strftime('%d/%m/%Y %H:%M')}"
                content_fechados = process_uploaded_file(uploaded_file_fechados)
                if content_fechados is not None:
                    try:
                        update_github_file(repo, "dados_fechados.csv", content_fechados, commit_msg)

                        # --- INÍCIO DA MODIFICAÇÃO v0.9.30 ---
                        datas_existentes = read_github_text_file(repo, "datas_referencia.txt")
                        data_atual_existente = datas_existentes.get('data_atual', 'N/A')
                        data_15dias_existente = datas_existentes.get('data_15dias', 'N/A')
                        hora_atualizacao_nova = now_sao_paulo.strftime('%H:%M')

                        datas_referencia_content_novo = (f"data_atual:{data_atual_existente}\n"
                                                       f"data_15dias:{data_15dias_existente}\n"
                                                       f"hora_atualizacao:{hora_atualizacao_nova}")
                        update_github_file(repo, "datas_referencia.txt", datas_referencia_content_novo.encode('utf-8'), commit_msg)
                        # --- FIM DA MODIFICAÇÃO v0.9.30 ---

                        st.cache_data.clear()
                        st.cache_resource.clear()
                        st.sidebar.success("Arquivo de fechados salvo e hora atualizada! Recarregando...")
                        st.rerun()
                    except Exception as e:
                         st.sidebar.error(f"Erro durante a atualização rápida: {e}")
        else:
            st.sidebar.warning("Por favor, carregue o arquivo de chamados fechados para salvar.")
elif password:
    st.sidebar.error("Senha incorreta.")

try:
    if 'contacted_tickets' not in st.session_state:
        try:
            file_content = repo.get_contents("contacted_tickets.json").decoded_content.decode("utf-8")
            st.session_state.contacted_tickets = set(json.loads(file_content))
        except GithubException as e:
            if e.status == 404: st.session_state.contacted_tickets = set()
            else: st.error(f"Erro ao carregar o estado dos tickets: {e}"); st.session_state.contacted_tickets = set()

    if 'observations' not in st.session_state:
        st.session_state.observations = read_github_json_dict(repo, "ticket_observations.json")

    needs_scroll = "scroll" in st.query_params
    if "faixa" in st.query_params:
        faixa_from_url = st.query_params.get("faixa")
        ordem_faixas_validas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
        if faixa_from_url in ordem_faixas_validas:
                st.session_state.faixa_selecionada = faixa_from_url
    if "scroll" in st.query_params or "faixa" in st.query_params:
        st.query_params.clear()

    df_atual = read_github_file(repo, "dados_atuais.csv")
    df_15dias = read_github_file(repo, "dados_15_dias.csv")
    df_fechados = read_github_file(repo, "dados_fechados.csv")
    datas_referencia = read_github_text_file(repo, "datas_referencia.txt")
    data_atual_str = datas_referencia.get('data_atual', 'N/A')
    data_15dias_str = datas_referencia.get('data_15dias', 'N/A')
    hora_atualizacao_str = datas_referencia.get('hora_atualizacao', '')
    if df_atual.empty or df_15dias.empty:
        st.warning("Ainda não há dados para exibir. Por favor, carregue os arquivos na área do administrador.")
        st.stop()
    if 'ID do ticket' in df_atual.columns:
        df_atual['ID do ticket'] = df_atual['ID do ticket'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

    closed_ticket_ids = []
    if not df_fechados.empty:
        id_col_name = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_fechados.columns), None)
        if id_col_name:
            df_fechados[id_col_name] = df_fechados[id_col_name].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            closed_ticket_ids = df_fechados[id_col_name].dropna().unique()

    df_encerrados = df_atual[df_atual['ID do ticket'].isin(closed_ticket_ids)]
    df_abertos = df_atual[~df_atual['ID do ticket'].isin(closed_ticket_ids)]
    df_atual_filtrado = df_abertos[~df_abertos['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]
    df_15dias_filtrado = df_15dias[~df_15dias['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]
    df_aging = analisar_aging(df_atual_filtrado)
    df_encerrados_filtrado = df_encerrados[~df_encerrados['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]

    
    total_chamados = len(df_aging) if not df_aging.empty else 0
    total_fechados = len(df_encerrados_filtrado)
    ordem_faixas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
    
    if not df_aging.empty:
        aging_counts = df_aging['Faixa de Antiguidade'].value_counts().reset_index()
        aging_counts.columns = ['Faixa de Antiguidade', 'Quantidade']
        todas_as_faixas = pd.DataFrame({'Faixa de Antiguidade': ordem_faixas})
        aging_counts = pd.merge(todas_as_faixas, aging_counts, on='Faixa de Antiguidade', how='left').fillna(0).astype({'Quantidade': int})
        aging_counts['Faixa de Antiguidade'] = pd.Categorical(aging_counts['Faixa de Antiguidade'], categories=ordem_faixas, ordered=True)
        aging_counts = aging_counts.sort_values('Faixa de Antiguidade')
    else:
        aging_counts = pd.DataFrame({'Faixa de Antiguidade': ordem_faixas, 'Quantidade': 0})

    fig_stacked_bar_para_png = go.Figure()
    chart_data = pd.DataFrame()
    sorted_new_labels = []
    color_map = {}

    if not df_aging.empty:
        chart_data = df_aging.groupby(['Atribuir a um grupo', 'Faixa de Antiguidade']).size().reset_index(name='Quantidade')
        group_totals = chart_data.groupby('Atribuir a um grupo')['Quantidade'].sum().sort_values(ascending=False)
        new_labels_map = {group: f"{group} ({total})" for group, total in group_totals.items()}
        chart_data['Atribuir a um grupo (com total)'] = chart_data['Atribuir a um grupo'].map(new_labels_map)
        sorted_new_labels = [new_labels_map[group] for group in group_totals.index]
        base_color = "#375623"
        palette = [ lighten_color(base_color, 0.85), lighten_color(base_color, 0.70), lighten_color(base_color, 0.55), lighten_color(base_color, 0.40), lighten_color(base_color, 0.20), base_color ]
        color_map = {faixa: color for faixa, color in zip(ordem_faixas, palette)}
        
        fig_stacked_bar_para_png = px.bar( 
            chart_data, x='Atribuir a um grupo (com total)', y='Quantidade', color='Faixa de Antiguidade', 
            title="Composição da Idade do Backlog por Grupo", 
            labels={'Quantidade': 'Qtd. de Chamados', 'Atribuir a um grupo (com total)': 'Grupo'}, 
            category_orders={'Atribuir a um grupo (com total)': sorted_new_labels, 'Faixa de Antiguidade': ordem_faixas}, 
            color_discrete_map=color_map, text_auto=True 
        )
        fig_stacked_bar_para_png.update_traces(textangle=0, textfont_size=12)
        fig_stacked_bar_para_png.update_layout(height=600, xaxis_title=None, xaxis_tickangle=-45, legend_title_text='Antiguidade')

    dias_evolucao_default = 7 
    df_evolucao_tab3 = carregar_dados_evolucao(repo, closed_ticket_ids_list=closed_ticket_ids, dias_para_analisar=dias_evolucao_default)
    
    fig_total_evolucao = go.Figure() 
    fig_evolucao_grupo = go.Figure() 

    if not df_evolucao_tab3.empty:
        df_evolucao_tab3['Data'] = pd.to_datetime(df_evolucao_tab3['Data'])
        df_evolucao_tab3 = df_evolucao_tab3[df_evolucao_tab3['Data'].dt.dayofweek < 5].copy()

        if not df_evolucao_tab3.empty:
            df_total_diario = df_evolucao_tab3.groupby('Data')['Total Chamados'].sum().reset_index()
            df_total_diario = df_total_diario.sort_values('Data')
            df_total_diario['Data (Eixo)'] = df_total_diario['Data'].dt.strftime('%d/%m')
            ordem_datas_total = df_total_diario['Data (Eixo)'].tolist()

            fig_total_evolucao = px.area(
                df_total_diario, x='Data (Eixo)', y='Total Chamados',
                title=f'Evolução do Total Geral (Últimos {dias_evolucao_default} dias de semana)',
                markers=True, labels={"Data (Eixo)": "Data", "Total Chamados": "Total Geral"},
                category_orders={'Data (Eixo)': ordem_datas_total}
            )
            fig_total_evolucao.update_layout(height=400)

            df_evolucao_tab3_sorted = df_evolucao_tab3.sort_values('Data')
            df_evolucao_tab3_sorted['Data (Eixo)'] = df_evolucao_tab3_sorted['Data'].dt.strftime('%d/%m')
            ordem_datas_grupo = df_evolucao_tab3_sorted['Data (Eixo)'].unique().tolist()
            df_filtrado_display = df_evolucao_tab3_sorted.rename(columns={'Atribuir a um grupo': 'Grupo Atribuído'})

            fig_evolucao_grupo = px.line(
                df_filtrado_display, x='Data (Eixo)', y='Total Chamados', color='Grupo Atribuído',
                title=f'Evolução por Grupo (Últimos {dias_evolucao_default} dias de semana)',
                markers=True, labels={ "Data (Eixo)": "Data", "Total Chamados": "Nº de Chamados", "Grupo Atribuído": "Grupo" },
                category_orders={'Data (Eixo)': ordem_datas_grupo}
            )
            fig_evolucao_grupo.update_layout(height=600)

    ordem_faixas_scaffold = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
    hoje_data = None
    hoje_counts_df = pd.DataFrame()
    df_combinado = pd.DataFrame()
    data_comparacao_final_7dias = None
    df_comparacao_dados_7dias = pd.DataFrame()
    data_comparacao_str_7dias = "N/A"
    fig_aging_all = go.Figure() 

    try:
        df_hist = carregar_evolucao_aging(repo, closed_ticket_ids_list=closed_ticket_ids, dias_para_analisar=90)
        
        if 'df_aging' in locals() and not df_aging.empty and data_atual_str != 'N/A':
            try:
                hoje_data = pd.to_datetime(datetime.strptime(data_atual_str, "%d/%m/%Y").date())
                hoje_counts_raw = df_aging['Faixa de Antiguidade'].value_counts().reset_index()
                hoje_counts_raw.columns = ['Faixa de Antiguidade', 'total']
                df_todas_faixas_hoje = pd.DataFrame({'Faixa de Antiguidade': ordem_faixas_scaffold})
                hoje_counts_df = pd.merge(df_todas_faixas_hoje, hoje_counts_raw, on='Faixa de Antiguidade', how='left').fillna(0)
                hoje_counts_df['total'] = hoje_counts_df['total'].astype(int)
                hoje_counts_df['data'] = hoje_data
            except ValueError:
                hoje_data = None

        if not df_hist.empty and not hoje_counts_df.empty:
            df_combinado = pd.concat([df_hist, hoje_counts_df], ignore_index=True)
            df_combinado = df_combinado.drop_duplicates(subset=['data', 'Faixa de Antiguidade'], keep='last')
        elif not df_hist.empty: df_combinado = df_hist.copy()
        elif not hoje_counts_df.empty: df_combinado = hoje_counts_df.copy()

        if not df_combinado.empty:
            df_combinado['data'] = pd.to_datetime(df_combinado['data'])
            df_combinado = df_combinado.sort_values(by=['data', 'Faixa de Antiguidade'])

            if hoje_data:
                target_comp_date_7dias = hoje_data.date() - timedelta(days=7)
                data_comp_encontrada_7dias, _ = find_closest_snapshot_before(repo, hoje_data.date(), target_comp_date_7dias)
                if data_comp_encontrada_7dias:
                    data_comparacao_final_7dias = pd.to_datetime(data_comp_encontrada_7dias)
                    data_comparacao_str_7dias = data_comparacao_final_7dias.strftime('%d/%m')
                    df_comparacao_dados_7dias = df_combinado[df_combinado['data'] == data_comparacao_final_7dias].copy()

            hoje_filtro_grafico = datetime.now().date()
            data_inicio_filtro_grafico = hoje_filtro_grafico - timedelta(days=7)
            df_filtrado_grafico = df_combinado[df_combinado['data'].dt.date >= data_inicio_filtro_grafico].copy()

            if not df_filtrado_grafico.empty:
                df_grafico = df_filtrado_grafico.sort_values(by='data')
                df_grafico['Data (Eixo)'] = df_grafico['data'].dt.strftime('%d/%m')
                ordem_datas_grafico = df_grafico['Data (Eixo)'].unique().tolist()
                
                base_color_aging = "#375623"
                palette_aging = [ lighten_color(base_color_aging, 0.85), lighten_color(base_color_aging, 0.70), lighten_color(base_color_aging, 0.55), lighten_color(base_color_aging, 0.40), lighten_color(base_color_aging, 0.20), base_color_aging ]
                color_map_aging = {faixa: color for faixa, color in zip(ordem_faixas_scaffold, palette_aging)}

                fig_aging_all = px.area(
                    df_grafico, x='Data (Eixo)', y='total', color='Faixa de Antiguidade',
                    title='Composição da Evolução por Antiguidade (Últimos 7 dias)',
                    markers=True, labels={"Data (Eixo)": "Data", "total": "Total Chamados", "Faixa de Antiguidade": "Faixa"},
                    category_orders={ 'Data (Eixo)': ordem_datas_grafico, 'Faixa de Antiguidade': ordem_faixas_scaffold },
                    color_discrete_map=color_map_aging
                )
                fig_aging_all.update_layout(height=500)
    except Exception as e_tab4:
        st.error(f"Ocorreu um erro ao pré-calcular dados da Tab4: {e_tab4}")
    
    
    tab1, tab2, tab3, tab4 = st.tabs(["Dashboard Completo", "Report Visual", "Evolução Semanal", "Evolução Aging"])

    with tab1:
        info_messages = ["**Filtros e Regras Aplicadas:**", "- Grupos contendo 'RH' foram desconsiderados da análise.", "- A contagem de dias do chamado desconsidera o dia da sua abertura (prazo -1 dia)."]
        if not df_encerrados.empty:
            info_messages.append(f"- **{len(df_encerrados_filtrado)} chamados fechados no dia** (exceto RH) foram deduzidos das contagens principais.")
        st.info("\n".join(info_messages))
        st.subheader("Análise de Antiguidade do Backlog Atual")
        texto_hora = f" (atualizado às {hora_atualizacao_str})" if hora_atualizacao_str else ""
        st.markdown(f"<p style='font-size: 0.9em; color: #666;'><i>Data de referência: {data_atual_str}{texto_hora}</i></p>", unsafe_allow_html=True)
        if not df_aging.empty:
            col_spacer1, col_total, col_fechados, col_spacer2 = st.columns([1, 1.5, 1.5, 1])
            with col_total:
                st.markdown(f"""<div class="metric-box"><span class="label">Total de Chamados Abertos</span><span class="value">{total_chamados}</span></div>""", unsafe_allow_html=True)
            with col_fechados:
                valor_fechados = total_fechados if total_fechados > 0 else "N/A"
                st.markdown(f"""<div class="metric-box"><span class="label">Chamados Fechados no Dia</span><span class="value">{valor_fechados}</span></div>""", unsafe_allow_html=True)

            st.markdown("---")
            if 'faixa_selecionada' not in st.session_state:
                st.session_state.faixa_selecionada = "0-2 dias"
            cols = st.columns(len(ordem_faixas))
            for i, row in aging_counts.iterrows():
                with cols[i]:
                    faixa_encoded = quote(row['Faixa de Antiguidade'])
                    card_html = f"""<a href="?faixa={faixa_encoded}&scroll=true" target="_self" class="metric-box"><span class="label">{row['Faixa de Antiguidade']}</span><span class="value">{row['Quantidade']}</span></a>"""
                    st.markdown(card_html, unsafe_allow_html=True)
        else:
            st.warning("Nenhum dado válido para a análise de antiguidade.")
        st.markdown(f"<h3>Comparativo de Backlog: Atual vs. 15 Dias Atrás <span style='font-size: 0.6em; color: #666; font-weight: normal;'>({data_15dias_str})</span></h3>", unsafe_allow_html=True)
        df_comparativo = processar_dados_comparativos(df_atual_filtrado.copy(), df_15dias_filtrado.copy())
        df_comparativo['Status'] = df_comparativo.apply(get_status, axis=1)
        df_comparativo.rename(columns={'Atribuir a um grupo': 'Grupo'}, inplace=True)
        df_comparativo = df_comparativo[['Grupo', '15 Dias Atrás', 'Atual', 'Diferença', 'Status']]
        st.dataframe(df_comparativo.set_index('Grupo').style.map(lambda val: 'background-color: #ffcccc' if val > 0 else ('background-color: #ccffcc' if val < 0 else 'background-color: white'), subset=['Diferença']), use_container_width=True)
        st.markdown("---")
        st.markdown(f"<h3>Chamados Encerrados no Dia <span style='font-size: 0.6em; color: #666; font-weight: normal;'>({data_atual_str})</span></h3>", unsafe_allow_html=True)

        if df_fechados.empty:
            st.info("O arquivo de chamados encerrados ainda não foi carregado.")
        elif not df_encerrados_filtrado.empty:
            st.data_editor(df_encerrados_filtrado[['ID do ticket', 'Descrição', 'Atribuir a um grupo']], hide_index=True, disabled=True, use_container_width=True)
        else:
            st.info("O arquivo de chamados encerrados do dia ainda não foi carregado.")

        if not df_aging.empty:
            st.markdown("---")
            st.subheader("Detalhar e Buscar Chamados")
            st.info('Marque "Contato" se já falou com o usuário e a solicitação continua pendente. Use "Observações" para anotações.')
            if 'scroll_to_details' not in st.session_state:
                st.session_state.scroll_to_details = False
            if needs_scroll or st.session_state.get('scroll_to_details', False):
                js_code = """<script> setTimeout(() => { const element = window.parent.document.getElementById('detalhar-e-buscar-chamados'); if (element) { element.scrollIntoView({ behavior: 'smooth', block: 'start' }); } }, 250); </script>"""
                components.html(js_code, height=0)
                st.session_state.scroll_to_details = False
            st.selectbox("Selecione uma faixa de idade para ver os detalhes (ou clique em um card acima):", options=ordem_faixas, key='faixa_selecionada')
            faixa_atual = st.session_state.faixa_selecionada
            filtered_df = df_aging[df_aging['Faixa de Antiguidade'] == faixa_atual].copy()
            if not filtered_df.empty:
                def highlight_row(row):
                    return ['background-color: #fff8c4'] * len(row) if row['Contato'] else [''] * len(row)
                filtered_df['Contato'] = filtered_df['ID do ticket'].apply(lambda id: str(id) in st.session_state.contacted_tickets)
                filtered_df['Observações'] = filtered_df['ID do ticket'].apply(lambda id: st.session_state.observations.get(str(id), ''))
                st.session_state.last_filtered_df = filtered_df.reset_index(drop=True)
                colunas_para_exibir_renomeadas = {
                    'Contato': 'Contato', 'ID do ticket': 'ID do ticket', 'Descrição': 'Descrição',
                    'Atribuir a um grupo': 'Grupo Atribuído', 'Dias em Aberto': 'Dias em Aberto',
                    'Data de criação': 'Data de criação', 'Observações': 'Observações'
                }
                st.data_editor(
                    st.session_state.last_filtered_df.rename(columns=colunas_para_exibir_renomeadas)[list(colunas_para_exibir_renomeadas.values())].style.apply(highlight_row, axis=1),
                    use_container_width=True, hide_index=True,
                    disabled=['ID do ticket', 'Descrição', 'Grupo Atribuído', 'Dias em Aberto', 'Data de criação'],
                    key='ticket_editor', on_change=sync_ticket_data
                )
            else:
                st.info("Não há chamados nesta categoria.")
            st.subheader("Buscar Chamados por Grupo")
            lista_grupos = sorted(df_aging['Atribuir a um grupo'].dropna().unique())
            grupo_selecionado = st.selectbox("Busca de chamados por grupo:", options=lista_grupos)
            if grupo_selecionado:
                resultados_busca = df_aging[df_aging['Atribuir a um grupo'] == grupo_selecionado].copy()
                if 'Data de criação' in resultados_busca.columns:
                    resultados_busca['Data de criação'] = resultados_busca['Data de criação'].dt.strftime('%d/%m/%Y')
                st.write(f"Encontrados {len(resultados_busca)} chamados para o grupo '{grupo_selecionado}':")
                colunas_para_exibir_busca = ['ID do ticket', 'Descrição', 'Dias em Aberto', 'Data de criação']
                st.data_editor(resultados_busca[[col for col in colunas_para_exibir_busca if col in resultados_busca.columns]], use_container_width=True, hide_index=True, disabled=True)

    with tab2:
        st.subheader("Gerar Relatório Unificado em PNG")
        st.markdown("Este recurso compila os principais indicadores e gráficos do dashboard em uma **única imagem PNG** para fácil compartilhamento.")
        
        if st.button("Gerar Relatório PNG de 1 Página", use_container_width=True):
            with st.spinner("Gerando seu relatório... isso pode levar alguns segundos..."):
                try:
                    report_png_buffer = gerar_relatorio_png(
                        fig_composicao_grupo=fig_stacked_bar_para_png,
                        total_aberto=total_chamados,
                        total_fechados=total_fechados,
                        data_atual=data_atual_str,
                        hora_atual=hora_atualizacao_str,
                        df_aging_counts=aging_counts,
                        fig_evol_geral=fig_total_evolucao,
                        fig_evol_grupo=fig_evolucao_grupo,
                        hoje_counts_df=hoje_counts_df, 
                        df_comparacao_dados=df_comparacao_dados_7dias,
                        data_comparacao_str=data_comparacao_str_7dias, 
                        ordem_faixas=ordem_faixas_scaffold, 
                        formatar_delta_card_func=formatar_delta_card,
                        fig_evol_7_dias=fig_aging_all
                    )
                    
                    st.success("Relatório gerado!")
                    st.download_button(
                        label="Baixar Relatório PNG",
                        data=report_png_buffer,
                        file_name=f"relatorio_backlog_{date.today().strftime('%Y-%m-%d')}.png",
                        mime="image/png",
                        key="download_png_report"
                    )
                except Exception as e:
                    st.error(f"Erro ao gerar o relatório: {e}")
                    st.exception(e)

        st.markdown("---")

        st.subheader("Resumo do Backlog Atual")
        if not df_aging.empty:
            _, col_total_tab2, _ = st.columns([2, 1.5, 2])
            with col_total_tab2: 
                st.markdown( f"""<div class="metric-box"><span class="label">Total de Chamados</span><span class="value">{total_chamados}</span></div>""", unsafe_allow_html=True )
            
            st.markdown("---")
            
            cols_tab2 = st.columns(len(ordem_faixas))
            for i, row in aging_counts.iterrows():
                with cols_tab2[i]: 
                    st.markdown( f"""<div class="metric-box"><span class="label">{row['Faixa de Antiguidade']}</span><span class="value">{row['Quantidade']}</span></div>""", unsafe_allow_html=True )
            
            st.markdown("---")
            st.subheader("Distribuição do Backlog por Grupo")
            
            orientation_choice = st.radio( "Orientação do Gráfico:", ["Vertical", "Horizontal"], index=0, horizontal=True, key="radio_tab2_orient" )
            
            if orientation_choice == 'Horizontal':
                num_groups = len(sorted_new_labels)
                dynamic_height = max(500, num_groups * 30)
                fig_stacked_bar_tab2 = px.bar( 
                    chart_data, x='Quantidade', y='Atribuir a um grupo (com total)', orientation='h', color='Faixa de Antiguidade', 
                    title="Composição da Idade do Backlog por Grupo", 
                    labels={'Quantidade': 'Qtd. de Chamados', 'Atribuir a um grupo (com total)': ''}, 
                    category_orders={'Atribuir a um grupo (com total)': sorted_new_labels, 'Faixa de Antiguidade': ordem_faixas}, 
                    color_discrete_map=color_map, text_auto=True 
                )
                fig_stacked_bar_tab2.update_traces(textangle=0, textfont_size=12)
                fig_stacked_bar_tab2.update_layout(height=dynamic_height, legend_title_text='Antiguidade')
            else:
                fig_stacked_bar_tab2 = px.bar( 
                    chart_data, x='Atribuir a um grupo (com total)', y='Quantidade', color='Faixa de Antiguidade', 
                    title="Composição da Idade do Backlog por Grupo", 
                    labels={'Quantidade': 'Qtd. de Chamados', 'Atribuir a um grupo (com total)': 'Grupo'}, 
                    category_orders={'Atribuir a um grupo (com total)': sorted_new_labels, 'Faixa de Antiguidade': ordem_faixas}, 
                    color_discrete_map=color_map, text_auto=True 
                )
                fig_stacked_bar_tab2.update_traces(textangle=0, textfont_size=12)
                fig_stacked_bar_tab2.update_layout(height=600, xaxis_title=None, xaxis_tickangle=-45, legend_title_text='Antiguidade')
            
            st.plotly_chart(fig_stacked_bar_tab2, use_container_width=True)
        else:
            st.warning("Nenhum dado para gerar o report visual.")

    with tab3:
        st.subheader("Evolução do Backlog")
        dias_evolucao = st.slider("Ver evolução dos últimos dias:", min_value=7, max_value=30, value=7, key="slider_evolucao")
        df_evolucao_tab3_slider = carregar_dados_evolucao(repo, closed_ticket_ids_list=closed_ticket_ids, dias_para_analisar=dias_evolucao)
        if not df_evolucao_tab3_slider.empty:
            df_evolucao_tab3_slider['Data'] = pd.to_datetime(df_evolucao_tab3_slider['Data'])
            df_evolucao_tab3_slider = df_evolucao_tab3_slider[df_evolucao_tab3_slider['Data'].dt.dayofweek < 5].copy()
            if not df_evolucao_tab3_slider.empty:
                st.info("Esta visualização ainda está coletando dados históricos. Utilize as outras abas como referência principal por enquanto.")
                df_total_diario = df_evolucao_tab3_slider.groupby('Data')['Total Chamados'].sum().reset_index()
                df_total_diario = df_total_diario.sort_values('Data')
                df_total_diario['Data (Eixo)'] = df_total_diario['Data'].dt.strftime('%d/%m')
                ordem_datas_total = df_total_diario['Data (Eixo)'].tolist()
                fig_total_evolucao_slider = px.area(
                    df_total_diario, x='Data (Eixo)', y='Total Chamados',
                    title='Evolução do Total Geral de Chamados Abertos (Apenas Dias de Semana)',
                    markers=True, labels={"Data (Eixo)": "Data", "Total Chamados": "Total Geral de Chamados"},
                    category_orders={'Data (Eixo)': ordem_datas_total}
                )
                fig_total_evolucao_slider.update_layout(height=400)
                st.plotly_chart(fig_total_evolucao_slider, use_container_width=True)
                st.markdown("---")
                st.info("Esta visualização já filtra os chamados fechados e permite filtrar grupos clicando 2x na legenda.")
                df_evolucao_tab3_sorted = df_evolucao_tab3_slider.sort_values('Data')
                df_evolucao_tab3_sorted['Data (Eixo)'] = df_evolucao_tab3_sorted['Data'].dt.strftime('%d/%m')
                ordem_datas_grupo = df_evolucao_tab3_sorted['Data (Eixo)'].unique().tolist()
                df_filtrado_display = df_evolucao_tab3_sorted.rename(columns={'Atribuir a um grupo': 'Grupo Atribuído'})
                fig_evolucao_grupo_slider = px.line(
                    df_filtrado_display, x='Data (Eixo)', y='Total Chamados', color='Grupo Atribuído',
                    title='Evolução por Grupo (Apenas Dias de Semana)',
                    markers=True, labels={ "Data (Eixo)": "Data", "Total Chamados": "Nº de Chamados", "Grupo Atribuído": "Grupo" },
                    category_orders={'Data (Eixo)': ordem_datas_grupo}
                )
                fig_evolucao_grupo_slider.update_layout(height=600)
                st.plotly_chart(fig_evolucao_grupo_slider, use_container_width=True)
            else:
                 st.info("Ainda não há dados históricos suficientes (considerando apenas dias de semana).")
        else:
            st.info("Ainda não há dados históricos suficientes.")

    with tab4:
        st.subheader("Evolução do Aging do Backlog")
        try:
            if df_combinado.empty:
                st.error("Não há dados históricos nem dados de hoje para a análise de aging.")
                st.stop()
            
            st.markdown("##### Comparativo")
            periodo_comp_opts = {
                "Ontem": 1, "7 dias atrás": 7, "15 dias atrás": 15, "30 dias atrás": 30
            }
            periodo_comp_selecionado = st.radio(
                "Comparar 'Hoje' com:", options=periodo_comp_opts.keys(),
                horizontal=True, key="radio_comp_periodo"
            )
            data_comparacao_final_tab4 = None
            df_comparacao_dados_tab4 = pd.DataFrame()
            data_comparacao_str_tab4 = "N/A"
            if hoje_data:
                target_comp_date_tab4 = hoje_data.date() - timedelta(days=periodo_comp_opts[periodo_comp_selecionado])
                data_comp_encontrada_tab4, _ = find_closest_snapshot_before(repo, hoje_data.date(), target_comp_date_tab4)
                if data_comp_encontrada_tab4:
                    data_comparacao_final_tab4 = pd.to_datetime(data_comp_encontrada_tab4)
                    data_comparacao_str_tab4 = data_comparacao_final_tab4.strftime('%d/%m')
                    df_comparacao_dados_tab4 = df_combinado[df_combinado['data'] == data_comparacao_final_tab4].copy()
                else:
                    st.warning(f"Não foi encontrado snapshot próximo a {periodo_comp_selecionado} ({target_comp_date_tab4.strftime('%d/%m')}).")

            cols_linha1 = st.columns(3)
            cols_linha2 = st.columns(3)
            cols_map = {0: cols_linha1[0], 1: cols_linha1[1], 2: cols_linha1[2],
                        3: cols_linha2[0], 4: cols_linha2[1], 5: cols_linha2[2]}
            for i, faixa in enumerate(ordem_faixas_scaffold):
                with cols_map[i]:
                    valor_hoje = 'N/A'
                    if not hoje_counts_df.empty:
                        valor_hoje_series = hoje_counts_df.loc[hoje_counts_df['Faixa de Antiguidade'] == faixa, 'total']
                        if not valor_hoje_series.empty:
                            valor_hoje = int(valor_hoje_series.iloc[0])
                    valor_comparacao = 0
                    delta_text = "N/A"
                    delta_class = "delta-neutral"
                    if data_comparacao_final_tab4 and not df_comparacao_dados_tab4.empty and isinstance(valor_hoje, int):
                        valor_comp_series = df_comparacao_dados_tab4.loc[df_comparacao_dados_tab4['Faixa de Antiguidade'] == faixa, 'total']
                        if not valor_comp_series.empty:
                            valor_comparacao = int(valor_comp_series.iloc[0])
                        delta_abs = valor_hoje - valor_comparacao
                        delta_perc = (delta_abs / valor_comparacao) if valor_comparacao > 0 else 0
                        delta_text, delta_class = formatar_delta_card(delta_abs, delta_perc, valor_comparacao, data_comparacao_str_tab4)
                    elif isinstance(valor_hoje, int):
                        delta_text = "Sem dados para comparar"
                    st.markdown(f"""
                    <div class="metric-box">
                        <span class="label">{faixa}</span>
                        <span class="value">{valor_hoje}</span>
                        <span class="delta {delta_class}">{delta_text}</span>
                    </div>
                    """, unsafe_allow_html=True)
            st.divider()
            st.markdown(f"##### Gráfico de Evolução (Últimos 7 dias)")
            if df_filtrado_grafico.empty:
                st.warning("Não há dados para o período selecionado.")
            else:
                df_grafico = df_filtrado_grafico.sort_values(by='data')
                df_grafico['Data (Eixo)'] = df_grafico['data'].dt.strftime('%d/%m')
                ordem_datas_grafico = df_grafico['Data (Eixo)'].unique().tolist()
                base_color_aging = "#375623"
                palette_aging = [ lighten_color(base_color_aging, 0.85), lighten_color(base_color_aging, 0.70), lighten_color(base_color_aging, 0.55), lighten_color(base_color_aging, 0.40), lighten_color(base_color_aging, 0.20), base_color_aging ]
                color_map_aging = {faixa: color for faixa, color in zip(ordem_faixas_scaffold, palette_aging)}
                tipo_grafico = st.radio(
                    "Selecione o tipo de gráfico:",
                    ("Gráfico de Linha (Comparativo)", "Gráfico de Área (Composição)"),
                    horizontal=True, key="radio_tipo_grafico_aging"
                )
                if tipo_grafico == "Gráfico de Linha (Comparativo)":
                    fig_aging_all_tab4 = px.line(
                        df_grafico, x='Data (Eixo)', y='total', color='Faixa de Antiguidade',
                        title='Evolução por Faixa de Antiguidade', markers=True,
                        labels={"Data (Eixo)": "Data", "total": "Total Chamados", "Faixa de Antiguidade": "Faixa"},
                        category_orders={ 'Data (Eixo)': ordem_datas_grafico, 'Faixa de Antiguidade': ordem_faixas_scaffold },
                        color_discrete_map=color_map_aging
                    )
                else:
                    fig_aging_all_tab4 = px.area(
                        df_grafico, x='Data (Eixo)', y='total', color='Faixa de Antiguidade',
                        title='Composição da Evolução por Antiguidade', markers=True,
                        labels={"Data (Eixo)": "Data", "total": "Total Chamados", "Faixa de Antiguidade": "Faixa"},
                        category_orders={ 'Data (Eixo)': ordem_datas_grafico, 'Faixa de Antiguidade': ordem_faixas_scaffold },
                        color_discrete_map=color_map_aging
                    )
                fig_aging_all_tab4.update_layout(height=500)
                st.plotly_chart(fig_aging_all_tab4, use_container_width=True)
        except Exception as e:
            st.error(f"Ocorreu um erro ao gerar a aba de Evolução Aging: {e}")
            st.exception(e)

except Exception as e:
    st.error(f"Ocorreu um erro ao carregar os dados: {e}")
    st.exception(e)

st.markdown("---")
st.markdown("""
<p style='text-align: center; color: #666; font-size: 0.9em; margin-bottom: 0;'>v0.9.30-742 | Este dashboard está em desenvolvimento.</p>
<p style='text-align: center; color: #666; font-size: 0.9em; margin-top: 0;'>Desenvolvido por Leonir Scatolin Junior</p>
""", unsafe_allow_html=True)
