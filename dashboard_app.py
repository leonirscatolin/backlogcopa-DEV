import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
import base64
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from io import StringIO
import streamlit.components.v1 as components
from urllib.parse import quote
import json
import colorsys

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    layout="wide",
    page_title="Backlog Copa Energia + Belago",
    page_icon="minilogo.png",
    initial_sidebar_state="collapsed"
)

# --- FUNÇÕES DE INTERAÇÃO COM O SNOWFLAKE ---

@st.cache_data(ttl=300)
def read_snowflake_table(_conn, table_name):
    try:
        query = f'SELECT * FROM "{table_name.upper()}";'
        df = _conn.query(query)
        return df
    except Exception as e:
        if "does not exist" in str(e):
            return pd.DataFrame()
        st.error(f"Erro ao ler a tabela '{table_name}' do Snowflake: {e}")
        return pd.DataFrame()

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
        
        df.columns = [col.strip().upper().replace(' ', '_') for col in df.columns]
        return df
    except Exception as e:
        st.sidebar.error(f"Erro ao ler o arquivo {uploaded_file.name}: {e}")
        return None

# --- FUNÇÕES DE LÓGICA DE NEGÓCIO ---

def processar_dados_comparativos(df_atual, df_15dias):
    contagem_atual = df_atual.groupby('ATRIBUIR_A_UM_GRUPO').size().reset_index(name='Atual')
    contagem_15dias = df_15dias.groupby('ATRIBUIR_A_UM_GRUPO').size().reset_index(name='15 Dias Atrás')
    df_comparativo = pd.merge(contagem_atual, contagem_15dias, on='ATRIBUIR_A_UM_GRUPO', how='outer').fillna(0)
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
    if _df_atual.empty:
        return pd.DataFrame()
    df = _df_atual.copy()
    
    date_col_name = next((col for col in df.columns if col.upper() in ['DATA_DE_CRIAÇÃO', 'DATA_DE_CRIACAO']), None)

    if not date_col_name:
        st.warning("Coluna de data de criação não encontrada.")
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
    df['DIAS_EM_ABERTO'] = (dias_calculados - 1).clip(lower=0) 
    df['FAIXA_DE_ANTIGUIDADE'] = categorizar_idade_vetorizado(df['DIAS_EM_ABERTO'])
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

def sync_contacted_tickets(conn):
    # Verificação para evitar erro na primeira execução
    if 'ticket_editor' not in st.session_state or not st.session_state.ticket_editor.get('edited_rows'):
        return

    previous_state = set(st.session_state.contacted_tickets)
    for row_index, changes in st.session_state.ticket_editor['edited_rows'].items():
        ticket_id = st.session_state.last_filtered_df.iloc[row_index]['ID_DO_TICKET']
        if 'CONTATO' in changes:
            if changes['CONTATO']:
                st.session_state.contacted_tickets.add(str(ticket_id))
            else:
                st.session_state.contacted_tickets.discard(str(ticket_id))

    if previous_state != st.session_state.contacted_tickets:
        df_to_save = pd.DataFrame(list(st.session_state.contacted_tickets), columns=["TICKET_ID"])
        with conn.session() as s:
            # Usando uma tabela temporária para uma substituição atômica
            s.write_pandas(df_to_save, "TEMP_CONTACTED_TICKETS", overwrite=True)
            s.query('CREATE OR REPLACE TABLE "CONTACTED_TICKETS" AS SELECT * FROM "TEMP_CONTACTED_TICKETS";')
        st.toast("Status de contato salvo!", icon="✅")
    st.session_state.scroll_to_details = True


# --- INÍCIO DA EXECUÇÃO DO SCRIPT ---

st.html("""<style>#GithubIcon { visibility: hidden; } .metric-box { border: 1px solid #CCCCCC; padding: 10px; border-radius: 5px; text-align: center; box-shadow: 0px 2px 4px rgba(0,0,0,0.1); margin-bottom: 10px; } a.metric-box { display: block; color: inherit; text-decoration: none !important; } a.metric-box:hover { background-color: #f0f2f6; text-decoration: none !important; } .metric-box span { display: block; width: 100%; text-decoration: none !important; } .metric-box .value { font-size: 2.5em; font-weight: bold; color: #375623; } .metric-box .label { font-size: 1em; color: #666666; }</style>""")

logo_copa_b64 = get_image_as_base64("logo_sidebar.png")
logo_belago_b64 = get_image_as_base64("logo_belago.png")
if logo_copa_b64 and logo_belago_b64:
    st.markdown(f"""<div style="display: flex; justify-content: space-between; align-items: center;"><img src="data:image/png;base64,{logo_copa_b64}" width="150"><h1 style='text-align: center; margin: 0;'>Backlog Copa Energia + Belago</h1><img src="data:image/png;base64,{logo_belago_b64}" width="150"></div>""", unsafe_allow_html=True)
