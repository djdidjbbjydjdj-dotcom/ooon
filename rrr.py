import asyncio
from telethon.tl.types import Channel
from telethon import TelegramClient, events, Button
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import PhoneCodeInvalidError, PhoneNumberInvalidError, SessionPasswordNeededError, ChatAdminRequiredError, ChannelPrivateError, UserBannedInChannelError, FloodWaitError
from telethon.sessions import StringSession
from datetime import datetime
import os
import motor.motor_asyncio # مكتبة المونجو دي بي

# --- إعدادات الاتصال ---
api_id = 28557217
api_hash = "22fb694b8c569117cc056073fc444597"
bot_token = "6872922603:AAEckw1ILOGNhq9fYQB8L-bK_DAHdSNCue0"
owner_id = 6646631745

# رابط الاتصال بقاعدة البيانات (تم إزالة المسافة المتوقعة في كلمة المرور لضمان الاتصال)
# اذا كانت كلمة المرور تحتوي مسافة بالفعل، اعدها كما كانت
MONGO_URL = "mongodb+srv://djdidjbbjydjdj_db_user:d1JifOpzMkiL6Mkf@cluster0.gm4nvdj.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

# تهيئة عميل المونجو
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = mongo_client["TelethonBotDB"] # اسم قاعدة البيانات
users_collection = db["users"]
settings_collection = db["settings"]

bot = TelegramClient("bot", api_id, api_hash).start(bot_token=bot_token)

# --- متغيرات الذاكرة المؤقتة (Cache) ---
# سيتم تحميل البيانات هنا عند تشغيل البوت لتقليل الضغط على القاعدة
users = {}
vip_users = []
added_channels = []

# --- دوال التعامل مع قاعدة البيانات ---

async def load_data_from_db():
    """تحميل البيانات من القاعدة إلى الذاكرة عند التشغيل"""
    global users, vip_users, added_channels
    
    print("جاري تحميل البيانات من MongoDB...")
    
    # تحميل المستخدمين
    users = {}
    async for user in users_collection.find():
        user_id = str(user["_id"])
        users[user_id] = user
        # تحويل القوائم والقيم الافتراضية إذا لم تكن موجودة
        if "sessions" not in users[user_id]: users[user_id]["sessions"] = []
        if "groups" not in users[user_id]: users[user_id]["groups"] = []
    
    # تحميل الإعدادات العامة (VIPs والقنوات)
    settings = await settings_collection.find_one({"_id": "global_settings"})
    if settings:
        vip_users = settings.get("vip_users", [])
        added_channels = settings.get("added_channels", [])
    else:
        # إنشاء مستند الإعدادات إذا لم يكن موجوداً
        await settings_collection.insert_one({
            "_id": "global_settings",
            "vip_users": [],
            "added_channels": []
        })
        vip_users = []
        added_channels = []
        
    print("تم تحميل البيانات بنجاح.")

async def save_user(user_id):
    """حفظ بيانات مستخدم محدد في القاعدة"""
    user_id_str = str(user_id)
    if user_id_str in users:
        user_data = users[user_id_str].copy()
        user_data["_id"] = int(user_id) # استخدام الـ ID كمفتاح أساسي
        await users_collection.replace_one({"_id": int(user_id)}, user_data, upsert=True)

async def save_global_settings():
    """حفظ إعدادات VIP والقنوات"""
    await settings_collection.update_one(
        {"_id": "global_settings"},
        {"$set": {"vip_users": vip_users, "added_channels": added_channels}},
        upsert=True
    )

def is_vip(user_id):
    return user_id == owner_id or user_id in vip_users

# --- القوائم والأزرار ---
home_markup = [
    [Button.inline("- الحسابات -", b"acc_mun")],
    [Button.inline("- إدارة السوبرات -", b"manage_super"), Button.inline("- إعدادات النشر -", b"posting_settings")], 
    [Button.inline("- تحكم المطور -", b"manage_vip")],
]

