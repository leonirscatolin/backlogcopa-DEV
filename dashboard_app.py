# VERSÃO 0.9.8-700 - Backend: GitHub (Coluna Observações adicionada)

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

# --- Funções GitHub ---
@st.cache_resource
def get_github_repo():
    try:
        expected_repo_name = st.secrets.get("EXPECTED_REPO")
        if not expected_repo_name:
            st.error("Configuração de segurança incompleta.")
            st.stop()
        auth = Auth.Token(st.secrets["GITHUB_TOKEN"])
        g = Github(auth=auth)
        return g.get_repo(expected_repo_name)
    except GithubException as e:
        if e.status == 404: st.error("Erro: Token sem acesso ao repo ou repo inexistente.")
        else: st.error(f"Erro GitHub: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Erro conexão: {e}")
        st.stop()

def update_github_file(_repo, file_path, file_content, commit_message):
    try:
        contents = _repo.get_contents(file_path)
        if isinstance(file_content, str): file_content = file_content.encode('utf-8')
        _repo.update_file(contents.path, commit_message, file_content, contents.sha)
        if file_path not in ["contacted_tickets.json", "ticket_observations.json"]:
             st.sidebar.info(f"Arquivo '{file_path}' atualizado.")
    except GithubException as e:
        if e.status == 404:
            if isinstance(file_content, str): file_content = file_content.encode('utf-8')
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
        df = pd.read_csv(StringIO(content), delimiter=';', encoding='utf-8', dtype={'ID do ticket': str, 'ID do Ticket': str})
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

# --- NOVA FUNÇÃO PARA LER JSON COMO DICIONÁRIO ---
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
        st.error(f"Erro ao decodificar JSON '{file_path}'. Verifique o conteúdo do arquivo.")
        return {}
    except Exception as e:
        st.error(f"Erro inesperado ao ler JSON '{file_path}': {e}")
        return {}

# --- Funções de Processamento ---
def process_uploaded_file(uploaded_file):
    if uploaded_file is None: return None
    try:
        dtype_spec = {'ID do ticket': str, 'ID do Ticket': str, 'ID': str}
        if uploaded_file.name.endswith('.xlsx'):
            df = pd.read_excel(uploaded_file, dtype=dtype_spec)
        else:
            try: content = uploaded_file.getvalue().decode('utf-8')
            except UnicodeDecodeError: content = uploaded_file.getvalue().decode('latin1')
            df = pd.read_csv(StringIO(content), delimiter=';', dtype=dtype_spec)
        df.columns = df.columns.str.strip()
        output = StringIO()
        df.to_csv(output, index=False, sep=';', encoding='utf-8')
        return output.getvalue().encode('utf-8')
    except Exception as e:
        st.sidebar.error(f"Erro ao ler {uploaded_file.name}: {e}")
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
    if not date_col_name: return pd.DataFrame()
    df[date_col_name] = pd.to_datetime(df[date_col_name], errors='coerce')
    linhas_invalidas = df[df[date_col_name].isna()]
    if not linhas_invalidas.empty:
        with st.expander(f"⚠️ Atenção: {len(linhas_invalidas)} chamados descartados."):
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
        with open(path, "rb") as image_file: return base64.b64encode(image_file.read()).decode()
    except FileNotFoundError: return None

# --- FUNÇÃO DE SINCRONIZAÇÃO ATUALIZADA ---
def sync_ticket_data():
    if 'ticket_editor' not in st.session_state or not st.session_state.ticket_editor.get('edited_rows'):
        return

    edited_rows = st.session_state.ticket_editor['edited_rows']
    contact_changed = False
    observation_changed = False

    # Atualiza estado local
    for row_index, changes in edited_rows.items():
        try:
            ticket_id = str(st.session_state.last_filtered_df.iloc[row_index]['ID do ticket'])
            if 'Contato' in changes:
                if changes['Contato']: st.session_state.contacted_tickets.add(ticket_id)
                else: st.session_state.contacted_tickets.discard(ticket_id)
                contact_changed = True
            if 'Observações' in changes:
                st.session_state.observations[ticket_id] = changes['Observações']
                observation_changed = True
        except IndexError:
            st.warning(f"Erro ao processar a linha {row_index}. Os dados podem ter sido recarregados.")
            continue # Pula para a próxima iteração se o índice for inválido

    now_str = datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')

    # Salva contatos se mudou
    if contact_changed:
        data_to_save = list(st.session_state.contacted_tickets)
        json_content = json.dumps(data_to_save, indent=4)
        commit_msg = f"Atualizando tickets contatados em {now_str}"
        update_github_file(st.session_state.repo, "contacted_tickets.json", json_content.encode('utf-8'), commit_msg)

    # Salva observações se mudou
    if observation_changed:
        json_content = json.dumps(st.session_state.observations, indent=4, ensure_ascii=False)
        commit_msg = f"Atualizando observações de tickets em {now_str}"
        update_github_file(st.session_state.repo, "ticket_observations.json", json_content.encode('utf-8'), commit_msg)

    st.session_state.scroll_to_details = True
    # Limpa estado editado para evitar re-salvamento desnecessário
    st.session_state.ticket_editor['edited_rows'] = {}


@st.cache_data(ttl=3600)
def carregar_dados_evolucao(_repo, dias_para_analisar=7):
    #... (código da função igual ao anterior)

# --- Interface ---
st.html("""<style>...</style>""") # Estilos CSS omitidos para brevidade

logo_copa_b64 = get_image_as_base64("logo_sidebar.png")
logo_belago_b64 = get_image_as_base64("logo_belago.png")
if logo_copa_b64 and logo_belago_b64:
    st.markdown(f"""...""", unsafe_allow_html=True) # Logos omitidos para brevidade