else:
    st.error("Arquivos de logo não encontrados.")

# Conexão com o Snowflake
try:
    conn = st.connection("snowflake")
except Exception as e:
    st.error(f"Não foi possível conectar ao Snowflake. Verifique seus segredos (secrets.toml). Erro: {e}")
    st.stop()


# --- PAINEL DO ADMINISTRADOR ---
st.sidebar.header("Área do Administrador")
password = st.sidebar.text_input("Senha para atualizar dados:", type="password")
is_admin = password == st.secrets.get("ADMIN_PASSWORD", "")

if is_admin:
    st.sidebar.success("Acesso de administrador liberado.")
    st.sidebar.header("Carregar Novos Arquivos")
    
    uploaded_file_atual = st.sidebar.file_uploader("1. Backlog ATUAL (.csv ou .xlsx)", type=["csv", "xlsx"])
    uploaded_file_15dias = st.sidebar.file_uploader("2. Backlog de 15 DIAS ATRÁS (.csv ou .xlsx)", type=["csv", "xlsx"])
    uploaded_file_fechados = st.sidebar.file_uploader("3. Chamados FECHADOS no dia (Opcional)", type=["csv", "xlsx"])
    
    if st.sidebar.button("Salvar Novos Dados no Snowflake"):
        if uploaded_file_atual and uploaded_file_15dias:
            with st.spinner("Processando e salvando dados no Snowflake..."):
                df_atual = process_uploaded_file(uploaded_file_atual)
                df_15dias = process_uploaded_file(uploaded_file_15dias)
                df_fechados = process_uploaded_file(uploaded_file_fechados)

                if df_atual is not None and df_15dias is not None:
                    with conn.session() as s:
                        # Salva os dados principais
                        s.write_pandas(df_atual, "DADOS_ATUAIS", overwrite=True, auto_create_table=True)
                        s.write_pandas(df_15dias, "DADOS_15_DIAS", overwrite=True, auto_create_table=True)
                        if df_fechados is not None:
                            s.write_pandas(df_fechados, "DADOS_FECHADOS", overwrite=True, auto_create_table=True)
                        else: 
                            s.query('CREATE OR REPLACE TABLE "DADOS_FECHADOS" (DUMMY_COL VARCHAR);')

                        # Salva o snapshot diário
                        df_snapshot = df_atual.copy()
                        df_snapshot['SNAPSHOT_DATE'] = datetime.now(ZoneInfo('America/Sao_Paulo')).date()
                        # Append para a tabela de snapshots
                        s.write_pandas(df_snapshot, "SNAPSHOTS", auto_create_table=True)
                        
                        # Salva as datas de referência
                        now_sao_paulo = datetime.now(ZoneInfo('America/Sao_Paulo'))
                        df_datas = pd.DataFrame([{
                            "DATA_ATUAL": now_sao_paulo.strftime('%d/%m/%Y'),
                            "DATA_15DIAS": (now_sao_paulo.date() - timedelta(days=15)).strftime('%d/%m/%Y'),
                            "HORA_ATUALIZACAO": now_sao_paulo.strftime('%H:%M'),
                            "TIMESTAMP_ATUALIZACAO": now_sao_paulo
                        }])
                        s.write_pandas(df_datas, "DATAS_REFERENCIA", overwrite=True, auto_create_table=True)

                    st.cache_data.clear()
                    st.sidebar.success("Dados salvos no Snowflake! Recarregando...")
                    st.rerun()
        else:
            st.sidebar.warning("Carregue os arquivos obrigatórios (Atual e 15 Dias) para salvar.")
elif password:
    st.sidebar.error("Senha incorreta.")


