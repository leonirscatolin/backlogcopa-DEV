# VERSÃO 0.9.0-692 - Backend: GitHub

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
        _repo.update_file(contents.path, commit_message, file_content, contents.sha)
        if file_path != "contacted_tickets.json":
            st.sidebar.info(f"Arquivo '{file_path}' atualizado com sucesso.")
    except GithubException as e:
        if e.status == 404:
            _repo.create_file(file_path, commit_message, file_content)
            if file_path != "contacted_tickets.json":
                st.sidebar.info(f"Arquivo '{file_path}' criado com sucesso.")
        else:
            st.sidebar.error(f"Falha ao salvar '{file_path}': {e}")

@st.cache_data(ttl=300)
def read_github_file(_repo, file_path):
    try:
        content_file = _repo.get_contents(file_path)
        content = content_file.decoded_content.decode("utf-8")
        if not content.strip():
            return pd.DataFrame()
        df = pd.read_csv(StringIO(content), delimiter=';', encoding='utf-8', dtype={'ID do ticket': str, 'ID do Ticket': str})
        df.columns = df.columns.str.strip()
        return df
    except GithubException as e:
        if e.status == 404: # Arquivo não existe ainda
            return pd.DataFrame()
        st.error(f"Erro ao ler arquivo do GitHub '{file_path}': {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao ler arquivo do GitHub '{file_path}': {e}")
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
    
    hoje = pd.to_datetime('today')
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

def sync_contacted_tickets():
    if 'ticket_editor' not in st.session_state or not st.session_state.ticket_editor.get('edited_rows'):
        return

    previous_state = set(st.session_state.contacted_tickets)
    for row_index, changes in st.session_state.ticket_editor['edited_rows'].items():
        ticket_id = st.session_state.last_filtered_df.iloc[row_index]['ID do ticket']
        if 'Contato' in changes:
            if changes['Contato']:
                st.session_state.contacted_tickets.add(str(ticket_id))
            else:
                st.session_state.contacted_tickets.discard(str(ticket_id))

    if previous_state != st.session_state.contacted_tickets:
        data_to_save = list(st.session_state.contacted_tickets)
        json_content = json.dumps(data_to_save, indent=4)
        commit_msg = f"Atualizando tickets contatados em {datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')}"
        update_github_file(st.session_state.repo, "contacted_tickets.json", json_content, commit_msg)
    st.session_state.scroll_to_details = True

