import os
import json
import logging
import sys

# เพิ่ม Folder ปัจจุบัน และโฟลเดอร์ package เข้า path เพื่อให้ import lambda_function และ library ต่างๆ ได้
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
sys.path.append(os.path.join(current_dir, 'package'))

# อ่านไฟล์ .env แบบ Manual (กรณีไม่มี python-dotenv)
def load_env_manual():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value
        print("✅ โหลดค่าจากไฟล์ .env เรียบร้อยแล้ว")
    else:
        print("❌ ไม่พบไฟล์ .env กรุณาสร้างไฟล์ก่อน!")

load_env_manual()

# Import Lambda function code
try:
    import lambda_function
    from linebot.models import MessageEvent, TextMessage, TextSendMessage
except ImportError as e:
    print(f"❌ Error: ขาด Library บางตัว ({e})")
    print("กรุณารัน: pip install line-bot-sdk pinecone-client cohere groq requests")
    sys.exit(1)

def run_local_test():
    print("\n--- 🚀 เริ่มการทดสอบระบบ Chatbot RAG (Local) ---")
    
    # กำหนดคำถามที่ต้องการเทส
    test_question = "AIBeacon คืออะไร?"
    print(f"❓ คำถามทดสอบ: {test_question}")

    try:
        # 1. ทดสอบการดึง Clients
        print("\n[1/3] กำลังทดสอบการเชื่อมต่อ API...")
        line_api, handler, pinecone_idx, co_client, groq_client = lambda_function.get_clients()
        
        # 2. ทดสอบ Embedding (Cohere)
        print("[2/3] กำลังเช็ค Cohere Embeddings...")
        emb_res = co_client.embed(
            texts=[test_question],
            model='embed-multilingual-v3.0',
            input_type='search_query'
        )
        query_vec = emb_res.embeddings[0]
        print(f"   ✅ Cohere OK! (Vector length: {len(query_vec)})")

        # 3. ทดสอบ Pinecone Search
        print("[3/3] กำลังเช็ค Pinecone Search...")
        search_res = pinecone_idx.query(
            vector=query_vec,
            top_k=3,
            include_metadata=True
        )
        matches = search_res.get('matches', [])
        print(f"   ✅ Pinecone OK! (พบข้อมูลที่เกี่ยวข้อง {len(matches)} รายการ)")
        
        # 4. ทดสอบ Groq RAG
        print("\n🤖 [ผลลัพธ์จาก AI Aiya]:")
        # จำลองการสร้าง Context แบบในโค้ดจริง
        faq_texts = []
        for m in matches:
            meta = m.get('metadata', {})
            q = meta.get('question', '')
            a = meta.get('answer', '')
            if q and a:
                faq_texts.append(f"คำถาม: {q}\nคำตอบ: {a}")
        
        context_str = "\n\n".join(faq_texts) if faq_texts else "ไม่พบข้อมูลใน FAQ"
        
        # เรียก groq สร้างคำตอบ (Mocking the prompt)
        chat_completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": f"คุณคือ AI Aiya... ข้อมูลบริบทคือ:\n{context_str}"},
                {"role": "user", "content": test_question}
            ],
            max_tokens=500,
            temperature=0.0
        )
        
        ai_answer = chat_completion.choices[0].message.content
        print("-" * 30)
        print(ai_answer)
        print("-" * 30)
        
        print("\n✨ ทดสอบสำเร็จ! API ทุกตัวทำงานได้ปกติครับ")

    except Exception as e:
        print(f"\n❌ เกิดข้อผิดพลาด: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_local_test()