# --- بدء البوت ---
@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    user_id = event.sender_id
    user_id_str = str(user_id)
    
    # التحقق مما إذا كان المستخدم جديداً وإضافته
    if user_id_str not in users:
        users[user_id_str] = {
            "_id": user_id,
            "sessions": [], 
            "groups": [], 
            "posting": False, 
            "caption_1": "",
            "caption_2": "",
            "caption_3": "", 
            "caption_4": "",
            "waitTime": 60
        }
        await save_user(user_id) # حفظ في القاعدة

    # التحقق من الاشتراك الإجباري
    if added_channels:
        channel = added_channels[0]
        try:
            participants = await bot.get_participants(channel)
            if user_id not in [u.id for u in participants]:
                await event.reply(
                    f"- يجب عليك الاشتراك في القناة التالية لاستخدام البوت:\n{channel}\n"
                    "- بعد الاشتراك، اضغط /start مجددًا.",
                    buttons=[[Button.url("اشترك في القناة", f"https://t.me/{channel.lstrip('@')}")]]
                )
                return
        except ChatAdminRequiredError:
            pass # تجاهل الخطأ للمطور لتجنب توقف البوت
        except Exception as e:
            print(f"Error checking channel: {e}")

    await event.reply(
        "- مرحبًا بك! يمكنك التحكم في حسابك باستخدام الخيارات التالية:",
        buttons=home_markup
    )

@bot.on(events.CallbackQuery(data=b"home"))
async def back_to_home(event):
    await event.edit(
        "- مرحبًا بك! يمكنك التحكم في حسابك باستخدام الخيارات التالية:",
        buttons=home_markup
    )

@bot.on(events.CallbackQuery(data=b"acc_mun"))
async def acc_mun(event):
    buttons = [
        [Button.inline("اضف حساب", b"register"), Button.inline("حذف حساب", b"delete_account")],
        [Button.inline("عرض الحسابات", b"view_account")],
        [Button.inline("العودة", b"home")]
    ]
    await event.edit("-قائمة الحسابات :", buttons=buttons)
    
@bot.on(events.CallbackQuery(data=b"manage_vip"))
async def manage_vip(event):
    user_id = event.sender_id
    if user_id != owner_id:
        await event.answer("- هذه الميزة متاحة للمالك فقط.", alert=True)
        return
    buttons = [
        [Button.inline("إضافة مستخدم VIP", b"add_vip"), Button.inline("حذف مستخدم VIP", b"remove_vip")],
        [Button.inline("عرض المستخدمين VIP", b"list_vip")],
        [Button.inline("- إضافة قناة الاشتراك -", b"add_subscription_channel"), Button.inline("- عرض الإحصائيات -", b"stats")],
        [Button.inline("العودة", b"home")]
    ]
    await event.edit("-تحكم المطور :", buttons=buttons)

@bot.on(events.CallbackQuery(data=b"add_vip"))
async def add_vip(event):
    user_id = event.sender_id
    if user_id != owner_id:
        return

    async with bot.conversation(owner_id) as conv:
        await conv.send_message("- أرسل معرف المستخدم الذي تريد إضافته كمستخدم VIP:")
        vip_id = (await conv.get_response(timeout=None)).text.strip()

        try:
            vip_id = int(vip_id)
            if vip_id in vip_users:
                await conv.send_message("- المستخدم موجود بالفعل كمستخدم VIP.")
            else:
                vip_users.append(vip_id)
                await save_global_settings() # حفظ التغيير في القاعدة
                await conv.send_message(f"- تم إضافة المستخدم {vip_id} كمستخدم VIP.")
        except ValueError:
            await conv.send_message("- يرجى إدخال معرف مستخدم صالح (رقم فقط).")

