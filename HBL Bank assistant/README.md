# 🏦 HBL Bank Assistant (RAG + Gemini + Upstash Vector)

Ek simple **RAG (Retrieval-Augmented Generation)** chatbot jo aapki bank
document (PDF) parh kar us par sawalon ke jawab deta hai — Google
**Gemini** LLM aur **Upstash Vector** database ke saath.

---

## 🧠 Ye kaam kaise karta hai (Road Map)

```
Your PDF
   ↓
document_loader.py        →  PDF parh kar text nikalta hai
   ↓
text_splitter.py          →  Text ko chhote chunks mein todta hai
   ↓
vector_store.py           →  Chunks ko Upstash Vector mein save karta hai
   ↓                          (embedding Upstash khud banata hai)
   ↓
[User sawal poochta hai]
   ↓
vector_store.py (retriever)  →  Sawal se related chunks Upstash se dhoondta hai
   ↓
llm_chain.py               →  Chunks + sawal ko Gemini ko bhejta hai
   ↓
Gemini                     →  Sirf document ke context se jawab deta hai
   ↓
app.py (Streamlit)         →  Jawab user ko screen par dikhata hai
```

---

## 📁 Project Structure

```
hbl-bank-assistant/
├── app.py                     # Sirf UI + modules ko connect karta hai (thin layer)
├── src/
│   ├── config.py               # .env se saari settings/keys ek jagah load karta hai
│   ├── document_loader.py      # PDF load karta hai
│   ├── text_splitter.py        # Text ko chunks mein todta hai
│   ├── vector_store.py         # Upstash Vector: save + search
│   └── llm_chain.py             # Gemini LLM + prompt + answer generation
├── bank_documents/
│   └── HBL.pdf                 # <-- Apna PDF yahan rakhein (yeh khud add karein)
├── .env.example                # Env variables ka template
├── .gitignore
├── requirements.txt
└── README.md
```

---

## ✅ Setup — Step by Step (A to Z)

### 1. Project folder mein jayein
```bash
cd hbl-bank-assistant
```

### 2. Virtual environment banayein (recommended)
```bash
python -m venv venv

# Windows:
venv\Scripts\activate

# Mac/Linux:
source venv/bin/activate
```

### 3. Dependencies install karein
```bash
pip install -r requirements.txt
```

### 4. Gemini API Key hasil karein
1. https://aistudio.google.com/app/apikey par jayein.
2. "Create API Key" par click karein aur key copy kar lein.

### 5. Upstash Vector Index banayein
1. https://console.upstash.com/vector par jayein aur login/signup karein.
2. **Create Index** par click karein.
3. Index ka naam dein (jaise `hbl-assistant`).
4. **Region**: sabse qareeb wala select karein (jaise `us-east-1`).
5. **Embedding Model** section mein koi bhi embedding model select
   karein (jaise `mxbai-embed-large-v1`) — is se Upstash khud text ko
   vectors mein convert karega, aapko koi alag embedding library
   install karne ki zaroorat nahi.
6. Index create hone ke baad, index par click karein aur **Details**
   tab se `UPSTASH_VECTOR_REST_URL` aur `UPSTASH_VECTOR_REST_TOKEN`
   copy kar lein.

### 6. `.env` file banayein
```bash
# .env.example ko copy karke .env banayein
cp .env.example .env        # Mac/Linux
copy .env.example .env      # Windows
```

Ab `.env` file kholein aur teen values bharein:
```env
GOOGLE_API_KEY=apni_gemini_key_yahan_dalein
UPSTASH_VECTOR_REST_URL=apna_upstash_url_yahan_dalein
UPSTASH_VECTOR_REST_TOKEN=apna_upstash_token_yahan_dalein
```

### 7. Apni bank PDF add karein
`bank_documents/` folder ke andar apni PDF file rakhein aur naam
`HBL.pdf` rakhein (ya `src/config.py` mein `pdf_path` change kar dein).

### 8. App run karein
```bash
streamlit run app.py
```

Browser mein `http://localhost:8501` khud khul jayega.

### 9. Sawal poochein
Pehli baar run karne par PDF process ho kar Upstash mein save hoga
(thoda time lagega). Agli baar app fori (instant) load hogi kyunke
data pehle se Upstash mein maujood hai — dobara process nahi hoga.

---

## ⚙️ Optional Settings (`.env` mein)

| Variable | Default | Matlab |
|---|---|---|
| `UPSTASH_NAMESPACE` | `hbl-handbook` | Upstash index ke andar data ka group/section |
| `CHUNK_SIZE` | `1200` | Har chunk mein kitne characters honge |
| `CHUNK_OVERLAP` | `200` | Chunks ke darmiyan overlap (context na tootey) |
| `RETRIEVER_K` | `5` | Har sawal ke liye kitne chunks retrieve honge |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Konsa Gemini model use ho |

---

## 🔁 Naya data dobara index karna ho to?

Agar aap PDF change karein aur chahte hain ke naye data se dobara
index ho, to Upstash Console se us namespace ka data delete kar dein
(ya `.env` mein `UPSTASH_NAMESPACE` ka naam change kar dein) — agli
baar app run karne par naya data automatically upload ho jayega.

---

## 🛠️ Common Issues

| Problem | Solution |
|---|---|
| `GOOGLE_API_KEY nahi mila` | `.env` file check karein, key sahi se paste hui ho |
| `UPSTASH_VECTOR_REST_URL/TOKEN missing` | Upstash Console → Vector → Index → Details se dobara copy karein |
| `PDF nahi mila` | `bank_documents/HBL.pdf` file mojood honi chahiye |
| Slow first run | Normal hai — pehli dafa PDF process + Upstash upload ho raha hota hai |

---

## 📌 Note

Yeh project sirf ek reference/demo tool hai. HBL ke official aur
binding terms hamesha **www.hbl.com** aur official branch se confirm
karein.
