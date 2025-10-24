# VERSÃO v0.9.20-713 (Base 0.9.7 + Fechados + Observações + Tab3 Nova c/ Avisos Ajustados)

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
        if not content.strip():
            return pd.DataFrame()
        df = pd.read_csv(StringIO(content), delimiter=';', encoding='utf-8', dtype={'ID do ticket': str, 'ID do Ticket': str})
        df.columns = df.columns.str.strip()
        return df
    except GithubException as e:
        if e.status == 404:
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
    st.session_state.scroll_to_details = True # <-- Lógica de scroll original mantida


@st.cache_data(ttl=3600)
def carregar_dados_evolucao(_repo, closed_ticket_ids_list, dias_para_analisar=7):
    try:
        all_files_content = _repo.get_contents("snapshots")
        all_files = [f.path for f in all_files_content]
        df_evolucao_list = []
        end_date = date.today()
        start_date = end_date - timedelta(days=dias_para_analisar - 1)
        
        closed_ids_set = set(closed_ticket_ids_list)

        for file_name in all_files:
            if file_name.startswith("snapshots/backlog_") and file_name.endswith(".csv"):
                try:
                    date_str = file_name.replace("snapshots/backlog_", "").replace(".csv", "")
                    file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if start_date <= file_date <= end_date:
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
                except ValueError:
                    continue
                except Exception:
                    continue
        if not df_evolucao_list:
            return pd.DataFrame()
        df_consolidado = pd.concat(df_evolucao_list, ignore_index=True)
        return df_consolidado.sort_values(by=['Data', 'Atribuir a um grupo'])
    except GithubException as e:
        if e.status == 404: return pd.DataFrame()
        st.warning(f"Não foi possível carregar snapshots: {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar evolução: {e}")
        return pd.DataFrame()


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
    # Lógica de carregamento de "contacted_tickets" (Original do 0.9.7)
    if 'contacted_tickets' not in st.session_state:
        try:
            file_content = repo.get_contents("contacted_tickets.json").decoded_content.decode("utf-8")
            st.session_state.contacted_tickets = set(json.loads(file_content))
        except GithubException as e:
            if e.status == 404: st.session_state.contacted_tickets = set()
            else: st.error(f"Erro ao carregar o estado dos tickets: {e}"); st.session_state.contacted_tickets = set()

    # Carregamento das 'observations'
    if 'observations' not in st.session_state:
        st.session_state.observations = read_github_json_dict(repo, "ticket_observations.json")
    
    # Lógica de scroll/query_params (Original do 0.9.7)
    needs_scroll = "scroll" in st.query_params
    if "faixa" in st.query_params:
        faixa_from_url = st.query_params.get("faixa")
        ordem_faixas_validas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]
        if faixa_from_url in ordem_faixas_validas:
                st.session_state.faixa_selecionada = faixa_from_url
    if "scroll" in st.query_params or "faixa" in st.query_params:
        st.query_params.clear()
    
    # Carregamento dos dados (Original do 0.9.7)
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
    
    # Cálculo de IDs Fechados (Original do 0.9.7 - necessário para as novas features)
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
    
    # Definição de 'df_encerrados_filtrado' e 'df_evolucao'
    df_encerrados_filtrado = df_encerrados[~df_encerrados['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]
    
    tab1, tab2, tab3 = st.tabs(["Dashboard Completo", "Report Visual", "Evolução Semanal"])
    
    with tab1:
        info_messages = ["**Filtros e Regras Aplicadas:**", "- Grupos contendo 'RH' foram desconsiderados da análise.", "- A contagem de dias do chamado desconsidera o dia da sua abertura (prazo -1 dia)."]
        if not df_encerrados.empty:
            # Texto ajustado para usar a contagem de df_encerrados_filtrado
            info_messages.append(f"- **{len(df_encerrados_filtrado)} chamados fechados no dia** (exceto RH) foram deduzidos das contagens principais.")
        st.info("\n".join(info_messages))
        st.subheader("Análise de Antiguidade do Backlog Atual")
        texto_hora = f" (atualizado às {hora_atualizacao_str})" if hora_atualizacao_str else ""
        st.markdown(f"<p style='font-size: 0.9em; color: #666;'><i>Data de referência: {data_atual_str}{texto_hora}</i></p>", unsafe_allow_html=True)
        if not df_aging.empty:
            
            # Cards de Métrica (Total + Fechados)
            total_chamados = len(df_aging)
            total_fechados = len(df_encerrados_filtrado)
            col_spacer1, col_total, col_fechados, col_spacer2 = st.columns([1, 1.5, 1.5, 1])
            with col_total: 
                st.markdown(f"""<div class="metric-box"><span class="value">{total_chamados}</span><span class="label">Total de Chamados Abertos</span></div>""", unsafe_allow_html=True)
            with col_fechados:
                valor_fechados = total_fechados if total_fechados > 0 else "N/A"
                card_fechados_html = f"""<div class="metric-box"><span class="value">{valor_fechados}</span><span class="label">Chamados Fechados no Dia</span></div>"""
                st.markdown(card_fechados_html, unsafe_allow_html=True)
            
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
                    # Lógica de link/scroll original do 0.9.7
                    card_html = f"""<a href="?faixa={faixa_encoded}&scroll=true" target="_self" class="metric-box"><span class="value">{row['Quantidade']}</span><span class="label">{row['Faixa de Antiguidade']}</span></a>"""
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
        
        # ==========================================================
        # INÍCIO DA MODIFICAÇÃO (Mensagem de Chamados Encerrados)
        # ==========================================================
        if df_fechados.empty:
            st.info("O arquivo de chamados encerrados ainda não foi carregado.")
        elif not df_encerrados_filtrado.empty:
            st.data_editor(df_encerrados_filtrado[['ID do ticket', 'Descrição', 'Atribuir a um grupo']], hide_index=True, disabled=True, use_container_width=True)
        else:
            # Caso o arquivo de fechados exista, mas os IDs não batam ou sejam todos RH
            st.info("O arquivo de chamados encerrados do dia ainda não foi carregado.")
        # ==========================================================
        # FIM DA MODIFICAÇÃO
        # ==========================================================

        if not df_aging.empty:
            st.markdown("---")
            st.subheader("Detalhar e Buscar Chamados")
            # Info alterada para incluir 'Observações'
            st.info('Marque "Contato" se já falou com o usuário e a solicitação continua pendente. Use "Observações" para anotações.')
            
            # Lógica de scroll original do 0.9.7
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
                
                # Inclusão da coluna 'Observações' no data_editor
                filtered_df['Contato'] = filtered_df['ID do ticket'].apply(lambda id: str(id) in st.session_state.contacted_tickets)
                filtered_df['Observações'] = filtered_df['ID do ticket'].apply(lambda id: st.session_state.observations.get(str(id), '')) # <-- ADICIONADO
                
                st.session_state.last_filtered_df = filtered_df.reset_index(drop=True)
                
                # 'Observações' adicionada à lista
                colunas_para_exibir_renomeadas = {
                    'Contato': 'Contato', 
                    'ID do ticket': 'ID do ticket', 
                    'Descrição': 'Descrição', 
                    'Atribuir a um grupo': 'Grupo Atribuído', 
                    'Dias em Aberto': 'Dias em Aberto', 
                    'Data de criação': 'Data de criação', 
                    'Observações': 'Observações' # <-- ADICIONADO
                }
                
                st.data_editor(
                    st.session_state.last_filtered_df.rename(columns=colunas_para_exibir_renomeadas)[list(colunas_para_exibir_renomeadas.values())].style.apply(highlight_row, axis=1),
                    use_container_width=True, 
                    hide_index=True, 
                    disabled=['ID do ticket', 'Descrição', 'Grupo Atribuído', 'Dias em Aberto', 'Data de criação'], # 'Observações' é editável
                    key='ticket_editor', 
                    on_change=sync_ticket_data # <-- ATUALIZADO
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
        # Tab 2 mantida EXATAMENTE como no código 0.9.7
        st.subheader("Resumo do Backlog Atual")
        if not df_aging.empty:
            total_chamados = len(df_aging)
            _, col_total_tab2, _ = st.columns([2, 1.5, 2])
            with col_total_tab2: st.markdown( f"""<div class="metric-box"><span class="value">{total_chamados}</span><span class="label">Total de Chamados</span></div>""", unsafe_allow_html=True )
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
                with cols_tab2[i]: st.markdown( f"""<div class="metric-box"><span class="value">{row['Quantidade']}</span><span class="label">{row['Faixa de Antiguidade']}</span></div>""", unsafe_allow_html=True )
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

    # ==========================================================
    # INÍCIO DA MODIFICAÇÃO (Avisos da Tab 3)
    # ==========================================================
    with tab3:
        st.subheader("Evolução do Backlog")
        dias_evolucao = st.slider("Ver evolução dos últimos dias:", min_value=7, max_value=30, value=7, key="slider_evolucao")
        
        # Recalcula os dados da evolução com base no slider
        df_evolucao_tab3 = carregar_dados_evolucao(repo, closed_ticket_ids_list=closed_ticket_ids, dias_para_analisar=dias_evolucao)
        
        if not df_evolucao_tab3.empty:
            
            # Aviso 1: Para o gráfico de Total Geral
            st.info("Esta visualização ainda está coletando dados históricos. Utilize as outras abas como referência principal por enquanto.")
            
            df_total_diario = df_evolucao_tab3.groupby('Data')['Total Chamados'].sum().reset_index()
            df_total_diario = df_total_diario.sort_values('Data')
            fig_total_evolucao = px.area(
                df_total_diario,
                x='Data',
                y='Total Chamados',
                title='Evolução do Total Geral de Chamados Abertos',
                markers=True,
                labels={"Data": "Data", "Total Chamados": "Total Geral de Chamados"}
            )
            fig_total_evolucao.update_layout(height=400)
            st.plotly_chart(fig_total_evolucao, use_container_width=True)
            
            st.markdown("---")
            
            # Aviso 2: Para o gráfico de Evolução por Grupo
            st.info("Esta visualização já filtra os chamados fechados e permite filtrar grupos clicando 2x na legenda.")

            # Gráfico de linhas sem o multiselect
            df_filtrado_display = df_evolucao_tab3.rename(columns={'Atribuir a um grupo': 'Grupo Atribuído'})
            fig_evolucao_grupo = px.line(
                df_filtrado_display.sort_values('Data'),
                x='Data',
                y='Total Chamados',
                color='Grupo Atribuído',
                title='Evolução por Grupo',
                markers=True,
                labels={ "Data": "Data", "Total Chamados": "Nº de Chamados", "Grupo Atribuído": "Grupo" }
            )
            fig_evolucao_grupo.update_layout(height=600)
            st.plotly_chart(fig_evolucao_grupo, use_container_width=True)
            
        else: st.info("Ainda não há dados históricos suficientes.")
    # ==========================================================
    # FIM DA MODIFICAÇÃO
    # ==========================================================

except Exception as e:
    st.error(f"Ocorreu um erro ao carregar os dados: {e}")
    st.exception(e)

st.markdown("---")
# Rodapé atualizado para a versão solicitada
st.markdown("""<p style='text-align: center; color: #666; font-size: 0.9em;'>v0.9.20-713 | Este dashboard está em desenvolvimento.</p>""", unsafe_allow_html=True)
