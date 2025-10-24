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
import plotly.graph_objects as go # Importar graph_objects

st.set_page_config(
    layout="wide",
    page_title="Backlog Copa Energia + Belago",
    page_icon="minilogo.png",
    initial_sidebar_state="collapsed"
)

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
        if file_path not in ["contacted_tickets.json", "ticket_observations.json"]:
             st.sidebar.info(f"Arquivo '{file_path}' atualizado.")
    except GithubException as e:
        if e.status == 404:
            if isinstance(file_content, str):
                file_content = file_content.encode('utf-8')
            _repo.create_file(file_path, commit_message, file_content)
            if file_path not in ["contacted_tickets.json", "ticket_observations.json"]:
                 st.sidebar.info(f"Arquivo '{file_path}' criado.")
        else:
            st.sidebar.error(f"Falha ao salvar '{file_path}': {e}")

@st.cache_data(ttl=300)
def read_github_file(_repo, file_path):
    try:
        content_file = _repo.get_contents(file_path)
        content = content_file.decoded_content.decode("utf-8")
        if not content.strip(): return pd.DataFrame()
        # Ensure ID columns are read as strings by checking first row
        try:
            first_row_df = pd.read_csv(StringIO(content), delimiter=';', encoding='utf-8', nrows=0)
            dtype_spec = {col: str for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in first_row_df.columns}
        except Exception: # Handle case where reading first row fails (e.g., empty file after header)
            dtype_spec = {'ID do ticket': str, 'ID do Ticket': str, 'ID': str} # Default guess
        df = pd.read_csv(StringIO(content), delimiter=';', encoding='utf-8', dtype=dtype_spec)
        df.columns = df.columns.str.strip()
        return df
    except GithubException as e:
        if e.status == 404: return pd.DataFrame()
        st.error(f"Erro ao ler CSV '{file_path}': {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao ler CSV '{file_path}': {e}")
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
        if e.status == 404: return {}
        st.error(f"Erro ao ler TXT '{file_path}': {e}")
        return {}
    except Exception: return {}

@st.cache_data(ttl=300)
def read_github_json_dict(_repo, file_path):
    try:
        file_content = _repo.get_contents(file_path).decoded_content.decode("utf-8")
        # Handle potential empty file or invalid JSON
        return json.loads(file_content) if file_content and file_content.strip() else {}
    except GithubException as e:
        if e.status == 404: return {}
        st.error(f"Erro ao carregar JSON '{file_path}': {e}")
        return {}
    except json.JSONDecodeError:
        st.warning(f"Arquivo JSON '{file_path}' vazio ou mal formatado. Iniciando com dados vazios.")
        return {} # Return empty dict if JSON is invalid or empty
    except Exception as e:
        st.error(f"Erro inesperado ao ler JSON '{file_path}': {e}")
        return {}


def process_uploaded_file(uploaded_file):
    if uploaded_file is None: return None
    try:
        # Define dtype for potential ID columns consistently
        dtype_spec = {'ID do ticket': str, 'ID do Ticket': str, 'ID': str}
        if uploaded_file.name.endswith('.xlsx'):
            # Read only necessary columns if possible, enforce string type for IDs
            df = pd.read_excel(uploaded_file, dtype=dtype_spec)
        else:
            # Detect encoding
            try:
                content_bytes = uploaded_file.getvalue()
                content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                content = content_bytes.decode('latin1') # Fallback encoding
            # Read CSV enforcing string type for IDs
            df = pd.read_csv(StringIO(content), delimiter=';', dtype=dtype_spec)

        df.columns = df.columns.str.strip()
        output = StringIO()
        df.to_csv(output, index=False, sep=';', encoding='utf-8')
        return output.getvalue().encode('utf-8')
    except Exception as e:
        st.sidebar.error(f"Erro ao ler {uploaded_file.name}: {e}")
        return None

def processar_dados_comparativos(df_atual, df_15dias):
    # Ensure 'Atribuir a um grupo' exists and handle potential missing column
    if 'Atribuir a um grupo' not in df_atual.columns or 'Atribuir a um grupo' not in df_15dias.columns:
        st.warning("Coluna 'Atribuir a um grupo' não encontrada em um dos dataframes para comparação.")
        return pd.DataFrame(columns=['Grupo Atribuído', '15 Dias Atrás', 'Atual', 'Diferença', 'Status'])

    contagem_atual = df_atual.groupby('Atribuir a um grupo').size().reset_index(name='Atual')
    contagem_15dias = df_15dias.groupby('Atribuir a um grupo').size().reset_index(name='15 Dias Atrás')
    df_comparativo = pd.merge(contagem_atual, contagem_15dias, on='Atribuir a um grupo', how='outer').fillna(0)
    df_comparativo['Diferença'] = df_comparativo['Atual'] - df_comparativo['15 Dias Atrás']
    # Convert relevant columns to integer type
    df_comparativo[['Atual', '15 Dias Atrás', 'Diferença']] = df_comparativo[['Atual', '15 Dias Atrás', 'Diferença']].astype(int)
    df_comparativo.rename(columns={'Atribuir a um grupo': 'Grupo Atribuído'}, inplace=True) # Rename after merge
    df_comparativo['Status'] = df_comparativo.apply(get_status, axis=1) # Apply status after calculations
    # Reorder columns for final display
    df_comparativo = df_comparativo[['Grupo Atribuído', '15 Dias Atrás', 'Atual', 'Diferença', 'Status']]
    return df_comparativo


@st.cache_data
def categorizar_idade_vetorizado(dias_series):
    # Ensure input is numeric, coerce errors to NaN
    dias_numeric = pd.to_numeric(dias_series, errors='coerce')
    condicoes = [
        dias_numeric >= 30,
        (dias_numeric >= 21) & (dias_numeric <= 29),
        (dias_numeric >= 11) & (dias_numeric <= 20),
        (dias_numeric >= 6) & (dias_numeric <= 10),
        (dias_numeric >= 3) & (dias_numeric <= 5),
        (dias_numeric >= 0) & (dias_numeric <= 2)
    ]
    opcoes = ["30+ dias", "21-29 dias", "11-20 dias", "6-10 dias", "3-5 dias", "0-2 dias"]
    # Use fillna before select to handle potential NaNs from coercion
    return np.select(condicoes, opcoes, default="Inválido/Antigo") # Default for NaNs or negatives

