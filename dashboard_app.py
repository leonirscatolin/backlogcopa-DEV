# VERSÃO v0.9.63-773 (Limpeza final)

import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
import base64
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from github import Github, Auth, GithubException
from io import StringIO, BytesIO
import streamlit.components.v1 as components
from PIL import Image
from urllib.parse import quote
import json
import colorsys
import re

# --- Constantes Globais ---
GRUPOS_EXCLUSAO_PERMANENTE_REGEX = r'RH|Aprovadores GGM|RDM-GTR'
GRUPOS_EXCLUSAO_PERMANENTE_TEXTO = "'RH', 'Aprovadores GGM' ou 'RDM-GTR'"

GRUPOS_DE_AVISO_REGEX = r'Service Desk \(L1\)|LIQ-SUTEL'
GRUPOS_DE_AVISO_TEXTO = "'Service Desk (L1)' ou 'LIQ-SUTEL'"

GRUPOS_EXCLUSAO_TOTAL_REGEX = f"{GRUPOS_EXCLUSAO_PERMANENTE_REGEX}|{GRUPOS_DE_AVISO_REGEX}"
# --- FIM - Constantes Globais ---

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

/* Estiliza os botões de Salvar no Admin Sidebar */
[data-testid="stSidebar"] [data-testid="stButton"] button {
    background-color: #f28801;
    color: white;
    border: 1px solid #f28801;
}
[data-testid="stSidebar"] [data-testid="stButton"] button:hover {
    background-color: #d97900; /* Laranja mais escuro no hover */
    color: white;
    border-color: #d97900;
}
[data-testid="stSidebar"] [data-testid="stButton"] button:active {
    background-color: #b86700; /* Laranja ainda mais escuro no clique */
    color: white;
    border-color: #b86700;
}
[data-testid="stSidebar"] [data-testid="stButton"] button:focus:not(:active) {
    border-color: #f28801;
    box-shadow: 0 0 0 0.2rem rgba(242, 136, 1, 0.5); /* Anel de foco laranja */
}
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
        if file_path not in ["contacted_tickets.json", "ticket_observations.json", "datas_referencia.txt", "previous_closed_ids.json"]: 
            st.sidebar.info(f"Arquivo '{file_path}' atualizado.")
    except GithubException as e:
        if e.status == 404:
            if isinstance(file_content, str):
                file_content = file_content.encode('utf-8')
            _repo.create_file(file_path, commit_message, file_content)
            if file_path not in ["contacted_tickets.json", "ticket_observations.json", "datas_referencia.txt", "previous_closed_ids.json"]: 
                st.sidebar.info(f"Arquivo '{file_path}' criado.")
        else:
            st.sidebar.error(f"Falha ao salvar '{file_path}': {e}")
            raise 

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
        if e.status == 404: 
            return {}
        else:
            st.warning(f"Erro ao ler {file_path}: {e}")
            return {}
    except Exception as e:
        st.warning(f"Erro inesperado ao ler {file_path}: {e}")
        return {}


@st.cache_data(ttl=300)
def read_github_json_file(_repo, file_path, default_return_type='dict'): 
    try:
        file_content = _repo.get_contents(file_path).decoded_content.decode("utf-8")
        return json.loads(file_content) if file_content else (default_return_type == 'dict' and {} or [])
    except GithubException as e:
        if e.status == 404: return (default_return_type == 'dict' and {} or [])
        st.error(f"Erro ao carregar JSON '{file_path}': {e}")
        return (default_return_type == 'dict' and {} or [])
    except json.JSONDecodeError:
        st.error(f"Erro ao decodificar JSON '{file_path}'. Verifique o conteúdo.")
        return (default_return_type == 'dict' and {} or [])
    except Exception as e:
        st.error(f"Erro inesperado ao ler JSON '{file_path}': {e}")
        return (default_return_type == 'dict' and {} or [])

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
    
    df = df.dropna(subset=[date_col_name])
    
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
        try:
            if contact_changed:
                data_to_save = list(st.session_state.contacted_tickets)
                json_content = json.dumps(data_to_save, indent=4)
                commit_msg = f"Atualizando contatos em {now_str}"
                update_github_file(st.session_state.repo, "contacted_tickets.json", json_content.encode('utf-8'), commit_msg)
            if observation_changed:
                json_content = json.dumps(st.session_state.observations, indent=4, ensure_ascii=False)
                commit_msg = f"Atualizando observações em {now_str}"
                update_github_file(st.session_state.repo, "ticket_observations.json", json_content.encode('utf-8'), commit_msg)
            
            st.toast("Alterações salvas com sucesso!", icon="✅")
            
        except Exception as e:
            st.error(f"Erro ao salvar alterações: {e}")
            st.session_state.scroll_to_details = True
            return

    else:
        pass 

    st.session_state.ticket_editor['edited_rows'] = {}
    st.session_state.scroll_to_details = True