else: st.error("Arquivos de logo não encontrados.")

repo = get_github_repo()
st.session_state.repo = repo

# --- Área do Administrador ---
st.sidebar.header("Área do Administrador")
password = st.sidebar.text_input("Senha para atualizar dados:", type="password")
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
                    st.sidebar.success("Arquivos salvos! Recarregando...")
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
                    st.cache_data.clear()
                    st.cache_resource.clear()
                    st.sidebar.success("Fechados salvos! Recarregando...")
                    st.rerun()
        else: st.sidebar.warning("Carregue o arquivo de fechados.")
elif password: st.sidebar.error("Senha incorreta.")

# --- Lógica Principal ---
try:
    # --- CARREGAR ESTADOS DE CONTATO E OBSERVAÇÕES ---
    if 'contacted_tickets' not in st.session_state:
        st.session_state.contacted_tickets = set(read_github_json_dict(repo, "contacted_tickets.json"))
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
        st.warning("Sem dados para exibir. Carregue os arquivos.")
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
        info_messages = ["**Filtros e Regras Aplicadas:**", "- Grupos contendo 'RH' foram desconsiderados.", "- Contagem de dias desconsidera o dia da abertura (prazo -1 dia)."]
        if not df_encerrados.empty: info_messages.append(f"- **{len(df_encerrados)} chamados fechados** deduzidos das contagens.")
        st.info("\n".join(info_messages))
        st.subheader("Análise de Antiguidade do Backlog Atual")
        texto_hora = f" (às {hora_atualizacao_str})" if hora_atualizacao_str else ""
        st.markdown(f"<p style='font-size: 0.9em; color: #666;'><i>Ref: {data_atual_str}{texto_hora}</i></p>", unsafe_allow_html=True)
        if not df_aging.empty:
            total_chamados = len(df_aging)
            _, col_total, _ = st.columns([2, 1.5, 2])
            with col_total: st.markdown(f"""...""", unsafe_allow_html=True) # Métrica omitida
            st.markdown("---")
            aging_counts = df_aging['Faixa de Antiguidade'].value_counts().reset_index()
            # ... Lógica dos cards omitida para brevidade ...
        else: st.warning("Sem dados para análise de antiguidade.")
        st.markdown(f"<h3>Comparativo: Atual vs. {data_15dias_str}</h3>", unsafe_allow_html=True)
        df_comparativo = processar_dados_comparativos(df_atual_filtrado.copy(), df_15dias_filtrado.copy())
        # ... Lógica da tabela comparativa omitida ...
        st.markdown("---")
        st.markdown(f"<h3>Chamados Encerrados ({data_atual_str})</h3>", unsafe_allow_html=True)
        # ... Lógica dos encerrados omitida ...
        if not df_aging.empty:
            st.markdown("---")
            st.subheader("Detalhar e Buscar Chamados")
            st.info('Marque "Contato" se já falou com o usuário. Use "Observações" para anotações.')
            if 'scroll_to_details' not in st.session_state: st.session_state.scroll_to_details = False
            if needs_scroll or st.session_state.get('scroll_to_details', False):
                js_code = """...""" # Código JS omitido
                components.html(js_code, height=0)
                st.session_state.scroll_to_details = False
            ordem_faixas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
            st.selectbox("Detalhar por faixa de idade:", options=ordem_faixas, key='faixa_selecionada')
            faixa_atual = st.session_state.faixa_selecionada
            filtered_df = df_aging[df_aging['Faixa de Antiguidade'] == faixa_atual].copy()
            if not filtered_df.empty:
                def highlight_row(row): return ['background-color: #fff8c4'] * len(row) if row['Contato'] else [''] * len(row)
                
                # --- ADICIONA COLUNA OBSERVAÇÕES ---
                filtered_df['Contato'] = filtered_df['ID do ticket'].apply(lambda id: str(id) in st.session_state.contacted_tickets)
                filtered_df['Observações'] = filtered_df['ID do ticket'].apply(lambda id: st.session_state.observations.get(str(id), ''))
                
                st.session_state.last_filtered_df = filtered_df.reset_index(drop=True)
                
                # --- ATUALIZA COLUNAS E EDITOR ---
                colunas_para_exibir = ['Contato', 'ID do ticket', 'Descrição', 'Atribuir a um grupo', 'Dias em Aberto', 'Data de criação', 'Observações']
                st.data_editor(
                    st.session_state.last_filtered_df[colunas_para_exibir].style.apply(highlight_row, axis=1),
                    use_container_width=True,
                    hide_index=True,
                    disabled=['ID do ticket', 'Descrição', 'Atribuir a um grupo', 'Dias em Aberto', 'Data de criação'], # Observações é editável
                    key='ticket_editor',
                    on_change=sync_ticket_data # Função atualizada
                )
            else: st.info("Não há chamados nesta categoria.")
            st.subheader("Buscar Chamados por Grupo")
            # ... Lógica da busca por grupo omitida ...
    with tab2:
        # ... Lógica da Tab 2 omitida para brevidade ...
    with tab3:
        st.subheader("Evolução do Backlog")
        st.info("Coletando dados históricos. Análise completa em breve.")
        dias_evolucao = st.slider("Ver evolução (dias):", 7, 30, 7, key="slider_evolucao")
        df_evolucao = carregar_dados_evolucao(repo, dias_para_analisar=dias_evolucao)
        # ... Lógica do gráfico de evolução omitida ...

except Exception as e:
    st.error(f"Erro ao carregar dados: {e}")
    st.exception(e)

st.markdown("---")
st.markdown("""<p style='text-align: center; color: #666; font-size: 0.9em;'>v0.9.8-700 | Em desenvolvimento.</p>""", unsafe_allow_html=True)