@st.cache_data
def analisar_aging(_df_atual):
    if _df_atual.empty:
        return pd.DataFrame(columns=['ID do ticket', 'Descrição', 'Atribuir a um grupo', 'Data de criação', 'Dias em Aberto', 'Faixa de Antiguidade']) # Return empty dataframe with expected columns

    df = _df_atual.copy()
    date_col_name = None
    if 'Data de criação' in df.columns: date_col_name = 'Data de criação'
    elif 'Data de Criacao' in df.columns: date_col_name = 'Data de Criacao' # Handle variation

    if not date_col_name or date_col_name not in df.columns:
        st.warning(f"Coluna de data de criação ('Data de criação' ou 'Data de Criacao') não encontrada.")
        # Add missing columns if they don't exist
        if 'Dias em Aberto' not in df.columns: df['Dias em Aberto'] = pd.NA
        if 'Faixa de Antiguidade' not in df.columns: df['Faixa de Antiguidade'] = "Data Inválida"
        return df

    # Attempt conversion, coercing errors
    df[date_col_name] = pd.to_datetime(df[date_col_name], errors='coerce', dayfirst=True) # Assuming DD/MM/YYYY format might be present

    linhas_invalidas = df[df[date_col_name].isna()]
    if not linhas_invalidas.empty:
        # Show only a few problematic rows to avoid clutter
        with st.expander(f"⚠️ Atenção: {len(linhas_invalidas)} chamados com data de criação inválida foram descartados da análise de idade."):
             st.dataframe(linhas_invalidas[['ID do ticket', date_col_name]].head()) # Show relevant columns

    df.dropna(subset=[date_col_name], inplace=True) # Drop rows where date conversion failed

    # Proceed only if there are valid dates left
    if df.empty:
        st.warning("Nenhum chamado com data de criação válida encontrado após limpeza.")
        # Return empty df but with columns
        return pd.DataFrame(columns=_df_atual.columns.tolist() + ['Dias em Aberto', 'Faixa de Antiguidade'])

    hoje = pd.to_datetime('today').normalize()
    # Ensure dates are timezone-naive before subtraction if 'hoje' is naive
    data_criacao_normalizada = df[date_col_name].dt.tz_localize(None).normalize() if df[date_col_name].dt.tz is not None else df[date_col_name].dt.normalize()

    dias_calculados = (hoje - data_criacao_normalizada).dt.days
    # Apply calculation only where dias_calculados is valid
    df['Dias em Aberto'] = dias_calculados.apply(lambda x: max(0, x - 1) if pd.notna(x) else pd.NA)
    # Categorize based on valid 'Dias em Aberto'
    df['Faixa de Antiguidade'] = categorizar_idade_vetorizado(df['Dias em Aberto'])

    return df


def get_status(row):
    diferenca = row['Diferença']
    if diferenca > 0: return "Alta Demanda"
    elif diferenca == 0: return "Estável / Atenção"
    else: return "Redução de Backlog"

def get_image_as_base64(path):
    try:
        with open(path, "rb") as image_file: return base64.b64encode(image_file.read()).decode()
    except FileNotFoundError:
        st.warning(f"Arquivo de imagem não encontrado em: {path}")
        return None # Return None if file not found


def sync_ticket_data():
    # Check if the editor exists and has pending changes
    if 'ticket_editor' not in st.session_state or not st.session_state.ticket_editor.get('edited_rows'):
        return

    edited_rows = st.session_state.ticket_editor['edited_rows']
    contact_changed = False
    observation_changed = False

    # Check if the dataframe used for the editor exists
    if 'last_filtered_df' not in st.session_state or st.session_state.last_filtered_df is None:
        st.error("Erro interno: Dataframe base para edição não encontrado.")
        st.session_state.ticket_editor['edited_rows'] = {} # Clear edits to prevent re-triggering
        return

    df_base = st.session_state.last_filtered_df

    for row_index_str, changes in edited_rows.items():
        try:
            row_index = int(row_index_str) # dict keys are strings from JSON/frontend
            if row_index >= len(df_base):
                 st.warning(f"Índice de linha {row_index} fora dos limites do dataframe atual. Mudança ignorada.")
                 continue

            # Ensure 'ID do ticket' exists
            if 'ID do ticket' not in df_base.columns:
                st.error("Coluna 'ID do ticket' não encontrada no dataframe base para edição.")
                continue # Skip this row modification

            ticket_id = str(df_base.iloc[row_index]['ID do ticket'])

            if 'Contato' in changes:
                current_contact_status = ticket_id in st.session_state.get('contacted_tickets', set()) # Use get for safety
                new_contact_status = changes['Contato']
                if current_contact_status != new_contact_status:
                    if new_contact_status:
                        st.session_state.setdefault('contacted_tickets', set()).add(ticket_id)
                    else:
                        st.session_state.setdefault('contacted_tickets', set()).discard(ticket_id)
                    contact_changed = True

            if 'Observações' in changes:
                # Use get for safety, ensure observations is initialized
                current_observation = st.session_state.setdefault('observations', {}).get(ticket_id, '')
                new_observation = changes['Observações']
                # Allow clearing observation by setting it to None or empty string
                new_observation_processed = new_observation if new_observation else ''
                if current_observation != new_observation_processed:
                    st.session_state['observations'][ticket_id] = new_observation_processed
                    observation_changed = True
        except (IndexError, ValueError, KeyError) as e:
            st.warning(f"Erro ao processar alterações para a linha {row_index_str}: {e}. Mudança ignorada.")
            continue

    # Save changes to GitHub if any occurred
    if contact_changed or observation_changed:
        now_str = datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')
        repo = st.session_state.get('repo') # Get repo from session state

        if not repo:
            st.error("Erro: Conexão com o repositório não encontrada. Não foi possível salvar.")
            return # Prevent further action if repo connection is lost

        if contact_changed:
            data_to_save = list(st.session_state.get('contacted_tickets', set()))
            json_content = json.dumps(data_to_save, indent=4)
            commit_msg = f"Atualizando contatos em {now_str}"
            update_github_file(repo, "contacted_tickets.json", json_content.encode('utf-8'), commit_msg)

        if observation_changed:
            json_content = json.dumps(st.session_state.get('observations', {}), indent=4, ensure_ascii=False)
            commit_msg = f"Atualizando observações em {now_str}"
            update_github_file(repo, "ticket_observations.json", json_content.encode('utf-8'), commit_msg)

    # Clear edited rows ONLY AFTER processing and saving
    st.session_state.ticket_editor['edited_rows'] = {}


