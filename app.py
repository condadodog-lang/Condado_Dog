import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
import math
import gspread
from google.oauth2.service_account import Credentials
from fpdf import FPDF
from io import BytesIO
import os

# --- CONFIGURAÇÃO DA PÁGINA E ESTILO CSS ---
st.set_page_config(
    page_title="Orçamento Condado Dog",
    page_icon="🐾",
    layout="centered"
)

# CSS (Com ADIÇÕES para corrigir o logo)
st.markdown("""
<style>
    :root {
        --primary-color: #F37F21; --secondary-color: #2A3A60; --background-color: #F0F2F6;
        --text-color: #333333; --widget-background: #FFFFFF; --green-color: #28a745;
    }
    .main { background-color: var(--background-color); }
    .block-container { padding-top: 4rem; padding-bottom: 3rem; padding-left: 2rem; padding-right: 2rem; }
    h1, h2, h3 { color: var(--secondary-color); font-weight: bold; text-align: center; }
    h1 { white-space: nowrap; }
    .subtitle { text-align: center; color: #555; font-size: 1.1em; margin-bottom: 1.5rem; }

    /* --- ADIÇÃO CRÍTICA PARA CORRIGIR O LOGO --- */
    div[data-testid="stVerticalBlock"] > div:nth-child(1) > div:nth-child(1) {
        border-radius: 0 !important;
        overflow: visible !important;
        background: none !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    
    div[data-testid="stImage"] {
        text-align: center;
        border-radius: 0 !important;
        overflow: visible !important;
        max-height: none !important;
        height: auto !important;
        width: auto !important;
    }

    div[data-testid="stImage"] img {
        border-radius: 0 !important;
        min-height: auto !important;
    }
    /* --- FIM DA ADIÇÃO CRÍTICA --- */

    .stButton>button {
        background-color: var(--primary-color); color: white; border-radius: 8px; height: 3em;
        width: 100%; border: none; font-weight: bold; transition: all 0.2s ease-in-out;
    }
    .stButton>button:hover { background-color: #d86d1a; box-shadow: 0px 4px 15px rgba(0,0,0,0.1); }
    .results-grid {
        display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;
    }
    .metric-box {
        background-color: var(--widget-background); border: 1px solid #E0E0E0; border-radius: 8px;
        padding: 20px; display: flex; flex-direction: column; justify-content: center;
        align-items: center; height: 120px; box-shadow: 0px 4px 15px rgba(0,0,0,0.05);
    }
    .metric-label { font-size: 16px; color: #555; margin-bottom: 8px; }
    .metric-value { font-size: 28px; font-weight: bold; color: var(--secondary-color); }
    .metric-value.green { color: var(--green-color); }
    .final-value-box {
        background-color: #e6f7ff; border: 2px solid #a8dadc; padding: 20px;
        border-radius: 8px; text-align: center;
    }
    .final-value-box .metric-label { font-size: 18px; }
    .final-value-box .metric-value { font-size: 36px; color: var(--primary-color); }
    .stAlert { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)


# --- CONEXÃO COM GOOGLE SHEETS ---
@st.cache_data(ttl=600)
def fetch_all_data_from_gsheet():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(creds)
        # --- LINHA ALTERADA ---
        spreadsheet = client.open("Condado Dog") # Alterado de "HotelCanino" para "Condado Dog"
        
        worksheet_diaria = spreadsheet.worksheet("Diária")
        df_diaria = pd.DataFrame(worksheet_diaria.get_all_records())
        cols_to_numeric_diaria = ['Quantidade de Diárias', 'Valor da Diária', 'Alta temporada']
        for col in cols_to_numeric_diaria:
            df_diaria[col] = pd.to_numeric(df_diaria[col], errors='coerce')
        df_diaria.dropna(subset=cols_to_numeric_diaria, inplace=True)

        worksheet_mensal = spreadsheet.worksheet("Mensal")
        df_mensal = pd.DataFrame(worksheet_mensal.get_all_records())
        cols_to_numeric_mensal = ['Vezes por semana', 'Valor']
        for col in cols_to_numeric_mensal:
            df_mensal[col] = pd.to_numeric(df_mensal[col], errors='coerce')
        
        worksheet_fidelidade = spreadsheet.worksheet("Mensal Fidelidade")
        df_fidelidade = pd.DataFrame(worksheet_fidelidade.get_all_records())
        cols_to_numeric_fidelidade = ['Vezes por semana', 'Valor']
        for col in cols_to_numeric_fidelidade:
            df_fidelidade[col] = pd.to_numeric(df_fidelidade[col], errors='coerce')
        
        return df_diaria, df_mensal, df_fidelidade
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- LÓGICAS DE CÁLCULO ---
def calcular_diarias_com_tolerancia(total_horas):
    if total_horas <= 0: return 0.25
    if total_horas <= 6: return 0.25
    dias_inteiros = math.floor(total_horas / 24)
    horas_residuais = total_horas % 24
    if horas_residuais == 0: return float(dias_inteiros)
    if horas_residuais <= 2: return float(dias_inteiros)
    if 2 < horas_residuais <= 6: return dias_inteiros + 0.25
    elif 6 < horas_residuais <= 12: return dias_inteiros + 0.50
    elif 12 < horas_residuais <= 18: return dias_inteiros + 0.75
    else: return dias_inteiros + 1.0

def calcular_orcamento_base(df, num_caes, entrada_dt, saida_dt, alta_temporada):
    if df.empty or num_caes <= 0: return None, None, None
    if saida_dt <= entrada_dt:
        st.warning("A data e hora de saída devem ser posteriores à data e hora de entrada.")
        return None, None, None
    duracao = saida_dt - entrada_dt
    total_horas = duracao.total_seconds() / 3600
    qtd_diarias_cobradas = calcular_diarias_com_tolerancia(total_horas)
    dias_para_lookup = int(qtd_diarias_cobradas)
    if dias_para_lookup == 0: dias_para_lookup = 1
    coluna_preco = 'Alta temporada' if alta_temporada else 'Valor da Diária'
    if dias_para_lookup > df['Quantidade de Diárias'].max():
        valor_diaria = df.sort_values('Quantidade de Diárias', ascending=False).iloc[0][coluna_preco]
    else:
        preco_row = df[df['Quantidade de Diárias'] == dias_para_lookup]
        if not preco_row.empty:
            valor_diaria = preco_row.iloc[0][coluna_preco]
        else:
            preco_row = df[df['Quantidade de Diárias'] <= dias_para_lookup].sort_values('Quantidade de Diárias', ascending=False).iloc[0]
            valor_diaria = preco_row[coluna_preco]
    valor_total = num_caes * qtd_diarias_cobradas * valor_diaria
    return qtd_diarias_cobradas, valor_diaria, valor_total

def calcular_desconto_mensalista(entrada_dt, saida_dt, dias_plano_daycare, df_plano, num_caes):
    if not dias_plano_daycare or df_plano.empty: return 0, 0
    vezes_por_semana = len(dias_plano_daycare)
    plano_row = df_plano[df_plano['Vezes por semana'] == vezes_por_semana]
    if plano_row.empty:
        st.warning(f"Não foi encontrado um plano para {vezes_por_semana}x por semana na planilha.")
        return 0, 0
    valor_mensal = plano_row.iloc[0]['Valor']
    valor_diario_proporcional = valor_mensal / (vezes_por_semana * 4)
    dias_coincidentes = 0
    data_atual = entrada_dt.date()
    while data_atual <= saida_dt.date():
        dia_da_semana = data_atual.weekday()
        if dia_da_semana in dias_plano_daycare:
            dias_coincidentes += 1
        data_atual += timedelta(days=1)
    desconto_total = dias_coincidentes * valor_diario_proporcional * num_caes
    return desconto_total, dias_coincidentes

def formatar_diarias_fracao(dias):
    inteiro = int(dias)
    fracao_decimal = dias - inteiro
    fracao_map = {0.25: "¹⁄₄", 0.5: "¹⁄₂", 0.75: "³⁄₄"}
    if inteiro == 0 and fracao_decimal in fracao_map: return fracao_map[fracao_decimal]
    if fracao_decimal == 0: return str(inteiro)
    if fracao_decimal in fracao_map: return f"{inteiro}{fracao_map[fracao_decimal]}"
    return f"{dias:.2f}".replace('.',',')


# --- FUNÇÕES DE GERAÇÃO DE PDF ---

def preparar_proposta_pdf():
    pdf = FPDF()
    pdf.add_page()
    
    # Adiciona a imagem de fundo que já está no seu projeto
    if os.path.exists("fundo_relatorio.png"):
        pdf.image("fundo_relatorio.png", x=0, y=0, w=210, h=297)
    
    # Tenta carregar as fontes personalizadas (essencial para caracteres especiais)
    try:
        pdf.add_font('DejaVu', '', 'DejaVuSans.ttf', uni=True)
        pdf.add_font('DejaVu', 'B', 'DejaVuSans-Bold.ttf', uni=True)
        font_family = 'DejaVu'
    except RuntimeError:
        # Se a fonte não for encontrada, usa 'Arial' como alternativa
        font_family = 'Arial'
    
    return pdf, font_family

def gerar_proposta_pdf(dados):
    pdf, font_family = preparar_proposta_pdf()
    
    # --- CABEÇALHO ---
    # Posição ajustada para a data
    pdf.set_y(52)
    # Define a margem direita para alinhar o texto corretamente
    pdf.set_right_margin(20)

    # Fonte maior e em negrito para a data
    pdf.set_font(font_family, 'B', 14) 
    pdf.set_text_color(255, 255, 255) 
    # Célula da data alinhada à direita
    pdf.cell(w=0, h=10, txt=f"Data: {datetime.now().strftime('%d/%m/%Y')}", border=0, ln=1, align='R')

    #Set cor preta
    pdf.set_text_color(0, 0, 0) 

    # Restaura a margem esquerda para o conteúdo principal
    pdf.set_left_margin(20)

    # --- BLOCO DE INFORMAÇÕES PRINCIPAIS ---
    pdf.set_y(80) 
    
    # Função auxiliar
    def add_info_line(label, value):
        pdf.set_font(font_family, 'B', 12)
        pdf.cell(55, 8, label, 0, 0)
        pdf.set_font(font_family, '', 12)
        pdf.cell(0, 8, value, 0, 1)

    add_info_line("Tutor(a):", dados['nome_dono'])
    add_info_line("Dog(s):", dados['nomes_caes'])
    add_info_line("Check-in:", f"{dados['data_entrada']} às {dados['horario_entrada'].replace(':', 'H')}")
    add_info_line("Check-out:", f"{dados['data_saida']} às {dados['horario_saida'].replace(':', 'H')}")
    add_info_line("Diárias:", str(dados['diarias_cobradas']))
    add_info_line("Preço Diária:", f"R$ {dados['valor_diaria']:.2f}".replace('.', ','))
    add_info_line("Valor Total:", f"R$ {dados['valor_final']:.2f}".replace('.', ',')) 

    pdf.ln(8)

    # Retorna o buffer do PDF para o Streamlit
    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()

# --- INTERFACE DO USUÁRIO (STREAMLIT) ---

df_precos, df_mensal, df_fidelidade = fetch_all_data_from_gsheet()

col1, col2, col3 = st.columns([1, 1, 1])
with col2:
    st.image("image_c02280.png", width=220) 
st.title("Calculadora de Orçamento", anchor=False)
st.markdown("<p class='subtitle'>Ferramenta interna para simulação de orçamento de hospedagem.</p>", unsafe_allow_html=True)
st.markdown("---")

with st.container(border=True):
    st.subheader("🐾 Dados do Responsável e dos Pets")
    
    nome_dono = st.text_input("Nome do Responsável")
    if 'num_caes' not in st.session_state:
        st.session_state.num_caes = 1
    st.session_state.num_caes = st.number_input(
        "Quantidade de Cães", min_value=1, value=st.session_state.num_caes, step=1, key="num_caes_selector"
    )

    st.markdown("---")
    
    tipo_cliente = st.radio(
        "Tipo de Cliente",
        ["Cliente Avulso", "Cliente Mensal", "Cliente Mensal Fidelizado"],
        horizontal=True, key="tipo_cliente"
    )

    dias_plano_daycare = []
    if st.session_state.tipo_cliente != "Cliente Avulso":
        st.markdown("Marque os dias da semana do plano Daycare:")
        dias_semana_cols = st.columns(5)
        dias_map = {"Segunda": 0, "Terça": 1, "Quarta": 2, "Quinta": 3, "Sexta": 4}
        for i, (dia, valor) in enumerate(dias_map.items()):
            if dias_semana_cols[i].checkbox(dia, key=f"dia_{dia}"):
                dias_plano_daycare.append(valor)
    
    alta_temporada = st.checkbox("É Alta Temporada? (Feriados, Dezembro, Janeiro e Julho)") 

    with st.form("orcamento_form"):
        st.markdown("---")
        st.subheader("🐶 Nomes dos Pets")
        nomes_caes = []
        if st.session_state.num_caes > 0:
            for i in range(st.session_state.num_caes):
                nomes_caes.append(st.text_input(f"Nome do Cão {i+1}", key=f"nome_cao_{i}", placeholder=f"Nome do Cão {i+1}"))
        
        st.markdown("---")
        st.subheader("🗓️ Período da Estadia")
        col3, col4 = st.columns(2)
        with col3:
            data_entrada = st.date_input("Data de Entrada", format="DD/MM/YYYY")
            horario_entrada = st.time_input("Horário de Entrada", value=time(14, 0))
        with col4:
            data_saida = st.date_input("Data de Saída", format="DD/MM/YYYY")
            horario_saida = st.time_input("Horário de Saída", value=time(12, 0))
        
        st.markdown("<br>", unsafe_allow_html=True)
        submitted = st.form_submit_button("Calcular Orçamento")

# --- EXIBIÇÃO DO RESULTADO ---
if submitted:
    if df_precos.empty:
        st.error("Falha ao carregar dados. Verifique a planilha.")
    elif not nome_dono.strip() or not all(nome.strip() for nome in nomes_caes):
        st.warning("Por favor, preencha o nome do responsável e de todos os cães.")
    else:
        with st.spinner("Calculando..."):
            entrada_datetime = datetime.combine(data_entrada, horario_entrada)
            saida_datetime = datetime.combine(data_saida, horario_saida)
            
            resultado_base = calcular_orcamento_base(
                df_precos, st.session_state.num_caes, entrada_datetime, saida_datetime, alta_temporada
            )
            
            if resultado_base:
                qtd_diarias, valor_diaria, valor_total_base = resultado_base
                desconto = 0
                dias_coincidentes = 0
                
                if st.session_state.tipo_cliente == "Cliente Mensal":
                    desconto, dias_coincidentes = calcular_desconto_mensalista(entrada_datetime, saida_datetime, dias_plano_daycare, df_mensal, st.session_state.num_caes)
                elif st.session_state.tipo_cliente == "Cliente Mensal Fidelizado":
                    desconto, dias_coincidentes = calcular_desconto_mensalista(entrada_datetime, saida_datetime, dias_plano_daycare, df_fidelidade, st.session_state.num_caes)

                valor_final = valor_total_base - desconto
                
                st.markdown("---")
                st.subheader("💰 Orçamento Estimado")
                st.success(f"Orçamento para **{nome_dono}** e seu(s) pet(s) **{', '.join(nomes_caes)}** gerado com sucesso!")
                
                diarias_formatadas = formatar_diarias_fracao(qtd_diarias)
                valor_diaria_formatado = f"R$ {valor_diaria:,.2f}"
                valor_bruto_formatado = f"R$ {valor_total_base:,.2f}"
                desconto_formatado = f"- R$ {desconto:,.2f}"
                valor_final_formatado = f"R$ {valor_final:,.2f}"
                help_text = f"Desconto para {dias_coincidentes} dia(s) do plano que coincidiram com a estadia."

                st.markdown(f"""
                    <div class="results-grid">
                        <div class="metric-box">
                            <div class="metric-label">Diárias Cobradas</div>
                            <div class="metric-value">{diarias_formatadas}</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Valor da Diária (por pet)</div>
                            <div class="metric-value">{valor_diaria_formatado}</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Valor Bruto Hotel</div>
                            <div class="metric-value">{valor_bruto_formatado}</div>
                        </div>
                        <div class="metric-box" title="{help_text}">
                            <div class="metric-label">Desconto Daycare</div>
                            <div class="metric-value green">{desconto_formatado}</div>
                        </div>
                    </div>
                    <div class="final-value-box">
                        <div class="metric-label"><strong>Valor Final Estimado</strong></div>
                        <div class="metric-value">{valor_final_formatado}</div>
                    </div>
                """, unsafe_allow_html=True)
                
                st.markdown("<br>", unsafe_allow_html=True)

                dados_para_pdf = {
                    "nome_dono": nome_dono,
                    "nomes_caes": ", ".join(nomes_caes),
                    "data_entrada": data_entrada.strftime('%d/%m/%Y'),
                    "horario_entrada": horario_entrada.strftime('%H:%M'),
                    "data_saida": data_saida.strftime('%d/%m/%Y'),
                    "horario_saida": horario_saida.strftime('%H:%M'),
                    "diarias_cobradas": diarias_formatadas,
                    "valor_diaria": valor_diaria,
                    "valor_bruto": valor_total_base,
                    "desconto": desconto,
                    "dias_coincidentes": dias_coincidentes,
                    "valor_final": valor_final
                }
                
                pdf_bytes = gerar_proposta_pdf(dados_para_pdf)
                
                st.download_button(
                    label="📄 Download da Proposta em PDF",
                    data=pdf_bytes,
                    file_name=f"Proposta_{nome_dono.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf"
                )













