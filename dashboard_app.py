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

# --- Configuração da Página ---
st.set_page_config(
    layout="wide",
    page_title="Backlog Copa Energia + Belago",
    page_icon="minilogo.png",
    initial_sidebar_state="collapsed"
)

# --- FUNÇÕES ---
# (Todas as funções anteriores permanecem inalteradas, omitidas para brevidade)
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
# ... (Restante das funções omitido)

# --- INÍCIO DA EXECUÇÃO DO SCRIPT ---
# (O código de configuração, CSS, cabeçalho e barra lateral permanece o mesmo - omitido para brevidade)
# ...

try:
    # ... (código de inicialização e leitura de dados permanece o mesmo) ...
    
    # ######################################################################
    # O CÓDIGO DA ABA 1 (DASHBOARD COMPLETO) PERMANECE EXATAMENTE O MESMO
    # ######################################################################
    
    with tab2:
        st.subheader("Resumo do Backlog Atual")
        if not df_aging.empty:
            # ... (código dos cards de resumo permanece o mesmo) ...
            
            st.markdown("---")
            st.subheader("Distribuição do Backlog por Grupo")
            
            orientation_choice = st.radio(
                "Orientação do Gráfico:", ["Vertical", "Horizontal"], index=1, horizontal=True
            )

            chart_data = df_aging.groupby(['Atribuir a um grupo', 'Faixa de Antiguidade']).size().reset_index(name='Quantidade')
            group_totals = chart_data.groupby('Atribuir a um grupo')['Quantidade'].sum().sort_values(ascending=False)
            ordem_faixas = ["0-2 dias", "3-5 dias", "6-10 dias", "11-20 dias", "21-29 dias", "30+ dias"]

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
                    category_orders={'Atribuir a um grupo': group_totals.index.tolist(), 'Faixa de Antiguidade': ordem_faixas},
                    color_discrete_map=color_map, text_auto=True
                )
                # ######################## ALTERAÇÃO AQUI ########################
                fig_stacked_bar.update_traces(textangle=0, textfont_size=12)
                fig_stacked_bar.update_layout(height=dynamic_height, yaxis={'categoryorder':'total ascending'}, legend_title_text='Antiguidade')
            
            else: # Vertical
                fig_stacked_bar = px.bar(
                    chart_data, x='Atribuir a um grupo', y='Quantidade',
                    color='Faixa de Antiguidade', title="Composição da Idade do Backlog por Grupo",
                    labels={'Quantidade': 'Qtd. de Chamados', 'Atribuir a um grupo': 'Grupo'},
                    # category_orders={'Atribuir a um grupo': group_totals.index.tolist(), 'Faixa de Antiguidade': ordem_faixas}, # <-- ORDENAÇÃO REMOVIDA PARA TESTE
                    color_discrete_map=color_map, text_auto=True
                )
                # ######################## ALTERAÇÃO AQUI ########################
                fig_stacked_bar.update_traces(textangle=0, textfont_size=12)
                fig_stacked_bar.update_layout(height=600, xaxis_title=None, xaxis_tickangle=-45, legend_title_text='Antiguidade')

            st.plotly_chart(fig_stacked_bar, use_container_width=True)
        else:
            st.warning("Nenhum dado para gerar o report visual.")

except Exception as e:
    st.error(f"Ocorreu um erro ao carregar os dados: {e}")