@bot.on(events.CallbackQuery(data=b"remove_vip"))
async def remove_vip(event):
    user_id = event.sender_id
    if user_id != owner_id:
        return

    async with bot.conversation(owner_id) as conv:
        await conv.send_message("- أرسل معرف المستخدم الذي تريد حذفه من قائمة VIP:")
        vip_id = (await conv.get_response(timeout=None)).text.strip()

        try:
            vip_id = int(vip_id)
            if vip_id in vip_users:
                vip_users.remove(vip_id)
                await save_global_settings() # حفظ التغيير في القاعدة
                await conv.send_message(f"- تم حذف المستخدم {vip_id} من قائمة VIP.")
            else:
                await conv.send_message("- المستخدم غير موجود في قائمة VIP.")
        except ValueError:
            await conv.send_message("- يرجى إدخال معرف مستخدم صالح (رقم فقط).")

@bot.on(events.CallbackQuery(data=b"manage_super"))
async def manage_super(event):
    await event.edit(
        "- إدارة السوبرات:",
        buttons=[
            [Button.inline("إضافة سوبر", b"newSuper"), Button.inline("عرض السوبرات", b"currentSupers")],
            [Button.inline("حذف سوبر", b"deleteSpecificSuper"), Button.inline("حذف جميع السوبرات", b"deleteAllSupers")], 
            [Button.inline("العودة", b"home")]
        ]
    )

@bot.on(events.CallbackQuery(data=b"newSuper"))
async def new_super(event):
    user_id = event.sender_id
    await event.delete()

    async with bot.conversation(user_id) as conv:
        await conv.send_message("- أرسل رابط السوبر لإضافته:")
        super_group_link = (await conv.get_response(timeout=None)).text.strip()

        if not super_group_link:
            await conv.send_message("- يرجى إرسال رابط صالح للقروب.")
            return

        if super_group_link.startswith("https://t.me/+"):
            if not is_vip(user_id):
                await bot.send_message(user_id, "- عذرًا، لا يمكنك إضافة رابط خاص لأنك لست VIP.")
                return

        if "groups" in users[str(user_id)] and super_group_link in users[str(user_id)]["groups"]:
            await conv.send_message("- الرابط تم إضافته بالفعل.")
            return
            
        sessions = users[str(user_id)].get("sessions", [])
        if not sessions:
            await bot.send_message(user_id, "- لا توجد جلسات مسجلة لإضافة السوبر.")
            return
            
        valid_session_found = False
        for session_data in sessions:
            session_string = session_data.get("session")
            if not session_string:
                continue
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise Exception("الجلسة غير صالحة")
                try:
                    await client(JoinChannelRequest(super_group_link))
                    try:
                        entity = await client.get_entity(super_group_link)
                        if isinstance(entity, Channel) and entity.megagroup:
                            if "groups" not in users[str(user_id)]:
                                users[str(user_id)]["groups"] = []
                            users[str(user_id)]["groups"].append(super_group_link)
                            await save_user(user_id) # حفظ
                            await bot.send_message(user_id, f"- تم إضافة السوبر بنجاح: {super_group_link}")
                        else:
                            await bot.send_message(user_id, "- الرابط لا يشير إلى مجموعة.")
                    except Exception as e:
                        await bot.send_message(user_id, f"- حدث خطأ أثناء الحصول على معلومات المجموعة: {str(e)}")
                    valid_session_found = True
                    break
                except ChannelPrivateError:
                    await bot.send_message(user_id, "- المجموعة خاصة ولا يمكن الانضمام إليها بدون دعوة.")
                except UserBannedInChannelError:
                    await bot.send_message(user_id, "- تم حظر الحساب من الانضمام إلى هذه المجموعة.")
                except Exception as e:
                    await bot.send_message(user_id, f"- حدث خطأ أثناء محاولة الانضمام: {str(e)}")
            except Exception as e:
                # حذف الجلسة التالفة
                users[str(user_id)]["sessions"] = [s for s in users[str(user_id)]["sessions"] if s["session"] != session_string]
                await save_user(user_id)
            finally:
                await client.disconnect()
        if not valid_session_found:
            await bot.send_message(user_id, "حدث خطأ حاول الانضمام للرابط بشكل يدوي وارجع اضفه")