@st.cache_data(ttl=3600)
def carregar_dados_evolucao(_repo, dias_para_analisar=7):
    try:
        # Check if the 'snapshots' directory exists
        try:
            all_files_content = _repo.get_contents("snapshots")
        except GithubException as e:
            if e.status == 404:
                st.info("Diretório 'snapshots' não encontrado. Aguardando a criação de snapshots.")
                return pd.DataFrame() # Return empty if snapshots dir doesn't exist
            else:
                raise # Re-raise other GithubExceptions

        all_files = [f.path for f in all_files_content if f.type == 'file'] # Ensure we only process files
        df_evolucao_list = []
        end_date = date.today()
        start_date = end_date - timedelta(days=dias_para_analisar - 1)

        for file_path in all_files:
            # More robust check for snapshot files
            if file_path.startswith("snapshots/backlog_") and file_path.endswith(".csv"):
                try:
                    # Extract date safely
                    date_str = file_path.split("backlog_")[-1].replace(".csv", "")
                    file_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                    if start_date <= file_date <= end_date:
                        # Use the robust read_github_file function
                        df_snapshot = read_github_file(_repo, file_path)
                        # Check required column *after* loading
                        if not df_snapshot.empty and 'Atribuir a um grupo' in df_snapshot.columns:
                            # Apply RH filter
                            df_snapshot_filtrado = df_snapshot[~df_snapshot['Atribuir a um grupo'].astype(str).str.contains('RH', case=False, na=False)]
                            if not df_snapshot_filtrado.empty:
                                contagem_diaria = df_snapshot_filtrado.groupby('Atribuir a um grupo').size().reset_index(name='Total Chamados')
                                contagem_diaria['Data'] = pd.to_datetime(file_date)
                                df_evolucao_list.append(contagem_diaria)
                        # else:
                        #     st.warning(f"Snapshot '{file_path}' vazio ou sem coluna 'Atribuir a um grupo'.")

                except ValueError:
                    st.warning(f"Não foi possível extrair a data do nome do arquivo: {file_path}")
                    continue # Skip this file if date parsing fails
                except Exception as e:
                    st.warning(f"Erro ao processar o snapshot '{file_path}': {e}")
                    continue # Skip this file on other errors

        if not df_evolucao_list:
            st.info("Nenhum dado de snapshot válido encontrado no período selecionado.")
            return pd.DataFrame()

        df_consolidado = pd.concat(df_evolucao_list, ignore_index=True)
        return df_consolidado.sort_values(by=['Data', 'Atribuir a um grupo'])

    except GithubException as e:
        # Catch specific exceptions if needed, otherwise generalize
        st.warning(f"Não foi possível carregar snapshots: {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro inesperado ao carregar evolução: {e}")
        return pd.DataFrame()


# --- Start of UI ---

st.html("""<style>#GithubIcon { visibility: hidden; } .metric-box { border: 1px solid #CCCCCC; padding: 10px; border-radius: 5px; text-align: center; box-shadow: 0px 2px 4px rgba(0,0,0,0.1); margin-bottom: 10px; } a.metric-box { display: block; color: inherit; text-decoration: none !important; } a.metric-box:hover { background-color: #f0f2f6; text-decoration: none !important; } .metric-box span { display: block; width: 100%; text-decoration: none !important; } .metric-box .value { font-size: 2.5em; font-weight: bold; color: #375623; } .metric-box .label { font-size: 1em; color: #666666; }</style>""")

logo_copa_b64 = get_image_as_base64("logo_sidebar.png")
logo_belago_b64 = get_image_as_base64("logo_belago.png")
if logo_copa_b64 and logo_belago_b64:
    st.markdown(f"""<div style="display: flex; justify-content: space-between; align-items: center;"><img src="data:image/png;base64,{logo_copa_b64}" width="150"><h1 style='text-align: center; margin: 0;'>Backlog Copa Energia + Belago</h1><img src="data:image/png;base64,{logo_belago_b64}" width="150"></div>""", unsafe_allow_html=True)
else: st.error("Arquivos de logo não encontrados. Verifique os nomes 'logo_sidebar.png' e 'logo_belago.png'.")

# --- Admin Sidebar ---
repo = get_github_repo()
st.session_state.repo = repo # Store repo in session state for access in callbacks

st.sidebar.header("Área do Administrador")
password = st.sidebar.text_input("Senha para atualizar dados:", type="password")
# Use secrets for password check
is_admin = password == st.secrets.get("ADMIN_PASSWORD", "")

if is_admin:
    st.sidebar.success("Acesso liberado.")
    st.sidebar.subheader("Atualização Completa")
    uploaded_file_atual = st.sidebar.file_uploader("1. Backlog ATUAL", type=["csv", "xlsx"], key="uploader_atual")
    uploaded_file_15dias = st.sidebar.file_uploader("2. Backlog de 15 DIAS ATRÁS", type=["csv", "xlsx"], key="uploader_15dias")
    if st.sidebar.button("Salvar Novos Dados no Site"):
        if uploaded_file_atual and uploaded_file_15dias:
            with st.spinner("Processando e salvando..."):
                now_sao_paulo = datetime.now(ZoneInfo('America/Sao_Paulo'))
                commit_msg = f"Dados atualizados em {now_sao_paulo.strftime('%d/%m/%Y %H:%M')}"
                content_atual = process_uploaded_file(uploaded_file_atual)
                content_15dias = process_uploaded_file(uploaded_file_15dias)
                if content_atual is not None and content_15dias is not None:
                    update_github_file(repo, "dados_atuais.csv", content_atual, commit_msg)
                    update_github_file(repo, "dados_15_dias.csv", content_15dias, commit_msg)
                    # Create daily snapshot
                    today_str = now_sao_paulo.strftime('%Y-%m-%d')
                    snapshot_path = f"snapshots/backlog_{today_str}.csv"
                    update_github_file(repo, snapshot_path, content_atual, f"Snapshot de {today_str}")
                    # Update reference dates file
                    data_do_upload = now_sao_paulo.date()
                    data_arquivo_15dias = data_do_upload - timedelta(days=15)
                    hora_atualizacao = now_sao_paulo.strftime('%H:%M')
                    datas_referencia_content = (f"data_atual:{data_do_upload.strftime('%d/%m/%Y')}\n"
                                                f"data_15dias:{data_arquivo_15dias.strftime('%d/%m/%Y')}\n"
                                                f"hora_atualizacao:{hora_atualizacao}")
                    update_github_file(repo, "datas_referencia.txt", datas_referencia_content.encode('utf-8'), commit_msg)
                    # Clear caches and rerun
                    st.cache_data.clear()
                    st.cache_resource.clear()
                    st.sidebar.success("Arquivos salvos! Recarregando...")
                    # Clear session state related to potentially outdated data
                    if 'contacted_tickets' in st.session_state: del st.session_state['contacted_tickets']
                    if 'observations' in st.session_state: del st.session_state['observations']
                    st.rerun()
        else: st.sidebar.warning("Carregue os arquivos ATUAL e de 15 DIAS.")
    st.sidebar.markdown("---")
    st.sidebar.subheader("Atualização Rápida")
    uploaded_file_fechados = st.sidebar.file_uploader("Apenas Chamados FECHADOS", type=["csv", "xlsx"], key="uploader_fechados")
    if st.sidebar.button("Salvar Apenas Chamados Fechados"):
        if uploaded_file_fechados:
            with st.spinner("Salvando fechados..."):
                now_sao_paulo = datetime.now(ZoneInfo('America/Sao_Paulo'))
                commit_msg = f"Atualizando fechados em {now_sao_paulo.strftime('%d/%m/%Y %H:%M')}"
                content_fechados = process_uploaded_file(uploaded_file_fechados)
                if content_fechados is not None:
                    update_github_file(repo, "dados_fechados.csv", content_fechados, commit_msg)
                    # Only clear data cache, resource (repo connection) should persist
                    st.cache_data.clear()
                    st.sidebar.success("Fechados salvos! Recarregando...")
                    st.rerun()
        else: st.sidebar.warning("Carregue o arquivo de fechados.")
