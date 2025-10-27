# VERSÃO v0.9.20-729 (Base 0.9.7 + Fechados + Observações + Tab3 Eixo Correto + Limpeza NaN + Rodapé + Tab4 Layout Final + Read Robust + Indent Fix 2)

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
import re # Importado para parsear datas dos nomes de arquivo
import csv # Importado para sniffer

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
        content_bytes = content_file.decoded_content

        if not content_bytes:
            return pd.DataFrame()

        content = None
        tried_encodings = []
        try:
            content = content_bytes.decode("utf-8")
            tried_encodings.append("utf-8")
        except UnicodeDecodeError:
            try:
                content = content_bytes.decode("latin-1")
                tried_encodings.append("latin-1")
                if file_path == "dados_fechados.csv":
                    st.sidebar.warning(f"Arquivo '{file_path}' lido com encoding 'latin-1'. Verifique se o arquivo original foi salvo corretamente.")
            except Exception as decode_err:
                 st.error(f"Falha Crítica: Não foi possível decodificar o arquivo '{file_path}' com {', '.join(tried_encodings)}: {decode_err}")
                 return pd.DataFrame()

        if content is None or not content.strip():
            return pd.DataFrame()

        try:
             df = pd.read_csv(StringIO(content), delimiter=';', encoding='utf-8',
                              dtype={'ID do ticket': str, 'ID do Ticket': str}, low_memory=False,
                              on_bad_lines='warn')
        except pd.errors.ParserError as parse_err:
             st.error(f"Erro ao parsear o CSV '{file_path}': {parse_err}. Verifique delimitador (;) e estrutura.")
             return pd.DataFrame()
        except Exception as read_err:
             if 'unsupported encoding: none' in str(read_err):
                  st.error(f"Erro Crítico ao ler '{file_path}': O arquivo parece estar corrompido ou vazio no repositório. Por favor, faça upload novamente.")
                  return pd.DataFrame()
             else:
                  st.error(f"Erro inesperado ao ler conteúdo CSV de '{file_path}': {read_err}")
                  return pd.DataFrame()

        df.columns = df.columns.str.strip()
        df.dropna(how='all', inplace=True)
        return df

    except GithubException as e:
        if e.status == 404:
            return pd.DataFrame() # Arquivo não existe, normal para fechados no início
        st.error(f"Erro ao acessar arquivo do GitHub '{file_path}': {e}")
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
    except Exception:
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
                content_bytes = uploaded_file.getvalue()
                try:
                    content_str = content_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    content_str = content_bytes.decode('latin-1')
                
                sniffer = csv.Sniffer()
                try:
                    # Check first few lines for delimiter
                    sample = content_str[:2048] # Increase sample size
                    dialect = sniffer.sniff(sample) 
                    delimiter = dialect.delimiter
                    if delimiter != ';':
                        st.sidebar.warning(f"Detectado delimitador '{delimiter}' no arquivo CSV. Usando '{delimiter}'.")
                except csv.Error:
                     # If sniffer fails, assume semicolon but allow pandas to try auto-detect
                    delimiter = None 
                    st.sidebar.warning("Não foi possível detectar o delimitador CSV automaticamente. Tentando ';' e auto-detecção.")


                # Let pandas try to determine delimiter if sniffer failed or wasn't ';'
                df = pd.read_csv(StringIO(content_str), delimiter=delimiter or ';', # Use detected or fallback to ';'
                                 sep=None if delimiter is None else ';', # sep=None allows pandas auto-detect if delimiter is None
                                 dtype=dtype_spec, low_memory=False, on_bad_lines='warn')

            except Exception as read_err:
                 st.sidebar.error(f"Erro ao ler o arquivo CSV {uploaded_file.name}: {read_err}")
                 return None

        df.columns = df.columns.str.strip()
        df.dropna(how='all', inplace=True)

        output = StringIO()
        df.to_csv(output, index=False, sep=';', encoding='utf-8')
        return output.getvalue().encode('utf-8')
    except Exception as e:
        st.sidebar.error(f"Erro ao processar o arquivo {uploaded_file.name}: {e}")
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
        st.error("Coluna de data de criação ('Data de criação' ou 'Data de Criacao') não encontrada no arquivo atual.")
        return pd.DataFrame() # Retorna DF vazio se a coluna crucial falta
        
    df[date_col_name] = pd.to_datetime(df[date_col_name], errors='coerce')
    linhas_invalidas = df[df[date_col_name].isna()]
    
    # Verifica se há alguma linha válida antes de remover as inválidas
    if df[date_col_name].notna().sum() == 0 and not df.empty:
         st.error(f"Nenhuma data válida encontrada na coluna '{date_col_name}' do arquivo atual. A análise de aging não pode prosseguir.")
         return pd.DataFrame() # Retorna DF vazio se não houver datas válidas

    if not linhas_invalidas.empty:
        id_col = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in linhas_invalidas.columns), 'ID não encontrado')
        cols_to_show = [id_col, date_col_name, 'Atribuir a um grupo'] if id_col != 'ID não encontrado' else [date_col_name, 'Atribuir a um grupo']
        # Mostra apenas colunas que realmente existem
        cols_to_show = [col for col in cols_to_show if col in linhas_invalidas.columns] 
        with st.expander(f"⚠️ Atenção: {len(linhas_invalidas)} chamados foram descartados por data inválida ou vazia na coluna '{date_col_name}'."):
            st.dataframe(linhas_invalidas[cols_to_show].head())
            
    df.dropna(subset=[date_col_name], inplace=True)
    if df.empty: # Checa se o DF ficou vazio após dropar NaT
         st.warning("Após remover chamados com datas inválidas, nenhum chamado restou para análise.")
         return pd.DataFrame()
         
    hoje = pd.to_datetime('today').normalize()
    # Garante que a coluna de data é datetime antes de usar .dt
    df[date_col_name] = pd.to_datetime(df[date_col_name]) 
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
            ticket_id_obj = st.session_state.last_filtered_df.iloc[row_index]['ID do ticket']
            ticket_id = str(ticket_id_obj) if pd.notna(ticket_id_obj) else None
            if not ticket_id: continue 

            if 'Contato' in changes:
                current_contact_status = ticket_id in st.session_state.contacted_tickets
                new_contact_status = changes['Contato']
                if current_contact_status != new_contact_status:
                    if new_contact_status: st.session_state.contacted_tickets.add(ticket_id)
                    else: st.session_state.contacted_tickets.discard(ticket_id)
                    contact_changed = True
            if 'Observações' in changes:
                current_observation = st.session_state.observations.get(ticket_id, '')
                new_observation = changes['Observações'] if pd.notna(changes['Observações']) else '' 
                if current_observation != new_observation:
                    st.session_state.observations[ticket_id] = new_observation
                    observation_changed = True
        except IndexError:
            st.warning(f"Erro ao processar linha {row_index} (índice fora do alcance). Tente recarregar a página.")
            continue
        except Exception as e:
             st.warning(f"Erro inesperado ao processar alterações na linha {row_index}: {e}")
             continue


    if contact_changed or observation_changed:
        now_str = datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')
        if contact_changed:
            data_to_save = list(st.session_state.contacted_tickets)
            json_content = json.dumps(data_to_save, indent=4)
            commit_msg = f"Atualizando contatos em {now_str}"
            update_github_file(st.session_state.repo, "contacted_tickets.json", json_content.encode('utf-8'), commit_msg)
        if observation_changed:
            observations_to_save = {k: v for k, v in st.session_state.observations.items() if v}
            json_content = json.dumps(observations_to_save, indent=4, ensure_ascii=False)
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
        
        closed_ids_set = set(str(id_val) for id_val in closed_ticket_ids_list) 
        
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
        unique_dates = sorted(list(set(d[0] for d in processed_dates)), reverse=True)[:dias_para_analisar]
        files_to_process = [f[1] for f in processed_dates if f[0] in unique_dates]


        for file_name in files_to_process:
             try:
                 date_str = file_name.replace("snapshots/backlog_", "").replace(".csv", "")
                 file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                 df_snapshot = read_github_file(_repo, file_name)
                 if not df_snapshot.empty and 'Atribuir a um grupo' in df_snapshot.columns:
                     df_snapshot_filtrado_rh = df_snapshot[~df_snapshot['Atribuir a um grupo'].str.contains('RH', case=False, na=False)].copy() 
                     id_col_snapshot = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_snapshot_filtrado_rh.columns), None)
                     df_snapshot_final = df_snapshot_filtrado_rh 
                     if id_col_snapshot and closed_ids_set:
                         df_snapshot_filtrado_rh[id_col_snapshot] = df_snapshot_filtrado_rh[id_col_snapshot].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                         df_snapshot_final = df_snapshot_filtrado_rh[~df_snapshot_filtrado_rh[id_col_snapshot].isin(closed_ids_set)]
                     
                     contagem_diaria = df_snapshot_final.groupby('Atribuir a um grupo').size().reset_index(name='Total Chamados')
                     contagem_diaria['Data'] = pd.to_datetime(file_date)
                     df_evolucao_list.append(contagem_diaria)
             except Exception as e: 
                  st.warning(f"Erro ao processar snapshot {file_name}: {e}. Ignorando este arquivo.")
                  continue 

        if not df_evolucao_list: return pd.DataFrame()
        
        df_consolidado = pd.concat(df_evolucao_list, ignore_index=True)
        df_consolidado = df_consolidado.groupby(['Data', 'Atribuir a um grupo'])['Total Chamados'].first().reset_index()
        return df_consolidado.sort_values(by=['Data', 'Atribuir a um grupo'])
        
    except GithubException as e:
        if e.status == 404: return pd.DataFrame()
        st.warning(f"Não foi possível listar snapshots: {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar evolução: {e}")
        return pd.DataFrame()

