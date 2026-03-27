import json
import logging
import os
import sys

# === LOGGING SETUP (Do it early for debugging) ===
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# === Robust Path Searching ===
current_dir = os.path.dirname(os.path.abspath(__file__))
package_dir = os.path.join(current_dir, "package")

logger.info(f"Checking for package dir: {package_dir}")

if not os.path.exists(package_dir):
    logger.warning(f"❌ package dir NOT found at {package_dir}. Searching in subdirectories...")
    # Search for any directory that contains a 'package' folder
    # This helps if the zip was created with an extra parent folder layer
    found = False
    try:
        for entry in os.listdir(current_dir):
            potential_path = os.path.join(current_dir, entry, "package")
            if os.path.isdir(potential_path):
                package_dir = potential_path
                logger.info(f"✅ Found package dir in subdirectory: {package_dir}")
                found = True
                break
    except Exception as e:
        logger.error(f"Error searching subdirectories: {e}")
else:
    logger.info("✅ package dir found at root.")

# Add to sys.path
if os.path.exists(package_dir):
    sys.path.insert(0, package_dir)
    logger.info(f"Updated sys.path with: {package_dir}")
else:
    logger.error("❌ Could not find 'package' directory anywhere. Requests import will likely fail.")

# Now import external libraries
try:
    import requests
    from linebot import LineBotApi, WebhookHandler
    from linebot.exceptions import InvalidSignatureError
    from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
    from groq import Groq
    from pinecone import Pinecone
    import cohere
    logger.info("✅ Successfully imported all external libraries.")
except ImportError as e:
    logger.error(f"❌ Failed to import library: {e}")
    # Print sys.path for debugging
    logger.info(f"Final sys.path: {sys.path}")
    raise e

# ---------------------------------------------
# 1. Setup Configuration & Logging
# ---------------------------------------------
logger = logging.getLogger()
logger.setLevel(logging.INFO)

LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
PINECONE_API_KEY = os.environ.get('PINECONE_API_KEY', '')
PINECONE_INDEX_NAME = os.environ.get('PINECONE_INDEX_NAME', '')
COHERE_API_KEY = os.environ.get('COHERE_API_KEY', '')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')

# ---------------------------------------------
# 2. Initialize Core Clients
# ---------------------------------------------
def get_clients():
    """
    คืนค่า Clients ทั้งหมดเพื่อใช้ในการทดสอบ Local หรือใน Lambda Handler
    """
    line_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    wh_handler = WebhookHandler(LINE_CHANNEL_SECRET)
    
    # Pinecone
    pine_pc = Pinecone(api_key=PINECONE_API_KEY)
    pine_index = None
    if PINECONE_INDEX_NAME:
        pine_index = pine_pc.Index(PINECONE_INDEX_NAME)
        
    # Cohere
    co_client = cohere.Client(COHERE_API_KEY)
    
    # Groq
    groq_api_client = Groq(api_key=GROQ_API_KEY)
    
    return line_api, wh_handler, pine_index, co_client, groq_api_client

# Initialize clients at top level for Lambda use
line_bot_api, handler, pinecone_index, co, groq_client = get_clients()

# ---------------------------------------------
# 3. Helper Functions
# ---------------------------------------------
def show_loading_animation(user_id, duration=5):
    """
    แสดง Loading Animation ให้ผู้ใช้เห็นว่าบอทกำลังพิมพ์ข้อความอยู่
    """
    try:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
        }
        loading_url = 'https://api.line.me/v2/bot/chat/loading/start'
        payload = {
            "chatId": user_id,
            "loadingSeconds": duration
        }
        requests.post(loading_url, headers=headers, json=payload)
    except Exception as e:
        logger.error(f"Error in show_loading_animation: {e}")

# ---------------------------------------------
# 4. AWS Lambda Handler Entry Point
# ---------------------------------------------
def lambda_handler(event, context):
    try:
        if 'body' not in event:
            return {'statusCode': 400, 'body': 'No body'}
            
        signature = event.get('headers', {}).get('x-line-signature', '')
        if not signature:
            signature = event.get('headers', {}).get('X-Line-Signature', '')
        
        body = event.get('body', '')

        # รันการตรวจสอบ Webhook ด้วย Line SDK
        handler.handle(body, signature)

        return {
            'statusCode': 200,
            'body': json.dumps('OK')
        }
    except InvalidSignatureError:
        logger.error("Invalid signature.")
        return {'statusCode': 400, 'body': 'Invalid signature.'}
    except Exception as e:
        logger.error(f"Error handling event: {e}")
        # ปกติ LINE Webhook ควรคืนค่า 200 เสมอเพื่อให้ LINE เลิกส่งซ้ำ แต่จะพริ้น error ออก log
        return {'statusCode': 200, 'body': json.dumps('Error process')}

