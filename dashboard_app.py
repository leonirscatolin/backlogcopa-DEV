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
        auth = Auth.Token(st.secrets["GITHUB_TOKEN"])
        g = Github(auth=auth)
        return g.get_repo("leonirscatolin/dashboard-backlog")
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
        with st.expander(f"⚠️ Atenção: {len(linhas_invalidas)} chamados foram descartados por data inválida ou vazia. Clique para ver exemplos:"):
            st.write("Estas são algumas das linhas com datas que não puderam ser reconhecidas:")
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
    previous_state = set(st.session_state.contacted_tickets)
    for row_index, changes in st.session_state.ticket_editor['edited_rows'].items():
        ticket_id = st.session_state.last_filtered_df.iloc[row_index]['ID do ticket']
        if 'Contato' in changes:
            if changes['Contato']: st.session_state.contacted_tickets.add(ticket_id)
            else: st.session_state.contacted_tickets.discard(ticket_id)

    if previous_state != st.session_state.contacted_tickets:
        data_to_save = list(st.session_state.contacted_tickets)
        json_content = json.dumps(data_to_save, indent=4)
        commit_msg = f"Atualizando tickets contatados em {datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')}"
        update_github_file(st.session_state.repo, "contacted_tickets.json", json_content.encode('utf-8'), commit_msg)
    st.session_state.scroll_to_details = True

st.html("""
    <style>
        #GithubIcon { visibility: hidden; }
        .metric-box { border: 1px solid #CCCCCC; padding: 10px; border-radius: 5px; text-align: center; box-shadow: 0px 2px 4px rgba(0,0,0,0.1); margin-bottom: 10px; }
        a.metric-box { display: block; color: inherit; text-decoration: none !important; }
        a.metric-box:hover { background-color: #f0f2f6; text-decoration: none !important; }
        .metric-box span { display: block; width: 100%; text-decoration: none !important; }
        .metric-box .value { font-size: 2.5em; font-weight: bold; color: #375623; }
        .metric-box .label { font-size: 1em; color: #666666; }
    </style>
""")