@bot.on(events.CallbackQuery(data=b"currentSupers"))
async def current_supers(event):
    user_id = event.sender_id
    groups = users[str(user_id)].get("groups", [])
    if not groups:
        await event.answer("- لا توجد سوبرات مضافة.", alert=True)
    else:
        buttons = []
        for group in groups:
            # تقصير اسم الزر إذا كان طويلاً جداً
            display_text = group if len(group) < 30 else group[:27] + "..."
            buttons.append([Button.inline(display_text, f"delSuper:{groups.index(group)}")])
        buttons.append([Button.inline("العودة", b"home")])
        await event.edit("- السوبرات المضافة:", buttons=buttons)

@bot.on(events.CallbackQuery(data=b"deleteAllSupers"))
async def delete_all_supers(event):
    user_id = event.sender_id
    if "groups" in users[str(user_id)] and users[str(user_id)]["groups"]:
        users[str(user_id)]["groups"] = []
        await save_user(user_id) # حفظ
        await bot.send_message(user_id, "- تم حذف جميع السوبرات بنجاح.")
    else:
        await bot.send_message(user_id, "- لا توجد سوبرات لحذفها.")

@bot.on(events.CallbackQuery(data=b"add_subscription_channel"))
async def add_subscription_channel(event):
    user_id = event.sender_id
    if user_id != owner_id:
        await event.answer("- هذه الميزة متاحة للمالك فقط.", alert=True)
        return
    
    global added_channels 
    added_channels = [] # إعادة تعيين القائمة
    async with bot.conversation(owner_id) as conv:
        await conv.send_message("- أرسل معرف القناة التي تريد إضافتها كقناة اشتراك (مثل: @M_D_I):")
        channel_username = (await conv.get_response(timeout=None)).text.strip()
        added_channels.append(channel_username)
        await save_global_settings() # حفظ
        await conv.send_message(f"- تم تعيين القناة التالية كقناة اشتراك إجباري: {channel_username}")

@bot.on(events.CallbackQuery(data=b"list_vip"))
async def list_vip(event):
    user_id = event.sender_id
    if user_id != owner_id:
        await event.answer("- هذه الميزة متاحة للمالك فقط.", alert=True)
        return

    if not vip_users:
        await event.edit("- لا يوجد مستخدمون VIP حاليًا.", buttons=[[Button.inline("العودة", b"manage_vip")]])
    else:
        vip_list = "\n".join([f"- {vip_id}" for vip_id in vip_users])
        await event.edit(
            f"- قائمة المستخدمين VIP:\n\n{vip_list}",
            buttons=[[Button.inline("العودة", b"manage_vip")]]
        )

@bot.on(events.CallbackQuery(data=b"register"))
async def register_account(event):
    user_id = event.sender_id
    await event.delete()
    
    if str(user_id) not in users:
        # إنشاء هيكل المستخدم إذا لم يكن موجوداً
        users[str(user_id)] = {"_id": user_id, "sessions": [], "groups": [], "posting": False}
        
    if user_id == owner_id or user_id in vip_users:
        max_accounts = 10
    else:
        max_accounts = 1
        
    if len(users[str(user_id)]["sessions"]) >= max_accounts:
        if user_id not in vip_users:
            await bot.send_message(user_id, "- عذرًا، لا يمكنك إضافة أكثر من حساب واحد لأنك لست VIP.")
            return
        else:
            await bot.send_message(user_id, f"- لقد وصلت إلى الحد الأقصى من الحسابات ({max_accounts}).")
            return
            
    async with bot.conversation(user_id) as conv:
        await conv.send_message("- أرسل كود الجلسة الخاص بك:")
        try:
            response = await conv.get_response(timeout=60)
            session_string = response.text.strip()
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise Exception("Auth Error")
                me = await client.get_me()
                full_name = f"{me.first_name} {me.last_name}" if me.last_name else me.first_name
                await conv.send_message(f"- تم تسجيل الدخول باستخدام الجلسة بنجاح! مرحبًا {full_name} .")
                
                users[str(user_id)]["sessions"].append({
                    "session": session_string, 
                    "username": me.username, 
                    "id": me.id
                })
                await save_user(user_id) # حفظ
            except Exception as e:
                await conv.send_message(f"- الجلسة غير صالحة استخرج واحده جديدة وحاول مجدداً")
                return
            finally:
                await client.disconnect()
        except asyncio.TimeoutError:
            await conv.send_message("- لم يتم الرد في الوقت المحدد. تم إلغاء العملية.")