# ---------------------------------------------
# 5. LINE Webhook Events - Text Message
# ---------------------------------------------
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_message = event.message.text
    user_id = event.source.user_id
    reply_token = event.reply_token
    
    # === แสดง Loading Animation 5 วินาที ===
    show_loading_animation(user_id, 5)

    try:
        # === สร้าง Embeddings ด้วย Cohere แบบใหม่ผ่าน SDK ===
        embeddings_response = co.embed(
            texts=[user_message],
            model='embed-multilingual-v3.0',
            input_type='search_query' # Cohere แนะนำ search_query สำหรับการค้นหาของยูสเซอร์
        )
        query_embedding = embeddings_response.embeddings[0]

        # === ค้นหาใน Pinecone ===
        search_results = pinecone_index.query(
            vector=query_embedding,
            top_k=5, 
            include_metadata=True
        )

        matches = search_results.get('matches', [])

        # กรองเอามาทำเป็น Quick Replies
        quick_replies_items = []
        for match in matches:
            metadata = match.get('metadata', {})
            if 'question' in metadata:
                q_text = metadata['question']
                # LINE อนุญาตให้ label มีได้สูงสุด 20 ตัวอักษร
                label_text = q_text if len(q_text) <= 20 else q_text[:17] + "..."
                quick_replies_items.append(
                    QuickReplyButton(action=MessageAction(label=label_text, text=q_text))
                )
        
        quick_reply_obj = QuickReply(items=quick_replies_items) if quick_replies_items else None

        # === กรณีเจอคำตอบเป๊ะมาก (Score > 0.95) ให้ลัดคิวตอบทันทีแบบไม่เสีย Token LLM มั่ว ===
        exact_match = next((m for m in matches if m['score'] > 0.95), None)
        if exact_match:
            answer = exact_match['metadata']['answer']
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text=answer, quick_reply=quick_reply_obj)
            )
            return

        # === กรณีมีใน FAQ ทำ RAG Prompt ด้วย Groq (Llama-3.1-8b-instant) ===
        if matches:
            faq_texts = []
            for m in matches:
                metadata = m.get('metadata', {})
                q = metadata.get('question', '')
                a = metadata.get('answer', '')
                if q and a:
                    faq_texts.append(f"คำถาม: {q}\nคำตอบ: {a}")
            
            relevant_faqs = "\n\n".join(faq_texts)

            template = f"""คุณคือ Aiya เป็นแชทบอท AI ที่ออกแบบมาโดยเฉพาะสำหรับ AIBeacon:
AIBeacon เป็นอุปกรณ์ส่งสัญญาณพลังงานต่ำที่ใช้ชิปประมวลผล Nordic nRF52840 สามารถส่งสัญญาณได้ไกลถึง 25 เมตรโดยไม่ต้องใช้การเชื่อมต่อ Wi-Fi หน้าที่หลักของคุณคือการช่วยให้ผู้ใช้งานเข้าใจถึงความสามารถและคุณสมบัติของ AIBeacon

ใช้ข้อมูลต่อไปนี้ในการตอบคำถาม:

{relevant_faqs}

เมื่อทำการตอบคำถาม:
- ให้ข้อมูลที่ชัดเจนและกระชับเกี่ยวกับคุณสมบัติและความสามารถของ AIBeacon
- ใช้คำศัพท์ทางเทคนิคตามความเหมาะสม แต่หากถูกถามให้สามารถอธิบายให้เข้าใจง่ายขึ้นได้
- หากเป็นไปได้ ให้นำเสนอตัวอย่างการใช้งาน AIBeacon ในสถานการณ์ต่าง ๆ
- แนะนำให้ผู้ใช้งานสำรวจการใช้งาน AIBeacon ได้อย่างเต็มประสิทธิภาพโดยเสนอแนะการประยุกต์ใช้งานที่เป็นไปได้

อย่าลืมรักษาน้ำเสียงที่เป็นมิตรและช่วยเหลือในการสนทนาเสมอ และให้ความสำคัญกับการให้ข้อมูลที่ถูกต้องเกี่ยวกับ AIBeacon

หากมีคำถามที่ไม่เกี่ยวข้องกับข้อมูลที่ให้ไว้ หรือไม่สามารถตอบคำถามได้อย่างถูกต้องจากข้อมูลที่มีอยู่ ให้ตอบกลับว่า:
"ขออภัยค่ะ แต่ฉันไม่มีข้อมูลเพียงพอในการตอบคำถามนี้ได้อย่างถูกต้อง หากคุณมีคำถามเกี่ยวกับ AIBeacon โดยเฉพาะ โปรดถามมาได้เลย ฉันจะพยายามช่วยเหลือคุณอย่างเต็มที่ค่ะ"
"""

            chat_completion = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": template},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=1000,
                temperature=0.0
            )

            ai_response = chat_completion.choices[0].message.content.strip()

            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text=ai_response, quick_reply=quick_reply_obj)
            )
            
        # === กรณี Pinecone ไม่มีข้อมูลเลย ===
        else:
            no_info_text = "ขออภัย ฉันไม่มีข้อมูลเกี่ยวกับคำถามนี้ในฐานข้อมูลของฉัน หากคุณมีคำถามเกี่ยวกับ AIBeacon โปรดถามใหม่"
            line_bot_api.reply_message(
                reply_token, 
                TextSendMessage(text=no_info_text)
            )

    except Exception as e:
        logger.error(f"Error logic flow: {str(e)}")
        error_msg = "ขออภัย เกิดข้อผิดพลาดในการประมวลผลข้อความของคุณ โปรดลองอีกครั้งในภายหลัง"
        try:
            line_bot_api.reply_message(reply_token, TextSendMessage(text=error_msg))
        except:
             pass