@st.cache_data(ttl=3600)
def carregar_dados_evolucao(_repo, dias_para_analisar=7): 
    try:
        all_files_content = _repo.get_contents("snapshots")
        all_files = [f.path for f in all_files_content]
        df_evolucao_list = []
        end_date = date.today()
        start_date = end_date - timedelta(days=max(dias_para_analisar, 10))

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
                        
                        df_snapshot_filtrado = df_snapshot[~df_snapshot['Atribuir a um grupo'].str.contains(GRUPOS_EXCLUSAO_TOTAL_REGEX, case=False, na=False, regex=True)]
                        
                        df_snapshot_final = df_snapshot_filtrado
                        
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
def carregar_evolucao_aging(_repo, dias_para_analisar=90): 
    try:
        all_files_content = _repo.get_contents("snapshots")
        all_files = [f.path for f in all_files_content]
        lista_historico = []

        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=max(dias_para_analisar, 60))

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

                df_filtrado = df_snapshot[~df_snapshot['Atribuir a um grupo'].str.contains(GRUPOS_EXCLUSAO_TOTAL_REGEX, case=False, na=False, regex=True)]

                df_final = df_filtrado

                df_final = df_final.copy() 

                date_col_name = next((col for col in ['Data de criação', 'Data de Criacao'] if col in df_final.columns), None)
                if not date_col_name:
                    continue

                df_final[date_col_name] = pd.to_datetime(df_final[date_col_name], errors='coerce')
                df_final = df_final.dropna(subset=[date_col_name])

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
    st.sidebar.subheader("Atualização Rápida (Manual)")
    uploaded_file_fechados = st.sidebar.file_uploader("Apenas Chamados FECHADOS no dia", type=["csv", "xlsx"], key="uploader_fechados")
    if st.sidebar.button("Salvar Apenas Chamados Fechados"):
        if uploaded_file_fechados:
            with st.spinner("Salvando arquivo de fechados e atualizando snapshot diário..."):
                now_sao_paulo = datetime.now(ZoneInfo('America/Sao_Paulo'))
                commit_msg = f"Atualizando chamados fechados em {now_sao_paulo.strftime('%d/%m/%Y %H:%M')}"
                
                content_fechados = process_uploaded_file(uploaded_file_fechados)
                if content_fechados is None:
                    st.sidebar.error("Falha ao processar o arquivo de fechados.")
                    st.stop() 

                try:
                    df_fechados_anterior = read_github_file(repo, "dados_fechados.csv")
                    previous_closed_ids = set()
                    if not df_fechados_anterior.empty:
                        id_col_anterior = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_fechados_anterior.columns), None)
                        if id_col_anterior:
                            previous_closed_ids = set(df_fechados_anterior[id_col_anterior].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().dropna().unique())
                    
                    json_content = json.dumps(list(previous_closed_ids), indent=4)
                    update_github_file(repo, "previous_closed_ids.json", json_content.encode('utf-8'), "Snapshot dos IDs de fechados anteriores")

                    update_github_file(repo, "dados_fechados.csv", content_fechados, commit_msg)

                    datas_existentes = read_github_text_file(repo, "datas_referencia.txt")
                    data_atual_existente = datas_existentes.get('data_atual', 'N/A')
                    data_15dias_existente = datas_existentes.get('data_15dias', 'N/A')
                    hora_atualizacao_nova = now_sao_paulo.strftime('%H:%M')

                    datas_referencia_content_novo = (f"data_atual:{data_atual_existente}\n"
                                                    f"data_15dias:{data_15dias_existente}\n"
                                                    f"hora_atualizacao:{hora_atualizacao_nova}")
                    update_github_file(repo, "datas_referencia.txt", datas_referencia_content_novo.encode('utf-8'), commit_msg)
                    
                    df_atual_base = read_github_file(repo, "dados_atuais.csv")
                    if df_atual_base.empty:
                        st.sidebar.warning("Não foi possível ler o 'dados_atuais.csv' base para atualizar o snapshot.")
                        raise Exception("Arquivo 'dados_atuais.csv' base não encontrado.")

                    df_fechados_novo = pd.read_csv(BytesIO(content_fechados), delimiter=';', dtype={'ID do ticket': str, 'ID do Ticket': str, 'ID': str})
                    
                    id_col_fechados = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_fechados_novo.columns), None)
                    if not id_col_fechados:
                         st.sidebar.warning("Não foi possível encontrar coluna de ID no arquivo de fechados.")
                         raise Exception("Coluna de ID não encontrada nos fechados.")

                    closed_ids_set = set(df_fechados_novo[id_col_fechados].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().dropna().unique())

                    id_col_atual = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_atual_base.columns), None)
                    if not id_col_atual:
                         st.sidebar.warning("Não foi possível encontrar coluna de ID no 'dados_atuais.csv' base.")
                         raise Exception("Coluna de ID não encontrada no 'dados_atuais.csv' base.")
                    
                    df_atual_base[id_col_atual] = df_atual_base[id_col_atual].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    
                    df_atualizado_filtrado = df_atual_base[~df_atual_base[id_col_atual].isin(closed_ids_set)]

                    output = StringIO()
                    df_atualizado_filtrado.to_csv(output, index=False, sep=';', encoding='utf-8')
                    content_snapshot_novo = output.getvalue().encode('utf-8')

                    today_str = now_sao_paulo.strftime('%Y-%m-%d')
                    snapshot_path = f"snapshots/backlog_{today_str}.csv"
                    commit_msg_snapshot = f"Atualizando snapshot (rápido) em {now_sao_paulo.strftime('%d/%m/%Y %H:%M')}"
                    
                    update_github_file(repo, snapshot_path, content_snapshot_novo, commit_msg_snapshot)
                    
                    st.cache_data.clear()
                    st.cache_resource.clear()
                    st.sidebar.success("Arquivo de fechados salvo e snapshot diário atualizado! Recarregando...")
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
        st.session_state.observations = read_github_json_file(repo, "ticket_observations.json", default_return_type='dict')

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
    
    previous_closed_ids = set(read_github_json_file(repo, "previous_closed_ids.json", default_return_type='list'))
    
    data_atual_str = datas_referencia.get('data_atual', 'N/A')
    data_15dias_str = datas_referencia.get('data_15dias', 'N/A')
    hora_atualizacao_str = datas_referencia.get('hora_atualizacao', '')
    if df_atual.empty or df_15dias.empty:
        st.warning("Ainda não há dados para exibir. Por favor, carregue os arquivos na área do administrador.")
        st.stop()
    if 'ID do ticket' in df_atual.columns:
        df_atual['ID do ticket'] = df_atual['ID do ticket'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

    closed_ticket_ids = []
    current_closed_ids = set()
    newly_closed_ids = set() 

    if not df_fechados.empty:
        id_col_name = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_fechados.columns), None)
        if id_col_name:
            df_fechados[id_col_name] = df_fechados[id_col_name].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            current_closed_ids = set(df_fechados[id_col_name].dropna().unique())
            closed_ticket_ids = list(current_closed_ids) 
    
    if previous_closed_ids: 
        newly_closed_ids = current_closed_ids - previous_closed_ids
    else:
        newly_closed_ids = current_closed_ids
    
    df_encerrados = df_atual[df_atual['ID do ticket'].isin(closed_ticket_ids)]
    df_abertos = df_atual[~df_atual['ID do ticket'].isin(closed_ticket_ids)]
    
    df_atual_filtrado = df_abertos[~df_abertos['Atribuir a um grupo'].str.contains(GRUPOS_EXCLUSAO_PERMANENTE_REGEX, case=False, na=False, regex=True)]
    df_15dias_filtrado = df_15dias[~df_15dias['Atribuir a um grupo'].str.contains(GRUPOS_EXCLUSAO_TOTAL_REGEX, case=False, na=False, regex=True)]
    df_aging = analisar_aging(df_atual_filtrado)
    df_encerrados_filtrado = df_encerrados[~df_encerrados['Atribuir a um grupo'].str.contains(GRUPOS_EXCLUSAO_PERMANENTE_REGEX, case=False, na=False, regex=True)]


    tab1, tab2, tab3, tab4 = st.tabs(["Dashboard Completo", "Report Visual", "Evolução Semanal", "Evolução Aging"])

    with tab1:
        
        df_para_aviso = df_atual_filtrado[
            df_atual_filtrado['Atribuir a um grupo'].str.contains(
                GRUPOS_DE_AVISO_REGEX, case=False, na=False, regex=True
            )
        ]
        
        if not df_para_aviso.empty:
            total_para_aviso = len(df_para_aviso)
            contagem_por_grupo = df_para_aviso['Atribuir a um grupo'].value_counts()
            
            aviso_str_lista = [f"⚠️ **Atenção:** Foram encontrados **{total_para_aviso}** chamados em grupos que deveriam estar zerados ({GRUPOS_DE_AVISO_TEXTO}):"]
            for grupo, contagem in contagem_por_grupo.items():
                aviso_str_lista.append(f"- **{grupo}:** {contagem} chamado(s)")
            
            st.warning("\n".join(aviso_str_lista))

        info_messages = ["**Filtros e Regras Aplicadas:**", 
                         f"- Grupos contendo {GRUPOS_EXCLUSAO_PERMANENTE_TEXTO} foram desconsiderados da análise.", 
                         "- A contagem de dias do chamado desconsidera o dia da sua abertura (prazo -1 dia)."]
        
        if not df_encerrados.empty:
            info_messages.append(f"- **{len(df_encerrados_filtrado)} chamados fechados no dia** (exceto os grupos filtrados acima) foram deduzidos das contagens principais.")
        
        st.info("\n".join(info_messages))
        
        st.subheader("Análise de Antiguidade do Backlog Atual")
        texto_hora = f" (atualizado às {hora_atualizacao_str})" if hora_atualizacao_str else ""
        st.markdown(f"<p style='font-size: 0.9em; color: #666;'><i>Data de referência: {data_atual_str}{texto_hora}</i></p>", unsafe_allow_html=True)
        if not df_aging.empty:

            total_chamados = len(df_aging)
            total_fechados = len(df_encerrados_filtrado)
            col_spacer1, col_total, col_fechados, col_spacer2 = st.columns([1, 1.5, 1.5, 1])
            with col_total:
                st.markdown(f"""<div class="metric-box"><span class="label">Total de Chamados Abertos</span><span class="value">{total_chamados}</span></div>""", unsafe_allow_html=True)
            with col_fechados:
                valor_fechados = total_fechados if total_fechados > 0 else "N/A"
                st.markdown(f"""<div class="metric-box"><span class="label">Chamados Fechados no Dia</span><span class="value">{valor_fechados}</span></div>""", unsafe_allow_html=True)

            st.markdown("---")
            aging_counts = df_aging['Faixa de Antiguidade'].value_counts().reset_index()
            aging_counts.columns = ['Faixa de Antiguidade', 'Quantidade']
            ordem_faixas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
            todas_as_faixas = pd.DataFrame({'Faixa de Antiguidade': ordem_faixas})
            aging_counts = pd.merge(todas_as_faixas, aging_counts, on='Faixa de Antiguidade', how='left').fillna(0).astype({'Quantidade': int})
            aging_counts['Faixa de Antiguidade'] = pd.Categorical(aging_counts['Faixa de Antiguidade'], categories=ordem_faixas, ordered=True)
            aging_counts = aging_counts.sort_values('Faixa de Antiguidade')
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
        
        df_comparativo = df_comparativo.rename(columns={'Atribuir a um grupo': 'Grupo'})
        
        df_comparativo = df_comparativo[['Grupo', '15 Dias Atrás', 'Atual', 'Diferença', 'Status']]
        st.dataframe(df_comparativo.set_index('Grupo').style.map(lambda val: 'background-color: #ffcccc' if val > 0 else ('background-color: #ccffcc' if val < 0 else 'background-color: white'), subset=['Diferença']), use_container_width=True)
        st.markdown("---")
        st.markdown(f"<h3>Chamados Encerrados no Dia <span style='font-size: 0.6em; color: #666; font-weight: normal;'>({data_atual_str})</span></h3>", unsafe_allow_html=True)

        if df_fechados.empty:
            st.info("O arquivo de chamados encerrados ainda não foi carregado.")
        elif not df_encerrados_filtrado.empty:
            
            df_encerrados_para_exibir = df_encerrados_filtrado.copy()
            
            date_col_name = next((col for col in ['Data de criação', 'Data de Criacao'] if col in df_encerrados_para_exibir.columns), None)
            
            colunas_para_exibir_fechados = ['Status', 'ID do ticket', 'Descrição']
            
            novo_nome_analista = "Analista de Resolução" 
            analista_col_name_origem = "Analista atribuído" 
            
            id_col_encerrados = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_encerrados_para_exibir.columns), None)
            if id_col_encerrados:
                 df_encerrados_para_exibir['Status'] = df_encerrados_para_exibir[id_col_encerrados].apply(
                    lambda x: "Novo" if x in newly_closed_ids else ""
                )
            else:
                df_encerrados_para_exibir['Status'] = ""
            
            id_col_fechados = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_fechados.columns), None)
            
            if id_col_fechados and analista_col_name_origem in df_fechados.columns:
                df_analistas_lookup = df_fechados[[id_col_fechados, analista_col_name_origem]].drop_duplicates(subset=[id_col_fechados]).copy()
                
                df_analistas_lookup[analista_col_name_origem] = df_analistas_lookup[analista_col_name_origem].astype(str).replace(r'\s+', ' ', regex=True).str.strip()
                
                df_encerrados_para_exibir = pd.merge(
                    df_encerrados_para_exibir,
                    df_analistas_lookup,
                    left_on='ID do ticket',
                    right_on=id_col_fechados,
                    how='left'
                )
                
                df_encerrados_para_exibir.rename(columns={analista_col_name_origem: novo_nome_analista}, inplace=True)
                colunas_para_exibir_fechados.append(novo_nome_analista)
            
            colunas_para_exibir_fechados.append('Atribuir a um grupo')

            if date_col_name:
                try:
                    df_encerrados_para_exibir[date_col_name] = pd.to_datetime(df_encerrados_para_exibir[date_col_name], errors='coerce')
                    
                    hoje = pd.to_datetime('today').normalize()
                    
                    data_criacao_normalizada = df_encerrados_para_exibir[date_col_name].dt.normalize()
                    
                    dias_calculados = (hoje - data_criacao_normalizada).dt.days
                    
                    df_encerrados_para_exibir['Dias em Aberto'] = (dias_calculados - 1).clip(lower=0)
                    
                    colunas_para_exibir_fechados.append('Dias em Aberto')
                    
                except Exception as e:
                    st.warning(f"Não foi possível calcular os 'Dias em Aberto' para os chamados fechados: {e}")
            
            st.data_editor(
                df_encerrados_para_exibir[colunas_para_exibir_fechados], 
                hide_index=True, 
                disabled=True, 
                use_container_width=True,
                column_config={
                    "Status": st.column_config.Column(
                        width="small"
                    )
                }
            )
            
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

            st.selectbox("Selecione uma faixa de idade para ver os detalhes (ou clique em um card acima):", 
                         options=ordem_faixas, 
                         key='faixa_selecionada',
                         on_change=sync_ticket_data) # v0.9.42: Salva ao trocar de faixa
            
            faixa_atual = st.session_state.faixa_selecionada
            filtered_df = df_aging[df_aging['Faixa de Antiguidade'] == faixa_atual].copy()
            if not filtered_df.empty:
                def highlight_row(row):
                    return ['background-color: #fff8c4'] * len(row) if row['Contato'] else [''] * len(row)

                filtered_df['Contato'] = filtered_df['ID do ticket'].apply(lambda id: str(id) in st.session_state.contacted_tickets)
                filtered_df['Observações'] = filtered_df['ID do ticket'].apply(lambda id: st.session_state.observations.get(str(id), ''))

                st.session_state.last_filtered_df = filtered_df.reset_index(drop=True)

                colunas_para_exibir_renomeadas = {
                    'Contato': 'Contato',
                    'ID do ticket': 'ID do ticket',
                    'Descrição': 'Descrição',
                    'Atribuir a um grupo': 'Grupo Atribuído',
                    'Dias em Aberto': 'Dias em Aberto',
                    'Data de criação': 'Data de criação',
                    'Observações': 'Observações'
                }

                st.data_editor(
                    st.session_state.last_filtered_df.rename(columns=colunas_para_exibir_renomeadas)[list(colunas_para_exibir_renomeadas.values())].style.apply(highlight_row, axis=1),
                    use_container_width=True,
                    hide_index=True,
                    disabled=['ID do ticket', 'Descrição', 'Grupo Atribuído', 'Dias em Aberto', 'Data de criação'],
                    key='ticket_editor'
                )
                
                st.button(
                    "Salvar Contatos e Observações",
                    on_click=sync_ticket_data,
                    type="primary"
                )
                
                if st.session_state.ticket_editor.get('edited_rows'):
                    js_code = """
                    <script>
                    window.onbeforeunload = function() {
                        return "Você tem alterações não salvas. Deseja realmente sair?";
                    };
                    </script>
                    """
                    components.html(js_code, height=0)
                else:
                    js_code = """
                    <script>
                    window.onbeforeunload = null;
                    </script>
                    """
                    components.html(js_code, height=0)
                
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
        st.subheader("Resumo do Backlog Atual")
        if not df_aging.empty:
            total_chamados = len(df_aging)
            _, col_total_tab2, _ = st.columns([2, 1.5, 2])
            with col_total_tab2: st.markdown( f"""<div class="metric-box"><span class="label">Total de Chamados</span><span class="value">{total_chamados}</span></div>""", unsafe_allow_html=True )
            st.markdown("---")
            aging_counts_tab2 = df_aging['Faixa de Antiguidade'].value_counts().reset_index()
            aging_counts_tab2.columns = ['Faixa de Antiguidade', 'Quantidade']
            ordem_faixas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
            todas_as_faixas_tab2 = pd.DataFrame({'Faixa de Antiguidade': ordem_faixas})
            aging_counts_tab2 = pd.merge(todas_as_faixas_tab2, aging_counts_tab2, on='Faixa de Antiguidade', how='left').fillna(0).astype({'Quantidade': int})
            aging_counts_tab2['Faixa de Antiguidade'] = pd.Categorical(aging_counts_tab2['Faixa de Antiguidade'], categories=ordem_faixas, ordered=True)
            aging_counts_tab2 = aging_counts_tab2.sort_values('Faixa de Antiguidade')
            cols_tab2 = st.columns(len(ordem_faixas))
            for i, row in aging_counts_tab2.iterrows():
                with cols_tab2[i]: st.markdown( f"""<div class="metric-box"><span class="label">{row['Faixa de Antiguidade']}</span><span class="value">{row['Quantidade']}</span></div>""", unsafe_allow_html=True )
            st.markdown("---")
            st.subheader("Distribuição do Backlog por Grupo")
            orientation_choice = st.radio( "Orientação do Gráfico:", ["Vertical", "Horizontal"], index=0, horizontal=True )
            chart_data = df_aging.groupby(['Atribuir a um grupo', 'Faixa de Antiguidade']).size().reset_index(name='Quantidade')
            group_totals = chart_data.groupby('Atribuir a um grupo')['Quantidade'].sum().sort_values(ascending=False)
            new_labels_map = {group: f"{group} ({total})" for group, total in group_totals.items()}
            chart_data['Atribuir a um grupo'] = chart_data['Atribuir a um grupo'].map(new_labels_map)
            sorted_new_labels = [new_labels_map[group] for group in group_totals.index]
            def lighten_color(hex_color, amount=0.2):
                try:
                    hex_color = hex_color.lstrip('#')
                    h, l, s = colorsys.rgb_to_hls(*[int(hex_color[i:i+2], 16)/255.0 for i in (0, 2, 4)])
                    new_l = l + (1 - l) * amount
                    r, g, b = colorsys.hls_to_rgb(h, new_l, s)
                    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
                except Exception: return hex_color
            base_color = "#375623"
            palette = [ lighten_color(base_color, 0.85), lighten_color(base_color, 0.70), lighten_color(base_color, 0.55), lighten_color(base_color, 0.40), lighten_color(base_color, 0.20), base_color ]
            color_map = {faixa: color for faixa, color in zip(ordem_faixas, palette)}
            if orientation_choice == 'Horizontal':
                num_groups = len(group_totals)
                dynamic_height = max(500, num_groups * 30)
                fig_stacked_bar = px.bar( chart_data, x='Quantidade', y='Atribuir a um grupo', orientation='h', color='Faixa de Antiguidade', title="Composição da Idade do Backlog por Grupo", labels={'Quantidade': 'Qtd. de Chamados', 'Atribuir a um grupo': ''}, category_orders={'Atribuir a um grupo': sorted_new_labels, 'Faixa de Antiguidade': ordem_faixas}, color_discrete_map=color_map, text_auto=True )
                fig_stacked_bar.update_traces(textangle=0, textfont_size=12)
                fig_stacked_bar.update_layout(height=dynamic_height, legend_title_text='Antiguidade')
            else:
                fig_stacked_bar = px.bar( chart_data, x='Atribuir a um grupo', y='Quantidade', color='Faixa de Antiguidade', title="Composição da Idade do Backlog por Grupo", labels={'Quantidade': 'Qtd. de Chamados', 'Atribuir a um grupo': 'Grupo'}, category_orders={'Atribuir a um grupo': sorted_new_labels, 'Faixa de Antiguidade': ordem_faixas}, color_discrete_map=color_map, text_auto=True )
                fig_stacked_bar.update_traces(textangle=0, textfont_size=12)
                fig_stacked_bar.update_layout(height=600, xaxis_title=None, xaxis_tickangle=-45, legend_title_text='Antiguidade')
            st.plotly_chart(fig_stacked_bar, use_container_width=True)
        else:
            st.warning("Nenhum dado para gerar o report visual.")

    with tab3:
        st.subheader("Evolução do Backlog")
        dias_evolucao = st.slider("Ver evolução dos últimos dias:", min_value=7, max_value=30, value=7, key="slider_evolucao")

        df_evolucao_tab3 = carregar_dados_evolucao(repo, dias_para_analisar=dias_evolucao)

        if not df_evolucao_tab3.empty:

            df_evolucao_tab3['Data'] = pd.to_datetime(df_evolucao_tab3['Data'])
            df_evolucao_tab3 = df_evolucao_tab3[df_evolucao_tab3['Data'].dt.dayofweek < 5].copy()

            if not df_evolucao_tab3.empty:

                st.info("Esta visualização ainda está coletando dados históricos. Utilize as outras abas como referência principal por enquanto.")

                df_total_diario = df_evolucao_tab3.groupby('Data')['Total Chamados'].sum().reset_index()
                df_total_diario = df_total_diario.sort_values('Data')

                df_total_diario['Data (Eixo)'] = df_total_diario['Data'].dt.strftime('%d/%m')
                ordem_datas_total = df_total_diario['Data (Eixo)'].tolist()

                fig_total_evolucao = px.area(
                    df_total_diario,
                    x='Data (Eixo)',
                    y='Total Chamados',
                    title='Evolução do Total Geral de Chamados Abertos (Apenas Dias de Semana)',
                    markers=True,
                    labels={"Data (Eixo)": "Data", "Total Chamados": "Total Geral de Chamados"},
                    category_orders={'Data (Eixo)': ordem_datas_total}
                )
                fig_total_evolucao.update_layout(height=400)
                st.plotly_chart(fig_total_evolucao, use_container_width=True)

                st.markdown("---")

                st.info("Esta visualização já filtra os chamados fechados e permite filtrar grupos clicando 2x na legenda.")

                df_evolucao_tab3_sorted = df_evolucao_tab3.sort_values('Data')
                df_evolucao_tab3_sorted['Data (Eixo)'] = df_evolucao_tab3_sorted['Data'].dt.strftime('%d/%m')

                ordem_datas_grupo = df_evolucao_tab3_sorted['Data (Eixo)'].unique().tolist()

                df_filtrado_display = df_evolucao_tab3_sorted.rename(columns={'Atribuir a um grupo': 'Grupo Atribuído'})

                fig_evolucao_grupo = px.line(
                    df_filtrado_display,
                    x='Data (Eixo)',
                    y='Total Chamados',
                    color='Grupo Atribuído',
                    title='Evolução por Grupo (Apenas Dias de Semana)',
                    markers=True,
                    labels={ "Data (Eixo)": "Data", "Total Chamados": "Nº de Chamados", "Grupo Atribuído": "Grupo" },
                    category_orders={'Data (Eixo)': ordem_datas_grupo}
                )
                fig_evolucao_grupo.update_layout(height=600)
                st.plotly_chart(fig_evolucao_grupo, use_container_width=True)

            else:
                st.info("Ainda não há dados históricos suficientes (considerando apenas dias de semana).")

        else:
            st.info("Ainda não há dados históricos suficientes.")

    with tab4:
        st.subheader("Evolução do Aging do Backlog")
        
        st.info("Esta visualização ainda está coletando dados históricos. Utilize as outras abas como referência principal por enquanto.")

        try:
            df_hist = carregar_evolucao_aging(repo, dias_para_analisar=90)

            ordem_faixas_scaffold = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
            hoje_data = None
            hoje_counts_df = pd.DataFrame()

            if 'df_aging' in locals() and not df_aging.empty and data_atual_str != 'N/A':
                try:
                    hoje_data = pd.to_datetime(datetime.strptime(data_atual_str, "%d/%m/%Y").date())
                    hoje_counts_raw = df_aging['Faixa de Antiguidade'].value_counts().reset_index()
                    hoje_counts_raw.columns = ['Faixa de Antiguidade', 'total']
                    df_todas_faixas_hoje = pd.DataFrame({'Faixa de Antiguidade': ordem_faixas_scaffold})
                    hoje_counts_df = pd.merge(
                        df_todas_faixas_hoje,
                        hoje_counts_raw,
                        on='Faixa de Antiguidade',
                        how='left'
                    ).fillna(0)
                    hoje_counts_df['total'] = hoje_counts_df['total'].astype(int)
                    hoje_counts_df['data'] = hoje_data
                except ValueError:
                    st.warning("Data atual inválida. Não foi possível carregar dados de 'hoje'.")
                    hoje_data = None
            else:
                st.warning("Não foi possível carregar dados de 'hoje'.")


            if not df_hist.empty and not hoje_counts_df.empty:
                df_combinado = pd.concat([df_hist, hoje_counts_df], ignore_index=True)
                df_combinado = df_combinado.drop_duplicates(subset=['data', 'Faixa de Antiguidade'], keep='last')
            elif not df_hist.empty:
                df_combinado = df_hist.copy()
            elif not hoje_counts_df.empty:
                df_combinado = hoje_counts_df.copy()
            else:
                st.error("Não há dados históricos nem dados de hoje para a análise de aging.")
                st.stop()

            df_combinado['data'] = pd.to_datetime(df_combinado['data'])
            df_combinado = df_combinado.sort_values(by=['data', 'Faixa de Antiguidade'])


            st.markdown("##### Comparativo")
            periodo_comp_opts = {
                "Ontem": 1,
                "7 dias atrás": 7,
                "15 dias atrás": 15,
                "30 dias atrás": 30
            }
            periodo_comp_selecionado = st.radio(
                "Comparar 'Hoje' com:",
                options=periodo_comp_opts.keys(),
                horizontal=True,
                key="radio_comp_periodo"
            )

            data_comparacao_final = None
            df_comparacao_dados = pd.DataFrame()
            data_comparacao_str = "N/A"

            if hoje_data:
                target_comp_date = hoje_data.date() - timedelta(days=periodo_comp_opts[periodo_comp_selecionado])
                data_comparacao_encontrada, _ = find_closest_snapshot_before(repo, hoje_data.date(), target_comp_date)

                if data_comparacao_encontrada:
                    data_comparacao_final = pd.to_datetime(data_comparacao_encontrada)
                    data_comparacao_str = data_comparacao_final.strftime('%d/%m')
                    df_comparacao_dados = df_combinado[df_combinado['data'] == data_comparacao_final].copy()
                else:
                    st.warning(f"Não foi encontrado snapshot próximo a {periodo_comp_selecionado} ({target_comp_date.strftime('%d/%m')}). A comparação pode não ser precisa.")


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

                    if data_comparacao_final and not df_comparacao_dados.empty and isinstance(valor_hoje, int):
                        valor_comp_series = df_comparacao_dados.loc[df_comparacao_dados['Faixa de Antiguidade'] == faixa, 'total']
                        if not valor_comp_series.empty:
                            valor_comparacao = int(valor_comp_series.iloc[0])

                        delta_abs = valor_hoje - valor_comparacao
                        delta_perc = (delta_abs / valor_comparacao) if valor_comparacao > 0 else 0
                        delta_text, delta_class = formatar_delta_card(delta_abs, delta_perc, valor_comparacao, data_comparacao_str)
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

            periodo_grafico = "Últimos 7 dias"
            hoje_filtro_grafico = datetime.now().date()
            data_inicio_filtro_grafico = hoje_filtro_grafico - timedelta(days=7)
            df_filtrado_grafico = df_combinado[df_combinado['data'].dt.date >= data_inicio_filtro_grafico].copy()


            if df_filtrado_grafico.empty:
                st.warning("Não há dados para o período selecionado.")
            else:
                df_grafico = df_filtrado_grafico.sort_values(by='data')
                df_grafico['Data (Eixo)'] = df_grafico['data'].dt.strftime('%d/%m')
                ordem_datas_grafico = df_grafico['Data (Eixo)'].unique().tolist()

                def lighten_color(hex_color, amount=0.2):
                    try:
                        hex_color = hex_color.lstrip('#')
                        h, l, s = colorsys.rgb_to_hls(*[int(hex_color[i:i+2], 16)/255.0 for i in (0, 2, 4)])
                        new_l = l + (1 - l) * amount
                        r, g, b = colorsys.hls_to_rgb(h, new_l, s)
                        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
                    except Exception: return hex_color
                base_color = "#375623"
                palette = [ lighten_color(base_color, 0.85), lighten_color(base_color, 0.70), lighten_color(base_color, 0.55), lighten_color(base_color, 0.40), lighten_color(base_color, 0.20), base_color ]
                color_map = {faixa: color for faixa, color in zip(ordem_faixas_scaffold, palette)}

                tipo_grafico = st.radio(
                    "Selecione o tipo de gráfico:",
                    ("Gráfico de Linha (Comparativo)", "Gráfico de Área (Composição)"),
                    horizontal=True,
                    key="radio_tipo_grafico_aging"
                )

                if tipo_grafico == "Gráfico de Linha (Comparativo)":
                    fig_aging_all = px.line(
                        df_grafico,
                        x='Data (Eixo)',
                        y='total',
                        color='Faixa de Antiguidade',
                        title='Evolução por Faixa de Antiguidade',
                        markers=True,
                        labels={"Data (Eixo)": "Data", "total": "Total Chamados", "Faixa de Antiguidade": "Faixa"},
                        category_orders={
                            'Data (Eixo)': ordem_datas_grafico,
                            'Faixa de Antiguidade': ordem_faixas_scaffold
                        },
                        color_discrete_map=color_map
                    )
                else:
                    fig_aging_all = px.area(
                        df_grafico,
                        x='Data (Eixo)',
                        y='total',
                        color='Faixa de Antiguidade',
                        title='Composição da Evolução por Antiguidade',
                        markers=True,
                        labels={"Data (Eixo)": "Data", "total": "Total Chamados", "Faixa de Antiguidade": "Faixa"},
                        category_orders={
                            'Data (Eixo)': ordem_datas_grafico,
                            'Faixa de Antiguidade': ordem_faixas_scaffold
                        },
                        color_discrete_map=color_map
                    )

                fig_aging_all.update_layout(height=500)
                st.plotly_chart(fig_aging_all, use_container_width=True)

        except Exception as e:
            st.error(f"Ocorreu um erro ao gerar a aba de Evolução Aging: {e}")
            st.exception(e)

except Exception as e:
    st.error(f"Ocorreu um erro ao carregar os dados: {e}")
    st.exception(e)

st.markdown("---")
st.markdown("""
<p style='text-align: center; color: #666; font-size: 0.9em; margin-bottom: 0;'>v0.9.63-773 | Este dashboard está em desenvolvimento.</p>
<p style='text-align: center; color: #666; font-size: 0.9em; margin-top: 0;'>Desenvolvido por Leonir Scatolin Junior</p>
""", unsafe_allow_html=True)