@bot.on(events.CallbackQuery(data=b"view_account"))
async def view_account(event):
    user_id = event.sender_id
    sessions = users[str(user_id)].get("sessions", [])    
    if not sessions:
        await event.edit(
            "- لا توجد حسابات مسجلة حاليًا. قم بتسجيل حساب جديد.",
            buttons=[[Button.inline("تسجيل حساب", b"register")]]
        )
        return
        
    accounts_info = []
    valid_sessions = []
    has_changes = False
    
    for i, session_data in enumerate(sessions):
        session_string = session_data["session"]
        try:
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise Exception("Auth Error")
            me = await client.get_me()
            full_name = f"{me.first_name} {me.last_name}" if me.last_name else me.first_name
            phone = getattr(me, 'phone', 'Unknown')
            accounts_info.append(
                f"**الحساب {i+1}:**\n"
                f"- **الاسم الكامل**: {full_name}\n"
                f"- **ID**: {me.id}\n"
                f"- **الرقم المرتبط**: {phone}"
            )
            valid_sessions.append(session_data)
        except Exception as e:
            accounts_info.append(f"**الحساب {i+1}:**\n- الجلسة غير صالحة وتم حذفها")
            has_changes = True
        finally:
            await client.disconnect()
            
    if has_changes:
        users[str(user_id)]["sessions"] = valid_sessions
        await save_user(user_id) # حفظ التعديلات

    accounts_info_text = "\n\n".join(accounts_info)
    await event.edit(
        f"- الحسابات الحالية:\n\n{accounts_info_text}",
        buttons=[[Button.inline("العودة", b"home")]]
    )

@bot.on(events.CallbackQuery(data=b"posting_settings"))
async def posting_settings(event):
    await event.edit(
        "- إعدادات النشر:",
        buttons=[
            [Button.inline("تعيين الكليشة", b"newCaption"), Button.inline("الكليشة الثانية", b"newCaption2")],
            [Button.inline("الكليشة الثالثة", b"newCaption3"), Button.inline("الكليشة الرابعة", b"newCaption4")],
            [Button.inline("حذف الكلايش", b"deleteAllCaptions")],
            [Button.inline("بدء النشر", b"startPosting"), Button.inline("إيقاف النشر", b"stopPosting")],
            [Button.inline("تعيين وقت الانتظار", b"waitTime")],
            [Button.inline("العودة", b"home")]
        ]
    )

@bot.on(events.CallbackQuery(data=b"deleteAllCaptions"))
async def delete_all_captions(event):
    user_id = event.sender_id
    users[str(user_id)]["caption_1"] = ""
    users[str(user_id)]["caption_2"] = ""
    users[str(user_id)]["caption_3"] = ""
    users[str(user_id)]["caption_4"] = ""
    await save_user(user_id)
    await bot.send_message(user_id, "- تم مسح جميع الكلايش بنجاح!")

