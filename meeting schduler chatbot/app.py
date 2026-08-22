"""
app.py
======
Ye file jaan-boojh kar "thin" rakhi gayi hai — is mein koi bhi heavy
logic (PDF loading, splitting, embeddings, Upstash calls) nahi hai.
Ye sirf `src/` ke modules ko import karke "connect" karti hai aur
Streamlit UI dikhati hai.

Poora data-processing pipeline:
    src/document_loader.py  -> PDF load
    src/text_splitter.py    -> chunks
    src/vector_store.py     -> Upstash Vector mein save + retrieve
    src/llm_chain.py         -> Gemini se answer
"""

import time

import streamlit as st

from src.config import config, validate_config
from src.document_loader import load_pdf
from src.text_splitter import split_documents
from src.vector_store import get_vector_store, is_index_empty, index_documents, get_retriever
from src.llm_chain import get_llm, get_prompt, generate_answer

# ---------------------------------------------------------------
# 1. PAGE SETUP
# ---------------------------------------------------------------
st.set_page_config(page_title="HBL Bank Assistant", page_icon="🏦", layout="centered")
st.title("🏦 HBL Bank Assistant")
st.write("Ask questions from the HBL bank document.")

missing_keys = validate_config()
if missing_keys:
    st.error(
        "❌ Kuch zaroori keys `.env` file mein missing hain:\n\n"
        + "\n".join(f"- `{key}`" for key in missing_keys)
        + "\n\n`.env.example` ko copy karke `.env` banayein aur values bharein."
    )
    st.stop()


# ---------------------------------------------------------------
# 2. VECTOR STORE SETUP (PDF -> chunks -> Upstash, sirf ek dafa)
# ---------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def setup_vector_store():
    store = get_vector_store()

    if is_index_empty(store):
        documents = load_pdf(config.pdf_path)
        chunks = split_documents(documents)
        uploaded_count = index_documents(store, chunks)
        return store, len(documents), uploaded_count, True

    return store, None, None, False


try:
    with st.spinner("Connecting to Upstash Vector..."):
        vector_store, num_pages, num_chunks, freshly_indexed = setup_vector_store()

    if freshly_indexed:
        st.success(f"✅ PDF processed and saved to Upstash! (Pages: {num_pages}, Chunks: {num_chunks})")
    else:
        st.success("✅ Connected to existing Upstash Vector index (data already indexed).")

except Exception as e:
    st.error(f"❌ Upstash/PDF setup mein error: {e}")
    st.stop()


# ---------------------------------------------------------------
# 3. LLM + RETRIEVER
# ---------------------------------------------------------------
retriever = get_retriever(vector_store)
llm = get_llm()
prompt = get_prompt()


# ---------------------------------------------------------------
# 4. QUESTION INPUT + ANSWER
# ---------------------------------------------------------------
question = st.text_input(
    "Ask your question:",
    placeholder="Example: What services does HBL provide?",
)

if st.button("🔍 Ask Question"):
    if question.strip() == "":
        st.warning("⚠️ Please enter a question.")
    else:
        start_time = time.time()
        relevant_docs = retriever.invoke(question)

        with st.spinner("Thinking..."):
            try:
                answer_text = generate_answer(llm, prompt, question, relevant_docs)
            except Exception as e:
                answer_text = None
                st.error(f"❌ Answer generate karte waqt error aayi: {e}")

        latency = time.time() - start_time

        if answer_text is not None:
            st.subheader("💬 Answer")
            st.write(answer_text)
            st.caption(f"⏱️ Latency: {latency:.3f} seconds")

            with st.expander("📄 View Retrieved Information"):
                for i, doc in enumerate(relevant_docs):
                    page_number = doc.metadata.get("page")
                    page_display = page_number + 1 if isinstance(page_number, int) else "Unknown"
                    st.markdown(f"### Source {i + 1} — Page {page_display}")
                    st.write(doc.page_content)
                    st.divider()
