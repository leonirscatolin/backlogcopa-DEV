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

# --- Funções GitHub (sem alterações) ---
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


@st.cache_data(ttl=3600)
def carregar_dados_evolucao(_repo, dias_para_analisar=7):
    # ... (código da função igual ao anterior)

st.html("""<style>...</style>""") # CSS omitido

logo_copa_b64 = get_image_as_base64("logo_sidebar.png")
logo_belago_b64 = get_image_as_base64("logo_belago.png")
if logo_copa_b64 and logo_belago_b64:
    st.markdown(f"""...""", unsafe_allow_html=True) # Logos omitidos
else: st.error("Arquivos de logo não encontrados.")

repo = get_github_repo()
st.session_state.repo = repo

st.sidebar.header("Área do Administrador")
password = st.sidebar.text_input("Senha para atualizar dados:", type="password")
is_admin = password == st.secrets.get("ADMIN_PASSWORD", "")

if is_admin:
    # Código da área do Admin (sem alterações)
    # ...
elif password:
    st.sidebar.error("Senha incorreta.")

try:
    if 'contacted_tickets' not in st.session_state:
        st.session_state.contacted_tickets = set(read_github_json_dict(repo, "contacted_tickets.json"))
    if 'observations' not in st.session_state:
        st.session_state.observations = read_github_json_dict(repo, "ticket_observations.json")

    # --- LEITURA INICIAL DOS PARÂMETROS DA URL ---
    url_params = st.query_params.to_dict()
    scroll_target_id_on_load = None
    faixa_from_url = None

    if "scroll_to" in url_params and url_params.get("scroll_to") == "encerrados":
        scroll_target_id_on_load = 'chamados-encerrados'
    elif "faixa" in url_params:
        faixa_from_url = url_params.get("faixa")
        ordem_faixas_validas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
        if faixa_from_url in ordem_faixas_validas:
             # Atualiza a faixa selecionada apenas se veio da URL e é diferente
             if 'faixa_selecionada' not in st.session_state or st.session_state.faixa_selecionada != faixa_from_url:
                 st.session_state.faixa_selecionada = faixa_from_url
        scroll_target_id_on_load = 'detalhar-e-buscar-chamados'

    # --- INJEÇÃO DO JS SE NECESSÁRIO ---
    if scroll_target_id_on_load:
        js_code = f"""
        <script>
            setTimeout(() => {{
                console.log('Attempting to scroll to: {scroll_target_id_on_load}');
                const element = window.parent.document.getElementById('{scroll_target_id_on_load}');
                if (element) {{
                    element.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                    console.log('Scroll successful.');
                }} else {{
                     console.log('Scroll target element not found.');
                }}
                // Limpa params da URL após tentar rolar
                try {{
                    const url = new URL(window.location);
                    url.searchParams.delete('faixa');
                    url.searchParams.delete('scroll');
                    url.searchParams.delete('scroll_to');
                    window.history.replaceState({{}}, '', url);
                }} catch (e) {{ console.error("Could not clear URL parameters:", e); }}
            }}, 350);
        </script>
        """
        components.html(js_code, height=0)
        # Limpa os query params do Streamlit *depois* de usar para injetar o JS
        st.query_params.clear()
    # ----------------------------------------------------

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
    df_encerrados_filtrado = df_encerrados[~df_encerrados['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]

    tab1, tab2, tab3 = st.tabs(["Dashboard Completo", "Report Visual", "Evolução Semanal"])

    with tab1:
        info_messages = ["**Filtros e Regras Aplicadas:**", "- Grupos contendo 'RH' foram desconsiderados da análise.", "- A contagem de dias do chamado desconsidera o dia da sua abertura (prazo -1 dia)."]
        if not df_encerrados_filtrado.empty:
             info_messages.append("- Os chamados marcados como fechados no dia já foram excluídos das contagens principais e dos grupos correspondentes.")
        st.info("\n".join(info_messages))
        st.subheader("Análise de Antiguidade do Backlog Atual")
        texto_hora = f" (atualizado às {hora_atualizacao_str})" if hora_atualizacao_str else ""
        st.markdown(f"<p style='font-size: 0.9em; color: #666;'><i>Data de referência: {data_atual_str}{texto_hora}</i></p>", unsafe_allow_html=True)
        if not df_aging.empty:
            total_chamados = len(df_aging)
            total_fechados = len(df_encerrados_filtrado)
            col_spacer1, col_total, col_fechados, col_spacer2 = st.columns([1, 1.5, 1.5, 1])
            with col_total: st.markdown(f"""<div class="metric-box"><span class="value">{total_chamados}</span><span class="label">Total de Chamados Abertos</span></div>""", unsafe_allow_html=True)
            with col_fechados:
                valor_fechados = total_fechados if total_fechados > 0 else "N/A"
                card_fechados_html = f"""<a href="?scroll_to=encerrados" target="_self" class="metric-box" style="text-decoration: none;"><span class="value">{valor_fechados}</span><span class="label">Chamados Fechados no Dia</span></a>"""
                st.markdown(card_fechados_html, unsafe_allow_html=True)
            st.markdown("---")
            aging_counts = df_aging['Faixa de Antiguidade'].value_counts().reset_index()
            aging_counts.columns = ['Faixa de Antiguidade', 'Quantidade']
            ordem_faixas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
            todas_as_faixas = pd.DataFrame({'Faixa de Antiguidade': ordem_faixas})
            aging_counts = pd.merge(todas_as_faixas, aging_counts, on='Faixa de Antiguidade', how='left').fillna(0).astype({'Quantidade': int})
            aging_counts['Faixa de Antiguidade'] = pd.Categorical(aging_counts['Faixa de Antiguidade'], categories=ordem_faixas, ordered=True)
            aging_counts = aging_counts.sort_values('Faixa de Antiguidade')
            if 'faixa_selecionada' not in st.session_state: st.session_state.faixa_selecionada = "0-2 dias"
            cols = st.columns(len(ordem_faixas))
            for i, row in aging_counts.iterrows():
                with cols[i]:
                    faixa_encoded = quote(row['Faixa de Antiguidade'])
                    card_html = f"""<a href="?faixa={faixa_encoded}&scroll=true" target="_self" class="metric-box"><span class="value">{row['Quantidade']}</span><span class="label">{row['Faixa de Antiguidade']}</span></a>"""
                    st.markdown(card_html, unsafe_allow_html=True)
        else: st.warning("Sem dados para análise de antiguidade.")
        st.markdown(f"<h3>Comparativo de Backlog: Atual vs. 15 Dias Atrás <span style='font-size: 0.6em; color: #666; font-weight: normal;'>({data_15dias_str})</span></h3>", unsafe_allow_html=True)
        df_comparativo = processar_dados_comparativos(df_atual_filtrado.copy(), df_15dias_filtrado.copy())
        df_comparativo['Status'] = df_comparativo.apply(get_status, axis=1)
        df_comparativo.rename(columns={'Atribuir a um grupo': 'Grupo Atribuído'}, inplace=True)
        df_comparativo = df_comparativo[['Grupo Atribuído', '15 Dias Atrás', 'Atual', 'Diferença', 'Status']]
        st.dataframe(df_comparativo.set_index('Grupo Atribuído').style.map(lambda val: 'background-color: #ffcccc' if val > 0 else ('background-color: #ccffcc' if val < 0 else 'background-color: white'), subset=['Diferença']), use_container_width=True)
        st.markdown("---")
        st.markdown(f"<h3 id='chamados-encerrados'>Chamados Encerrados no Dia <span style='font-size: 0.6em; color: #666; font-weight: normal;'>({data_atual_str})</span></h3>", unsafe_allow_html=True)
        if not df_encerrados_filtrado.empty:
            df_encerrados_display = df_encerrados_filtrado[['ID do ticket', 'Descrição', 'Atribuir a um grupo']].rename(columns={'Atribuir a um grupo': 'Grupo Atribuído'})
            st.data_editor(df_encerrados_display, hide_index=True, disabled=True, use_container_width=True)
        else: st.info("Arquivo não carregado.")
        if not df_aging.empty:
            st.markdown("---")
            st.markdown("<h3 id='detalhar-e-buscar-chamados'>Detalhar e Buscar Chamados</h3>", unsafe_allow_html=True)
            st.info('Marque "Contato" se já falou com o usuário e a solicitação continua pendente. Use "Observações" para anotações.')
            ordem_faixas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
            if 'faixa_selecionada' not in st.session_state:
                 st.session_state.faixa_selecionada = "0-2 dias"
            st.selectbox("Detalhar por faixa de idade:", options=ordem_faixas, key='faixa_selecionada')
            faixa_atual = st.session_state.faixa_selecionada
            filtered_df = df_aging[df_aging['Faixa de Antiguidade'] == faixa_atual].copy()
            if not filtered_df.empty:
                def highlight_row(row): return ['background-color: #fff8c4'] * len(row) if row['Contato'] else [''] * len(row)
                filtered_df['Contato'] = filtered_df['ID do ticket'].apply(lambda id: str(id) in st.session_state.contacted_tickets)
                filtered_df['Observações'] = filtered_df['ID do ticket'].apply(lambda id: st.session_state.observations.get(str(id), ''))
                st.session_state.last_filtered_df = filtered_df.reset_index(drop=True)
                colunas_para_exibir_renomeadas = {'Contato': 'Contato', 'ID do ticket': 'ID do ticket', 'Descrição': 'Descrição', 'Atribuir a um grupo': 'Grupo Atribuído', 'Dias em Aberto': 'Dias em Aberto', 'Data de criação': 'Data de criação', 'Observações': 'Observações'}
                st.data_editor(st.session_state.last_filtered_df.rename(columns=colunas_para_exibir_renomeadas)[list(colunas_para_exibir_renomeadas.values())].style.apply(highlight_row, axis=1), use_container_width=True, hide_index=True, disabled=['ID do ticket', 'Descrição', 'Grupo Atribuído', 'Dias em Aberto', 'Data de criação'], key='ticket_editor', on_change=sync_ticket_data)
            else: st.info("Não há chamados nesta categoria.")
            st.subheader("Buscar Chamados por Grupo")
            lista_grupos = sorted(df_aging['Atribuir a um grupo'].dropna().unique())
            grupo_selecionado = st.selectbox("Busca por grupo:", options=lista_grupos)
            if grupo_selecionado:
                resultados_busca = df_aging[df_aging['Atribuir a um grupo'] == grupo_selecionado].copy()
                if 'Data de criação' in resultados_busca.columns:
                    resultados_busca['Data de criação'] = resultados_busca['Data de criação'].dt.strftime('%d/%m/%Y')
                st.write(f"Encontrados {len(resultados_busca)} chamados para '{grupo_selecionado}':")
                colunas_para_exibir_busca = ['ID do ticket', 'Descrição', 'Dias em Aberto', 'Data de criação']
                st.data_editor(resultados_busca[[col for col in colunas_para_exibir_busca if col in resultados_busca.columns]], use_container_width=True, hide_index=True, disabled=True)
    with tab2:
        # ... (Código da Tab 2 sem alterações)
    with tab3:
        # ... (Código da Tab 3 sem alterações)
except Exception as e:
    st.error(f"Erro ao carregar dados: {e}")
    st.exception(e)

st.markdown("---")
st.markdown("""<p style='text-align: center; color: #666; font-size: 0.9em;'>v0.9.18-711 | Dashboard em desenvolvimento.</p>""", unsafe_allow_html=True)