@st.cache_data(ttl=3600)
def carregar_dados_evolucao(_repo, dias_para_analisar=7):
    try:
        all_files = _repo.get_contents("snapshots")
        df_evolucao_list = []
        
        end_date = date.today()
        start_date = end_date - timedelta(days=dias_para_analisar - 1)

        for content_file in all_files:
            file_name = content_file.path
            if file_name.startswith("snapshots/backlog_") and file_name.endswith(".csv"):
                try:
                    date_str = file_name.replace("snapshots/backlog_", "").replace(".csv", "")
                    file_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                    if start_date <= file_date <= end_date:
                        df_snapshot = read_github_file(_repo, file_name)
                        if not df_snapshot.empty and 'Atribuir a um grupo' in df_snapshot.columns:
                            df_snapshot_filtrado = df_snapshot[~df_snapshot['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]
                            contagem_diaria = df_snapshot_filtrado.groupby('Atribuir a um grupo').size().reset_index(name='Total Chamados')
                            contagem_diaria['Data'] = pd.to_datetime(file_date)
                            df_evolucao_list.append(contagem_diaria)
                except ValueError:
                    continue

        if not df_evolucao_list:
            return pd.DataFrame()

        df_consolidado = pd.concat(df_evolucao_list, ignore_index=True)
        return df_consolidado.sort_values(by=['Data', 'Atribuir a um grupo'])

    except GithubException as e:
        if e.status == 404:
            return pd.DataFrame()
        st.warning(f"Não foi possível carregar o histórico de snapshots: {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Ocorreu um erro inesperado ao carregar dados de evolução: {e}")
        return pd.DataFrame()


# --- INÍCIO DA EXECUÇÃO DO SCRIPT ---

st.html("""<style>#GithubIcon { visibility: hidden; } .metric-box { border: 1px solid #CCCCCC; padding: 10px; border-radius: 5px; text-align: center; box-shadow: 0px 2px 4px rgba(0,0,0,0.1); margin-bottom: 10px; } a.metric-box { display: block; color: inherit; text-decoration: none !important; } a.metric-box:hover { background-color: #f0f2f6; text-decoration: none !important; } .metric-box span { display: block; width: 100%; text-decoration: none !important; } .metric-box .value { font-size: 2.5em; font-weight: bold; color: #375623; } .metric-box .label { font-size: 1em; color: #666666; }</style>""")

logo_copa_b64 = get_image_as_base64("logo_sidebar.png")
logo_belago_b64 = get_image_as_base64("logo_belago.png")
if logo_copa_b64 and logo_belago_b64:
    st.markdown(f"""<div style="display: flex; justify-content: space-between; align-items: center;"><img src="data:image/png;base64,{logo_copa_b64}" width="150"><h1 style='text-align: center; margin: 0;'>Backlog Copa Energia + Belago</h1><img src="data:image/png;base64,{logo_belago_b64}" width="150"></div>""", unsafe_allow_html=True)
else:
    st.error("Arquivos de logo não encontrados.")

# A conexão agora é feita pela função get_github_repo()
repo = get_github_repo()
st.session_state.repo = repo 

st.sidebar.header("Área do Administrador")
password = st.sidebar.text_input("Senha para atualizar dados:", type="password")
is_admin = password == st.secrets.get("ADMIN_PASSWORD", "")

if is_admin:
    st.sidebar.success("Acesso de administrador liberado.")
    st.sidebar.header("Carregar Novos Arquivos")
    
    uploaded_file_atual = st.sidebar.file_uploader("1. Backlog ATUAL", type=["csv", "xlsx"])
    uploaded_file_15dias = st.sidebar.file_uploader("2. Backlog de 15 DIAS ATRÁS", type=["csv", "xlsx"])
    uploaded_file_fechados = st.sidebar.file_uploader("3. Chamados FECHADOS no dia (Opcional)", type=["csv", "xlsx"])
    
    if st.sidebar.button("Salvar Novos Dados no Site"):
        if uploaded_file_atual and uploaded_file_15dias:
            with st.spinner("Processando e salvando arquivos..."):
                now_sao_paulo = datetime.now(ZoneInfo('America/Sao_Paulo'))
                commit_msg = f"Dados atualizados em {now_sao_paulo.strftime('%d/%m/%Y %H:%M')}"
                
                content_atual = process_uploaded_file(uploaded_file_atual)
                content_15dias = process_uploaded_file(uploaded_file_15dias)
                content_fechados = process_uploaded_file(uploaded_file_fechados)

                if content_atual is not None and content_15dias is not None:
                    update_github_file(repo, "dados_atuais.csv", content_atual, commit_msg)
                    update_github_file(repo, "dados_15_dias.csv", content_15dias, commit_msg)
                    
                    today_str = now_sao_paulo.strftime('%Y-%m-%d')
                    snapshot_path = f"snapshots/backlog_{today_str}.csv"
                    update_github_file(repo, snapshot_path, content_atual, f"Snapshot de {today_str}")

                    if content_fechados is not None:
                        update_github_file(repo, "dados_fechados.csv", content_fechados, commit_msg)
                    else:
                        update_github_file(repo, "dados_fechados.csv", b"", commit_msg)

                    data_do_upload = now_sao_paulo.date()
                    data_arquivo_15dias = data_do_upload - timedelta(days=15)
                    hora_atualizacao = now_sao_paulo.strftime('%H:%M')
                    
                    datas_referencia_content = (f"data_atual:{data_do_upload.strftime('%d/%m/%Y')}\n"
                                                f"data_15dias:{data_arquivo_15dias.strftime('%d/%m/%Y')}\n"
                                                f"hora_atualizacao:{hora_atualizacao}")
                    update_github_file(repo, "datas_referencia.txt", datas_referencia_content, commit_msg)

                    st.cache_data.clear()
                    st.sidebar.success("Arquivos salvos! Forçando recarregamento...")
                    st.rerun()
        else:
            st.sidebar.warning("Carregue os arquivos obrigatórios (Atual e 15 Dias) para salvar.")
elif password:
    st.sidebar.error("Senha incorreta.")


# --- LÓGICA PRINCIPAL DO DASHBOARD ---
try:
    if 'contacted_tickets' not in st.session_state:
        try:
            file_content = repo.get_contents("contacted_tickets.json").decoded_content.decode("utf-8")
            st.session_state.contacted_tickets = set(json.loads(file_content))
        except GithubException as e:
            if e.status == 404: st.session_state.contacted_tickets = set()
            else: st.error(f"Erro ao carregar o estado dos tickets: {e}"); st.session_state.contacted_tickets = set()

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
    
    tab1, tab2, tab3 = st.tabs(["Dashboard Completo", "Report Visual", "Evolução Semanal"])
    
    with tab1:
        # Lógica da Tab1
        pass # Você pode colar a lógica da Tab1 aqui

    with tab2:
        # Lógica da Tab2
        pass # Você pode colar a lógica da Tab2 aqui
    
    with tab3:
        st.subheader("Evolução do Backlog")
        dias_evolucao = st.slider("Ver evolução dos últimos dias:", 7, 30, 7)
        df_evolucao = carregar_dados_evolucao(repo, dias_para_analisar=dias_evolucao)

        if not df_evolucao.empty:
            todos_grupos = sorted(df_evolucao['Atribuir a um grupo'].unique())
            grupos_selecionados = st.multiselect("Selecione os grupos para visualizar:", options=todos_grupos, default=todos_grupos)

            if grupos_selecionados:
                df_filtrado = df_evolucao[df_evolucao['Atribuir a um grupo'].isin(grupos_selecionados)]
                fig_evolucao = px.line(df_filtrado, x='Data', y='Total Chamados', color='Atribuir a um grupo', title='Total de Chamados Abertos por Grupo', markers=True)
                st.plotly_chart(fig_evolucao, use_container_width=True)
        else:
            st.info("Ainda não há dados históricos para exibir a evolução. Os dados serão coletados a cada novo upload.")

except Exception as e:
    st.error(f"Ocorreu um erro ao carregar os dados: {e}")
    st.exception(e)

st.markdown("---")
st.markdown("""<p style='text-align: center; color: #666; font-size: 0.9em;'>v0.9.0-692 | Este dashboard está em desenvolvimento.</p>""", unsafe_allow_html=True)
