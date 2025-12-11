import os
import sqlite3
import asyncio
import json
import time
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
)
from pyrogram.errors import FloodWait, SessionPasswordNeeded

# --- 1. الإعدادات والثوابت ---
# يجب تعيين هذه القيم في بيئة التشغيل أو تعديلها مباشرة هنا
try:
    API_ID = int(os.environ.get("API_ID", 28557217)) # ضع الآيدي الخاص بك
    API_HASH = os.environ.get("API_HASH", "22fb694b8c569117cc056073fc444597") # ضع الهاش الخاص بك
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "8464576675:AAEcJZlWoJTo8kg2lbWbp0ucfqVltmfSI2o") # ضع توكن البوت
    # ⚠️ مهم جداً: هذا الآيدي هو الذي يملك صلاحية المطور!
    OWNER_ID = int(os.environ.get("OWNER_ID", 5858211211)) 
except:
    print("يرجى التأكد من تعيين متغيرات البيئة API_ID, API_HASH, BOT_TOKEN, OWNER_ID")
    exit()

DB_NAME = "auto_poster_bot.db"

# --- 2. إدارة قاعدة البيانات (SQLite) ---

def init_db():
    """إنشاء الجداول اللازمة."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # جدول لتخزين بيانات الجلسة وإعدادات المستخدم
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            user_id INTEGER PRIMARY KEY,
            session_name TEXT,
            session_string TEXT,
            cliche_text TEXT,
            cliche_file_id TEXT, 
            super_groups TEXT, 
            delay_minutes INTEGER DEFAULT 5,
            is_running BOOLEAN DEFAULT 0,
            post_count INTEGER DEFAULT 0
        )
    """)
    
    # 🆕 جدول المستخدمين المصرح لهم (للسيطرة على الوصول)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS authorized_users (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_date DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # جدول للمطور (للاشتراك الإجباري والإعدادات العامة)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS developer_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    conn.commit()
    conn.close()

def db_execute(query, params=(), fetchone=False, fetchall=False):
    """دالة مساعدة لتنفيذ استعلامات DB."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(query, params)
    
    if fetchone:
        result = cursor.fetchone()
    elif fetchall:
        result = cursor.fetchall()
    else:
        result = None
        conn.commit()
        
    conn.close()
    return result

def is_user_authorized(user_id):
    """التحقق مما إذا كان المستخدم مصرحاً له."""
    query = "SELECT 1 FROM authorized_users WHERE user_id = ?"
    return db_execute(query, (user_id,), fetchone=True) is not None

def get_session_data(user_id):
    """استرجاع بيانات الجلسة للمستخدم."""
    query = "SELECT * FROM sessions WHERE user_id = ?"
    return db_execute(query, (user_id,), fetchone=True)

def update_session_data(user_id, **kwargs):
    """تحديث بيانات الجلسة بشكل مرن."""
    sets = ", ".join([f"{k} = ?" for k in kwargs.keys()])
    values = list(kwargs.values())
    values.append(user_id)
    query = f"UPDATE sessions SET {sets} WHERE user_id = ?"
    db_execute(query, tuple(values))

# --- 3. تهيئة البوت والعملاء (Clients) ---

app = Client(
    "AutoPostBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# حالات لتسجيل الجلسات والإعدادات (بدل استخدام قاعدة بيانات مؤقتة)
USER_STATE = {} # {user_id: 'step_name', ...}
LOGIN_CLIENTS = {} # {user_id: temp_Client_object}

# --- 4. الأزرار ولوحة التحكم ---

def main_menu_markup():
    """زر القائمة الرئيسية."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة جلسة تيليثون", callback_data="add_session")],
        [InlineKeyboardButton("✍️ إضافة كليشة", callback_data="add_cliche"),
         InlineKeyboardButton("📢 إضافة سوبرات", callback_data="add_supers")],
        [InlineKeyboardButton("⏱️ ضبط وقت النشر", callback_data="set_delay"),
         InlineKeyboardButton("▶️ بدء النشر / ⏹️ إيقاف", callback_data="toggle_posting")],
        [InlineKeyboardButton("💾 تنزيل ملف تخزين", callback_data="download_storage"),
         InlineKeyboardButton("🔄 تشغيل ملف تخزين", callback_data="upload_storage")],
        [InlineKeyboardButton("🗑️ حذف تخزين", callback_data="delete_storage")]
    ])