logo_copa_b64 = get_image_as_base64("logo_sidebar.png")
logo_belago_b64 = get_image_as_base64("logo_belago.png")
if logo_copa_b64 and logo_belago_b64:
    st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <img src="data:image/png;base64,{logo_copa_b64}" width="150">
            <h1 style='text-align: center; margin: 0;'>Backlog Copa Energia + Belago</h1>
            <img src="data:image/png;base64,{logo_belago_b64}" width="150">
        </div>
    """, unsafe_allow_html=True)
else:
    st.error("Arquivos de logo não encontrados.")

st.sidebar.header("Área do Administrador")
password = st.sidebar.text_input("Senha para atualizar dados:", type="password")
is_admin = password == st.secrets.get("ADMIN_PASSWORD", "")
repo = get_github_repo()
st.session_state.repo = repo 

if is_admin:
    st.sidebar.success("Acesso de administrador liberado.")
    st.sidebar.header("Carregar Novos Arquivos")
    
    file_types = ["csv", "xlsx"]
    uploaded_file_atual = st.sidebar.file_uploader("1. Backlog ATUAL", type=file_types)
    uploaded_file_15dias = st.sidebar.file_uploader("2. Backlog de 15 DIAS ATRÁS", type=file_types)
    uploaded_file_fechados = st.sidebar.file_uploader("3. Chamados FECHADOS no dia (Opcional)", type=file_types)
    
    if st.sidebar.button("Salvar Novos Dados no Site"):
        if uploaded_file_atual and uploaded_file_15dias:
            with st.spinner("Processando e salvando arquivos..."):
                commit_msg = f"Dados atualizados em {datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')}"
                
                content_atual = process_uploaded_file(uploaded_file_atual)
                content_15dias = process_uploaded_file(uploaded_file_15dias)
                content_fechados = process_uploaded_file(uploaded_file_fechados)

                if content_atual is not None and content_15dias is not None:
                    update_github_file(repo, "dados_atuais.csv", content_atual, commit_msg)
                    update_github_file(repo, "dados_15_dias.csv", content_15dias, commit_msg)
                    
                    if content_fechados is not None:
                        update_github_file(repo, "dados_fechados.csv", content_fechados, commit_msg)
                    else:
                        update_github_file(repo, "dados_fechados.csv", b"", commit_msg)

                    data_do_upload = date.today()
                    data_arquivo_15dias = data_do_upload - timedelta(days=15) 
                    agora_correta = datetime.now(ZoneInfo("America/Sao_Paulo"))
                    hora_atualizacao = agora_correta.strftime('%H:%M')
                    
                    datas_referencia_content = (
                        f"data_atual:{data_do_upload.strftime('%d/%m/%Y')}\n" 
                        f"data_15dias:{data_arquivo_15dias.strftime('%d/%m/%Y')}\n" 
                        f"hora_atualizacao:{hora_atualizacao}"
                    )
                    update_github_file(repo, "datas_referencia.txt", datas_referencia_content.encode('utf-8'), commit_msg)

                    read_github_file.clear()
                    read_github_text_file.clear()
                    st.sidebar.success("Arquivos salvos! Forçando recarregamento...")
                    st.rerun()
        else:
            st.sidebar.warning("Carregue os arquivos obrigatórios (Atual e 15 Dias) para salvar.")
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
        st.warning("Ainda não há dados para exibir.")
    else:
        if 'ID do ticket' in df_atual.columns:
            df_atual['ID do ticket'] = df_atual['ID do ticket'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        closed_ticket_ids = []
        if not df_fechados.empty:
            id_column_name = None
            if 'ID do ticket' in df_fechados.columns: id_column_name = 'ID do ticket'
            elif 'ID do Ticket' in df_fechados.columns: id_column_name = 'ID do Ticket'
            elif 'ID' in df_fechados.columns: id_column_name = 'ID'
            
            if id_column_name:
                df_fechados[id_column_name] = df_fechados[id_column_name].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                df_fechados.dropna(subset=[id_column_name], inplace=True)
                closed_ticket_ids = df_fechados[id_column_name].unique()

        df_encerrados = df_atual[df_atual['ID do ticket'].isin(closed_ticket_ids)]
        df_abertos = df_atual[~df_atual['ID do ticket'].isin(closed_ticket_ids)]
        
        df_atual_filtrado = df_abertos[~df_abertos['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]
        df_15dias_filtrado = df_15dias[~df_15dias['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]
        
        df_aging = analisar_aging(df_atual_filtrado)
        
        tab1, tab2 = st.tabs(["Dashboard Completo", "Report Visual"])
        with tab1:
            info_messages = [
                "**Filtros e Regras Aplicadas:**",
                "- Grupos contendo 'RH' foram desconsiderados da análise.",
                "- A contagem de dias do chamado desconsidera o dia da sua abertura (prazo -1 dia)."
            ]
            if not df_encerrados.empty:
                info_messages.append(f"- **{len(df_encerrados)} chamados fechados no dia** foram deduzidos das contagens principais.")
            st.info("\n".join(info_messages))
            st.subheader("Análise de Antiguidade do Backlog Atual")
            texto_hora = f" (atualizado às {hora_atualizacao_str})" if hora_atualizacao_str else ""
            st.markdown(f"<p style='font-size: 0.9em; color: #666;'><i>Data de referência: {data_atual_str}{texto_hora}</i></p>", unsafe_allow_html=True)
            if not df_aging.empty:
                total_chamados = len(df_aging)
                _, col_total, _ = st.columns([2, 1.5, 2])
                with col_total: st.markdown(f"""<div class="metric-box"><span class="value">{total_chamados}</span><span class="label">Total de Chamados</span></div>""", unsafe_allow_html=True)
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
            if not df_encerrados.empty:
                df_encerrados_filtrado = df_encerrados[~df_encerrados['Atribuir a um grupo'].str.contains('RH', case=False, na=False)]
                st.data_editor(df_encerrados_filtrado[['ID do ticket', 'Descrição', 'Atribuir a um grupo']], hide_index=True, disabled=True, use_container_width=True)
            else:
                st.info("Nenhum chamado da lista de fechados foi encontrado no backlog atual ou o arquivo de encerrados não foi carregado.")
            if not df_aging.empty:
                st.markdown("---")
                st.subheader("Detalhar e Buscar Chamados")
                st.info('A caixa "Contato" sinaliza que o contato com o usuário foi realizado e a solicitação continua pendente.')
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
                    filtered_df['Contato'] = filtered_df['ID do ticket'].apply(lambda id: id in st.session_state.contacted_tickets)
                    st.session_state.last_filtered_df = filtered_df.reset_index(drop=True)
                    colunas_para_exibir = ['Contato', 'ID do ticket', 'Descrição', 'Atribuir a um grupo', 'Dias em Aberto', 'Data de criação']
                    st.data_editor(st.session_state.last_filtered_df[colunas_para_exibir].style.apply(highlight_row, axis=1), use_container_width=True, hide_index=True, disabled=['ID do ticket', 'Descrição', 'Atribuir a um grupo', 'Dias em Aberto', 'Data de criação'], key='ticket_editor', on_change=sync_contacted_tickets)
                else:
                    st.info("Não há chamados nesta categoria.")
                st.subheader("Buscar Chamados por Grupo")
                lista_grupos = sorted(df_aging['Atribuir a um grupo'].dropna().unique())
                grupo_selecionado = st.selectbox("Busca de chamados por grupo:", options=lista_grupos)
                if grupo_selecionado:
                    resultados_busca = df_aging[df_aging['Atribuir a um grupo'] == grupo_selecionado].copy()
                    resultados_busca['Data de criação'] = resultados_busca['Data de criação'].dt.strftime('%d/%m/%Y')
                    st.write(f"Encontrados {len(resultados_busca)} chamados para o grupo '{grupo_selecionado}':")
                    colunas_para_exibir_busca = ['ID do ticket', 'Descrição', 'Dias em Aberto', 'Data de criação']
                    st.data_editor(resultados_busca[colunas_para_exibir_busca], use_container_width=True, hide_index=True, disabled=True)

        with tab2:
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
                
                orientation_choice = st.radio(
                    "Orientação do Gráfico:", ["Vertical", "Horizontal"], 
                    index=0,
                    horizontal=True
                )

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
                palette = [
                    lighten_color(base_color, 0.85), lighten_color(base_color, 0.70),
                    lighten_color(base_color, 0.55), lighten_color(base_color, 0.40),
                    lighten_color(base_color, 0.20), base_color
                ]
                color_map = {faixa: color for faixa, color in zip(ordem_faixas, palette)}

                if orientation_choice == 'Horizontal':
                    num_groups = len(group_totals)
                    dynamic_height = max(500, num_groups * 30)

                    fig_stacked_bar = px.bar(
                        chart_data, x='Quantidade', y='Atribuir a um grupo', orientation='h',
                        color='Faixa de Antiguidade', title="Composição da Idade do Backlog por Grupo",
                        labels={'Quantidade': 'Qtd. de Chamados', 'Atribuir a um grupo': ''},
                        category_orders={'Atribuir a um grupo': sorted_new_labels, 'Faixa de Antiguidade': ordem_faixas},
                        color_discrete_map=color_map, text_auto=True
                    )
                    fig_stacked_bar.update_traces(textangle=0, textfont_size=12)
                    fig_stacked_bar.update_layout(height=dynamic_height, legend_title_text='Antiguidade')
                
                else:
                    fig_stacked_bar = px.bar(
                        chart_data, x='Atribuir a um grupo', y='Quantidade',
                        color='Faixa de Antiguidade', title="Composição da Idade do Backlog por Grupo",
                        labels={'Quantidade': 'Qtd. de Chamados', 'Atribuir a um grupo': 'Grupo'},
                        category_orders={'Atribuir a um grupo': sorted_new_labels, 'Faixa de Antiguidade': ordem_faixas},
                        color_discrete_map=color_map, text_auto=True
                    )
                    fig_stacked_bar.update_traces(textangle=0, textfont_size=12)
                    fig_stacked_bar.update_layout(height=600, xaxis_title=None, xaxis_tickangle=-45, legend_title_text='Antiguidade')

                st.plotly_chart(fig_stacked_bar, use_container_width=True)
            else:
                st.warning("Nenhum dado para gerar o report visual.")

except Exception as e:
    st.error(f"Ocorreu um erro ao carregar os dados: {e}")