@bot.on(events.CallbackQuery(data=b"newCaption"))
async def new_caption(event):
    user_id = event.sender_id
    await event.delete()
    async with bot.conversation(user_id) as conv:
        await conv.send_message("- أرسل الكليشة الجديدة:") 
        caption_1 = (await conv.get_response(timeout=None)).text 
        users[str(user_id)]["caption_1"] = caption_1
        await save_user(user_id)
        await bot.send_message(user_id, f"- تم تحديث الكليشة بنجاح! الكليشة الجديدة هي: {caption_1}")
        
@bot.on(events.CallbackQuery(data=b"newCaption2"))
async def new_caption2(event):
    user_id = event.sender_id
    if not is_vip(user_id):
        await bot.send_message(user_id, "- عذرًا، لا يمكنك تحديد أكثر من كليشة لأنك لست VIP.")
        return
    await event.delete()
    async with bot.conversation(user_id) as conv:
        await conv.send_message("- أرسل الكليشة الثانية الجديدة:")
        caption_2 = (await conv.get_response(timeout=None)).text 
        users[str(user_id)]["caption_2"] = caption_2 
        await save_user(user_id)
        await bot.send_message(user_id, f"- تم تحديث الكليشة الثانية بنجاح! الكليشة الثانية الجديدة هي: {caption_2}")

@bot.on(events.CallbackQuery(data=b"newCaption3"))
async def new_caption3(event):
    user_id = event.sender_id
    if not is_vip(user_id):
        await bot.send_message(user_id, "- عذرًا، لا يمكنك تحديد أكثر من كليشة لأنك لست VIP.")
        return
    await event.delete()
    async with bot.conversation(user_id) as conv:
        await conv.send_message("- أرسل الكليشة الثالثة الجديدة:")
        caption_3 = (await conv.get_response(timeout=None)).text 
        users[str(user_id)]["caption_3"] = caption_3 
        await save_user(user_id)
        await bot.send_message(user_id, f"- تم تحديث الكليشة الثالثة بنجاح! الكليشة الثالثة الجديدة هي: {caption_3}")

@bot.on(events.CallbackQuery(data=b"newCaption4"))
async def new_caption4(event):
    user_id = event.sender_id
    if not is_vip(user_id):
        await bot.send_message(user_id, "- عذرًا، لا يمكنك تحديد أكثر من كليشة لأنك لست VIP.")
        return
    await event.delete()
    async with bot.conversation(user_id) as conv:
        await conv.send_message("- أرسل الكليشة الرابعة الجديدة:")
        caption_4 = (await conv.get_response(timeout=None)).text 
        users[str(user_id)]["caption_4"] = caption_4
        await save_user(user_id)
        await bot.send_message(user_id, f"- تم تحديث الكليشة الرابعة بنجاح! الكليشة الرابعة الجديدة هي: {caption_4}")

@bot.on(events.CallbackQuery(data=b"waitTime"))
async def wait_time(event):
    user_id = event.sender_id
    await event.delete()
    async with bot.conversation(user_id) as conv:
        await conv.send_message("- أرسل مدة الانتظار (بالثواني):")
        wait_txt = (await conv.get_response(timeout=None)).text
        try:
            wait_val = int(wait_txt)
            if wait_val <= 59:
                raise ValueError("القيمة يجب أن تكون أكبر من دقيقة.")
            users[str(user_id)]["waitTime"] = wait_val
            await save_user(user_id)
            await bot.send_message(user_id, f"- تم تعيين وقت الانتظار بنجاح: {wait_val} ثواني")
        except ValueError as e:
            await bot.send_message(user_id, f"القيمة يجب أن تكون أكبر من دقيقة.")