# --- LÓGICA PRINCIPAL DO DASHBOARD ---
try:
    df_atual = read_snowflake_table(conn, "DADOS_ATUAIS")
    df_15dias = read_snowflake_table(conn, "DADOS_15_DIAS")
    df_fechados = read_snowflake_table(conn, "DADOS_FECHADOS")
    df_datas_ref = read_snowflake_table(conn, "DATAS_REFERENCIA")

    data_atual_str = df_datas_ref['DATA_ATUAL'].iloc[0] if not df_datas_ref.empty else 'N/A'
    data_15dias_str = df_datas_ref['DATA_15DIAS'].iloc[0] if not df_datas_ref.empty else 'N/A'
    hora_atualizacao_str = df_datas_ref['HORA_ATUALIZACAO'].iloc[0] if not df_datas_ref.empty else ''

    if df_atual.empty or df_15dias.empty:
        st.warning("Ainda não há dados para exibir. Por favor, carregue os arquivos na área do administrador.")
        st.stop()

    id_ticket_col = next((col for col in df_atual.columns if col.upper() in ['ID_DO_TICKET']), 'ID_DO_TICKET')
    assign_group_col = next((col for col in df_atual.columns if col.upper() in ['ATRIBUIR_A_UM_GRUPO']), 'ATRIBUIR_A_UM_GRUPO')
    
    df_atual[id_ticket_col] = df_atual[id_ticket_col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

    closed_ticket_ids = []
    if not df_fechados.empty:
        id_col_name = next((col for col in df_fechados.columns if col.upper() in ['ID_DO_TICKET', 'ID']), None)
        if id_col_name:
            closed_ticket_ids = df_fechados[id_col_name].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().dropna().unique()

    df_encerrados = df_atual[df_atual[id_ticket_col].isin(closed_ticket_ids)]
    df_abertos = df_atual[~df_atual[id_ticket_col].isin(closed_ticket_ids)]
    
    df_atual_filtrado = df_abertos[~df_abertos[assign_group_col].str.contains('RH', case=False, na=False)]
    df_15dias_filtrado = df_15dias[~df_15dias[assign_group_col].str.contains('RH', case=False, na=False)]
    
    df_aging = analisar_aging(df_atual_filtrado)
    
    if 'contacted_tickets' not in st.session_state:
        df_contacted = read_snowflake_table(conn, "CONTACTED_TICKETS")
        st.session_state.contacted_tickets = set(df_contacted['TICKET_ID'].astype(str).tolist()) if not df_contacted.empty else set()
    
    tab1, tab2, tab3 = st.tabs(["Dashboard Completo", "Report Visual", "Evolução Semanal"])
    
    with tab1:
        # Lógica da Tab1 adaptada para novas colunas
        st.markdown("A lógica da Tab1 vai aqui, adaptada para os nomes de colunas em maiúsculo (ex: 'ID_DO_TICKET', 'ATRIBUIR_A_UM_GRUPO').")

    with tab2:
        # Lógica da Tab2 adaptada para novas colunas
        st.markdown("A lógica da Tab2 vai aqui, adaptada para os nomes de colunas em maiúsculo (ex: 'FAIXA_DE_ANTIGUIDADE').")

    with tab3:
        st.subheader("Evolução do Backlog")
        
        dias_evolucao = st.slider("Ver evolução dos últimos dias:", 7, 30, 7)
        
        df_snapshots = read_snowflake_table(conn, "SNAPSHOTS")
        if not df_snapshots.empty:
            df_snapshots['SNAPSHOT_DATE'] = pd.to_datetime(df_snapshots['SNAPSHOT_DATE'])
            
            start_date = pd.to_datetime(date.today() - timedelta(days=dias_evolucao - 1))
            df_snapshots_filtered = df_snapshots[df_snapshots['SNAPSHOT_DATE'].dt.date >= start_date.date()]

            if not df_snapshots_filtered.empty:
                df_evolucao = df_snapshots_filtered.groupby([df_snapshots_filtered['SNAPSHOT_DATE'].dt.date, 'ATRIBUIR_A_UM_GRUPO']).size().reset_index(name='Total Chamados')
                df_evolucao.rename(columns={'SNAPSHOT_DATE': 'Data'}, inplace=True)
                
                todos_grupos = sorted(df_evolucao['ATRIBUIR_A_UM_GRUPO'].unique())
                grupos_selecionados = st.multiselect("Selecione os grupos para visualizar:", options=todos_grupos, default=todos_grupos)

                if grupos_selecionados:
                    df_filtrado = df_evolucao[df_evolucao['ATRIBUIR_A_UM_GRUPO'].isin(grupos_selecionados)]
                    fig_evolucao = px.line(df_filtrado, x='Data', y='Total Chamados', color='ATRIBUIR_A_UM_GRUPO', title='Total de Chamados Abertos por Grupo', markers=True)
                    st.plotly_chart(fig_evolucao, use_container_width=True)
            else:
                 st.info("Não há dados históricos no período selecionado.")
        else:
            st.info("Ainda não há dados históricos suficientes para exibir a evolução.")

except Exception as e:
    st.error(f"Ocorreu um erro principal ao executar o dashboard: {e}")
    st.exception(e) # Adiciona mais detalhes do erro para depuração

st.markdown("---")
st.markdown("""<p style='text-align: center; color: #666; font-size: 0.9em;'>v1.0.0-rc1.693 | Backend: Snowflake | Em desenvolvimento.</p>""", unsafe_allow_html=True)