elif password: # Only show error if password was entered but incorrect
    st.sidebar.error("Senha incorreta.")


# --- Main App Logic ---
try:
    # Initialize session state for contacts and observations if they don't exist
    if 'contacted_tickets' not in st.session_state:
        st.session_state.contacted_tickets = set(map(str, read_github_json_dict(repo, "contacted_tickets.json"))) # Ensure IDs are strings
    if 'observations' not in st.session_state:
        st.session_state.observations = read_github_json_dict(repo, "ticket_observations.json")

    # --- Scrolling Logic ---
    url_params = st.query_params.to_dict()
    scroll_target_id_on_load = None

    if "scroll_to" in url_params:
        target = url_params.get("scroll_to")
        if target == "encerrados":
            scroll_target_id_on_load = 'chamados-encerrados'
        # Add other potential scroll targets here if needed
    elif "faixa" in url_params:
        faixa_from_url = url_params.get("faixa")
        # Define valid ranges clearly
        ordem_faixas_validas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
        if faixa_from_url in ordem_faixas_validas:
             # Update session state only if faixa is valid and different
             if st.session_state.get('faixa_selecionada') != faixa_from_url:
                 st.session_state.faixa_selecionada = faixa_from_url
        scroll_target_id_on_load = 'detalhar-e-buscar-chamados' # Target section for faixa clicks

    if scroll_target_id_on_load:
        # ==========================================================
        # Timeout set to 200ms as requested by the user
        # ==========================================================
        js_code = f"""
        <script>
            setTimeout(() => {{
                const element = window.parent.document.getElementById('{scroll_target_id_on_load}');
                if (element) {{
                    // Use 'start' to align the top of the element with the top of the viewport
                    element.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                }} else {{
                    console.warn("Scroll target element '{scroll_target_id_on_load}' not found.");
                }}
                // Attempt to clean URL parameters after scrolling
                try {{
                    const url = new URL(window.location);
                    url.searchParams.delete('faixa');
                    url.searchParams.delete('scroll'); // Remove the scroll trigger param
                    url.searchParams.delete('scroll_to'); // Remove the scroll target param
                    // Use replaceState to avoid adding to browser history
                    window.history.replaceState({{}}, '', url);
                }} catch (e) {{ console.error("Could not clear URL parameters:", e); }}
            }}, 200);
        </script>
        """
        components.html(js_code, height=0)
        # Clear query params server-side immediately to prevent re-triggering on non-click refresh
        # st.query_params.clear() # This might interfere with immediate rerun after upload, test carefully

    # --- Load Data ---
    df_atual = read_github_file(repo, "dados_atuais.csv")
    df_15dias = read_github_file(repo, "dados_15_dias.csv")
    df_fechados = read_github_file(repo, "dados_fechados.csv")
    datas_referencia = read_github_text_file(repo, "datas_referencia.txt")

    data_atual_str = datas_referencia.get('data_atual', 'N/A')
    data_15dias_str = datas_referencia.get('data_15dias', 'N/A')
    hora_atualizacao_str = datas_referencia.get('hora_atualizacao', '')

    # --- Basic Data Validation ---
    if df_atual.empty:
        st.warning("Arquivo de dados atuais ('dados_atuais.csv') está vazio ou não foi carregado. Carregue os arquivos na área do administrador.")
        st.stop() # Stop execution if essential data is missing

    # --- Data Processing ---
    # Standardize ID column name across dataframes
    def find_id_column(df, possible_names=['ID do ticket', 'ID do Ticket', 'ID']):
        for name in possible_names:
            if name in df.columns:
                return name
        return None # Return None if no standard ID column is found

    id_col_atual = find_id_column(df_atual)
    id_col_fechados = find_id_column(df_fechados)

    if not id_col_atual:
        st.error("Coluna de ID ('ID do ticket', 'ID do Ticket', ou 'ID') não encontrada no arquivo atual. Verifique o arquivo.")
        st.stop()

    # Ensure the ID column in df_atual is string and clean
    df_atual[id_col_atual] = df_atual[id_col_atual].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()


    closed_ticket_ids = set()
    if not df_fechados.empty and id_col_fechados:
        # Ensure the ID column in df_fechados is string and clean
        df_fechados[id_col_fechados] = df_fechados[id_col_fechados].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        closed_ticket_ids = set(df_fechados[id_col_fechados].dropna().unique())
    elif not df_fechados.empty and not id_col_fechados:
         st.warning("Arquivo de chamados fechados carregado, mas coluna de ID ('ID do ticket', 'ID do Ticket', ou 'ID') não encontrada.")


    # Separate open and closed tickets using the standardized ID column
    df_encerrados = df_atual[df_atual[id_col_atual].isin(closed_ticket_ids)].copy() # Use .copy() to avoid SettingWithCopyWarning
    df_abertos = df_atual[~df_atual[id_col_atual].isin(closed_ticket_ids)].copy()

    # Filter out 'RH' group, handle potential missing column gracefully
    rh_filter_col = 'Atribuir a um grupo'
    if rh_filter_col in df_abertos.columns:
        df_atual_filtrado = df_abertos[~df_abertos[rh_filter_col].astype(str).str.contains('RH', case=False, na=False)].copy()
    else:
        st.warning(f"Coluna '{rh_filter_col}' não encontrada para aplicar filtro RH nos dados atuais.")
        df_atual_filtrado = df_abertos.copy() # Proceed without filtering if column missing

    if not df_15dias.empty and rh_filter_col in df_15dias.columns:
         df_15dias_filtrado = df_15dias[~df_15dias[rh_filter_col].astype(str).str.contains('RH', case=False, na=False)].copy()
    elif not df_15dias.empty:
         st.warning(f"Coluna '{rh_filter_col}' não encontrada para aplicar filtro RH nos dados de 15 dias.")
         df_15dias_filtrado = df_15dias.copy()
    else:
         df_15dias_filtrado = pd.DataFrame() # Create empty if df_15dias itself is empty

    # Perform aging analysis only on filtered open tickets
    df_aging = analisar_aging(df_atual_filtrado)

    # Filter closed tickets similarly
    if not df_encerrados.empty and rh_filter_col in df_encerrados.columns:
        df_encerrados_filtrado = df_encerrados[~df_encerrados[rh_filter_col].astype(str).str.contains('RH', case=False, na=False)].copy()
    elif not df_encerrados.empty:
         st.warning(f"Coluna '{rh_filter_col}' não encontrada para aplicar filtro RH nos dados encerrados.")
         df_encerrados_filtrado = df_encerrados.copy()
    else:
         df_encerrados_filtrado = pd.DataFrame()


    df_evolucao_agente = carregar_dados_evolucao(repo, dias_para_analisar=7) # For trend analysis if needed later

    # --- Define Tabs ---
    tab1, tab2, tab3 = st.tabs(["Dashboard Completo", "Report Visual", "Evolução Semanal"])

    # --- Tab 1: Dashboard Completo ---
    with tab1:
        info_messages = ["**Filtros e Regras Aplicadas:**"]
        if rh_filter_col in df_atual.columns: # Only mention RH filter if column exists
            info_messages.append("- Grupos contendo 'RH' foram desconsiderados da análise.")
        info_messages.append("- A contagem de dias do chamado desconsidera o dia da sua abertura (prazo -1 dia).")
        if not df_encerrados_filtrado.empty:
             info_messages.append("- Os chamados marcados como fechados no dia já foram excluídos das contagens principais e dos grupos correspondentes.")
        st.info("\n".join(info_messages))

        # Box "Análise e Foco do Dia" foi removido

        st.subheader("Análise de Antiguidade do Backlog Atual")
        texto_hora = f" (atualizado às {hora_atualizacao_str})" if hora_atualizacao_str else ""
        st.markdown(f"<p style='font-size: 0.9em; color: #666;'><i>Data de referência: {data_atual_str}{texto_hora}</i></p>", unsafe_allow_html=True)

        if not df_aging.empty:
            total_chamados = len(df_aging) # Use df_aging which is already filtered and analyzed
            total_fechados = len(df_encerrados_filtrado) # Use filtered closed count
            col_spacer1, col_total, col_fechados, col_spacer2 = st.columns([1, 1.5, 1.5, 1])

            with col_total:
                st.markdown(f"""<div class="metric-box"><span class="value">{total_chamados}</span><span class="label">Total de Chamados Abertos</span></div>""", unsafe_allow_html=True)

            with col_fechados:
                valor_fechados = total_fechados if total_fechados > 0 else "N/A"
                # RESTORED clickable card pointing to scroll target
                card_fechados_html = f"""<a href="?scroll_to=encerrados&scroll=true" target="_self" class="metric-box" style="text-decoration: none;"><span class="value">{valor_fechados}</span><span class="label">Chamados Fechados no Dia</span></a>"""
                st.markdown(card_fechados_html, unsafe_allow_html=True)

            st.markdown("---") # Separator

            # Display aging counts as clickable cards
            # Ensure 'Faixa de Antiguidade' column exists from analisar_aging
            if 'Faixa de Antiguidade' in df_aging.columns:
                aging_counts = df_aging['Faixa de Antiguidade'].value_counts().reset_index()
                aging_counts.columns = ['Faixa de Antiguidade', 'Quantidade']
                ordem_faixas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias", "Inválido/Antigo"] # Include default category
                # Use pd.Categorical for sorting and ensuring all categories appear
                aging_counts['Faixa de Antiguidade'] = pd.Categorical(aging_counts['Faixa de Antiguidade'], categories=ordem_faixas, ordered=True)
                # Add missing categories with 0 count
                aging_counts = aging_counts.set_index('Faixa de Antiguidade').reindex(ordem_faixas, fill_value=0).reset_index()

                # Initialize session state for faixa selection if needed
                if 'faixa_selecionada' not in st.session_state:
                    st.session_state.faixa_selecionada = "0-2 dias" # Default selection

                # Create columns for cards
                cols = st.columns(len(ordem_faixas))
                for i, row in aging_counts.iterrows():
                    with cols[i]:
                        faixa_encoded = quote(row['Faixa de Antiguidade'])
                        # Link triggers scroll and sets faixa param
                        card_html = f"""<a href="?faixa={faixa_encoded}&scroll=true" target="_self" class="metric-box"><span class="value">{row['Quantidade']}</span><span class="label">{row['Faixa de Antiguidade']}</span></a>"""
                        st.markdown(card_html, unsafe_allow_html=True)
            else:
                 st.warning("Coluna 'Faixa de Antiguidade' não gerada. Análise de idade pode ter falhado.")

        else:
            st.warning("Sem dados de chamados abertos válidos para análise de antiguidade.")

        # --- Comparative Backlog ---
        st.markdown(f"<h3>Comparativo de Backlog: Atual vs. 15 Dias Atrás <span style='font-size: 0.6em; color: #666; font-weight: normal;'>({data_15dias_str if data_15dias_str != 'N/A' else 'Data Anterior N/A'})</span></h3>", unsafe_allow_html=True)
        if not df_15dias.empty and not df_15dias_filtrado.empty:
            df_comparativo = processar_dados_comparativos(df_atual_filtrado.copy(), df_15dias_filtrado.copy()) # Use filtered data
            if not df_comparativo.empty:
                # Apply styling to the difference column
                st.dataframe(df_comparativo.set_index('Grupo Atribuído').style.map(
                    lambda val: 'background-color: #ffcccc' if val > 0 else ('background-color: #ccffcc' if val < 0 else None), # Use None for default
                    subset=['Diferença']
                ), use_container_width=True)
            else:
                 st.info("Não foi possível gerar o comparativo (verifique se 'Atribuir a um grupo' existe nos arquivos).")
        elif df_15dias.empty:
             st.info("Arquivo de 15 dias atrás não carregado. Comparativo não disponível.")
        else: # df_15dias exists but df_15dias_filtrado might be empty after RH filter
             st.info("Nenhum dado válido encontrado no arquivo de 15 dias atrás após filtros.")


        st.markdown("---")

        # --- Closed Tickets Section ---
        # ID is back in H3 for correct scroll target alignment
        st.markdown(f"<h3 id='chamados-encerrados'>Chamados Encerrados no Dia <span style='font-size: 0.6em; color: #666; font-weight: normal;'>({data_atual_str})</span></h3>", unsafe_allow_html=True)

        if not df_encerrados_filtrado.empty:
            # Select and rename columns for display
            cols_to_show_closed = [id_col_atual, 'Descrição', rh_filter_col] # Use standardized column names
            # Filter df_encerrados_filtrado to only include existing columns
            cols_to_show_closed = [col for col in cols_to_show_closed if col in df_encerrados_filtrado.columns]
            df_encerrados_display = df_encerrados_filtrado[cols_to_show_closed]
            # Rename columns for better readability if they exist
            rename_map_closed = {id_col_atual: 'ID do Ticket', rh_filter_col: 'Grupo Atribuído'}
            df_encerrados_display = df_encerrados_display.rename(columns={k: v for k, v in rename_map_closed.items() if k in df_encerrados_display.columns})

            st.data_editor(df_encerrados_display, hide_index=True, disabled=True, use_container_width=True)
        else:
            st.info("Nenhum chamado encerrado (ou arquivo 'dados_fechados.csv' não carregado/vazio).")


        # --- Detailed Ticket View (Aging Drilldown) ---
        if not df_aging.empty and 'Faixa de Antiguidade' in df_aging.columns: # Check if aging analysis was successful
            st.markdown("---")
            st.markdown("<h3 id='detalhar-e-buscar-chamados'>Detalhar e Buscar Chamados</h3>", unsafe_allow_html=True)
            st.info('Marque "Contato" se já falou com o usuário e a solicitação continua pendente. Use "Observações" para anotações.')

            ordem_faixas_selectbox = df_aging['Faixa de Antiguidade'].cat.categories.tolist() # Get categories from the dataframe

            # Use faixa_selecionada from session state, ensuring it exists in the valid categories
            selected_faixa_index = 0 # Default to first category
            if 'faixa_selecionada' in st.session_state and st.session_state.faixa_selecionada in ordem_faixas_selectbox:
                 selected_faixa_index = ordem_faixas_selectbox.index(st.session_state.faixa_selecionada)

            # Update session state based on selectbox interaction
            st.session_state.faixa_selecionada = st.selectbox(
                "Detalhar por faixa de idade:",
                options=ordem_faixas_selectbox,
                index=selected_faixa_index,
                key='selectbox_faixa' # Use a distinct key if 'faixa_selecionada' is used elsewhere
            )

            faixa_atual_selected = st.session_state.faixa_selecionada
            filtered_df_details = df_aging[df_aging['Faixa de Antiguidade'] == faixa_atual_selected].copy()

            if not filtered_df_details.empty:
                def highlight_row(row):
                    # Check if 'Contato' column exists before trying to access it
                    return ['background-color: #fff8c4'] * len(row) if 'Contato' in row and row['Contato'] else [''] * len(row)

                # Add 'Contato' and 'Observações' columns safely
                filtered_df_details['Contato'] = filtered_df_details[id_col_atual].apply(lambda ticket_id: str(ticket_id) in st.session_state.get('contacted_tickets', set()))
                filtered_df_details['Observações'] = filtered_df_details[id_col_atual].apply(lambda ticket_id: st.session_state.get('observations', {}).get(str(ticket_id), ''))

                # Store the potentially modified dataframe for the callback
                st.session_state.last_filtered_df = filtered_df_details.reset_index(drop=True) # Ensure index is standard 0, 1, 2...

                # Define columns to display and rename them
                colunas_editor = {
                    'Contato': 'Contato',
                    id_col_atual: 'ID do ticket',
                    'Descrição': 'Descrição',
                    rh_filter_col: 'Grupo Atribuído',
                    'Dias em Aberto': 'Dias em Aberto',
                    'Data de criação': 'Data de criação', # Assuming 'Data de criação' is the name after analisar_aging
                    'Observações': 'Observações'
                }
                # Filter out columns that might not exist in df_aging
                colunas_existentes = [col for col in colunas_editor.keys() if col in st.session_state.last_filtered_df.columns]
                colunas_renomeadas_para_exibir = {k: colunas_editor[k] for k in colunas_existentes}
                colunas_desabilitadas = [colunas_renomeadas_para_exibir[k] for k in colunas_existentes if k not in ['Contato', 'Observações']]


                # Format 'Data de criação' if it exists
                date_display_col = colunas_renomeadas_para_exibir.get('Data de criação')
                df_display_editor = st.session_state.last_filtered_df[colunas_existentes].rename(columns=colunas_renomeadas_para_exibir)
                if date_display_col and date_display_col in df_display_editor.columns:
                     # Ensure it's datetime before formatting
                     df_display_editor[date_display_col] = pd.to_datetime(df_display_editor[date_display_col], errors='coerce').dt.strftime('%d/%m/%Y')


                st.data_editor(
                    df_display_editor[list(colunas_renomeadas_para_exibir.values())].style.apply(highlight_row, axis=1), # Apply style after selecting columns
                    use_container_width=True,
                    hide_index=True,
                    disabled=colunas_desabilitadas,
                    key='ticket_editor',
                    on_change=sync_ticket_data
                )
            else:
                st.info(f"Não há chamados abertos na categoria '{faixa_atual_selected}'.")


            # --- Search by Group ---
            st.subheader("Buscar Chamados por Grupo")
            if rh_filter_col in df_aging.columns:
                lista_grupos = sorted(df_aging[rh_filter_col].dropna().unique())
                grupo_selecionado = st.selectbox("Busca por grupo:", options=lista_grupos, key='selectbox_grupo')
                if grupo_selecionado:
                    resultados_busca = df_aging[df_aging[rh_filter_col] == grupo_selecionado].copy()
                    # Prepare columns for display
                    colunas_busca_raw = [id_col_atual, 'Descrição', 'Dias em Aberto', 'Data de criação']
                    colunas_busca_existentes = [col for col in colunas_busca_raw if col in resultados_busca.columns]
                    df_busca_display = resultados_busca[colunas_busca_existentes]
                    # Rename
                    rename_map_busca = {id_col_atual: 'ID do Ticket', 'Data de criação': 'Data Criação'}
                    df_busca_display = df_busca_display.rename(columns={k:v for k,v in rename_map_busca.items() if k in df_busca_display.columns})
                    # Format date if exists
                    date_display_col_busca = rename_map_busca.get('Data de criação', 'Data de criação') # Use the potentially renamed column name
                    if date_display_col_busca in df_busca_display.columns:
                         df_busca_display[date_display_col_busca] = pd.to_datetime(df_busca_display[date_display_col_busca], errors='coerce').dt.strftime('%d/%m/%Y')


                    st.write(f"Encontrados {len(resultados_busca)} chamados para '{grupo_selecionado}':")
                    st.data_editor(
                        df_busca_display,
                        use_container_width=True,
                        hide_index=True,
                        disabled=True # Search results are read-only
                    )
            else:
                 st.warning(f"Coluna '{rh_filter_col}' não encontrada para busca por grupo.")

    # --- Tab 2: Report Visual ---
    with tab2:
        st.subheader("Resumo do Backlog Atual")
        if not df_aging.empty and 'Faixa de Antiguidade' in df_aging.columns:
            total_chamados_tab2 = len(df_aging)
            _, col_total_tab2, _ = st.columns([2, 1.5, 2])
            with col_total_tab2: st.markdown( f"""<div class="metric-box"><span class="value">{total_chamados_tab2}</span><span class="label">Total de Chamados Abertos</span></div>""", unsafe_allow_html=True )

            st.markdown("---") # Separator

            # Display aging counts (non-clickable)
            aging_counts_tab2 = df_aging['Faixa de Antiguidade'].value_counts().reset_index()
            aging_counts_tab2.columns = ['Faixa de Antiguidade', 'Quantidade']
            ordem_faixas_tab2 = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias", "Inválido/Antigo"]
            aging_counts_tab2['Faixa de Antiguidade'] = pd.Categorical(aging_counts_tab2['Faixa de Antiguidade'], categories=ordem_faixas_tab2, ordered=True)
            aging_counts_tab2 = aging_counts_tab2.set_index('Faixa de Antiguidade').reindex(ordem_faixas_tab2, fill_value=0).reset_index()

            cols_tab2 = st.columns(len(ordem_faixas_tab2))
            for i, row in aging_counts_tab2.iterrows():
                with cols_tab2[i]: st.markdown( f"""<div class="metric-box"><span class="value">{row['Quantidade']}</span><span class="label">{row['Faixa de Antiguidade']}</span></div>""", unsafe_allow_html=True )

            st.markdown("---") # Separator
            st.subheader("Distribuição do Backlog por Grupo")

            if rh_filter_col in df_aging.columns:
                orientation_choice = st.radio( "Orientação do Gráfico:", ["Vertical", "Horizontal"], index=0, horizontal=True, key="tab2_orientation_choice" )

                # Prepare data for stacked bar chart
                chart_data = df_aging.groupby([rh_filter_col, 'Faixa de Antiguidade']).size().reset_index(name='Quantidade')
                # Calculate totals per group for sorting and labeling
                group_totals = chart_data.groupby(rh_filter_col)['Quantidade'].sum().sort_values(ascending=False)
                # Create labels like "Group Name (Total)"
                new_labels_map = {group: f"{group} ({total})" for group, total in group_totals.items()}
                chart_data['Grupo Atribuído (Total)'] = chart_data[rh_filter_col].map(new_labels_map)
                # Define sort order based on total counts
                sorted_new_labels = [new_labels_map[group] for group in group_totals.index]

                # Define color palette
                def lighten_color(hex_color, amount=0.2):
                    try:
                        hex_color = hex_color.lstrip('#')
                        h, l, s = colorsys.rgb_to_hls(*[int(hex_color[i:i+2], 16)/255.0 for i in (0, 2, 4)])
                        new_l = l + (1 - l) * amount
                        r, g, b = colorsys.hls_to_rgb(h, new_l, s)
                        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
                    except Exception: return hex_color # Return original if conversion fails

                base_color = "#375623" # Base color for palette
                palette_categories = ordem_faixas_tab2 # Use the same order as cards
                palette = [ lighten_color(base_color, i * (0.85 / (len(palette_categories)-1))) for i in range(len(palette_categories)-1) ] + [base_color] # Generate shades
                color_map = {faixa: color for faixa, color in zip(palette_categories, palette)}

                # Create the plot based on orientation
                if orientation_choice == 'Horizontal':
                    num_groups = len(group_totals)
                    dynamic_height = max(500, num_groups * 30) # Adjust height based on number of groups
                    fig_stacked_bar = px.bar(
                        chart_data,
                        x='Quantidade',
                        y='Grupo Atribuído (Total)', # Use the combined label for y-axis
                        orientation='h',
                        color='Faixa de Antiguidade',
                        title="Composição da Idade do Backlog por Grupo",
                        labels={'Quantidade': 'Qtd. de Chamados', 'Grupo Atribuído (Total)': ''}, # Clear y-axis label
                        category_orders={'Grupo Atribuído (Total)': sorted_new_labels, 'Faixa de Antiguidade': palette_categories}, # Use correct order
                        color_discrete_map=color_map,
                        text_auto=True # Display values on bars
                    )
                    fig_stacked_bar.update_traces(textangle=0, textfont_size=10, textposition='inside') # Adjust text
                    fig_stacked_bar.update_layout(height=dynamic_height, legend_title_text='Antiguidade', yaxis={'categoryorder':'array', 'categoryarray':sorted_new_labels[::-1]}) # Ensure correct sorting
                else: # Vertical orientation
                    fig_stacked_bar = px.bar(
                        chart_data,
                        x='Grupo Atribuído (Total)', # Use the combined label for x-axis
                        y='Quantidade',
                        color='Faixa de Antiguidade',
                        title="Composição da Idade do Backlog por Grupo",
                        labels={'Quantidade': 'Qtd. de Chamados', 'Grupo Atribuído (Total)': 'Grupo'}, # Clear x-axis label
                        category_orders={'Grupo Atribuído (Total)': sorted_new_labels, 'Faixa de Antiguidade': palette_categories}, # Use correct order
                        color_discrete_map=color_map,
                        text_auto=True # Display values on bars
                    )
                    fig_stacked_bar.update_traces(textangle=0, textfont_size=10, textposition='outside') # Adjust text
                    fig_stacked_bar.update_layout(height=600, xaxis_title=None, xaxis_tickangle=-45, legend_title_text='Antiguidade', xaxis={'categoryorder':'array', 'categoryarray':sorted_new_labels}) # Ensure correct sorting

                st.plotly_chart(fig_stacked_bar, use_container_width=True)
            else:
                 st.warning(f"Coluna '{rh_filter_col}' necessária para o gráfico de distribuição não encontrada.")

        else: st.warning("Sem dados de chamados abertos válidos para gerar report visual.")

    # --- Tab 3: Evolução Semanal ---
    with tab3:
        st.subheader("Evolução do Backlog")
        st.info("Esta visualização mostra o total de chamados abertos ao final de cada dia e a variação líquida (novos - fechados) em relação ao dia anterior.") # Mensagem atualizada
        dias_evolucao = st.slider("Ver evolução dos últimos dias:", min_value=3, max_value=30, value=7, key="slider_evolucao") # Min value 3 for difference calc
        df_evolucao = carregar_dados_evolucao(repo, dias_para_analisar=dias_evolucao)

        if not df_evolucao.empty and 'Data' in df_evolucao.columns and 'Total Chamados' in df_evolucao.columns:
            # Aggregate total calls per day
            df_total_diario = df_evolucao.groupby('Data')['Total Chamados'].sum().reset_index()
            df_total_diario = df_total_diario.sort_values('Data')

            # Calculate daily net change if more than one day is available
            if len(df_total_diario) > 1:
                df_total_diario['Anterior'] = df_total_diario['Total Chamados'].shift(1)
                # Calculate difference, fill first NaN with 0
                df_total_diario['Variacao Liquida'] = (df_total_diario['Total Chamados'] - df_total_diario['Anterior']).fillna(0).astype(int)
            else:
                 df_total_diario['Variacao Liquida'] = 0 # Assign 0 if only one day's data

            # Create the figure using Plotly Graph Objects
            fig_total_evolucao = go.Figure()

            # Trace 1: Total Open Tickets (Area + Text)
            fig_total_evolucao.add_trace(go.Scatter(
                x=df_total_diario['Data'],
                y=df_total_diario['Total Chamados'],
                mode='lines+markers+text', # Show lines, markers, and text values
                name='Total Aberto',
                text=df_total_diario['Total Chamados'], # Text is the total count
                textposition='top center',
                fill='tozeroy', # Fill area below the line
                line=dict(color='royalblue')
            ))

            # Trace 2: Net Daily Variation (Dashed Line + Text) - only if variation exists
            if 'Variacao Liquida' in df_total_diario.columns and len(df_total_diario) > 1 :
                fig_total_evolucao.add_trace(go.Scatter(
                    x=df_total_diario['Data'],
                    y=df_total_diario['Variacao Liquida'],
                    mode='lines+markers+text', # Show lines, markers, and text values
                    name='Variação Líquida Diária',
                    text=df_total_diario['Variacao Liquida'].apply(lambda x: f"+{x}" if x > 0 else str(x)), # Add '+' sign to positive numbers
                    textposition='bottom center', # Position text below markers
                    line=dict(color='firebrick', dash='dash') # Red dashed line
                ))

            # Update layout
            fig_total_evolucao.update_layout(
                title='Evolução do Total Geral de Chamados Abertos e Variação Líquida Diária',
                xaxis_title="Data",
                yaxis_title="Número de Chamados",
                height=450,
                legend_title_text='Métrica',
                hovermode="x unified" # Improve hover experience
            )
            # Adjust text font size for clarity
            fig_total_evolucao.update_traces(textfont_size=10)

            st.plotly_chart(fig_total_evolucao, use_container_width=True)

            # --- Evolution by Group ---
            st.markdown("---")
            st.subheader("Evolução por Grupo")
            if rh_filter_col in df_evolucao.columns:
                todos_grupos = sorted(df_evolucao[rh_filter_col].dropna().unique())
                # Default selection: try to select top 5 groups by latest count, or all if <= 5
                if not todos_grupos:
                    st.warning("Nenhum grupo encontrado nos dados de evolução.")
                else:
                    latest_date = df_evolucao['Data'].max()
                    top_groups_latest = df_evolucao[df_evolucao['Data'] == latest_date].groupby(rh_filter_col)['Total Chamados'].sum().nlargest(5).index.tolist()
                    default_selection = top_groups_latest if top_groups_latest else todos_grupos[:5] # Fallback if no data on latest date

                    grupos_selecionados = st.multiselect(
                        "Selecione os grupos para visualizar:",
                        options=todos_grupos,
                        default=default_selection,
                        key="select_evolucao_grupos"
                    )
                    if not grupos_selecionados:
                        st.warning("Selecione pelo menos um grupo.")
                    else:
                        df_filtrado_grupo = df_evolucao[df_evolucao[rh_filter_col].isin(grupos_selecionados)]
                        # Rename column for legend clarity
                        df_filtrado_display_grupo = df_filtrado_grupo.rename(columns={rh_filter_col: 'Grupo Atribuído'})

                        fig_evolucao_grupo = px.line(
                            df_filtrado_display_grupo.sort_values('Data'), # Ensure data is sorted by date for lines
                            x='Data',
                            y='Total Chamados',
                            color='Grupo Atribuído', # Color lines by group
                            title='Evolução por Grupo',
                            markers=True, # Show markers on data points
                            labels={ "Data": "Data", "Total Chamados": "Nº de Chamados", "Grupo Atribuído": "Grupo" }
                        )
                        fig_evolucao_grupo.update_layout(height=600)
                        st.plotly_chart(fig_evolucao_grupo, use_container_width=True)
            else:
                 st.warning(f"Coluna '{rh_filter_col}' não encontrada nos dados de evolução para análise por grupo.")


        else: st.info("Ainda não há dados históricos suficientes ou válidos para a evolução.")

# --- Error Handling for Main Block ---
except Exception as e:
    st.error(f"Ocorreu um erro inesperado ao carregar ou processar os dados: {e}")
    st.exception(e) # Display detailed traceback for debugging

# --- Footer ---
st.markdown("---")
# Update version number or timestamp dynamically if desired
st.markdown("""<p style='text-align: center; color: #666; font-size: 0.9em;'>v0.9.21 | Dashboard em desenvolvimento.</p>""", unsafe_allow_html=True)