@bot.on(events.CallbackQuery(data=b"startPosting"))
async def start_posting(event):
    user_id = event.sender_id
    
    if str(user_id) not in users:
        await event.answer("- المستخدم غير موجود!", alert=True)
        return
        
    users[str(user_id)]["posting"] = True
    await save_user(user_id)
    await event.answer("- تم بدء النشر التلقائي لجميع الحسابات!")
    
    if not users[str(user_id)].get("sessions"):
        await event.answer("- لا توجد حسابات مضافة للنشر فيها.", alert=True)
        users[str(user_id)]["posting"] = False
        await save_user(user_id)
        return
    
    groups = users[str(user_id)].get("groups", [])
    if not groups:
        await event.answer("- لا توجد سوبرات مضافة للنشر فيها.", alert=True)
        users[str(user_id)]["posting"] = False
        await save_user(user_id)
        return
        
    captions = [
        users[str(user_id)].get("caption_1", ""),
        users[str(user_id)].get("caption_2", ""),
        users[str(user_id)].get("caption_3", ""),
        users[str(user_id)].get("caption_4", "")
    ]
    captions = [caption for caption in captions if caption]
    
    if not captions:
        await event.answer("- لا توجد كليشة لنشرها.", alert=True)
        return

    wait_time_val = users[str(user_id)].get("waitTime", 60)
    
    async def post_in_group(session_string, group):
        client = TelegramClient(StringSession(session_string), api_id, api_hash)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise Exception("Auth Error")
            
            try:
                await client.send_message("me", "✅ تم تشغيل الجلسة بنجاح.")
            except: pass
            
            while users[str(user_id)]["posting"]:
                for caption in captions:
                    if not users[str(user_id)]["posting"]: break 
                    try:
                        if group.startswith("https://t.me/"):
                            try:
                                await client(JoinChannelRequest(group))
                                await client.send_message(group, caption)
                            except ChannelPrivateError:
                                if group in users[str(user_id)]["groups"]:
                                    users[str(user_id)]["groups"].remove(group)
                                    await save_user(user_id)
                                continue
                            except UserBannedInChannelError:
                                if group in users[str(user_id)]["groups"]:
                                    users[str(user_id)]["groups"].remove(group)
                                    await save_user(user_id)
                                continue
                        else:
                            await client.send_message(group, caption)
                    except FloodWaitError as e:
                        await asyncio.sleep(e.seconds)
                    except Exception as e:
                        print(f"Error posting in {group}: {e}")
                
                await asyncio.sleep(wait_time_val)
        except Exception as e:
            # حذف الجلسة إذا كانت تالفة
            print(f"Session Error: {e}")
            current_sessions = users[str(user_id)]["sessions"]
            new_sessions = [s for s in current_sessions if s["session"] != session_string]
            if len(current_sessions) != len(new_sessions):
                users[str(user_id)]["sessions"] = new_sessions
                await save_user(user_id)
        finally:
            await client.disconnect()

    tasks = []
    for session_data in users[str(user_id)]["sessions"]:
        session_string = session_data["session"]
        for group in groups:
            tasks.append(post_in_group(session_string, group))
    
    # تشغيل المهام في الخلفية
    asyncio.create_task(asyncio.gather(*tasks))

@bot.on(events.CallbackQuery(data=b"stopPosting"))
async def stop_posting(event):
    user_id = event.sender_id
    users[str(user_id)]["posting"] = False
    await save_user(user_id) 
    await event.answer("- تم إيقاف النشر التلقائي!")
    
@bot.on(events.CallbackQuery(data=b"stats"))
async def stats(event):
    if event.sender_id == owner_id:
        total_users = len(users)
        total_groups = sum(len(user.get("groups", [])) for user in users.values())
        total_accounts = sum(len(user.get("sessions", [])) for user in users.values())

        await event.edit(
            f"- عدد المستخدمين: {total_users}\n"
            f"- عدد السوبرات: {total_groups}\n"
            f"- عدد الحسابات المسجلة: {total_accounts}",
            buttons=[[Button.inline("العودة", b"home")]]
        )
    else:
        await event.answer("- هذه الميزة متاحة للمالك فقط.", alert=True)

# نقطة الدخول الرئيسية (Entry Point)
if __name__ == '__main__':
    bot.loop.run_until_complete(load_data_from_db())
    print("Bot is running with MongoDB...")
    bot.run_until_disconnected()
