# VERSÃO v0.9.20-729 (Base 0.9.7 + Fechados + Observações + Tab3 Eixo Correto + Limpeza NaN + Rodapé + Tab4 Layout Final + Read Robust)

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

# --- FUNÇÃO ATUALIZADA ---
@st.cache_data(ttl=300)
def read_github_file(_repo, file_path):
    try:
        content_file = _repo.get_contents(file_path)
        content_bytes = content_file.decoded_content

        # Se o arquivo no GitHub estiver literalmente vazio (0 bytes), retorna DataFrame vazio.
        if not content_bytes:
            # st.sidebar.warning(f"Arquivo '{file_path}' encontrado no GitHub, mas está vazio.") # Descomente se quiser o aviso
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
            # Arquivo decodificado mas vazio
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
# --- FIM DA FUNÇÃO ATUALIZADA ---

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
                # Tenta detectar encoding antes de ler com pandas
                try:
                    content_str = content_bytes.decode('utf-8')
                    detected_encoding = 'utf-8'
                except UnicodeDecodeError:
                    content_str = content_bytes.decode('latin-1')
                    detected_encoding = 'latin-1'
                 # Usa o delimitador ; por padrão, mas avisa se detectar ,
                sniffer = csv.Sniffer()
                try:
                    dialect = sniffer.sniff(content_str[:1024]) # Lê os primeiros 1024 bytes para detectar
                    delimiter = dialect.delimiter
                    if delimiter != ';':
                        st.sidebar.warning(f"Detectado delimitador '{delimiter}' no arquivo CSV. Usando '{delimiter}'.")
                except csv.Error:
                    delimiter = ';' # Mantém ; se a detecção falhar
                
                df = pd.read_csv(StringIO(content_str), delimiter=delimiter, dtype=dtype_spec, low_memory=False, on_bad_lines='warn')

            except Exception as read_err:
                 st.sidebar.error(f"Erro ao ler o arquivo CSV {uploaded_file.name}: {read_err}")
                 return None

        df.columns = df.columns.str.strip()
        df.dropna(how='all', inplace=True)

        output = StringIO()
        # Salva sempre como UTF-8 com ; para padronizar
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
        return pd.DataFrame()
    df[date_col_name] = pd.to_datetime(df[date_col_name], errors='coerce')
    linhas_invalidas = df[df[date_col_name].isna()]
    if not linhas_invalidas.empty:
        # Mostra apenas as primeiras 5 linhas inválidas para não poluir
        with st.expander(f"⚠️ Atenção: {len(linhas_invalidas)} chamados foram descartados por data inválida ou vazia."):
            st.dataframe(linhas_invalidas[['ID do ticket', date_col_name, 'Atribuir a um grupo']].head())
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
            # Tenta pegar o ID, tratando possível erro se o dataframe foi reordenado/filtrado
            ticket_id_obj = st.session_state.last_filtered_df.iloc[row_index]['ID do ticket']
            ticket_id = str(ticket_id_obj) if pd.notna(ticket_id_obj) else None
            if not ticket_id: continue # Pula se não conseguiu ID

            if 'Contato' in changes:
                current_contact_status = ticket_id in st.session_state.contacted_tickets
                new_contact_status = changes['Contato']
                if current_contact_status != new_contact_status:
                    if new_contact_status: st.session_state.contacted_tickets.add(ticket_id)
                    else: st.session_state.contacted_tickets.discard(ticket_id)
                    contact_changed = True
            if 'Observações' in changes:
                current_observation = st.session_state.observations.get(ticket_id, '')
                new_observation = changes['Observações'] if pd.notna(changes['Observações']) else '' # Trata NaN
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
             # Remove entradas vazias antes de salvar
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
        start_date = end_date - timedelta(days=max(dias_para_analisar, 10)) # Busca um pouco mais
        
        closed_ids_set = set(str(id_val) for id_val in closed_ticket_ids_list) # Garante que são strings
        
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
        # Pega os N dias únicos mais recentes, não apenas N arquivos
        unique_dates = sorted(list(set(d[0] for d in processed_dates)), reverse=True)[:dias_para_analisar]
        files_to_process = [f[1] for f in processed_dates if f[0] in unique_dates]


        for file_name in files_to_process:
             try:
                 date_str = file_name.replace("snapshots/backlog_", "").replace(".csv", "")
                 file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                 df_snapshot = read_github_file(_repo, file_name)
                 if not df_snapshot.empty and 'Atribuir a um grupo' in df_snapshot.columns:
                     df_snapshot_filtrado_rh = df_snapshot[~df_snapshot['Atribuir a um grupo'].str.contains('RH', case=False, na=False)].copy() # Adiciona copy
                     id_col_snapshot = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_snapshot_filtrado_rh.columns), None)
                     df_snapshot_final = df_snapshot_filtrado_rh 
                     if id_col_snapshot and closed_ids_set:
                         # Garante que a coluna ID é string antes de comparar
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
         # Agrupa novamente para garantir uma contagem única por dia/grupo se houver múltiplos uploads no mesmo dia
        df_consolidado = df_consolidado.groupby(['Data', 'Atribuir a um grupo'])['Total Chamados'].first().reset_index()
        return df_consolidado.sort_values(by=['Data', 'Atribuir a um grupo'])
        
    except GithubException as e:
        if e.status == 404: return pd.DataFrame()
        st.warning(f"Não foi possível listar snapshots: {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar evolução: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def find_closest_snapshot(_repo, current_report_date, target_date):
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


# ... (Restante do código das tabs 1, 2, 3 permanece igual) ...

# --- Código da Tab 4 com os ajustes finais ---
with tab4:
    st.subheader("Análise Semana vs Semana: Variação do Backlog por Grupo")
        
    current_report_date = None
    try:
        current_report_date = datetime.strptime(data_atual_str, "%d/%m/%Y").date()
    except ValueError:
        st.error("Não foi possível determinar a data de referência atual para a comparação semanal.")
        st.stop()
            
    target_start_date = current_report_date - timedelta(days=7)

    actual_start_date, start_snapshot_path = find_closest_snapshot(repo, current_report_date, target_start_date)

    if start_snapshot_path is None:
        st.warning(f"Não foi encontrado um snapshot de dados próximo a {target_start_date.strftime('%d/%m/%Y')} (7 dias antes) para realizar a comparação semanal.")
    else:
        df_inicio_raw = read_github_file(repo, start_snapshot_path)
            
        if df_inicio_raw.empty or 'Atribuir a um grupo' not in df_inicio_raw.columns:
             st.warning(f"O snapshot encontrado para {actual_start_date.strftime('%d/%m/%Y')} está vazio ou inválido.")
        else:
            df_inicio_filtrado = df_inicio_raw[~df_inicio_raw['Atribuir a um grupo'].str.contains('RH', case=False, na=False)].copy() # Adiciona .copy()
            id_col_inicio = next((col for col in ['ID do ticket', 'ID do Ticket', 'ID'] if col in df_inicio_filtrado.columns), None)
            if id_col_inicio:
                df_inicio_filtrado[id_col_inicio] = df_inicio_filtrado[id_col_inicio].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                # Remove fechados (do dia atual) que já poderiam estar no snapshot da semana anterior
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
                    st.markdown("<h3 style='text-align: center;'>Grupos que Precisam de Atenção</h3>", unsafe_allow_html=True) # Removido (Pareto)
                    
                if df_aumentos.empty:
                    st.success("🎉 Nenhum grupo apresentou aumento no backlog na última semana!")
                else:
                    # Caption Removida
                        
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

# --- FIM DA MODIFICAÇÃO (Tab 4) ---

except Exception as e:
    st.error(f"Ocorreu um erro ao carregar os dados: {e}")
    st.exception(e)

st.markdown("---")
st.markdown("""
<p style='text-align: center; color: #666; font-size: 0.9em; margin-bottom: 0;'>v0.9.20-728 | Este dashboard está em desenvolvimento.</p>
<p style='text-align: center; color: #666; font-size: 0.9em; margin-top: 0;'>Desenvolvido por Leonir Scatolin Junior</p>
""", unsafe_allow_html=True)
