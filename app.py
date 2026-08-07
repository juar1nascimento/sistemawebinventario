import io
from datetime import datetime
import cv2
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import barcode
from barcode.writer import ImageWriter
import gspread
from google.oauth2.service_account import Credentials

# -----------------------------------------------------------------------------
# Configuração da Página
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Sistema de Código de Barras & Inventário",
    page_icon="📦",
    layout="wide"
)

# --- URL DA PLANILHA GOOGLE ---
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/13awqdg1h2sMrlMxE-Mg77EPlZHN-UAlYKEnw2xJo26o/edit?gid=0#gid=0"

# -----------------------------------------------------------------------------
# Autenticação e Conexão Nativa com Google Sheets (gspread)
# -----------------------------------------------------------------------------
@st.cache_resource
def get_gspread_client():
    """Autentica na API do Google Sheets usando as credenciais do secrets.toml."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    try:
        # Carrega credenciais da Service Account a partir da chave [connections.gsheets] no secrets.toml
        creds = Credentials.from_service_account_info(
            st.secrets["connections"]["gsheets"],
            scopes=scopes
        )
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Erro ao autenticar no Google Sheets: {e}")
        return None

def salvar_no_google_sheets(codigo: str, origem: str, descricao: str = "") -> bool:
    """Insere um novo registro como linha no final da planilha Google."""
    client = get_gspread_client()
    if client is None:
        st.error("Falha na autenticação da Service Account. Verifique o arquivo .streamlit/secrets.toml.")
        return False
        
    try:
        sheet = client.open_by_url(SPREADSHEET_URL).sheet1
        
        # Garante cabeçalhos se a planilha estiver totalmente vazia
        if len(sheet.get_all_values()) == 0:
            sheet.append_row(["Data_Hora", "Codigo", "Origem", "Descricao"])

        nova_linha = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(codigo),
            origem,
            descricao
        ]
        
        sheet.append_row(nova_linha)
        st.cache_data.clear()
        return True

    except Exception as e:
        st.error(f"Falha ao salvar os dados na planilha Google: {str(e)}")
        return False

@st.cache_data(ttl=5)
def carregar_dados_planilha():
    """Lê os dados gravados na planilha Google."""
    client = get_gspread_client()
    if client is None:
        return pd.DataFrame()
    try:
        sheet = client.open_by_url(SPREADSHEET_URL).sheet1
        records = sheet.get_all_records()
        return pd.DataFrame(records)
    except Exception as e:
        st.error(f"Erro ao carregar dados da planilha: {e}")
        return pd.DataFrame()

# -----------------------------------------------------------------------------
# Funções Utilitárias de Código de Barras
# -----------------------------------------------------------------------------
def decode_barcode(image_bytes):
    image_bytes.seek(0)
    file_bytes = np.asarray(bytearray(image_bytes.read()), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    
    detector = cv2.barcode.BarcodeDetector()
    ok, decoded_info, decoded_type, _ = detector.detectAndDecode(img)
    
    results = []
    if ok:
        for info, btype in zip(decoded_info, decoded_type):
            if info:
                results.append({"conteudo": info, "tipo": btype})
    return results, img

def generate_barcode(code_type, code_value):
    barcode_class = barcode.get_barcode_class(code_type)
    rv = io.BytesIO()
    code_instance = barcode_class(code_value, writer=ImageWriter())
    code_instance.write(rv)
    rv.seek(0)
    return rv

# -----------------------------------------------------------------------------
# Estado da Sessão (Session State)
# -----------------------------------------------------------------------------
if "historico_leituras" not in st.session_state:
    st.session_state.historico_leituras = []

# -----------------------------------------------------------------------------
# Interface Principal
# -----------------------------------------------------------------------------
st.title("📦 Sistema de Código de Barras e Gestão de Inventário")

tab_manual, tab_scan, tab_generate, tab_sheets = st.tabs([
    "⌨️ Digitação / Leitor USB", 
    "📷 Leitura via Câmera/Imagem", 
    "🏷️ Gerador de Código",
    "📊 Dados Gravados"
])

# --- ABA 1: DIGITAÇÃO E LEITOR USB ---
with tab_manual:
    st.header("Digitação / Entrada Rápida USB")
    st.caption("Insira o número manualmente ou utilize um leitor de código de barras USB (bipador).")

    with st.form(key="form_digitacao", clear_on_submit=True):
        col_inp1, col_inp2 = st.columns([2, 1])
        with col_inp1:
            codigo_digitado = st.text_input(
                "Código de Barras",
                placeholder="Bipe com o leitor ou digite o número...",
                key="input_codigo_manual"
            )
        with col_inp2:
            descricao_item = st.text_input(
                "Descrição / Observação (Opcional)",
                placeholder="Ex: Item Estoque A"
            )
        
        btn_salvar_manual = st.form_submit_button("💾 Salvar Registro", type="primary")

    if btn_salvar_manual:
        if codigo_digitado.strip():
            cod_limpo = codigo_digitado.strip()
            sucesso = salvar_no_google_sheets(cod_limpo, "Digitação / Leitor USB", descricao_item)
            if sucesso:
                st.session_state.historico_leituras.insert(0, {
                    "Data_Hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                    "Codigo": cod_limpo,
                    "Origem": "Digitação / Leitor USB",
                    "Descricao": descricao_item
                })
                st.toast(f"Código **{cod_limpo}** gravado na planilha com sucesso!", icon="✅")
        else:
            st.warning("Por favor, digite ou bipe um código válido.")

    components.html(
        """
        <script>
            const doc = window.parent.document;
            const inputs = doc.querySelectorAll('input[type="text"]');
            if (inputs.length > 0) {
                inputs[0].focus();
            }
        </script>
        """,
        height=0,
    )

# --- ABA 2: LEITURA VIA CÂMERA/IMAGEM ---
with tab_scan:
    st.header("Escaneamento por Imagem")
    source_option = st.radio("Selecione a fonte de entrada:", ["Upload de Imagem", "Câmera ao Vivo"], horizontal=True)

    image_file = None
    if source_option == "Upload de Imagem":
        image_file = st.file_uploader("Envie uma imagem com código de barras", type=["png", "jpg", "jpeg", "webp"])
    else:
        image_file = st.camera_input("Tire uma foto do código de barras")

    if image_file is not None:
        col1, col2 = st.columns(2)
        with col1:
            st.image(image_file, caption="Imagem Carregada", use_container_width=True)

        with col2:
            with st.spinner("Processando e identificando código..."):
                results, _ = decode_barcode(image_file)
                
                if results:
                    st.success(f"Identificado(s) {len(results)} código(s)!")
                    for i, res in enumerate(results, 1):
                        cod = res["conteudo"]
                        st.text_input(f"Conteúdo Identificado #{i}", value=cod, key=f"res_{i}")
                        st.caption(f"Tipo detectado: {res['tipo']}")
                        
                        if st.button(f"Enviar #{i} para a Planilha", key=f"btn_send_{i}_{cod}"):
                            if salvar_no_google_sheets(cod, f"Scanner ({res['tipo']})"):
                                st.toast(f"Código **{cod}** gravado na planilha com sucesso!", icon="✅")
                else:
                    st.warning("Nenhum código de barras foi identificado nesta imagem.")

# --- ABA 3: GERAÇÃO DE CÓDIGOS DE BARRAS ---
with tab_generate:
    st.header("Gerador de Código de Barras")
    
    col_input, col_preview = st.columns([1, 1])
    
    with col_input:
        bc_type = st.selectbox("Selecione o Padrão", ["code128", "ean13", "code39", "upc"])
        bc_value = st.text_input("Digite o número / valor a ser gerado", value="123456789012")
        generate_btn = st.button("Gerar Código", type="primary")

    with col_preview:
        if generate_btn or bc_value:
            try:
                img_buf = generate_barcode(bc_type, bc_value)
                st.image(img_buf, caption=f"Código {bc_type.upper()}: {bc_value}")
                
                st.download_button(
                    label="Baixar Imagem PNG",
                    data=img_buf.getvalue(),
                    file_name=f"barcode_{bc_value}.png",
                    mime="image/png"
                )
            except Exception as e:
                st.error(f"Erro ao gerar código de barras: {str(e)}")

# --- ABA 4: VISUALIZAÇÃO DOS DADOS SALVOS ---
with tab_sheets:
    st.header("📊 Dados Gravados na Planilha Google")
    
    if st.button("🔄 Atualizar Dados"):
        st.cache_data.clear()
        st.rerun()
        
    df_sheets = carregar_dados_planilha()
    if not df_sheets.empty:
        st.dataframe(df_sheets, use_container_width=True)
    else:
        st.info("Nenhum dado encontrado ou planilha vazia.")