# --- Função find_closest_snapshot com indentação corrigida ---
@st.cache_data(ttl=300)
def find_closest_snapshot(_repo, current_report_date, target_date):
    """Encontra o snapshot mais próximo da target_date, buscando nos últimos ~10 dias."""
    try:
        all_files_content = _repo.get_contents("snapshots")
        snapshots = []
        search_start_date = current_report_date - timedelta(days=10)

        for file in all_files_content:
            match = re.search(r"backlog_(\d{4}-\d{2}-\d{2})\.csv", file.path)
            if match:
                snapshot_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                if search_start_date <= snapshot_date < current_report_date:
                    snapshots.append((snapshot_date, file.path))

        if not snapshots:
            return None, None

        diffs = [abs((snapshot[0] - target_date).days) for snapshot in snapshots]
        min_index = diffs.index(min(diffs))
        return snapshots[min_index]

    except GithubException as e:
        if e.status == 404: # Se a pasta snapshots não existir
            return None, None
        st.warning(f"Erro ao buscar snapshots no GitHub: {e}")
        return None, None
    except Exception as e:
        st.warning(f"Erro inesperado ao buscar snapshots: {e}")
        return None, None
# --- Fim da correção ---

st.html("""<style>#GithubIcon { visibility: hidden; } .metric-box { border: 1px solid #CCCCCC; padding: 10px; border-radius: 5px; text-align: center; box-shadow: 0px 2px 4px rgba(0,0,0,0.1); margin-bottom: 10px; } a.metric-box { display: block; color: inherit; text-decoration: none !important; } a.metric-box:hover { background-color: #f0f2f6; text-decoration: none !important; } .metric-box span { display: block; width: 100%; text-decoration: none !important; } .metric-box .value { font-size: 2.5em; font-weight: bold; color: #375623; } .metric-box .label { font-size: 1em; color: #666666; }</style>""")

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
                    update_github_file(repo, "dados_fechados.csv", content_fechados, commit_msg)
                    st.cache_data.clear()
                    st.cache_resource.clear()
                    st.sidebar.success("Arquivo de fechados salvo! Recarregando...")
                    st.rerun()
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
    if df_atual.empty: # Não precisa mais checar df_15dias aqui
        st.warning("Arquivo 'dados_atuais.csv' não encontrado ou vazio. Carregue os dados na área do administrador.")
        st.stop()
    if data_atual_str == 'N/A':
         st.warning("Arquivo 'datas_referencia.txt' não encontrado ou inválido.")
         # Tenta usar a data de hoje como fallback, mas avisa
         data_atual_date = date.today()
         data_atual_str = data_atual_date.strftime("%d/%m/%Y")
         st.info(f"Usando data atual ({data_atual_str}) como referência para análise semanal.")
    else:
         try:
              data_atual_date = datetime.strptime(data_atual_str, "%d/%m/%Y").date()
         except ValueError:
              st.error(f"Data atual '{data_atual_str}' em 'datas_referencia.txt' é inválida.")
              data_atual_date = date.today() # Fallback
              data_atual_str = data_atual_date.strftime("%d/%m/%Y")
              st.info(f"Usando data atual ({data_atual_str}) como referência para análise semanal.")


    if 'ID do ticket' in df_atual.columns:
        df_atual['ID do ticket'] = df_atual['ID do ticket'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    else:
        st.error("Coluna 'ID do ticket' não encontrada no arquivo atual. Verifique o cabeçalho.")
        st.stop() # ID do ticket é crucial

    
    closed_ticket_ids = []
    if not df_fechados.empty:
        id_col_name_fechados = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_fechados.columns), None)
        if id_col_name_fechados:
            # Garante que a coluna de ID seja string antes de processar
            df_fechados[id_col_name_fechados] = df_fechados[id_col_name_fechados].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            closed_ticket_ids = df_fechados[id_col_name_fechados].dropna().unique().tolist() # Converte para lista

    # Verifica se a coluna 'Atribuir a um grupo' existe
    if 'Atribuir a um grupo' not in df_atual.columns:
         st.error("Coluna 'Atribuir a um grupo' não encontrada no arquivo atual. Verifique o cabeçalho.")
         st.stop() # Coluna de grupo é crucial

    df_encerrados = df_atual[df_atual['ID do ticket'].isin(closed_ticket_ids)]
    df_abertos = df_atual[~df_atual['ID do ticket'].isin(closed_ticket_ids)]
    df_atual_filtrado = df_abertos[~df_abertos['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]
    
    # Carrega df_15dias somente se existir para a Tab1
    if not df_15dias.empty and 'Atribuir a um grupo' in df_15dias.columns:
        df_15dias_filtrado = df_15dias[~df_15dias['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]
    else:
        df_15dias_filtrado = pd.DataFrame() # Cria um DF vazio se não puder carregar/filtrar o de 15 dias

    df_aging = analisar_aging(df_atual_filtrado.copy()) # Passa cópia para não modificar o original
    
    df_encerrados_filtrado = df_encerrados[~df_encerrados['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]
    
    tab1, tab2, tab3, tab4 = st.tabs(["Dashboard Completo", "Report Visual", "Evolução Semanal", "Análise de Tendência"])
    
    # ... (Código das tabs 1, 2, 3 permanece o mesmo) ...

    # --- Código da Tab 4 com os ajustes finais ---
    with tab4:
        st.subheader("Análise Semana vs Semana: Variação do Backlog por Grupo")
            
        target_start_date = data_atual_date - timedelta(days=7)

        actual_start_date, start_snapshot_path = find_closest_snapshot(repo, data_atual_date, target_start_date)

        if start_snapshot_path is None:
            st.warning(f"Não foi encontrado um snapshot de dados próximo a {target_start_date.strftime('%d/%m/%Y')} (7 dias antes) para realizar a comparação semanal.")
        else:
            df_inicio_raw = read_github_file(repo, start_snapshot_path)
            
            if df_inicio_raw.empty or 'Atribuir a um grupo' not in df_inicio_raw.columns:
                 st.warning(f"O snapshot encontrado para {actual_start_date.strftime('%d/%m/%Y')} está vazio ou inválido.")
            else:
                df_inicio_filtrado = df_inicio_raw[~df_inicio_raw['Atribuir a um grupo'].str.contains('RH', case=False, na=False)].copy() 
                id_col_inicio = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_inicio_filtrado.columns), None)
                if id_col_inicio:
                    # Garante IDs como string antes de filtrar
                    df_inicio_filtrado[id_col_inicio] = df_inicio_filtrado[id_col_inicio].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    df_inicio_filtrado = df_inicio_filtrado[~df_inicio_filtrado[id_col_inicio].isin(closed_ticket_ids)]
                
                df_inicio_data = df_inicio_filtrado.groupby('Atribuir a um grupo').size().reset_index(name='Início').rename(
                    columns={'Atribuir a um grupo': 'Grupo'}
                )

                df_fim_data = df_atual_filtrado.groupby('Atribuir a um grupo').size().reset_index(name='Fim').rename(
                    columns={'Atribuir a um grupo': 'Grupo'}
                )
                
                st.info(f"Comparando backlog de **{actual_start_date.strftime('%d/%m/%Y')} (Início - data mais próxima de 7 dias atrás)** com **{data_atual_str} (Fim)**.")
                st.markdown("---")

                df_tendencia = pd.merge(df_inicio_data, df_fim_data, on='Grupo', how='outer').fillna(0)
                df_tendencia[['Início', 'Fim']] = df_tendencia[['Início', 'Fim']].astype(int)
                df_tendencia['Variação Absoluta'] = df_tendencia['Fim'] - df_tendencia['Início']
                
                df_tendencia['Variação (%)'] = np.where(
                    df_tendencia['Início'] > 0, 
                    100 * (df_tendencia['Fim'] - df_tendencia['Início']) / df_tendencia['Início'], 
                    np.nan 
                )
                
                df_aumentos = df_tendencia[df_tendencia['Variação Absoluta'] > 0].copy()
                df_reducoes = df_tendencia[df_tendencia['Variação Absoluta'] < 0].copy()

                col_reducoes, col_aumentos_pareto = st.columns(2)

                # Coluna da Esquerda: Grupos com Redução
                with col_reducoes:
                    title_spacer1, title_col, title_spacer2 = st.columns([1, 2, 1])
                    with title_col:
                        st.markdown("<h3 style='text-align: center;'>Grupos com Maiores Reduções</h3>", unsafe_allow_html=True)
                    
                    if df_reducoes.empty:
                         st.info("Nenhum grupo apresentou redução no backlog na última semana.")
                    else:
                        df_reducoes = df_reducoes.sort_values(by='Variação Absoluta', ascending=True) 
                        for _, row in df_reducoes.head(5).iterrows(): 
                            spacer1, metric_col, spacer2 = st.columns([1, 2, 1]) 
                            with metric_col:
                                delta_help_red = f"Variação: {row['Variação Absoluta']:+.0f} (de {row['Início']:.0f} para {row['Fim']:.0f})"
                                st.metric(
                                    label=row['Grupo'],
                                    value=f"{row['Fim']:.0f} chamados",
                                    delta=f"{row['Variação (%)']:+.1f}%",
                                    delta_color="inverse", # Verde para redução
                                    help=delta_help_red
                                )
                            st.divider()

                # Coluna da Direita: Pareto dos Aumentos
                with col_aumentos_pareto:
                    title_spacer1, title_col, title_spacer2 = st.columns([1, 2, 1])
                    with title_col:
                        st.markdown("<h3 style='text-align: center;'>Grupos que Precisam de Atenção</h3>", unsafe_allow_html=True) 
                    
                    if df_aumentos.empty:
                        st.success("🎉 Nenhum grupo apresentou aumento no backlog na última semana!")
                    else:                        
                        aumento_total = df_aumentos['Variação Absoluta'].sum()
                        if aumento_total <= 0: 
                             st.info("Aumento total do backlog foi zero ou negativo.")
                        else:
                            df_aumentos = df_aumentos.sort_values(by='Variação Absoluta', ascending=False)
                            df_aumentos['Cumulativo'] = df_aumentos['Variação Absoluta'].cumsum()
                            df_aumentos['% Contribuição Acumulada'] = 100 * df_aumentos['Cumulativo'] / aumento_total
                            
                            limite_pareto = 80.0
                            df_pareto = df_aumentos[df_aumentos['% Contribuição Acumulada'] <= limite_pareto + 5] 
                            if df_pareto.empty and not df_aumentos.empty:
                                df_pareto = df_aumentos.head(1)
                            
                            for _, row in df_pareto.iterrows():
                                spacer1, metric_col, spacer2 = st.columns([1, 2, 1])
                                with metric_col:
                                    perc_contrib_total = (100 * row['Variação Absoluta'] / aumento_total) if aumento_total else 0
                                    delta_help = f"Responsável por {perc_contrib_total:.1f}% do aumento total. Variação: {row['Variação Absoluta']:+.0f} (de {row['Início']:.0f} para {row['Fim']:.0f})"
                                    st.metric(
                                        label=row['Grupo'],
                                        value=f"{row['Fim']:.0f} chamados", 
                                        delta=f"{row['Variação (%)']:+.1f}%" if not pd.isna(row['Variação (%)']) else "Grupo Novo", 
                                        delta_color="inverse", # VERMELHO PARA AUMENTO
                                        help=delta_help
                                    )
                                st.divider() 

except Exception as e:
    st.error(f"Ocorreu um erro geral ao carregar o dashboard: {e}")
    st.exception(e) # Mostra detalhes do erro para debug

st.markdown("---")
st.markdown("""
<p style='text-align: center; color: #666; font-size: 0.9em; margin-bottom: 0;'>v0.9.20-729 | Este dashboard está em desenvolvimento.</p>
<p style='text-align: center; color: #666; font-size: 0.9em; margin-top: 0;'>Desenvolvido por Leonir Scatolin Junior</p>
""", unsafe_allow_html=True)