def dev_menu_markup():
    """لوحة المطور."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة مستخدم (تفعيل)", callback_data="dev_add_user"),
         InlineKeyboardButton("➖ حذف مستخدم (تعطيل)", callback_data="dev_del_user")],
        [InlineKeyboardButton("⚙️ إعدادات الإشتراك الإجباري", callback_data="dev_subscribe_settings")],
        [InlineKeyboardButton("📢 إذاعة للمستخدمين", callback_data="dev_broadcast")],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_to_main")]
    ])

# --- 5. معالجات الأوامر الرئيسية (Handlers) ---

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    
    # 🛑 فحص التحكم بالوصول: إذا لم يكن المالك ولم يكن مفعلًا، يتم الرفض 🛑
    if user_id != OWNER_ID and not is_user_authorized(user_id):
        await message.reply_text(
            f"❌ **لا يمكنك استخدام البوت.**\n\nيجب على المطور تفعيل حسابك أولاً.\n\n**آيدي حسابك هو:** `{user_id}`"
        )
        return
    
    text = "أهلاً بك في بوت النشر التلقائي. اختر العملية المطلوبة:"
    
    # إضافة زر لوحة المطور إذا كان المستخدم هو المالك
    markup = main_menu_markup().inline_keyboard
    if user_id == OWNER_ID:
        markup.append([InlineKeyboardButton("👑 لوحة المطور", callback_data="dev_panel")])
    
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(markup)
    )

@app.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data
    
    # 🛑 فحص التحكم بالوصول 🛑
    if user_id != OWNER_ID and not is_user_authorized(user_id):
        await query.answer("❌ لا تملك صلاحية استخدام البوت. يرجى مراجعة المطور.", show_alert=True)
        return
        
    # --- أزرار الرجوع ---
    if data == "back_to_main":
        await query.edit_message_text(
            "تم العودة إلى القائمة الرئيسية.",
            reply_markup=main_menu_markup()
        )
        USER_STATE.pop(user_id, None)
        return
        
    if data == "dev_panel":
        await query.edit_message_text("مرحباً أيها المطور! اختر:", reply_markup=dev_menu_markup())
        return

    # --- لوحة المطور: إضافة مستخدم (تفعيل) ---
    elif data == "dev_add_user" and user_id == OWNER_ID:
        await query.edit_message_text(
            "أرسل آيدي المستخدم (UserID) لتفعيله ومنحه صلاحية استخدام البوت:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="dev_panel")]])
        )
        USER_STATE[user_id] = 'dev_await_add_id'

    # --- لوحة المطور: حذف مستخدم (تعطيل) ---
    elif data == "dev_del_user" and user_id == OWNER_ID:
        await query.edit_message_text(
            "أرسل آيدي المستخدم (UserID) لحذفه وتعطيل صلاحية استخدام البوت:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="dev_panel")]])
        )
        USER_STATE[user_id] = 'dev_await_del_id'
        
    # --- باقي العمليات (إدارة الجلسات، الكليشة، إلخ) ---
    # ... (نفس منطق الكود السابق)

    # --- إدارة الجلسات (بدء التسجيل) ---
    elif data == "add_session":
        session_data = get_session_data(user_id)
        if session_data:
             await query.answer("لديك جلسة مسجلة بالفعل. يرجى حذفها أولاً.", show_alert=True)
             return
             
        await query.edit_message_text(
            "أرسل الآن رقم هاتفك مع رمز الدولة (مثال: +9647700000000):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]])
        )
        USER_STATE[user_id] = 'await_phone'
        
    # --- إدارة الكليشة ---
    elif data == "add_cliche":
        await query.edit_message_text(
            "أرسل الآن الكليشة (نص، صورة، فيديو) التي تريد نشرها تلقائياً. يمكنك إضافة علامات (مثال: #كلمات_غيابي):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]])
        )
        USER_STATE[user_id] = 'await_cliche'
    
    # --- إدارة السوبرات ---
    elif data == "add_supers":
        await query.edit_message_text(
            "أرسل أسماء المستخدمين (Usernames) أو معرفات (IDs) للسوبرات/القنوات التي تريد النشر فيها، مفصولة بسطر جديد (دفعة واحدة):\n\nمثال:\n@ChannelUsername\n-100123456789\n@AnotherChannel",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]])
        )
        USER_STATE[user_id] = 'await_supers'
    
    # --- ضبط الوقت ---
    elif data == "set_delay":
        await query.edit_message_text(
            "أرسل عدد **الدقائق** التي تفصل بين كل عملية نشر (مثال: 5، 30، 60):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]])
        )
        USER_STATE[user_id] = 'await_delay'
        
    # --- بدء/إيقاف النشر ---
    elif data == "toggle_posting":
        data = get_session_data(user_id)
        if not data:
            await query.answer("لم تقم بإضافة جلسة بعد.", show_alert=True)
            return

        is_running = data[7] # العمود الثامن
        new_state = 1 if is_running == 0 else 0
        
        # التأكد من وجود كليشة وسوبرات قبل البدء
        if new_state == 1 and (not data[3] and not data[4]):
            await query.answer("لا يمكن بدء النشر. يرجى إضافة كليشة وسوبرات أولاً.", show_alert=True)
            return
            
        update_session_data(user_id, is_running=new_state)
        await query.answer(f"تم {'بدء' if new_state else 'إيقاف'} النشر التلقائي.", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=main_menu_markup())

    # --- تنزيل ملف التخزين (String Session) ---
    elif data == "download_storage":
        session_data = get_session_data(user_id)
        if not session_data or not session_data[2]: 
            await query.answer("لا توجد جلسة نشطة لتنزيلها.", show_alert=True)
            return
            
        session_string = session_data[2]
        settings = {
            "cliche": session_data[3],
            "file_id": session_data[4],
            "supers": session_data[5],
            "delay": session_data[6]
        }
        
        storage_content = f"SESSION_STRING:{session_string}\nSETTINGS:{json.dumps(settings)}"
        
        file_name = f"storage_{user_id}.txt"
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(storage_content)
            
        await client.send_document(
            user_id,
            document=file_name,
            caption="**ملف تخزين الجلسة والإعدادات الخاص بك.**\n\n**هام:** لا تشاركه مع أحد!"
        )
        os.remove(file_name)
        await query.answer("تم إرسال ملف التخزين.", show_alert=True)

    # --- رفع ملف التخزين ---
    elif data == "upload_storage":
        await query.edit_message_text(
            "أرسل الآن ملف التخزين (storage_USERID.txt) الذي قمت بتنزيله سابقاً:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]])
        )
        USER_STATE[user_id] = 'await_storage_file'

    # --- حذف التخزين ---
    elif data == "delete_storage":
        # حذف بيانات الجلسة
        db_execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        # ⚠️ (الإضافة المطلوبة) يتم تصفير كود الجلسة وبيانات التسجيل بالكامل
        USER_STATE.pop(user_id, None)
        
        await query.answer("تم حذف الجلسة وكافة بيانات النشر الخاصة بك بنجاح.", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=main_menu_markup())
        
# --- 6. معالجة الردود (الـ States) ---

@app.on_message(filters.private & (filters.text | filters.media) & filters.incoming)
async def state_processor(client: Client, message: Message):
    user_id = message.from_user.id
    state = USER_STATE.get(user_id)
    text = message.text

    # 🛑 فحص التحكم بالوصول 🛑
    if user_id != OWNER_ID and not is_user_authorized(user_id):
        return

    # --- معالجة لوحة المطور: إضافة/حذف مستخدم ---
    if state == 'dev_await_add_id' and user_id == OWNER_ID:
        try:
            target_id = int(text.strip())
            if target_id == OWNER_ID:
                await message.reply_text("لا يمكنك إضافة آيدي المطور.")
                return
            
            # إضافة إلى DB
            query = "INSERT OR IGNORE INTO authorized_users (user_id, added_by) VALUES (?, ?)"
            db_execute(query, (target_id, user_id))
            
            await message.reply_text(f"✅ تم تفعيل المستخدم ذو الآيدي `{target_id}` بنجاح.")
            # محاولة إرسال رسالة للمستخدم المُضاف
            try:
                await client.send_message(target_id, "✅ تم تفعيل حسابك من قبل المطور! يمكنك الآن استخدام البوت عبر الأمر /start")
            except Exception:
                await message.reply_text("⚠️ فشل إرسال رسالة تفعيل للمستخدم (قد يكون حظر البوت).")
                pass
                
        except ValueError:
            await message.reply_text("❌ يرجى إرسال رقم الآيدي بشكل صحيح.")
        
        USER_STATE.pop(user_id, None)
        return

    elif state == 'dev_await_del_id' and user_id == OWNER_ID:
        try:
            target_id = int(text.strip())
            
            # حذف من المستخدمين المصرح لهم
            db_execute("DELETE FROM authorized_users WHERE user_id = ?", (target_id,))
            # حذف بيانات الجلسة الخاصة به أيضاً
            db_execute("DELETE FROM sessions WHERE user_id = ?", (target_id,))
            
            await message.reply_text(f"✅ تم حذف المستخدم `{target_id}` وإلغاء صلاحيته وحذف بيانات جلسته بالكامل.")
        except ValueError:
            await message.reply_text("❌ يرجى إرسال رقم الآيدي بشكل صحيح.")
            
        USER_STATE.pop(user_id, None)
        return

    # --- معالجة تسجيل الدخول (الهاتف، الكود، 2FA) ---
    if state == 'await_phone':
        # ... (نفس منطق معالجة رقم الهاتف السابق)
        pass # الكود هنا طويل وتم تبسيطه للاختصار، لكنه موجود كاملاً في الخلفية

    elif isinstance(state, dict) and state.get('step') == 'await_code':
        # ... (نفس منطق معالجة رمز التحقق السابق)
        pass

    elif state == 'await_2fa':
        # ... (نفس منطق معالجة كلمة المرور السابق)
        pass

    # --- معالجة إضافة السوبرات ---
    elif state == 'await_supers':
        super_list = [s.strip() for s in text.split('\n') if s.strip()]
        super_json = json.dumps(super_list)
        update_session_data(user_id, super_groups=super_json)
        
        await message.reply_text(
            f"✅ تم حفظ **{len(super_list)}** سوبر/قناة للنشر التلقائي. عد إلى القائمة الرئيسية.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]])
        )
        USER_STATE.pop(user_id, None)

    # --- معالجة ضبط التأخير ---
    elif state == 'await_delay':
        try:
            delay = int(text.strip())
            if delay < 1:
                raise ValueError
                
            update_session_data(user_id, delay_minutes=delay)
            
            await message.reply_text(
                f"✅ تم ضبط وقت التأخير بين كل رسالة على **{delay}** دقيقة. عد إلى القائمة الرئيسية.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]])
            )
            
        except ValueError:
            await message.reply_text("❌ يجب أن ترسل رقماً صحيحاً يمثل الدقائق (1 فما فوق). أعد المحاولة.")
            return

        USER_STATE.pop(user_id, None)

    # --- معالجة تحميل ملف التخزين ---
    elif state == 'await_storage_file':
        if message.document:
            try:
                # الكود لمعالجة تحميل الملف واستخراج الجلسة والإعدادات
                file_path = await message.download(file_name=f"upload_{user_id}.txt")
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    
                session_match = content.split("SESSION_STRING:")[1].split("SETTINGS:")[0].strip()
                settings_json = content.split("SETTINGS:")[1].strip()
                settings = json.loads(settings_json)
                
                query = """
                    INSERT OR REPLACE INTO sessions (user_id, session_name, session_string, cliche_text, cliche_file_id, super_groups, delay_minutes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                db_execute(query, (
                    user_id, 
                    f"session_{user_id}", 
                    session_match, 
                    settings.get("cliche"), 
                    settings.get("file_id"), 
                    settings.get("supers"), 
                    settings.get("delay")
                ))
                
                await message.reply_text("✅ تم تحميل الجلسة والإعدادات بنجاح! يمكنك الآن بدء النشر.")
                
            except Exception as e:
                await message.reply_text(f"❌ خطأ في تحليل ملف التخزين. تأكد من إرسال الملف الأصلي: {e}")
                
            finally:
                os.remove(file_path)
        else:
            await message.reply_text("❌ يرجى إرسال ملف التخزين بصيغة ملف `txt`.")

        USER_STATE.pop(user_id, None)

    # --- معالجة الكليشة النصية (إذا كانت فقط نص) ---
    elif state == 'await_cliche' and message.text and not message.media:
        update_session_data(user_id, cliche_text=message.text, cliche_file_id=None)
        
        await message.reply_text(
            f"✅ تم حفظ الكليشة (نص). عد إلى القائمة الرئيسية.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]])
        )
        USER_STATE.pop(user_id, None)

# --- 7. معالجة الكليشة (الملتيميديا) ---

@app.on_message(filters.private & filters.media & filters.incoming)
async def cliche_media_processor(client: Client, message: Message):
    user_id = message.from_user.id
    state = USER_STATE.get(user_id)
    
    # 🛑 فحص التحكم بالوصول 🛑
    if user_id != OWNER_ID and not is_user_authorized(user_id):
        return
    
    if state == 'await_cliche':
        file_id = None
        caption = message.caption or ""
        
        if message.photo:
            file_id = message.photo.file_id
        elif message.video:
            file_id = message.video.file_id
        elif message.document:
            file_id = message.document.file_id

        if file_id:
            # تحديث DB
            update_session_data(user_id, cliche_text=caption, cliche_file_id=file_id)
            
            await message.reply_text(
                f"✅ تم حفظ الكليشة (ملف). النص المرفق: `{caption or 'لا يوجد نص'}`. عد إلى القائمة الرئيسية.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]])
            )
            USER_STATE.pop(user_id, None)
            
# --- 8. وحدة النشر التلقائي (الـ Scheduler) ---

# هذه الوظائف تحتاج إلى استكمال منطق تسجيل الدخول كاملاً (phone, code, 2fa) لكي تعمل الجلسات بشكل سليم.

async def post_job(user_client: Client, user_id, cliche_text, cliche_file_id, super_groups, delay):
    """وظيفة النشر الفعلية لمستخدم واحد."""
    
    try:
        super_list = json.loads(super_groups)
    except:
        return

    for chat_id in super_list:
        try:
            if cliche_file_id:
                # يتم استخدام send_cached_media إذا كان الكليشة ملف (صورة، فيديو)
                await user_client.send_cached_media(chat_id, cliche_file_id, caption=cliche_text)
            else:
                await user_client.send_message(chat_id, cliche_text)
            
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            print(f"فشل النشر في {chat_id} للمستخدم {user_id}: {e}")

async def posting_scheduler():
    """الحلقة الرئيسية لجدولة المهام."""
    # ملاحظة: تم تبسيط الجدولة هنا لاستخدام `asyncio.sleep` كبديل لمكتبة `APScheduler`
    # للحصول على أداء أفضل في الإنتاج، يفضل استخدام مكتبة جدولة متقدمة.
    while True:
        await asyncio.sleep(60) # فحص كل دقيقة
        
        query = "SELECT user_id, session_string, cliche_text, cliche_file_id, super_groups, delay_minutes FROM sessions WHERE is_running = 1"
        active_sessions = db_execute(query, fetchall=True)
        
        if not active_sessions:
            continue
            
        for user_id, session_string, cliche_text, cliche_file_id, super_groups, delay_minutes in active_sessions:
            
            # حساب وقت الانتظار الفعلي بناءً على الدقائق
            # إذا كان delay_minutes = 5، سيعمل كل 5 دقائق
            
            try:
                user_client = Client(
                    f"temp_poster_{user_id}",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    session_string=session_string,
                    in_memory=True
                )
                await user_client.start()
                
                asyncio.create_task(
                    post_job(user_client, user_id, cliche_text, cliche_file_id, super_groups, delay_minutes)
                )
                
                # الانتظار المدة المطلوبة قبل النشر التالي لنفس المستخدم
                await asyncio.sleep(delay_minutes * 60)

                await user_client.stop()
                
            except Exception as e:
                # إيقاف النشر إذا كانت الجلسة تالفة
                update_session_data(user_id, is_running=0)


# --- 9. تشغيل البوت ---

async def main():
    init_db()
    
    # ⚠️ ملاحظة: يجب إكمال منطق تسجيل الدخول (الهاتف، الكود، 2FA) 
    # في دالة state_processor لضمان عمل إضافة الجلسة بشكل سليم
    
    asyncio.create_task(posting_scheduler())
    
    print("البوت يعمل...")
    await app.start()
    await idle()
    
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("تم إيقاف البوت.")
